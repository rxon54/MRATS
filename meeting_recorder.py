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

from audio_sources import find_system_audio_source, find_microphone_source, list_audio_sources
from rec_utils import check_dependencies, save_recording_metadata, get_file_duration, get_file_size_mb, post_process_audio
from processing_pipeline import ProcessingPipeline

class MeetingRecorder:
    def __init__(self, output_dir="~/Recordings/Meetings", format="wav", bitrate="192k",
                source_system=None, source_mic=None, combined=True, custom_name=None, segment_duration=300,
                automation_enabled=False):
        # Always use WAV for processing
        self.output_dir = os.path.expanduser(output_dir)
        self.format = "wav"  # Force WAV for all processing
        self.bitrate = bitrate
        self.system_source = source_system
        self.mic_source = source_mic
        self.combined = combined
        self.custom_name = custom_name
        self.segment_duration = segment_duration  # in seconds
        self.automation_enabled = automation_enabled
        
        # Initialize state variables
        self.ffmpeg_process = None
        self.recording = False
        self.recording_started = None
        self.current_output_path = None
        self.pipeline = ProcessingPipeline(automation_enabled=automation_enabled)
        
        # Setup
        os.makedirs(self.output_dir, exist_ok=True)
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Log file for recorded meetings
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
        """Log the recorded file path to the log file"""
        try:
            with open(self.log_file, "a") as f:
                timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
                f.write(f"{timestamp} {path}\n")
        except Exception as e:
            self.debug(f"Failed to log recording: {e}")
    
    def start_recording(self, name=None):
        """Start recording with optional custom name, using segmentation"""
        if self.ffmpeg_process:
            self.stop_recording()
        # Create output directory based on date
        date_folder = datetime.now().strftime("%Y-%m-%d")
        dir_path = os.path.join(self.output_dir, date_folder)
        os.makedirs(dir_path, exist_ok=True)
        
        # Create filename pattern with timestamp
        timestamp = datetime.now().strftime("%H%M%S")
        if name or self.custom_name:
            custom_name = name or self.custom_name
            if custom_name:
                # Sanitize name
                for char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
                    custom_name = custom_name.replace(char, '_')
                filename_pattern = f"{custom_name}_{timestamp}_%03d.wav"
            else:
                filename_pattern = f"recording_{timestamp}_%03d.wav"
        else:
            filename_pattern = f"recording_{timestamp}_%03d.wav"
        
        output_pattern = os.path.join(dir_path, filename_pattern)
        
        # Get audio input arguments based on selected sources
        input_args = self.get_audio_sources()
        self.debug(f"FFmpeg input args: {input_args}")
        try:
            # Build ffmpeg command for segmented WAV
            cmd = [
                "ffmpeg", "-v", "warning", "-stats",
                *input_args,
                "-c:a", "pcm_s16le", "-ar", "16000", "-ac", "1",
                "-f", "segment", "-segment_time", str(self.segment_duration), output_pattern
            ]
            self.debug(f"FFmpeg command: {' '.join(cmd)}")
            print(f"Starting segmented recording: {output_pattern}")
            self.ffmpeg_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            time.sleep(1)
            if self.ffmpeg_process.poll() is not None:
                print(f"Error: ffmpeg failed to start (exit code {self.ffmpeg_process.returncode})")
                # List available sources for debugging
                print("Available PulseAudio sources:")
                list_audio_sources()
                return False
            self.recording = True
            self.recording_started = datetime.now()
            self.current_output_path = output_pattern
            
            # Start a thread to monitor for new segments
            self._segment_monitor_thread = threading.Thread(
                target=self._monitor_segments,
                args=(dir_path, filename_pattern, self.recording_started),
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
        """Wait until file exists, is nonzero, and size is stable for stable_time seconds."""
        import time
        start = time.time()
        last_size = -1
        stable_since = None
        while time.time() - start < timeout:
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size >= min_size:
                    if size == last_size:
                        if stable_since is None:
                            stable_since = time.time()
                        elif time.time() - stable_since >= stable_time:
                            return True
                    else:
                        stable_since = None
                    last_size = size
            time.sleep(0.2)
        return False

    def _monitor_segments(self, dir_path, filename_pattern, start_time):
        import glob
        seen = set()
        pattern = os.path.join(dir_path, filename_pattern.replace('%03d', '*'))
        while self.recording:
            files = sorted(glob.glob(pattern))
            for f in files:
                if f not in seen and os.path.exists(f):
                    seen.add(f)
                    self.log_recording(f)
                    # Save metadata for this segment
                    idx = f.split('_')[-1].split('.')[0]
                    metadata = {
                        "start_time": start_time.isoformat(),
                        "segment_index": idx,
                        "sources": {
                            "system": self.system_source,
                            "mic": self.mic_source,
                            "combined": self.combined
                        },
                        "format": self.format,
                        "bitrate": self.bitrate
                    }
                    save_recording_metadata(f, metadata)
                    # Wait for file to be nonzero and stable before processing
                    if self.automation_enabled:
                        if self._wait_for_stable_file(f, min_size=1024, stable_time=1.0, timeout=10):
                            self.pipeline.enqueue_segment(f, metadata)
                        else:
                            print(f"[Recorder][WARN] Segment {f} did not become stable/nonzero in time, skipping automation.")
            time.sleep(2)

    def stop_recording(self, post_process=False):
        """Stop the current recording and optionally post-process"""
        if not self.ffmpeg_process:
            return
            
        now = datetime.now()
        time_str = now.strftime("[%H:%M:%S]")
        print(f"{time_str} Stopping recording...")
        
        # Store output path for post-processing
        output_path = self.current_output_path
        
        # Calculate duration
        duration = None
        if self.recording_started:
            duration = (now - self.recording_started).total_seconds()
        
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
        
        # Update metadata with final information
        if output_path and os.path.exists(output_path):
            # Get accurate duration from the file
            file_duration = get_file_duration(output_path)
            if not file_duration and duration:
                file_duration = duration
                
            # Get file size
            file_size = get_file_size_mb(output_path)
            
            # Update metadata
            metadata = {
                "start_time": self.recording_started.isoformat() if self.recording_started else None,
                "end_time": now.isoformat(),
                "duration_seconds": file_duration,
                "file_size_mb": file_size,
                "sources": {
                    "system": self.system_source,
                    "mic": self.mic_source,
                    "combined": self.combined
                },
                "format": self.format,
                "bitrate": self.bitrate
            }
            
            save_recording_metadata(output_path, metadata)
            
            # Apply post-processing if requested
            if post_process:
                print("Applying audio post-processing...")
                result = post_process_audio(
                    output_path, 
                    noise_reduce=True,
                    normalize=True,
                    enhance_speech=True
                )
                if result:
                    print("Post-processing complete")
                else:
                    print("Post-processing failed")
            
            # Print recording summary
            print("\nRecording Summary:")
            print(f"File: {os.path.basename(output_path)}")
            
            if file_duration:
                minutes, seconds = divmod(int(file_duration), 60)
                print(f"Duration: {minutes}m {seconds}s")
            
            if file_size:
                print(f"Size: {file_size:.2f} MB")
                
            print(f"Location: {output_path}")
            print(f"Metadata: {os.path.splitext(output_path)[0]}.json")
            
        self.recording_started = None
        self.current_output_path = None
    
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
            if self.current_output_path:
                print(f"Output: {self.current_output_path}")
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
                    name = input("Recording name (optional): ").strip()
                    if not name:
                        name = None
                    self.start_recording(name)
                elif cmd == "stop":
                    post_process = input("Apply post-processing? (y/N): ").strip().lower() == "y"
                    self.stop_recording(post_process)
                elif cmd == "status" or cmd == "":
                    self.print_status()
                elif cmd == "post":
                    if self.current_output_path:
                        print("Cannot post-process while recording")
                    else:
                        path = input("Enter path to recording file: ").strip()
                        if os.path.exists(path):
                            print("Applying post-processing...")
                            result = post_process_audio(
                                path,
                                noise_reduce=True,
                                normalize=True,
                                enhance_speech=True
                            )
                            if result:
                                print("Post-processing complete")
                            else:
                                print("Post-processing failed")
                        else:
                            print(f"File not found: {path}")
                elif cmd == "quit" or cmd == "exit":
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
    # Helper to get config value or fallback
    def cfg(key, default=None):
        v = config.get(key, default)
        # argparse expects None for unset option, not 'null' string
        return None if v == 'null' else v

    parser.add_argument("--output-dir", "-o", default=cfg("output_dir", "~/Recordings/Meetings"), help="Output directory for recordings")
    parser.add_argument("--format", "-f", default=cfg("format", "wav"), choices=["mp3", "wav"], help="Audio format for recordings")
    parser.add_argument("--bitrate", "-b", default=cfg("bitrate", "192k"), help="Bitrate for audio encoding (for mp3)")
    parser.add_argument("--list-sources", "-l", action="store_true", help="List available PulseAudio sources and exit")
    parser.add_argument("--source-system", "-s", default=cfg("source_system"), help="Specify system audio source")
    parser.add_argument("--source-mic", "-m", default=cfg("source_mic"), help="Specify microphone source")
    parser.add_argument("--system-only", action="store_true", default=cfg("system_only", False), help="Record only system audio (no microphone)")
    parser.add_argument("--mic-only", action="store_true", default=cfg("mic_only", False), help="Record only microphone (no system audio)")
    parser.add_argument("--name", "-n", default=cfg("name"), help="Custom name prefix for recordings")
    parser.add_argument("--start", action="store_true", help="Start recording immediately")
    parser.add_argument("--post-process", "-p", action="store_true", default=cfg("post_process", False), help="Apply post-processing after recording stops")
    parser.add_argument("--segment-duration", type=int, default=cfg("segment_duration", 300), help="Segment duration in seconds (default: 300)")
    parser.add_argument("--enable-automation", action="store_true", default=cfg("enable_automation", False), help="Enable automated transcription and summarization pipeline")
    parser.add_argument("--whisper-path", default=cfg("whisper_path", "/usr/local/bin/whisper"), help="Path to Whisper.cpp executable (default: /usr/local/bin/whisper)")
    parser.add_argument("--whisper-model", default=cfg("whisper_model", "base"), help="Whisper.cpp model size (tiny|base|small|medium|large)")
    parser.add_argument("--whisper-language", default=cfg("whisper_language", "auto"), help="Language code for Whisper.cpp (default: auto)")
    parser.add_argument("--whisper-threads", type=int, default=cfg("whisper_threads", 4), help="CPU threads for Whisper.cpp (default: 4)")
    parser.add_argument("--ollama-url", default=cfg("ollama_url", "http://localhost:11434"), help="Ollama server URL (default: http://localhost:11434)")
    parser.add_argument("--ollama-model", default=cfg("ollama_model", "llama2"), help="Ollama model name (default: llama2)")
    parser.add_argument("--ollama-system-prompt", default=cfg("ollama_system_prompt", None), help="Ollama system prompt (persona/context)")
    parser.add_argument("--ollama-prompt-initial", default=cfg("ollama_prompt_initial", None), help="Ollama initial summary prompt")
    parser.add_argument("--ollama-prompt-continuation", default=cfg("ollama_prompt_continuation", None), help="Ollama rolling summary prompt")
                      
    args = parser.parse_args()
    
    if args.list_sources:
        list_audio_sources()
        sys.exit(0)
        
    if not check_dependencies():
        sys.exit(1)
        
    # Determine recording mode
    combined = not (args.system_only or args.mic_only)
    system_source = args.source_system if not args.mic_only else None
    mic_source = args.source_mic if not args.system_only else None
    
    # Create recorder
    recorder = MeetingRecorder(
        output_dir=args.output_dir,
        format=args.format,
        bitrate=args.bitrate,
        source_system=system_source,
        source_mic=mic_source,
        combined=combined,
        custom_name=args.name,
        segment_duration=args.segment_duration,
        automation_enabled=args.enable_automation
    )
    # Pass whisper config to pipeline
    recorder.pipeline.whisper_path = args.whisper_path
    recorder.pipeline.whisper_model = args.whisper_model
    recorder.pipeline.whisper_language = args.whisper_language
    recorder.pipeline.whisper_threads = args.whisper_threads
    # Pass Ollama config to pipeline
    recorder.pipeline.ollama_url = args.ollama_url
    recorder.pipeline.ollama_model = args.ollama_model
    if args.ollama_system_prompt is not None:
        recorder.pipeline.system_prompt = args.ollama_system_prompt
    # Optionally, you can also pass initial/continuation prompts if you wire them into the pipeline logic
    
    # Start recording mode
    if args.start:
        print("Recording started. Press Ctrl+C to stop.")
        recorder.start_recording(args.name)
        try:
            while recorder.recording:
                time.sleep(1)
                # Display duration every 10 seconds
                if int(time.time()) % 10 == 0:
                    recorder.print_status()
        except KeyboardInterrupt:
            print("\nStopping recording...")
            recorder.stop_recording(args.post_process)
    else:
        recorder.interactive_mode()
