import threading
import queue
import time
import subprocess
import json
import os
import requests
import re
import wave
from datetime import datetime, timezone
from typing import Optional
import importlib

class ProcessingPipeline:
    """Orchestrates the automated workflow with decoupled stages:
       segments → [Transcription Queue] → transcripts → [Summarization Queue] → summaries
    """
    def __init__(self, automation_enabled=True, whisper_path="/usr/local/bin/whisper", whisper_model="base", whisper_language="auto", whisper_threads=4,
                 ollama_url="http://localhost:11434", ollama_model="llama2", system_prompt=None, summary_batch_size=1):
        self.automation_enabled = automation_enabled
        # Independent queues
        self.transcribe_queue = queue.Queue()
        self.summarize_queue = queue.Queue()
        # Worker threads & state
        self.tx_thread = None
        self.sum_thread = None
        self.running = False
        self._tx_busy = False
        self._sum_busy = False
        # Config
        self.whisper_path = whisper_path
        self.whisper_model = whisper_model
        self.whisper_language = whisper_language
        self.whisper_threads = whisper_threads
        # New: backend selection ("cli", "pywhispercpp", or "server")
        self.whisper_backend = "cli"
        # Cached pywhispercpp model instance
        self._pyw_model = None
        # Server backend configuration
        self.whisper_server_url = "http://127.0.0.1:8080"
        self.whisper_server_timeout = 120  # seconds
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self.system_prompt = system_prompt or ""
        self.rolling_summary_text = None  # maintains cumulative rolling summary
        self.last_summary = None  # For rolling summary
        # Metrics / instrumentation (Phase 1)
        self.metrics_enabled = False
        self.metrics_dir_name = "metrics"
        self.metrics_file_path = None
        self._processed_tx = 0
        self._processed_sum = 0
        self._ema_latency = None
        self._ema_alpha = 0.2
        self.session_dir = None
        # Optional: pad silence at the end of each segment before transcription (ms)
        self.pad_silence_ms = 300
        # New: add small pre-roll from previous segment to improve boundary recognition (ms)
        self.pre_roll_ms = 300
        # New: batch size for summarization
        self.summary_batch_size = summary_batch_size
        self._batch_summaries = []

    def set_session_dir(self, session_dir):
        self.session_dir = session_dir
        if self.metrics_enabled and self.session_dir:
            metrics_dir = os.path.join(self.session_dir, self.metrics_dir_name)
            os.makedirs(metrics_dir, exist_ok=True)
            self.metrics_file_path = os.path.join(metrics_dir, 'metrics.ndjson')

    def start(self):
        if not self.automation_enabled or self.running:
            return
        self.running = True
        self.tx_thread = threading.Thread(target=self._tx_worker, daemon=True)
        self.sum_thread = threading.Thread(target=self._sum_worker, daemon=True)
        self.tx_thread.start()
        self.sum_thread.start()

    def stop(self):
        self.running = False
        if self.tx_thread:
            self.tx_thread.join(timeout=5)
        if self.sum_thread:
            self.sum_thread.join(timeout=5)

    def enqueue_transcription(self, segment_path, metadata):
        md = dict(metadata)
        md['tx_enqueue_monotonic'] = time.monotonic()
        self.transcribe_queue.put((segment_path, md))

    def enqueue_summarization(self, segment_path, transcript_text, metadata):
        md = dict(metadata)
        md['sum_enqueue_monotonic'] = time.monotonic()
        payload = {
            'segment_path': segment_path,
            'transcript': transcript_text,
            'metadata': md
        }
        self.summarize_queue.put(payload)

    def enqueue_segment(self, segment_path, metadata):
        """Backward-compatible alias: enqueue a segment for transcription stage."""
        return self.enqueue_transcription(segment_path, metadata)

    def _tx_worker(self):
        while self.running:
            try:
                segment_path, metadata = self.transcribe_queue.get(timeout=1)
            except queue.Empty:
                continue
            self._tx_busy = True
            try:
                start = time.monotonic()
                wait_s = start - metadata.get('tx_enqueue_monotonic', start)
                transcript = self.transcribe(segment_path, metadata)
                proc_s = time.monotonic() - start
                if self.metrics_enabled:
                    chars = len(transcript) if transcript else 0
                    tokens = chars // 4
                    self._write_metrics_line({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "stage": "transcription",
                        "segment_index": metadata.get('segment_index'),
                        "wait_s": round(wait_s, 4),
                        "process_s": round(proc_s, 4),
                        "queues": {
                            "transcribe": self.transcribe_queue.qsize(),
                            "summarize": self.summarize_queue.qsize()
                        },
                        "chars_transcript": chars,
                        "tokens_transcript": tokens
                    })
                # handoff to summarization queue (non-blocking)
                self.enqueue_summarization(segment_path, transcript, metadata)
                self._processed_tx += 1
            except Exception as e:
                print(f"[Pipeline][ERROR] Transcription worker exception: {e}")
            finally:
                self._tx_busy = False

    def _sum_worker(self):
        batch = []
        batch_metadata = []
        batch_count = 0
        self._batch_summaries = []
        while self.running or not self.summarize_queue.empty():
            try:
                job = self.summarize_queue.get(timeout=1)
            except queue.Empty:
                # If not running and queue is empty, flush leftovers
                if not self.running and batch:
                    self._process_summary_batch(batch, batch_metadata, batch_count, self._batch_summaries)
                    batch = []
                    batch_metadata = []
                continue
            segment_path = job['segment_path']
            transcript = job.get('transcript', '')
            metadata = job.get('metadata', {})
            batch.append(transcript)
            batch_metadata.append(metadata)
            if len(batch) >= self.summary_batch_size:
                self._process_summary_batch(batch, batch_metadata, batch_count, self._batch_summaries)
                batch = []
                batch_metadata = []
                batch_count += 1
        # After draining, flush any leftovers
        if batch:
            self._process_summary_batch(batch, batch_metadata, batch_count, self._batch_summaries)
            batch = []
            batch_metadata = []
        # Synthesize final summary from all batch summaries
        if self._batch_summaries:
            self._synthesize_final_summary(self._batch_summaries)

    def _process_summary_batch(self, batch, batch_metadata, batch_count, batch_summaries):
        batch_text = '\n\n'.join(batch)
        # Use first segment's metadata for index, etc.
        first_meta = batch_metadata[0] if batch_metadata else {}
        # Summarize the batch
        summary = self.summarize(None, batch_text, first_meta)
        # Save batch summary file
        if self.session_dir:
            summaries_dir = os.path.join(self.session_dir, 'summaries')
            os.makedirs(summaries_dir, exist_ok=True)
            batch_summary_path = os.path.join(summaries_dir, f'batch_{batch_count:03d}_summary.md')
            with open(batch_summary_path, 'w') as f:
                f.write(summary.strip() + '\n')
        batch_summaries.append(summary)
        # Metrics: chars and tokens
        if self.metrics_enabled:
            chars = len(batch_text)
            tokens = chars // 4
            self._write_metrics_line({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": "summarization_batch",
                "batch_index": batch_count,
                "chars_batch": chars,
                "tokens_batch": tokens
            })

    def _synthesize_final_summary(self, batch_summaries):
        all_text = '\n\n'.join(batch_summaries)
        prompt = (
            "You are to write a comprehensive, concise summary of the entire meeting based on the following batch summaries. "
            "Focus on key decisions, topics, and action items.\n\n"
            f"Batch Summaries:\n{all_text}\n\nFinal Summary:"
        )
        data = {"model": self.ollama_model, "prompt": prompt, "stream": False}
        try:
            response = requests.post(f"{self.ollama_url}/api/generate", json=data, timeout=600)
            response.raise_for_status()
            final_summary = response.json().get("response", "").strip()
            if self.session_dir:
                summaries_dir = os.path.join(self.session_dir, 'summaries')
                os.makedirs(summaries_dir, exist_ok=True)
                final_path = os.path.join(summaries_dir, 'final_summary.md')
                with open(final_path, 'w') as f:
                    f.write(final_summary + '\n')
            # Metrics: chars and tokens
            if self.metrics_enabled:
                chars = len(all_text)
                tokens = chars // 4
                self._write_metrics_line({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "stage": "final_summary",
                    "chars_final_input": chars,
                    "tokens_final_input": tokens,
                    "chars_final_summary": len(final_summary),
                    "tokens_final_summary": len(final_summary) // 4
                })
        except Exception as e:
            print(f"[Pipeline][ERROR] Final summary synthesis failed: {e}")

    def drain(self, poll_interval=1.0):
        """Block until both queues are empty and both workers are idle. Then synthesize final summary and transcript."""
        print("[Pipeline] Draining: waiting for all queued work to finish...")
        while self.running and (not self.is_idle() or not self.transcribe_queue.empty() or not self.summarize_queue.empty()):
            print(f"[Pipeline] Queues - TX:{self.transcribe_queue.qsize()} SUM:{self.summarize_queue.qsize()} | busy TX:{self._tx_busy} SUM:{self._sum_busy}")
            time.sleep(poll_interval)
        print("[Pipeline] Drain complete.")
        # Always synthesize final summary and transcript at the end
        self.generate_final_transcript()
        if hasattr(self, '_batch_summaries') and self._batch_summaries:
            self._synthesize_final_summary(self._batch_summaries)

    def generate_final_transcript(self):
        """Aggregate all segment transcripts into final_transcript.txt and .json"""
        if not self.session_dir:
            return
        transcription_dir = os.path.join(self.session_dir, 'transcription')
        summaries_dir = os.path.join(self.session_dir, 'summaries')
        os.makedirs(summaries_dir, exist_ok=True)
        txt_out = os.path.join(transcription_dir, 'final_transcript.txt')
        json_out = os.path.join(transcription_dir, 'final_transcript.json')
        transcripts = []
        json_segments = []
        for fname in sorted(os.listdir(transcription_dir)):
            if fname.endswith('_transcript.txt'):
                with open(os.path.join(transcription_dir, fname), 'r', encoding='utf-8', errors='replace') as f:
                    transcripts.append(f.read().strip())
            elif fname.endswith('_transcript.json'):
                try:
                    with open(os.path.join(transcription_dir, fname), 'r', encoding='utf-8') as jf:
                        data = json.load(jf)
                        json_segments.extend(data.get('segments', []))
                except Exception:
                    pass
        # Write final_transcript.txt
        with open(txt_out, 'w') as f:
            f.write('\n\n'.join(transcripts) + '\n')
        # Write final_transcript.json
        with open(json_out, 'w') as jf:
            json.dump({'segments': json_segments}, jf, indent=2)
        print(f"[Pipeline] Final transcript written: {txt_out}, {json_out}")

    def is_idle(self):
        return (not self._tx_busy) and (not self._sum_busy)

    def _derive_session_dirs(self, segment_path):
        abs_seg = os.path.abspath(segment_path)
        segments_dir = os.path.dirname(abs_seg)
        session_dir = os.path.dirname(segments_dir)
        transcription_dir = os.path.join(session_dir, 'transcription')
        summaries_dir = os.path.join(session_dir, 'summaries')
        return session_dir, segments_dir, transcription_dir, summaries_dir

    def _write_metrics_line(self, data: dict):
        if not self.metrics_file_path:
            return
        try:
            with open(self.metrics_file_path, 'a') as f:
                f.write(json.dumps(data) + '\n')
        except Exception as e:
            print(f"[Pipeline][WARN] Failed to write metrics line: {e}")

    def _ensure_pywhisper_model(self, log_path: Optional[str] = None):
        """Lazy-load a pywhispercpp model if backend is selected."""
        if self._pyw_model is not None:
            return self._pyw_model
        try:
            mod = importlib.import_module('pywhispercpp.model')
            Model = getattr(mod, 'Model')
        except Exception as e:
            print(f"[Pipeline][WARN] pywhispercpp not available ({e}); falling back to CLI backend.")
            self.whisper_backend = "cli"
            return None
        # Map language 'auto' -> ""
        lang = self.whisper_language
        if lang is None or str(lang).lower() in ("auto", "none"):
            lang = ""
        try:
            self._pyw_model = Model(
                self.whisper_model,
                n_threads=self.whisper_threads,
                language=lang,
                print_realtime=False,
                print_progress=False,
                redirect_whispercpp_logs_to=(log_path or False)
            )
        except Exception as e:
            print(f"[Pipeline][ERROR] Failed to initialize pywhispercpp model: {e}. Falling back to CLI.")
            self.whisper_backend = "cli"
            self._pyw_model = None
        return self._pyw_model

    # Helper: build a context WAV by concatenating optional prev-tail, current segment, and optional silence pad
    def _build_context_wav(self, prev_seg_path: Optional[str], cur_seg_path: str, out_dir: str, base_segment_name: str, override_pad_ms: Optional[int] = None) -> tuple[str, dict]:
        ctx_info = {"used_prev": False, "prev_tail_ms": 0, "pad_ms": 0}
        ctx_wav_path = os.path.join(out_dir, base_segment_name + '_ctx.wav')
        ctx_ffmpeg_log = os.path.join(out_dir, base_segment_name + '_ctx_ffmpeg.log')
        
        # Calculate expected segment duration for validation
        expected_duration_s = self._get_wav_duration_seconds(cur_seg_path)
        pad_ms = max(0, int(override_pad_ms if override_pad_ms is not None else (getattr(self, 'pad_silence_ms', 0) or 0)))
        
        # If no pre-roll needed, just copy/pad the current segment
        if not (prev_seg_path and os.path.exists(prev_seg_path) and getattr(self, 'pre_roll_ms', 0) > 0):
            if pad_ms > 0:
                pad_sec = pad_ms / 1000.0
                cmd = [
                    'ffmpeg', '-y', '-loglevel', 'warning',
                    '-i', cur_seg_path,
                    '-f', 'lavfi', '-t', f"{pad_sec}", '-i', 'anullsrc=r=16000:cl=mono',
                    '-filter_complex', '[0:a][1:a]concat=n=2:v=0:a=1[aout]',
                    '-map', '[aout]', '-c:a', 'pcm_s16le', '-ar', '16000', '-ac', '1',
                    ctx_wav_path
                ]
                ctx_info["pad_ms"] = pad_ms
            else:
                # Just re-encode to ensure consistent format
                cmd = ['ffmpeg', '-y', '-loglevel', 'warning', '-i', cur_seg_path, '-c:a', 'pcm_s16le', '-ar', '16000', '-ac', '1', ctx_wav_path]
        else:
            # Use concat demuxer approach for robustness
            prev_tail_ms = max(0.0, float(self.pre_roll_ms))
            prev_tail_sec = prev_tail_ms / 1000.0
            ctx_info["used_prev"] = True
            ctx_info["prev_tail_ms"] = int(prev_tail_ms)
            
            # Create temporary files for concat demuxer
            temp_prev_tail = os.path.join(out_dir, base_segment_name + '_temp_prev.wav')
            temp_pad_silence = None
            concat_list_file = os.path.join(out_dir, base_segment_name + '_concat_list.txt')
            
            try:
                # Extract prev tail using atrim filter (more reliable than -sseof)
                prev_duration = self._get_wav_duration_seconds(prev_seg_path)
                if prev_duration > 0:
                    start_time = max(0, prev_duration - prev_tail_sec)
                    cmd_prev = [
                        'ffmpeg', '-y', '-loglevel', 'warning',
                        '-i', prev_seg_path,
                        '-filter_complex', f'[0:a]atrim=start={start_time:.3f}[aout]',
                        '-map', '[aout]', '-c:a', 'pcm_s16le', '-ar', '16000', '-ac', '1',
                        temp_prev_tail
                    ]
                    r_prev = subprocess.run(cmd_prev, capture_output=True, text=True)
                    if r_prev.returncode != 0:
                        print(f"[Pipeline][WARN] Failed to extract prev tail, using current segment only: {r_prev.stderr}")
                        return self._build_context_wav_fallback(cur_seg_path, out_dir, base_segment_name, override_pad_ms)
                
                # Create silence pad if needed
                if pad_ms > 0:
                    pad_sec = pad_ms / 1000.0
                    temp_pad_silence = os.path.join(out_dir, base_segment_name + '_temp_pad.wav')
                    cmd_pad = [
                        'ffmpeg', '-y', '-loglevel', 'warning',
                        '-f', 'lavfi', '-t', f"{pad_sec}", '-i', 'anullsrc=r=16000:cl=mono',
                        '-c:a', 'pcm_s16le', '-ar', '16000', '-ac', '1',
                        temp_pad_silence
                    ]
                    r_pad = subprocess.run(cmd_pad, capture_output=True, text=True)
                    if r_pad.returncode != 0:
                        print(f"[Pipeline][WARN] Failed to create silence pad: {r_pad.stderr}")
                    ctx_info["pad_ms"] = pad_ms
                
                # Create concat list file
                with open(concat_list_file, 'w') as f:
                    if os.path.exists(temp_prev_tail):
                        f.write(f"file '{os.path.abspath(temp_prev_tail)}'\n")
                    f.write(f"file '{os.path.abspath(cur_seg_path)}'\n")
                    if temp_pad_silence and os.path.exists(temp_pad_silence):
                        f.write(f"file '{os.path.abspath(temp_pad_silence)}'\n")
                
                # Use concat demuxer
                cmd = [
                    'ffmpeg', '-y', '-loglevel', 'warning',
                    '-f', 'concat', '-safe', '0', '-i', concat_list_file,
                    '-c:a', 'pcm_s16le', '-ar', '16000', '-ac', '1',
                    ctx_wav_path
                ]
                
            except Exception as e:
                print(f"[Pipeline][WARN] Error setting up concat demuxer, falling back: {e}")
                return self._build_context_wav_fallback(cur_seg_path, out_dir, base_segment_name, override_pad_ms)
        
        # Execute ffmpeg command
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
            
            # Always log ffmpeg output for debugging
            try:
                with open(ctx_ffmpeg_log, 'w') as f:
                    f.write("COMMAND: " + " ".join(cmd) + "\n\n")
                    f.write("STDOUT:\n" + (r.stdout or "") + "\n\n")
                    f.write("STDERR:\n" + (r.stderr or "") + "\n")
            except Exception:
                pass
            
            if r.returncode != 0 or not os.path.exists(ctx_wav_path):
                print(f"[Pipeline][WARN] Context WAV build failed, using current segment only. See {ctx_ffmpeg_log}")
                return self._build_context_wav_fallback(cur_seg_path, out_dir, base_segment_name, override_pad_ms)
            
            # Validate context WAV duration
            ctx_duration = self._get_wav_duration_seconds(ctx_wav_path)
            if expected_duration_s > 0 and ctx_duration < (expected_duration_s - 2.0):
                print(f"[Pipeline][WARN] Context WAV duration ({ctx_duration:.1f}s) much shorter than expected ({expected_duration_s:.1f}s), falling back to raw segment")
                return self._build_context_wav_fallback(cur_seg_path, out_dir, base_segment_name, override_pad_ms)
            
        except Exception as e:
            print(f"[Pipeline][WARN] Context WAV error: {e}")
            return self._build_context_wav_fallback(cur_seg_path, out_dir, base_segment_name, override_pad_ms)
        finally:
            # Cleanup temporary files
            for temp_file in [
                os.path.join(out_dir, base_segment_name + '_temp_prev.wav'),
                os.path.join(out_dir, base_segment_name + '_temp_pad.wav'),
                os.path.join(out_dir, base_segment_name + '_concat_list.txt')
            ]:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                except Exception:
                    pass
        
        return ctx_wav_path, ctx_info

    def _build_context_wav_fallback(self, cur_seg_path: str, out_dir: str, base_segment_name: str, override_pad_ms: Optional[int] = None) -> tuple[str, dict]:
        """Fallback method that just uses the current segment with optional padding"""
        pad_ms = max(0, int(override_pad_ms if override_pad_ms is not None else (getattr(self, 'pad_silence_ms', 0) or 0)))
        ctx_info = {"used_prev": False, "prev_tail_ms": 0, "pad_ms": pad_ms}
        
        if pad_ms > 0:
            ctx_wav_path = os.path.join(out_dir, base_segment_name + '_ctx.wav')
            pad_sec = pad_ms / 1000.0
            cmd = [
                'ffmpeg', '-y', '-loglevel', 'warning',
                '-i', cur_seg_path,
                '-f', 'lavfi', '-t', f"{pad_sec}", '-i', 'anullsrc=r=16000:cl=mono',
                '-filter_complex', '[0:a][1:a]concat=n=2:v=0:a=1[aout]',
                '-map', '[aout]', '-c:a', 'pcm_s16le', '-ar', '16000', '-ac', '1',
                ctx_wav_path
            ]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True)
                if r.returncode == 0 and os.path.exists(ctx_wav_path):
                    return ctx_wav_path, ctx_info
            except Exception:
                pass
        
        # Ultimate fallback: just use the current segment as-is
        return cur_seg_path, {"used_prev": False, "prev_tail_ms": 0, "pad_ms": 0}

    # Helper: refine transcript using JSON timestamps to trim pre-roll and clamp to current duration
    def _refine_transcript_with_json(self, json_path: str, txt_fallback: str, orig_wav_path: str, prev_tail_ms: int) -> str:
        try:
            with open(json_path, 'r', encoding='utf-8') as jf:
                data = json.load(jf)
            segs = data.get('segments', [])
        except Exception as e:
            print(f"[Pipeline][WARN] Could not read/parse JSON for trimming: {e}")
            return txt_fallback
        dur_s = self._get_wav_duration_seconds(orig_wav_path) or 0.0
        keep_txt = []
        kept = 0
        for s in segs:
            try:
                # Support both pywhispercpp-style offsets and whisper.cpp JSON with start/end seconds
                if 'offsets' in s:
                    t0 = int(s.get('offsets', {}).get('from', 0))
                    t1 = int(s.get('offsets', {}).get('to', 0))
                else:
                    # start/end are in seconds (float)
                    t0 = int(float(s.get('start', 0.0)) * 1000.0)
                    t1 = int(float(s.get('end', 0.0)) * 1000.0)
                text = (s.get('text') or '').strip()
            except Exception:
                continue
            # Adjust for pre-roll
            local_t0 = max(0, t0 - int(prev_tail_ms or 0))
            local_t1 = max(0, t1 - int(prev_tail_ms or 0))
            # Keep only parts overlapping the current segment window [0, dur_s*1000]
            if dur_s > 0 and local_t0 >= int(dur_s * 1000) + 50:
                continue
            if text:
                keep_txt.append(text)
                kept += 1
        if kept == 0:
            return txt_fallback
        return '\n'.join(keep_txt)

    # Transcription stage (supports CLI or pywhispercpp backends)
    def transcribe(self, segment_path, metadata):
        print(f"[Pipeline] Transcribing {segment_path} with Whisper backend '{self.whisper_backend}' ...")
        segment_path_abs = os.path.abspath(segment_path)
        session_dir, segments_dir, transcription_dir, summaries_dir = self._derive_session_dirs(segment_path_abs)
        os.makedirs(transcription_dir, exist_ok=True)
        base_segment_name = os.path.splitext(os.path.basename(segment_path_abs))[0]
        transcript_base = os.path.join(transcription_dir, base_segment_name + '_transcript')
        transcript_txt_path = transcript_base + '.txt'
        transcript_json_path = transcript_base + '.json'
        whisper_log_path = transcript_base + '_whisper.log'
        transcript_txt = ""
        abs_model_path = os.path.expanduser(self.whisper_model)
        abs_whisper_path = os.path.expanduser(self.whisper_path)
        # Build context WAV: previous tail + current + optional pad
        prev_seg_path = None
        try:
            idx_str = str(metadata.get('segment_index', '')).strip()
            if idx_str.isdigit():
                prev_idx = int(idx_str) - 1
                if prev_idx >= 0:
                    prev_name = f"segment_{prev_idx:03d}.wav"
                    prev_candidate = os.path.join(os.path.dirname(segment_path_abs), prev_name)
                    if os.path.exists(prev_candidate):
                        prev_seg_path = prev_candidate
        except Exception:
            prev_seg_path = None
        segment_for_whisper, ctx_info = self._build_context_wav(prev_seg_path, segment_path_abs, transcription_dir, base_segment_name)
        
        # Collect context WAV metrics for debugging
        orig_duration_s = self._get_wav_duration_seconds(segment_path_abs) if os.path.exists(segment_path_abs) else 0.0
        orig_duration_ms = int(orig_duration_s * 1000)
        ctx_duration_s = self._get_wav_duration_seconds(segment_for_whisper) if os.path.exists(segment_for_whisper) else 0.0
        ctx_duration_ms = int(ctx_duration_s * 1000)
        
        # Debug logging for the suspicious duration
        if orig_duration_ms > 100000:  # More than 100 seconds, something's wrong
            print(f"[Pipeline][DEBUG] Suspicious duration detected!")
            print(f"[Pipeline][DEBUG] Path: {segment_path_abs}")
            print(f"[Pipeline][DEBUG] Exists: {os.path.exists(segment_path_abs)}")
            print(f"[Pipeline][DEBUG] Duration (s): {orig_duration_s}")
            print(f"[Pipeline][DEBUG] Duration (ms): {orig_duration_ms}")
            
            # Try alternative duration calculation
            try:
                import subprocess
                result = subprocess.run([
                    'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', 
                    '-of', 'csv=p=0', segment_path_abs
                ], capture_output=True, text=True)
                if result.returncode == 0:
                    alt_duration = float(result.stdout.strip())
                    print(f"[Pipeline][DEBUG] ffprobe duration: {alt_duration:.3f} s")
            except Exception as e:
                print(f"[Pipeline][DEBUG] ffprobe failed: {e}")
        
        if self.metrics_enabled:
            self._write_metrics_line({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "stage": "context_build",
                "segment_index": metadata.get('segment_index'),
                "orig_duration_ms": orig_duration_ms,
                "ctx_duration_ms": ctx_duration_ms,
                "ctx_info": ctx_info,
                "ctx_path": segment_for_whisper if segment_for_whisper != segment_path_abs else None
            })
        # Backend selection
        if (self.whisper_backend or "cli").lower() == "pywhispercpp":
            # In-process transcription via pywhispercpp
            try:
                model = self._ensure_pywhisper_model(log_path=whisper_log_path)
                if model is None:
                    # Fallback initiated inside _ensure_pywhisper_model
                    return self._transcribe_with_cli(segment_path_abs, segment_for_whisper, transcript_base, transcript_txt_path, transcript_json_path, whisper_log_path, abs_whisper_path, abs_model_path, ctx_info)
                segments = model.transcribe(segment_for_whisper)
                # Build outputs with offsets
                seg_list = []
                for seg in segments:
                    try:
                        t0 = int(getattr(seg, 't0', 0))
                        t1 = int(getattr(seg, 't1', 0))
                        text = str(getattr(seg, 'text', '')).strip()
                        if text:
                            seg_list.append({
                                'text': text,
                                'offsets': {'from': t0, 'to': t1}
                            })
                    except Exception:
                        continue
                # First write raw artifacts
                raw_txt = '\n'.join([s['text'] for s in seg_list])
                try:
                    with open(transcript_json_path, 'w') as jf:
                        json.dump({'segments': seg_list}, jf, indent=2)
                    with open(transcript_txt_path, 'w') as tf:
                        tf.write(raw_txt)
                except Exception as e:
                    print(f"[Pipeline][ERROR] Could not write transcript artifacts: {e}")
                # Refine (trim pre-roll and clamp end)
                refined_txt = self._refine_transcript_with_json(transcript_json_path, raw_txt, segment_path_abs, ctx_info.get('prev_tail_ms', 0))
                try:
                    if refined_txt and refined_txt != raw_txt:
                        with open(transcript_txt_path, 'w') as tf:
                            tf.write(refined_txt)
                except Exception as e:
                    print(f"[Pipeline][WARN] Could not write refined transcript: {e}")
                # Heuristic: compare original duration vs last offset after trimming
                wav_duration_s = self._get_wav_duration_seconds(segment_path_abs)
                last_offset_ms = 0
                if seg_list:
                    last_offset_ms = max([s['offsets']['to'] for s in seg_list]) - int(ctx_info.get('prev_tail_ms', 0))
                last_effective_ms = min(last_offset_ms, int(wav_duration_s * 1000.0)) if wav_duration_s else last_offset_ms
                suspected_truncated = bool(wav_duration_s and last_effective_ms and (wav_duration_s - (last_effective_ms/1000.0) > 3.0))
                if suspected_truncated:
                    print(f"[Pipeline][WARN] pywhispercpp transcript appears short: WAV {wav_duration_s:.1f}s vs last {last_effective_ms/1000.0:.1f}s. See {whisper_log_path}")
                print(f"[Pipeline] Transcript saved: {transcript_txt_path}")
                return refined_txt or raw_txt
            finally:
                # Cleanup context temp file if created
                try:
                    if segment_for_whisper != segment_path_abs and os.path.exists(segment_for_whisper):
                        os.remove(segment_for_whisper)
                except Exception:
                    pass
        elif (self.whisper_backend or "cli").lower() == "server":
            # Server backend: HTTP API calls to whisper.cpp server
            try:
                return self._transcribe_with_server(segment_path_abs, segment_for_whisper, transcript_base, transcript_txt_path, transcript_json_path, whisper_log_path, ctx_info)
            finally:
                # Cleanup context temp file if created
                try:
                    if segment_for_whisper != segment_path_abs and os.path.exists(segment_for_whisper):
                        os.remove(segment_for_whisper)
                except Exception:
                    pass
        else:
            # CLI path
            try:
                return self._transcribe_with_cli(segment_path_abs, segment_for_whisper, transcript_base, transcript_txt_path, transcript_json_path, whisper_log_path, abs_whisper_path, abs_model_path, ctx_info)
            finally:
                try:
                    if segment_for_whisper != segment_path_abs and os.path.exists(segment_for_whisper):
                        os.remove(segment_for_whisper)
                except Exception:
                    pass

    def _transcribe_with_cli(self, segment_path_abs, segment_for_whisper, transcript_base, transcript_txt_path, transcript_json_path, whisper_log_path, abs_whisper_path, abs_model_path, ctx_info: dict):
        print(f"[Pipeline] Transcribing {segment_path_abs} with Whisper.cpp CLI (safe blocking call) ...")
        transcript_txt = ""
        # Build command: write TXT and JSON-full for trimming; keep language/threads and explicit input file
        cmd = [
            abs_whisper_path,
            "-m", abs_model_path,
            "-f", segment_for_whisper,
            "-otxt",
            "-ojf",
            "-of", transcript_base,
            "-l", self.whisper_language,
            "-t", str(self.whisper_threads),
        ]
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True  # raise on non-zero exit
            )
            # Write logs after completion
            try:
                with open(whisper_log_path, 'w') as lf:
                    lf.write("COMMAND: " + " ".join(cmd) + "\n\n")
                    lf.write("STDOUT:\n" + (result.stdout or "") + "\n\n")
                    lf.write("STDERR:\n" + (result.stderr or "") + "\n")
            except Exception:
                pass
        except subprocess.CalledProcessError as e:
            # Log failure and exit
            try:
                with open(whisper_log_path, 'w') as lf:
                    lf.write("COMMAND: " + " ".join(cmd) + "\n\n")
                    lf.write("STDOUT:\n" + (e.stdout or "") + "\n\n")
                    lf.write("STDERR:\n" + (e.stderr or "") + "\n")
            except Exception:
                pass
            print(f"[Pipeline] Whisper.cpp failed: {e}\nSee log: {whisper_log_path}")
            return ""
        # After process exits successfully, wait for TXT/JSON to materialize & stabilize
        if os.path.exists(transcript_txt_path):
            _ = self.wait_for_file_stable(transcript_txt_path, min_size=16, stable_time=0.5, timeout=15)
        else:
            waited = self.wait_for_file_stable(transcript_txt_path, min_size=16, stable_time=0.5, timeout=5)
            if not waited:
                print(f"[Pipeline][WARN] No transcription TXT produced: {transcript_txt_path}")
                return ""
        if os.path.exists(transcript_json_path):
            _ = self.wait_for_file_stable(transcript_json_path, min_size=32, stable_time=0.5, timeout=15)
        # Read the transcript text (raw)
        try:
            with open(transcript_txt_path, 'r', encoding='utf-8', errors='replace') as tf:
                transcript_txt = tf.read()
        except Exception as e:
            print(f"[Pipeline][ERROR] Could not read transcript txt: {e}")
            return ""
        if not transcript_txt.strip():
            print(f"[Pipeline][WARN] Transcript TXT is empty: {transcript_txt_path}")
            return ""
        # Refine with JSON if available (trim pre-roll, clamp end)
        if os.path.exists(transcript_json_path) and ctx_info:
            refined = self._refine_transcript_with_json(transcript_json_path, transcript_txt, segment_path_abs, ctx_info.get('prev_tail_ms', 0))
            try:
                if refined and refined != transcript_txt:
                    with open(transcript_txt_path, 'w') as tf:
                        tf.write(refined)
                    transcript_txt = refined
            except Exception as e:
                print(f"[Pipeline][WARN] Could not write refined transcript: {e}")
        print(f"[Pipeline] Transcript saved: {transcript_txt_path}")
        return transcript_txt

    def _transcribe_with_server(self, segment_path_abs, segment_for_whisper, transcript_base, transcript_txt_path, transcript_json_path, whisper_log_path, ctx_info: dict):
        """Transcribe using Whisper.cpp HTTP server API"""
        print(f"[Pipeline] Transcribing {segment_path_abs} with Whisper.cpp server API ...")
        
        # Prepare the request data
        files = {
            'file': ('audio.wav', open(segment_for_whisper, 'rb'), 'audio/wav')
        }
        
        data = {
            'temperature': '0.0',
            'temperature_inc': '0.2',
            'response_format': 'json',
            'language': self.whisper_language if self.whisper_language != 'auto' else '',
            'max_len': '0',  # No limit
            'word_thold': '0.01',
            'no_timestamps': 'false'
        }
        
        try:
            # Make the HTTP request
            print(f"[Pipeline] Sending request to {self.whisper_server_url}/inference")
            response = requests.post(
                f"{self.whisper_server_url}/inference",
                files=files,
                data=data,
                timeout=self.whisper_server_timeout
            )
            
            # Close the file handle
            files['file'][1].close()
            
            # Check response
            response.raise_for_status()
            result_data = response.json()
            
            # Log the request/response
            try:
                with open(whisper_log_path, 'w') as lf:
                    lf.write(f"SERVER REQUEST: {self.whisper_server_url}/inference\n")
                    lf.write(f"DATA: {data}\n")
                    lf.write(f"STATUS: {response.status_code}\n\n")
                    lf.write("RESPONSE:\n" + json.dumps(result_data, indent=2) + "\n")
            except Exception:
                pass
            
            # Handle different response formats from whisper.cpp server
            segments = []
            raw_txt = ""
            
            if 'segments' in result_data:
                # New format: has segments with timestamps
                segments = result_data.get('segments', [])
                seg_list = []
                
                for seg in segments:
                    try:
                        # Server returns timestamps in seconds
                        text = str(seg.get('text', '')).strip()
                        if text:
                            seg_list.append({
                                'text': text,
                                'start': seg.get('start', 0.0),
                                'end': seg.get('end', 0.0)
                            })
                    except Exception:
                        continue
                
                raw_txt = '\n'.join([s['text'] for s in seg_list])
                segments = seg_list
                
            elif 'text' in result_data:
                # Simple format: just text field
                raw_txt = str(result_data.get('text', '')).strip()
                # Create a single segment covering the whole audio duration
                wav_duration_s = self._get_wav_duration_seconds(segment_path_abs)
                if raw_txt:
                    segments = [{
                        'text': raw_txt,
                        'start': 0.0,
                        'end': wav_duration_s
                    }]
                else:
                    segments = []
            else:
                print(f"[Pipeline][WARN] Unexpected server response format: {list(result_data.keys())}")
                raw_txt = ""
                segments = []
            
            # Write the artifacts
            try:
                with open(transcript_json_path, 'w') as jf:
                    json.dump({'segments': segments}, jf, indent=2)
                with open(transcript_txt_path, 'w') as tf:
                    tf.write(raw_txt)
            except Exception as e:
                print(f"[Pipeline][ERROR] Could not write transcript artifacts: {e}")
            
            # Refine transcript using JSON timestamps to trim pre-roll and clamp end
            if ctx_info and segments:
                refined_txt = self._refine_transcript_with_json(transcript_json_path, raw_txt, segment_path_abs, ctx_info.get('prev_tail_ms', 0))
                try:
                    if refined_txt and refined_txt != raw_txt:
                        with open(transcript_txt_path, 'w') as tf:
                            tf.write(refined_txt)
                        raw_txt = refined_txt
                except Exception as e:
                    print(f"[Pipeline][WARN] Could not write refined transcript: {e}")
            
            # Check for truncation issues (only if we have segments with timestamps)
            if segments and 'end' in segments[0]:
                wav_duration_s = self._get_wav_duration_seconds(segment_path_abs)
                last_end_s = max([s['end'] for s in segments])
                # Adjust for pre-roll
                last_effective_s = max(0, last_end_s - (ctx_info.get('prev_tail_ms', 0) / 1000.0)) if ctx_info else last_end_s
                suspected_truncated = bool(wav_duration_s and last_effective_s and (wav_duration_s - last_effective_s > 3.0))
                if suspected_truncated:
                    print(f"[Pipeline][WARN] Server transcript appears short: WAV {wav_duration_s:.1f}s vs last {last_effective_s:.1f}s")
                    print(f"[Pipeline] Retrying with simplified parameters to get full transcript...")
                    
                    # Retry with minimal parameters to avoid truncation
                    retry_data = {'response_format': 'json'}  # Minimal parameters
                    try:
                        with open(segment_for_whisper, 'rb') as retry_file:
                            retry_files = {'file': ('audio.wav', retry_file, 'audio/wav')}
                            
                            retry_response = requests.post(
                                f"{self.whisper_server_url}/inference",
                                files=retry_files,
                                data=retry_data,
                                timeout=self.whisper_server_timeout
                            )
                            
                            if retry_response.status_code == 200:
                                retry_result = retry_response.json()
                                
                                # Extract text from retry response
                                retry_text = ""
                                if 'text' in retry_result:
                                    retry_text = str(retry_result.get('text', '')).strip()
                                elif 'segments' in retry_result:
                                    retry_segments = retry_result.get('segments', [])
                                    retry_text = '\n'.join([str(s.get('text', '')).strip() for s in retry_segments if s.get('text', '').strip()])
                                
                                if retry_text and len(retry_text) > len(raw_txt):
                                    print(f"[Pipeline] Retry successful: {len(retry_text)} chars vs {len(raw_txt)} chars")
                                    raw_txt = retry_text
                                    
                                    # Update transcript file with retry result
                                    try:
                                        with open(transcript_txt_path, 'w') as tf:
                                            tf.write(raw_txt)
                                        print(f"[Pipeline] Updated transcript with retry result")
                                    except Exception as e:
                                        print(f"[Pipeline][WARN] Could not update transcript: {e}")
                                        
                                    # Log the retry success
                                    try:
                                        with open(whisper_log_path, 'a') as lf:
                                            lf.write(f"\n\nRETRY SUCCESSFUL:\n")
                                            lf.write(f"Original: {len(segments)} segments, {len(raw_txt)} chars\n")
                                            lf.write(f"Retry: {len(retry_text)} chars\n")
                                    except Exception:
                                        pass
                                else:
                                    print(f"[Pipeline][WARN] Retry did not improve transcript length")
                            else:
                                print(f"[Pipeline][WARN] Retry request failed: {retry_response.status_code}")
                                
                    except Exception as retry_e:
                        print(f"[Pipeline][WARN] Retry attempt failed: {retry_e}")
            
            print(f"[Pipeline] Transcript saved: {transcript_txt_path}")
            return raw_txt
            
        except requests.exceptions.RequestException as e:
            print(f"[Pipeline][ERROR] Whisper server request failed: {e}")
            try:
                with open(whisper_log_path, 'w') as lf:
                    lf.write(f"SERVER REQUEST FAILED: {self.whisper_server_url}/inference\n")
                    lf.write(f"ERROR: {e}\n")
                    lf.write(f"DATA: {data}\n")
            except Exception:
                pass
            return ""
        except Exception as e:
            print(f"[Pipeline][ERROR] Server transcription error: {e}")
            return ""

    def summarize(self, segment_path, transcript, metadata):
        print(f"[Pipeline] Summarizing transcript with Ollama ...")
        if not transcript.strip():
            print("[Pipeline][WARN] Empty transcript, skipping summarization.")
            return ""
        seg_index = metadata.get('segment_index') if metadata else None
        prev_roll = self.rolling_summary_text or ""
        # Structured, tagged output to avoid model overwriting issues
        instruction = (
            "You are updating a rolling meeting summary and generating a concise per-segment summary. "
            "Follow the format EXACTLY with the tags. Do not add any other text outside the tags.\n\n"
            "Inputs:\n"
            f"- Previous rolling summary (may be empty):\n{prev_roll}\n\n"
            f"- Current segment transcript:\n{transcript}\n\n"
            "Tasks:\n"
            "1) Update the rolling summary so it remains a cohesive, consolidated summary of the entire meeting so far.\n"
            "2) Produce a concise per-segment summary focusing only on NEW information from this segment.\n\n"
            "Output FORMAT (MANDATORY):\n"
            "<<ROLLING_SUMMARY>>\n"
            "<updated rolling summary text here>\n"
            "<</ROLLING_SUMMARY>>\n"
            "<<SEGMENT_SUMMARY>>\n"
            "<concise per-segment summary for this segment only>\n"
            "<</SEGMENT_SUMMARY>>\n"
        )
        prompt = self.system_prompt.strip() + "\n\n" + instruction if self.system_prompt else instruction
        data = {"model": self.ollama_model, "prompt": prompt, "stream": False}
        updated_roll = None
        seg_summary = None
        try:
            response = requests.post(f"{self.ollama_url}/api/generate", json=data, timeout=300)
            response.raise_for_status()
            resp_text = response.json().get("response", "")
            # Parse tagged sections
            updated_roll = self._extract_tag(resp_text, 'ROLLING_SUMMARY')
            seg_summary = self._extract_tag(resp_text, 'SEGMENT_SUMMARY')
            if not updated_roll and prev_roll:
                # Fallback: keep previous rolling summary if not provided
                updated_roll = prev_roll
            if not seg_summary:
                # Fallback: use full response as segment summary
                seg_summary = resp_text
            # Persist rolling summary
            self.rolling_summary_text = updated_roll or seg_summary or prev_roll
            # Save files only for per-segment summaries
            if segment_path:
                seg_path_abs = os.path.abspath(segment_path)
                session_dir, segments_dir, transcription_dir, summaries_dir = self._derive_session_dirs(seg_path_abs)
                os.makedirs(summaries_dir, exist_ok=True)
                base_segment_name = os.path.splitext(os.path.basename(seg_path_abs))[0]
                # Per-segment summary file
                summary_path = os.path.join(summaries_dir, base_segment_name + '_summary.md')
                try:
                    header = f"## Segment {seg_index} Summary\n\n" if seg_index is not None else ""
                    with open(summary_path, 'w') as f:
                        f.write(header + seg_summary.strip() + "\n")
                    print(f"[Pipeline] Summary saved: {summary_path}")
                except Exception as e:
                    print(f"[Pipeline][ERROR] Could not write summary file {summary_path}: {e}")
                # Rolling summary file
                rolling_path = os.path.join(summaries_dir, 'rolling_summary.md')
                try:
                    with open(rolling_path, 'w') as f:
                        f.write((self.rolling_summary_text or '').strip() + "\n")
                except Exception as e:
                    print(f"[Pipeline][ERROR] Could not write rolling summary file {rolling_path}: {e}")
            return seg_summary
        except Exception as e:
            print(f"[Pipeline][ERROR] Ollama summarization failed: {e}")
            return ""

    def _extract_tag(self, text: str, tag: str) -> str:
        """Extract content between <<TAG>> and <</TAG>>. Return empty string if not found."""
        try:
            pattern = rf"<<{tag}>>\n?(.*?)\n?<</{tag}>>"
            m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            return (m.group(1).strip() if m else "")
        except Exception:
            return ""

    def _get_wav_duration_seconds(self, wav_path: str) -> float:
        # Use ffprobe for reliable duration calculation
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                '-of', 'csv=p=0', wav_path
            ], capture_output=True, text=True, timeout=10)
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        
        # Fallback to wave module
        try:
            with wave.open(wav_path, 'rb') as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate and frames:
                    return frames / float(rate)
        except Exception:
            pass
        
        return 0.0

    def save_outputs(self, segment_path, transcript, summary, metadata):
        # No-op: batch and final summary logic handled elsewhere
        pass

    def wait_for_file_stable(self, path, min_size=32, stable_time=0.5, timeout=10):
        start = time.time()
        last_size = -1
        while time.time() - start < timeout:
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size >= min_size:
                    if size == last_size:
                        return True
                    last_size = size
                    time.sleep(stable_time)
                else:
                    time.sleep(0.1)
            else:
                time.sleep(0.1)
        print(f"[Pipeline][WARN] File {path} not stable after {timeout}s.")
        return False

    def _last_local_end_ms_from_json(self, json_path: str, prev_tail_ms: int) -> int:
        try:
            with open(json_path, 'r', encoding='utf-8') as jf:
                data = json.load(jf)
            segs = data.get('segments', [])
        except Exception:
            return 0
        last_ms = 0
        for s in segs:
            try:
                if 'offsets' in s:
                    t1 = int(s.get('offsets', {}).get('to', 0))
                else:
                    t1 = int(float(s.get('end', 0.0)) * 1000.0)
                local_t1 = max(0, t1 - int(prev_tail_ms or 0))
                if local_t1 > last_ms:
                    last_ms = local_t1
            except Exception:
                continue
        return last_ms
