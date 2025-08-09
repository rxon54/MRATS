import threading
import queue
import time
import subprocess
import json
import os
import requests
from datetime import datetime, timezone

class ProcessingPipeline:
    """Orchestrates the automated workflow: segmentation → transcription → summarization → output"""
    def __init__(self, automation_enabled=True, whisper_path="/usr/local/bin/whisper", whisper_model="base", whisper_language="auto", whisper_threads=4,
                 ollama_url="http://localhost:11434", ollama_model="llama2", system_prompt=None):
        self.automation_enabled = automation_enabled
        self.segment_queue = queue.Queue()
        self.worker_thread = None
        self.running = False
        self.whisper_path = whisper_path
        self.whisper_model = whisper_model
        self.whisper_language = whisper_language
        self.whisper_threads = whisper_threads
        self.ollama_url = ollama_url
        self.ollama_model = ollama_model
        self.system_prompt = system_prompt or ""
        self.last_summary = None  # For rolling summary
        # Metrics / instrumentation (Phase 1)
        self.metrics_enabled = False
        self.metrics_dir_name = "metrics"
        self.metrics_file_path = None
        self._processed_count = 0
        self._ema_latency = None  # exponential moving average of total latency
        self._ema_alpha = 0.2
        self.session_dir = None

    def set_session_dir(self, session_dir):
        """Set session directory (called by recorder) and prepare metrics path if enabled."""
        self.session_dir = session_dir
        if self.metrics_enabled and self.session_dir:
            metrics_dir = os.path.join(self.session_dir, self.metrics_dir_name)
            os.makedirs(metrics_dir, exist_ok=True)
            self.metrics_file_path = os.path.join(metrics_dir, 'metrics.ndjson')

    def start(self):
        if not self.automation_enabled or self.running:
            return
        self.running = True
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def stop(self):
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)

    def enqueue_segment(self, segment_path, metadata):
        # Store enqueue time for wait measurement
        metadata = dict(metadata)  # shallow copy to avoid mutation side effects
        metadata['enqueue_time_monotonic'] = time.monotonic()
        self.segment_queue.put((segment_path, metadata))

    def drain(self, poll_interval=1.0):
        """Block until the segment queue is empty and worker is idle."""
        print("[Pipeline] Draining: waiting for all queued segments to finish processing...")
        while self.running and (not self.segment_queue.empty() or not self.is_idle()):
            print(f"[Pipeline] Segments remaining: {self.segment_queue.qsize()} (worker busy: {not self.is_idle()})")
            time.sleep(poll_interval)
        print("[Pipeline] Drain complete.")

    def is_idle(self):
        # Returns True if worker is not processing a segment (i.e., between tasks)
        # We use a flag set at the start/end of process_segment
        return not getattr(self, '_worker_busy', False)

    def _worker(self):
        while self.running:
            try:
                segment_path, metadata = self.segment_queue.get(timeout=2)
                start_monotonic = time.monotonic()
                wait_s = start_monotonic - metadata.get('enqueue_time_monotonic', start_monotonic)
                segment_index = metadata.get('segment_index')
                total_start = start_monotonic
                print(f"[Pipeline] Processing segment: {segment_path} (wait {wait_s:.2f}s, queue size after get {self.segment_queue.qsize()})")
                # Transcription timing
                t_tx_start = time.monotonic()
                transcript = self.transcribe(segment_path, metadata)
                t_tx_end = time.monotonic()
                transcription_time = t_tx_end - t_tx_start
                # Summarization timing
                t_sum_start = time.monotonic()
                summary = self.summarize(transcript, metadata)
                t_sum_end = time.monotonic()
                summarization_time = t_sum_end - t_sum_start
                total_latency = t_sum_end - total_start
                # Update EMA
                if self._ema_latency is None:
                    self._ema_latency = total_latency
                else:
                    self._ema_latency = self._ema_alpha * total_latency + (1 - self._ema_alpha) * self._ema_latency
                self._processed_count += 1
                # Metrics line
                if self.metrics_enabled:
                    self._write_metrics_line({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "type": "segment",
                        "segment_index": segment_index,
                        "transcription": {
                            "wait_s": round(wait_s, 4),
                            "process_s": round(transcription_time, 4)
                        },
                        "summarization": {
                            "wait_s": 0.0,
                            "process_s": round(summarization_time, 4)
                        },
                        "total_latency_s": round(total_latency, 4),
                        "ema_latency_s": round(self._ema_latency, 4),
                        "backlog_sizes": {
                            "segment_queue": self.segment_queue.qsize()
                        },
                        "chars_transcript": len(transcript) if transcript else 0,
                        "chars_summary": len(summary) if summary else 0,
                        "processed_count": self._processed_count
                    })
                self.save_outputs(segment_path, transcript, summary, metadata)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[Pipeline][ERROR] Worker exception: {e}")

    def process_segment(self, segment_path, metadata):
        self._worker_busy = True
        try:
            print(f"[Pipeline] Processing segment: {segment_path}")
            transcript = self.transcribe(segment_path, metadata)
            summary = self.summarize(transcript, metadata)
            self.save_outputs(segment_path, transcript, summary, metadata)
        finally:
            self._worker_busy = False

    def _derive_session_dirs(self, segment_path):
        """Given a segment path .../session/segments/segment_000.wav, return base session dirs."""
        abs_seg = os.path.abspath(segment_path)
        segments_dir = os.path.dirname(abs_seg)
        session_dir = os.path.dirname(segments_dir)
        transcription_dir = os.path.join(session_dir, 'transcription')
        summaries_dir = os.path.join(session_dir, 'summaries')
        return session_dir, segments_dir, transcription_dir, summaries_dir

    def transcribe(self, segment_path, metadata):
        print(f"[Pipeline] Transcribing {segment_path} with Whisper.cpp ...")
        segment_path_abs = os.path.abspath(segment_path)
        session_dir, segments_dir, transcription_dir, summaries_dir = self._derive_session_dirs(segment_path_abs)
        os.makedirs(transcription_dir, exist_ok=True)
        base_segment_name = os.path.splitext(os.path.basename(segment_path_abs))[0]  # segment_000
        transcript_base = os.path.join(transcription_dir, base_segment_name + '_transcript')
        transcript_txt_path = transcript_base + '.txt'
        transcript_json_path = transcript_base + '.json'
        transcript_txt = ""
        transcript_json = None
        abs_model_path = os.path.expanduser(self.whisper_model)
        abs_whisper_path = os.path.expanduser(self.whisper_path)
        cmd = [
            abs_whisper_path,
            "-m", abs_model_path,
            "-t", str(self.whisper_threads),
            "-oj",
            "-of", transcript_base,
            "-l", self.whisper_language,
            "-t", str(self.whisper_threads),
            "-f", segment_path_abs
        ]
        print(f"[Pipeline][DEBUG] Whisper.cpp command: {' '.join(cmd)}")
        max_retries = 2
        for attempt in range(max_retries):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=os.environ.copy())
                print(f"[Pipeline][DEBUG] Whisper.cpp stderr: {result.stderr}")
                if result.returncode != 0:
                    print(f"[Pipeline] Whisper.cpp failed (attempt {attempt+1}): {result.stderr}")
                    time.sleep(2 ** attempt)
                    continue
                if os.path.exists(transcript_json_path):
                    if not self.wait_for_file_stable(transcript_json_path, min_size=32, stable_time=0.5, timeout=10):
                        print(f"[Pipeline][WARN] Transcript JSON not stable: {transcript_json_path}")
                        continue
                    with open(transcript_json_path, 'r') as f:
                        transcript_json = json.load(f)
                    segments = []
                    if isinstance(transcript_json, dict):
                        if 'transcription' in transcript_json:
                            segments = transcript_json['transcription']
                        elif 'segments' in transcript_json:
                            segments = transcript_json['segments']
                    elif isinstance(transcript_json, list):
                        segments = transcript_json
                    transcript_txt = '\n'.join([seg.get('text', '') for seg in segments if 'text' in seg])
                    if transcript_txt.strip():
                        try:
                            with open(transcript_txt_path, 'w') as f:
                                f.write(transcript_txt)
                            print(f"[Pipeline] Transcript saved: {transcript_txt_path}")
                        except Exception as e:
                            print(f"[Pipeline][ERROR] Could not write transcript txt: {e}")
                    return transcript_txt
                else:
                    print(f"[Pipeline][DEBUG] Whisper.cpp did not produce output file: {transcript_json_path}")
            except Exception as e:
                print(f"[Pipeline] Whisper.cpp error (attempt {attempt+1}): {e}")
                time.sleep(2 ** attempt)
        print(f"[Pipeline] Transcription failed for {segment_path}")
        return ""

    def summarize(self, transcript, metadata):
        print(f"[Pipeline] Summarizing transcript with Ollama ...")
        if not transcript.strip():
            print("[Pipeline][WARN] Empty transcript, skipping summarization.")
            return ""
        if not self.last_summary:
            user_prompt = f"This is the first segment of a meeting recording. Please summarize the following transcript:\n{transcript}"
        else:
            user_prompt = f"This is a continuation of a meeting. Previous summary:\n{self.last_summary}\nNew transcript:\n{transcript}\nPlease update the summary."
        prompt = self.system_prompt.strip() + "\n\n" + user_prompt if self.system_prompt else user_prompt
        data = {"model": self.ollama_model, "prompt": prompt, "stream": False}
        try:
            response = requests.post(f"{self.ollama_url}/api/generate", json=data, timeout=300)
            response.raise_for_status()
            summary = response.json().get("response", "")
            self.last_summary = summary
            # Determine output directories
            segment_path = metadata.get('segment_path', '')
            session_dir, segments_dir, transcription_dir, summaries_dir = self._derive_session_dirs(segment_path)
            os.makedirs(summaries_dir, exist_ok=True)
            base_segment_name = os.path.splitext(os.path.basename(segment_path))[0]
            summary_path = os.path.join(summaries_dir, base_segment_name + '_summary.md')
            try:
                with open(summary_path, 'w') as f:
                    f.write(summary)
                print(f"[Pipeline] Summary saved: {summary_path}")
            except Exception as e:
                print(f"[Pipeline][ERROR] Could not write summary file {summary_path}: {e}")
            rolling_path = os.path.join(summaries_dir, 'rolling_summary.md')
            try:
                with open(rolling_path, 'w') as f:
                    f.write(self.last_summary)
            except Exception as e:
                print(f"[Pipeline][ERROR] Could not write rolling summary file {rolling_path}: {e}")
            return summary
        except Exception as e:
            print(f"[Pipeline][ERROR] Ollama summarization failed: {e}")
            return ""

    def _write_metrics_line(self, data: dict):
        if not self.metrics_file_path:
            return
        try:
            with open(self.metrics_file_path, 'a') as f:
                f.write(json.dumps(data) + '\n')
        except Exception as e:
            print(f"[Pipeline][WARN] Failed to write metrics line: {e}")

    def save_outputs(self, segment_path, transcript, summary, metadata):
        # Placeholder for any additional aggregation logic
        pass

    def wait_for_file_stable(self, path, min_size=32, stable_time=0.5, timeout=10):
        import time
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
