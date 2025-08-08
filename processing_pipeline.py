import threading
import queue
import time
import subprocess
import json
import os
import requests

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
        self.segment_queue.put((segment_path, metadata))

    def _worker(self):
        while self.running:
            try:
                segment_path, metadata = self.segment_queue.get(timeout=2)
                self.process_segment(segment_path, metadata)
            except queue.Empty:
                continue

    def process_segment(self, segment_path, metadata):
        print(f"[Pipeline] Processing segment: {segment_path}")
        # Step 1: Transcription (stub)
        transcript = self.transcribe(segment_path, metadata)
        # Step 2: Summarization (stub)
        summary = self.summarize(transcript, metadata)
        # Step 3: Output (stub)
        self.save_outputs(segment_path, transcript, summary, metadata)

    def transcribe(self, segment_path, metadata):
        print(f"[Pipeline] Transcribing {segment_path} with Whisper.cpp ...")
        transcript_txt = ""
        transcript_json = None
        # Use absolute paths for all files
        abs_segment_path = os.path.abspath(segment_path)
        transcript_base = abs_segment_path.replace('.wav', '_transcript')
        transcript_path = transcript_base + '.txt'
        transcript_json_path = transcript_base + '.json'
        abs_model_path = os.path.expanduser(self.whisper_model)
        abs_whisper_path = os.path.expanduser(self.whisper_path)
        cmd = [
            abs_whisper_path,
            "-m", abs_model_path,
            "-oj",
            "-of", transcript_base,
            "-l", self.whisper_language,
            "-t", str(self.whisper_threads),
            "-f", abs_segment_path
        ]
        print(f"[Pipeline][DEBUG] Whisper.cpp command: {' '.join(cmd)}")
        print(f"[Pipeline][DEBUG] Working dir: {os.getcwd()}")
        print(f"[Pipeline][DEBUG] WAV exists: {os.path.exists(abs_segment_path)} | Size: {os.path.getsize(abs_segment_path) if os.path.exists(abs_segment_path) else 0}")
        print(f"[Pipeline][DEBUG] Model exists: {os.path.exists(abs_model_path)}")
        max_retries = 2
        for attempt in range(max_retries):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=os.environ.copy())
                print(f"[Pipeline][DEBUG] Whisper.cpp stdout: {result.stdout}")
                print(f"[Pipeline][DEBUG] Whisper.cpp stderr: {result.stderr}")
                print(f"[Pipeline][DEBUG] Return code: {result.returncode}")
                if result.returncode != 0:
                    print(f"[Pipeline] Whisper.cpp failed (attempt {attempt+1}): {result.stderr}")
                    time.sleep(2 ** attempt)
                    continue
                # Wait for transcript JSON to be stable
                if os.path.exists(transcript_json_path):
                    if not self.wait_for_file_stable(transcript_json_path, min_size=32, stable_time=0.5, timeout=10):
                        print(f"[Pipeline][WARN] Transcript JSON not stable: {transcript_json_path}")
                        continue
                    print(f"[Pipeline][DEBUG] Found transcript JSON: {transcript_json_path}")
                    with open(transcript_json_path, 'r') as f:
                        transcript_json = json.load(f)
                    # Robustly extract transcript text
                    segments = []
                    if isinstance(transcript_json, dict):
                        if 'transcription' in transcript_json:
                            segments = transcript_json['transcription']
                            print(f"[Pipeline][DEBUG] Using 'transcription' key from transcript JSON.")
                        elif 'segments' in transcript_json:
                            segments = transcript_json['segments']
                            print(f"[Pipeline][DEBUG] Using 'segments' key from transcript JSON.")
                        else:
                            print(f"[Pipeline][ERROR] No 'transcription' or 'segments' key in transcript JSON dict.")
                    elif isinstance(transcript_json, list):
                        segments = transcript_json
                        print(f"[Pipeline][DEBUG] Using top-level list from transcript JSON.")
                    else:
                        print(f"[Pipeline][ERROR] Unexpected transcript JSON structure: {type(transcript_json)}")
                    print(f"[Pipeline][DEBUG] Extracted {len(segments)} segments from transcript JSON.")
                    transcript_txt = '\n'.join([seg.get('text', '') for seg in segments if 'text' in seg])
                    if transcript_txt.strip():
                        with open(transcript_path, 'w') as f:
                            f.write(transcript_txt)
                        print(f"[Pipeline] Transcript saved: {transcript_path}")
                    else:
                        print(f"[Pipeline][WARN] No transcript text extracted; .txt not written.")
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
        # Prompt engineering
        if not self.last_summary:
            user_prompt = f"This is the first segment of a meeting recording. Please summarize the following transcript:\n{transcript}"
        else:
            user_prompt = f"This is a continuation of a meeting. Previous summary:\n{self.last_summary}\nNew transcript:\n{transcript}\nPlease update the summary."
        # Prepend system prompt if set
        prompt = self.system_prompt.strip() + "\n\n" + user_prompt if self.system_prompt else user_prompt
        data = {
            "model": self.ollama_model,
            "prompt": prompt,
            "stream": False
        }
        try:
            response = requests.post(f"{self.ollama_url}/api/generate", json=data, timeout=60)
            response.raise_for_status()
            summary = response.json().get("response", "")
            print(f"[Pipeline] Ollama summary: {summary[:120]}...")
            self.last_summary = summary
            # Save segment summary
            segment_path = metadata.get('segment_path') or metadata.get('path') or metadata.get('file') or ''
            if not segment_path:
                print(f"[Pipeline][WARN] No segment_path in metadata, using transcript[:16] as fallback.")
                segment_base = transcript[:16].replace(' ', '_')
                summary_path = os.path.join(os.getcwd(), f"{segment_base}_summary.md")
            else:
                segment_base = os.path.abspath(segment_path).replace('.wav', '')
                summary_path = segment_base + '_summary.md'
            summary_dir = os.path.dirname(summary_path)
            if not os.path.isdir(summary_dir):
                try:
                    os.makedirs(summary_dir, exist_ok=True)
                except Exception as e:
                    print(f"[Pipeline][ERROR] Could not create summary directory {summary_dir}: {e}")
            try:
                with open(summary_path, 'w') as f:
                    f.write(summary)
                print(f"[Pipeline] Summary saved: {summary_path}")
            except Exception as e:
                print(f"[Pipeline][ERROR] Could not write summary file {summary_path}: {e}")
            # Save/update rolling summary
            rolling_path = os.path.join(summary_dir, 'rolling_summary.md')
            try:
                with open(rolling_path, 'w') as f:
                    f.write(self.last_summary)
            except Exception as e:
                print(f"[Pipeline][ERROR] Could not write rolling summary file {rolling_path}: {e}")
            return summary
        except Exception as e:
            print(f"[Pipeline][ERROR] Ollama summarization failed: {e}")
            return ""

    def save_outputs(self, segment_path, transcript, summary, metadata):
        print(f"[Pipeline] (Stub) Saving outputs for {segment_path}")
        # TODO: Implement output management in later step
        # For now, just print
        print(f"Transcript: {transcript}\nSummary: {summary}")

    def wait_for_file_stable(self, path, min_size=32, stable_time=0.5, timeout=10):
        """Wait until file exists, is non-empty, and size is stable for stable_time seconds."""
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
