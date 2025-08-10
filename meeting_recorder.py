#!/usr/bin/env python3

import os
import time
import signal
import argparse
import subprocess
import sys
import threading
from datetime import datetime
import yaml
import json

from audio_sources import find_system_audio_source, find_microphone_source, list_audio_sources
from rec_utils import check_dependencies, save_recording_metadata, get_file_duration, get_file_size_mb, post_process_audio
from processing_pipeline import ProcessingPipeline

class MeetingRecorder:
    def __init__(self, output_dir="~/Recordings/Meetings",
                source_system=None, source_mic=None, combined=True, custom_name=None, segment_duration=300,
                automation_enabled=False, metrics_enabled=False, metrics_dir_name="metrics"):
        # Always use WAV for processing
        self.output_dir = os.path.expanduser(output_dir)
        self.format = "wav"  # Forced WAV
        self.bitrate = None   # Deprecated: bitrate only relevant for mp3 (removed)
        self.system_source = source_system
        self.mic_source = source_mic
        self.combined = combined
        self.custom_name = custom_name
        self.segment_duration = segment_duration  # in seconds
        self.automation_enabled = automation_enabled
        self.metrics_enabled = metrics_enabled
        self.metrics_dir_name = metrics_dir_name
        
        # Initialize state variables
        self.ffmpeg_process = None
        self.recording = False
        self.recording_started = None
        self.current_session_dir = None  # Root of session directory hierarchy
        self.session_metadata_path = None
        self.pipeline = ProcessingPipeline(automation_enabled=automation_enabled)
        self.pipeline.metrics_enabled = metrics_enabled
        self.pipeline.metrics_dir_name = metrics_dir_name
        
        # Setup base output dir
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Log file for recorded meetings (global)
        self.log_file = os.path.join(self.output_dir, "recordings.log")
        if not os.path.exists(self.log_file):
            with open(self.log_file, "a") as f:
                pass
    
    def debug(self, msg):
        """Print a debug message with timestamp"""
        now = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        print(f"{now} {msg}")

    def signal_handler(self, sig, frame):
        """Handle interrupt signals"""
        print("\nShutting down recorder...")
        self.stop_recording()
        sys.exit(0)
    
    def get_audio_sources(self):
        """Get ffmpeg arguments for audio sources based on configuration"""
        if self.combined and self.system_source and self.mic_source:
            self.debug(f"Using combined recording: system={self.system_source}, mic={self.mic_source}")
            return [
                "-f", "pulse", "-i", self.system_source,
                "-f", "pulse", "-i", self.mic_source,
                "-filter_complex", "amix=inputs=2:duration=longest"
            ]
        elif self.system_source:
            self.debug(f"Using system audio source: {self.system_source}")
            return ["-f", "pulse", "-i", self.system_source]
        elif self.mic_source:
            self.debug(f"Using microphone source: {self.mic_source}")
            return ["-f", "pulse", "-i", self.mic_source]
        else:
            # Try to auto-detect sources
            system_source = find_system_audio_source()
            mic_source = find_microphone_source()
            if self.combined and system_source and mic_source:
                self.debug(f"Auto-detected sources - system: {system_source}, mic: {mic_source}")
                return [
                    "-f", "pulse", "-i", system_source,
                    "-f", "pulse", "-i", mic_source,
                    "-filter_complex", "amix=inputs=2:duration=longest"
                ]
            elif system_source:
                self.debug(f"Auto-detected system source: {system_source}")
                return ["-f", "pulse", "-i", system_source]
            elif mic_source:
                self.debug(f"Auto-detected mic source: {mic_source}")
                return ["-f", "pulse", "-i", mic_source]
            self.debug("No specific sources found, using default")
            return ["-f", "pulse", "-i", "default"]

    def log_recording(self, path):
        """Log the recorded file path to the global log file"""
        try:
            with open(self.log_file, "a") as f:
                timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
                f.write(f"{timestamp} {path}\n")
        except Exception as e:
            self.debug(f"Failed to log recording: {e}")
    
    def _init_session_directories(self, session_dir):
        """Create session subdirectory structure"""
        for sub in ["segments", "transcription", "summaries"]:
            os.makedirs(os.path.join(session_dir, sub), exist_ok=True)

    def _write_session_metadata(self, extra=None):
        """Create or update session-level metadata.json"""
        if not self.session_metadata_path:
            return
        base = {
            "start_time": self.recording_started.isoformat() if self.recording_started else None,
            "segment_duration": self.segment_duration,
            "sources": {
                "system": self.system_source,
                "mic": self.mic_source,
                "combined": self.combined
            },
            "format": self.format,
            "automation_enabled": self.automation_enabled
        }
        if extra:
            base.update(extra)
        try:
            with open(self.session_metadata_path, 'w') as f:
                json.dump(base, f, indent=2)
        except Exception as e:
            self.debug(f"Failed to write session metadata: {e}")
    
    def start_recording(self, name=None):
        """Start recording with segmentation into structured hierarchy"""
        if self.ffmpeg_process:
            self.stop_recording()
        # Create date folder
        date_folder = datetime.now().strftime("%Y-%m-%d")
        date_dir = os.path.join(self.output_dir, date_folder)
        os.makedirs(date_dir, exist_ok=True)
        
        # Session folder name
        timestamp = datetime.now().strftime("%H%M%S")
        base_name = name or self.custom_name
        if base_name:
            for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
                base_name = base_name.replace(char, '_')
            session_folder = f"{base_name}_{timestamp}"
        else:
            session_folder = f"meeting_{timestamp}"
        session_dir = os.path.join(date_dir, session_folder)
        self.current_session_dir = session_dir
        self._init_session_directories(session_dir)
        # Pipeline aware of session dir (for metrics)
        self.pipeline.set_session_dir(session_dir)
        
        # Segment output pattern
        segments_dir = os.path.join(session_dir, "segments")
        filename_pattern = os.path.join(segments_dir, "segment_%03d.wav")
        
        # Prepare session metadata path
        self.session_metadata_path = os.path.join(session_dir, "metadata.json")
        self.recording_started = datetime.now()
        self._write_session_metadata()
        
        # Get audio input arguments
        input_args = self.get_audio_sources()
        self.debug(f"FFmpeg input args: {input_args}")
        try:
            cmd = [
                "ffmpeg", "-v", "warning", "-stats",
                *input_args,
                "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
                "-f", "segment", "-segment_time", str(self.segment_duration), filename_pattern
            ]
            self.debug(f"FFmpeg command: {' '.join(cmd)}")
            print(f"Starting segmented recording: {session_dir}")
            self.ffmpeg_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            time.sleep(1)
            if self.ffmpeg_process.poll() is not None:
                print(f"Error: ffmpeg failed to start (exit code {self.ffmpeg_process.returncode})")
                print("Available PulseAudio sources:")
                list_audio_sources()
                return False
            self.recording = True
            
            # Monitor segments
            self._segment_monitor_thread = threading.Thread(
                target=self._monitor_segments,
                args=(segments_dir, filename_pattern, self.recording_started),
                daemon=True
            )
            self._segment_monitor_thread.start()
            
            if self.automation_enabled:
                self.pipeline.start()
            return True
        except Exception as e:
            print(f"Error starting recording: {e}")
            return False

    def _wait_for_stable_file(self, path, min_size=1024, stable_time=1.0, timeout=10):
        """Wait until file exists, is nonzero, and size is stable for stable_time seconds.
        For segment files, also verify audio duration matches expected segment duration."""
        import time
        start = time.time()
        last_size = -1
        stable_since = None
        
        # For segment files, also check audio duration
        is_segment_file = '/segments/' in path and path.endswith('.wav')
        expected_duration = self.segment_duration if is_segment_file else None
        
        while time.time() - start < timeout:
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size >= min_size:
                    # Check if size is stable
                    size_stable = False
                    if size == last_size:
                        if stable_since is None:
                            stable_since = time.time()
                        elif time.time() - stable_since >= stable_time:
                            size_stable = True
                    else:
                        stable_since = None
                    last_size = size
                    
                    # For segment files, also verify audio duration
                    if size_stable and is_segment_file and expected_duration:
                        try:
                            # Get actual audio duration
                            import subprocess
                            result = subprocess.run([
                                'ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
                                '-of', 'csv=p=0', path
                            ], capture_output=True, text=True, timeout=5)
                            
                            if result.returncode == 0:
                                actual_duration = float(result.stdout.strip())
                                # Allow segment to be slightly shorter due to end-of-stream
                                if actual_duration >= (expected_duration - 2.0):
                                    self.debug(f"Segment {path} ready: {actual_duration:.1f}s (expected {expected_duration}s)")
                                    return True
                                else:
                                    #self.debug(f"Segment {path} still growing: {actual_duration:.1f}s / {expected_duration}s")
                                    # Reset stability timer since file is still growing
                                    stable_since = None
                                    continue
                            else:
                                # If ffprobe fails, fall back to size-only check
                                self.debug(f"Could not probe {path}, using size-only check")
                                return True
                        except Exception as e:
                            self.debug(f"Error probing {path}: {e}, using size-only check")
                            return True
                    elif size_stable and not is_segment_file:
                        # Non-segment files just need size stability
                        return True
                        
            time.sleep(0.2)
        return False

    def _monitor_segments(self, segments_dir, filename_pattern, start_time):
        import glob
        seen = set()
        pattern = filename_pattern.replace('%03d', '*')
        while self.recording:
            files = sorted(glob.glob(pattern))
            for f in files:
                if f not in seen and os.path.exists(f):
                    seen.add(f)
                    self.log_recording(f)
                    idx = os.path.splitext(os.path.basename(f))[0].split('_')[-1]
                    metadata = {
                        "segment_path": f,
                        "start_time": start_time.isoformat(),
                        "segment_index": idx,
                        "sources": {
                            "system": self.system_source,
                            "mic": self.mic_source,
                            "combined": self.combined
                        },
                        "format": self.format
                    }
                    save_recording_metadata(f, metadata)
                    if self.automation_enabled:
                        # Use longer timeout for segment files that need to reach full duration
                        timeout = self.segment_duration + 10 if '/segments/' in f else 10
                        if self._wait_for_stable_file(f, min_size=1024, stable_time=1.0, timeout=timeout):
                            self.pipeline.enqueue_segment(f, metadata)
                        else:
                            print(f"[Recorder][WARN] Segment {f} did not become stable/complete in time, skipping automation.")
            time.sleep(2)

    def stop_recording(self, post_process=False, drain=True):
        """Stop the current recording session, optionally drain pipeline."""
        if not self.ffmpeg_process:
            return
        now = datetime.now()
        time_str = now.strftime("[%H:%M:%S]")
        print(f"{time_str} Stopping recording...")
        
        # Terminate ffmpeg process
        self.ffmpeg_process.terminate()
        try:
            self.ffmpeg_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print("Warning: ffmpeg process didn't exit, forcing termination")
            self.ffmpeg_process.kill()
        self.ffmpeg_process = None
        self.recording = False
        print(f"{time_str} Recording stopped")
        
        # Session duration
        duration = None
        if self.recording_started:
            duration = (now - self.recording_started).total_seconds()
        
        # Count segments & compute aggregate size
        segment_count = 0
        total_size_mb = 0.0
        if self.current_session_dir:
            seg_dir = os.path.join(self.current_session_dir, 'segments')
            if os.path.isdir(seg_dir):
                for fname in os.listdir(seg_dir):
                    if fname.endswith('.wav'):
                        segment_count += 1
                        try:
                            total_size_mb += os.path.getsize(os.path.join(seg_dir, fname)) / (1024*1024)
                        except Exception:
                            pass
        
        # Update session metadata
        extra = {
            "end_time": now.isoformat(),
            "duration_seconds": duration,
            "segment_count": segment_count,
            "total_size_mb": round(total_size_mb, 2)
        }
        self._write_session_metadata(extra=extra)
        
        # Graceful drain: wait for pipeline to finish queued work
        if drain and self.automation_enabled:
            self.pipeline.drain()
        
        # Final summary generation (copy rolling_summary if exists)
        summaries_dir = os.path.join(self.current_session_dir, 'summaries') if self.current_session_dir else None
        if summaries_dir and os.path.isdir(summaries_dir):
            rolling_path = os.path.join(summaries_dir, 'rolling_summary.md')
            final_path = os.path.join(summaries_dir, 'final_summary.md')
            if os.path.exists(rolling_path):
                try:
                    with open(rolling_path, 'r') as rf, open(final_path, 'w') as wf:
                        wf.write(rf.read())
                    print(f"Final summary saved: {final_path}")
                except Exception as e:
                    print(f"[Recorder][WARN] Could not create final summary: {e}")
        
        # Print session summary
        if self.current_session_dir:
            print("\nSession Summary:")
            print(f"Session directory: {self.current_session_dir}")
            if duration:
                minutes, seconds = divmod(int(duration), 60)
                hours, minutes = divmod(minutes, 60)
                if hours:
                    print(f"Duration: {hours}h {minutes}m {seconds}s")
                else:
                    print(f"Duration: {minutes}m {seconds}s")
            print(f"Segments: {segment_count}")
            print(f"Total size: {total_size_mb:.2f} MB")
            if self.session_metadata_path:
                print(f"Metadata: {self.session_metadata_path}")
        
        self.recording_started = None
        self.current_session_dir = None
        self.session_metadata_path = None
    
    def print_status(self):
        """Print current recording status"""
        if self.recording:
            duration = 0
            if self.recording_started:
                duration = (datetime.now() - self.recording_started).total_seconds()
            minutes, seconds = divmod(int(duration), 60)
            hours, minutes = divmod(minutes, 60)
            if hours > 0:
                time_str = f"{hours}h {minutes}m {seconds}s"
            else:
                time_str = f"{minutes}m {seconds}s"
            print(f"Recording in progress ({time_str})")
            if self.current_session_dir:
                print(f"Session: {self.current_session_dir}")
        else:
            print("Not recording")
    
    def interactive_mode(self):
        """Start an interactive recording session"""
        print("Meeting Recorder Interactive Mode")
        print("Commands: start, stop, status, post (post-process), quit")
        print("Press Enter to see current status")
        
        while True:
            try:
                cmd = input("\n> ").strip().lower()
                if cmd == "start":
                    name = input("Recording name (optional): ").strip() or None
                    self.start_recording(name)
                elif cmd == "stop":
                    self.stop_recording(False)
                elif cmd in ("status", ""):
                    self.print_status()
                elif cmd == "post":
                    print("Post-processing now only applies to individual files manually (not implemented for session).")
                elif cmd in ("quit", "exit"):
                    if self.recording:
                        confirm = input("Recording in progress. Stop and exit? (y/N): ").strip().lower()
                        if confirm == "y":
                            self.stop_recording()
                            break
                    else:
                        break
                else:
                    print("Unknown command")
            except KeyboardInterrupt:
                print("\nUse 'quit' to exit or 'stop' to stop recording")
            except Exception as e:
                print(f"Error: {e}")
        print("Exiting...")

if __name__ == "__main__":
    # Load config.yaml if present
    config = {}
    config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f) or {}

    parser = argparse.ArgumentParser(description="Record meeting audio from system and/or microphone")
    def cfg(key, default=None):
        v = config.get(key, default)
        return None if v == 'null' else v

    parser.add_argument("--output-dir", "-o", default=cfg("output_dir", "~/Recordings/Meetings"), help="Output directory root for recordings")
    # Removed --format (always wav)
    # Removed --bitrate (not applicable for wav)
    parser.add_argument("--list-sources", "-l", action="store_true", help="List available PulseAudio sources and exit")
    parser.add_argument("--source-system", "-s", default=cfg("source_system"), help="Specify system audio source")
    parser.add_argument("--source-mic", "-m", default=cfg("source_mic"), help="Specify microphone source")
    parser.add_argument("--system-only", action="store_true", default=cfg("system_only", False), help="Record only system audio (no microphone)")
    parser.add_argument("--mic-only", action="store_true", default=cfg("mic_only", False), help="Record only microphone (no system audio)")
    parser.add_argument("--name", "-n", default=cfg("name"), help="Custom session name prefix")
    parser.add_argument("--start", action="store_true", help="Start recording immediately")
    parser.add_argument("--segment-duration", type=int, default=cfg("segment_duration", 300), help="Segment duration in seconds (default: 300)")
    parser.add_argument("--enable-automation", action="store_true", default=cfg("enable_automation", False), help="Enable automated transcription and summarization pipeline")
    # Whisper backend and params
    parser.add_argument("--whisper-backend", choices=["cli", "pywhispercpp", "server"], default=cfg("whisper_backend", "cli"), help="Transcription backend: CLI (default), pywhispercpp binding, or HTTP server")
    parser.add_argument("--whisper-path", default=cfg("whisper_path", "/usr/local/bin/whisper"), help="Path to Whisper.cpp executable (default: /usr/local/bin/whisper)")
    parser.add_argument("--whisper-model", default=cfg("whisper_model", "base"), help="Whisper.cpp model path or size (tiny|base|small|medium|large)")
    parser.add_argument("--whisper-language", default=cfg("whisper_language", "auto"), help="Language code for Whisper.cpp (default: auto)")
    parser.add_argument("--whisper-threads", type=int, default=cfg("whisper_threads", 4), help="CPU threads for Whisper.cpp (default: 4)")
    parser.add_argument("--whisper-server-url", default=cfg("whisper_server_url", "http://127.0.0.1:8080"), help="Whisper.cpp server URL (default: http://127.0.0.1:8080)")
    parser.add_argument("--whisper-server-timeout", type=int, default=cfg("whisper_server_timeout", 120), help="Whisper.cpp server timeout in seconds (default: 120)")
    parser.add_argument("--pad-silence-ms", type=int, default=cfg("pad_silence_ms", 300), help="Pad this many milliseconds of trailing silence per segment before transcription (default: 300)")
    parser.add_argument("--pre-roll-ms", type=int, default=cfg("pre_roll_ms", 300), help="Prepend this many milliseconds from previous segment for transcription context (default: 300)")
    # Ollama
    parser.add_argument("--ollama-url", default=cfg("ollama_url", "http://localhost:11434"), help="Ollama server URL (default: http://localhost:11434)")
    parser.add_argument("--ollama-model", default=cfg("ollama_model", "llama2"), help="Ollama model name (default: llama2)")
    parser.add_argument("--ollama-system-prompt", default=cfg("ollama_system_prompt", None), help="Ollama system prompt (persona/context)")
    parser.add_argument("--ollama-prompt-initial", default=cfg("ollama_prompt_initial", None), help="(Reserved) Custom initial summary prompt")
    parser.add_argument("--ollama-prompt-continuation", default=cfg("ollama_prompt_continuation", None), help="(Reserved) Custom continuation summary prompt")
    parser.add_argument("--metrics-enabled", action="store_true", help="Enable metrics collection (timings, backlog) for automation pipeline")
    parser.add_argument("--metrics-dir", default=cfg("metrics_dir", "metrics"), help="Relative directory name under session root for metrics output (default: metrics)")

    args = parser.parse_args()

    if args.list_sources:
        list_audio_sources()
        sys.exit(0)

    if not check_dependencies():
        sys.exit(1)

    combined = not (args.system_only or args.mic_only)
    system_source = args.source_system if not args.mic_only else None
    mic_source = args.source_mic if not args.system_only else None

    recorder = MeetingRecorder(
        output_dir=args.output_dir,
        source_system=system_source,
        source_mic=mic_source,
        combined=combined,
        custom_name=args.name,
        segment_duration=args.segment_duration,
        automation_enabled=args.enable_automation,
        metrics_enabled=args.metrics_enabled,
        metrics_dir_name=args.metrics_dir
    )

    recorder.pipeline.whisper_backend = args.whisper_backend
    recorder.pipeline.whisper_path = args.whisper_path
    recorder.pipeline.whisper_model = args.whisper_model
    recorder.pipeline.whisper_language = args.whisper_language
    recorder.pipeline.whisper_threads = args.whisper_threads
    recorder.pipeline.whisper_server_url = args.whisper_server_url
    recorder.pipeline.whisper_server_timeout = args.whisper_server_timeout
    recorder.pipeline.pad_silence_ms = max(0, int(args.pad_silence_ms or 0))
    recorder.pipeline.pre_roll_ms = max(0, int(args.pre_roll_ms or 0))
    recorder.pipeline.ollama_url = args.ollama_url
    recorder.pipeline.ollama_model = args.ollama_model
    if args.ollama_system_prompt is not None:
        recorder.pipeline.system_prompt = args.ollama_system_prompt

    if args.start:
        print("Recording started. Press Ctrl+C to stop.")
        recorder.start_recording(args.name)
        try:
            while recorder.recording:
                time.sleep(1)
                if int(time.time()) % 10 == 0:
                    recorder.print_status()
        except KeyboardInterrupt:
            print("\nStopping recording...")
            recorder.stop_recording(False)
    else:
        recorder.interactive_mode()
