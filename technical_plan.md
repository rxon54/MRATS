# Technical Implementation Plan

> **Status Note (2025-08-10): IMPLEMENTATION COMPLETE** ✅
> 
> This plan reflected the initial simplification phase transitioning from the Spotirec tool. **The implementation has been completed and significantly expanded beyond the original scope:**
> 
> **✅ Completed Beyond Plan**:
> - Full meeting recorder automation with segmentation
> - Whisper.cpp integration (CLI, pywhispercpp, and HTTP server backends)
> - Ollama summarization with rolling context
> - Decoupled processing pipeline with queues
> - Race condition fixes and reliability improvements
> - Comprehensive documentation and testing
> 
> **Current Status**: Production-ready system with advanced features including distributed processing, automatic retry mechanisms, and robust error handling. See README.md and CHANGELOG.md for current capabilities.

## Overview
This document outlined the technical approach for simplifying the Spotirec tool into a focused meeting audio recorder. **The implementation has been completed successfully and expanded well beyond the original scope.**

## Core Components to Implement

### 1. Recording Core
We'll remove the ncspot detection, smart cut functionality, and ID3 tagging, focusing instead on:

- Direct audio recording with manual start/stop
- System audio + microphone capture
- Simple output file management

### 2. Required Code Changes

#### From `ncspot_recorder_simple.py` to `meeting_recorder.py`:

1. **Remove These Components**:
   - All playerctl/MPRIS interactions
   - Track detection logic
   - Smart cut functionality
   - ID3 tagging features

2. **Simplify Class Structure**:
   ```python
   class MeetingRecorder:
       def __init__(self, output_dir="~/Recordings/Meetings", format="mp3", 
                  bitrate="192k", source_system=None, source_mic=None, combined=True):
           # Initialize with simplified config
           self.output_dir = os.path.expanduser(output_dir)
           self.format = format
           self.bitrate = bitrate
           self.system_source = source_system
           self.mic_source = source_mic
           self.combined = combined
           
           # Recording state
           self.ffmpeg_process = None
           self.recording = False
           self.recording_started = None
           
           # Setup
           os.makedirs(self.output_dir, exist_ok=True)
           
           # Register signal handlers
           signal.signal(signal.SIGINT, self.signal_handler)
           signal.signal(signal.SIGTERM, self.signal_handler)
           
           # Log file
           self.log_file = os.path.join(self.output_dir, "recordings.log")
   ```

3. **Recording Functions**:

   ```python
   def start_recording(self, name=None):
       """Start recording with optional custom name"""
       if self.ffmpeg_process:
           self.stop_recording()
           
       # Create output directory based on date
       date_folder = datetime.now().strftime("%Y-%m-%d")
       dir_path = os.path.join(self.output_dir, date_folder)
       os.makedirs(dir_path, exist_ok=True)
       
       # Create filename with timestamp
       timestamp = datetime.now().strftime("%H%M%S")
       if name:
           filename = f"{name}_{timestamp}.{self.format}"
       else:
           filename = f"recording_{timestamp}.{self.format}"
       
       output_path = os.path.join(dir_path, filename)
       
       # Get audio input arguments based on selected sources
       input_args = self.get_audio_sources()
       
       # Build ffmpeg command
       cmd = [
           "ffmpeg", "-v", "warning", "-stats", 
           *input_args,
           "-c:a", "libmp3lame" if self.format == "mp3" else "pcm_s16le",
           "-b:a", self.bitrate, "-y", output_path
       ]
       
       print(f"Starting recording: {output_path}")
       
       # Start recording process
       self.ffmpeg_process = subprocess.Popen(
           cmd, 
           stdout=subprocess.PIPE,
           stderr=subprocess.PIPE,
           text=True
       )
       
       # Check if process started correctly
       time.sleep(1)
       if self.ffmpeg_process.poll() is not None:
           print(f"Error: ffmpeg failed to start (exit code {self.ffmpeg_process.returncode})")
           return False
       
       self.recording = True
       self.recording_started = datetime.now()
       self.current_output_path = output_path
       self.log_recording(output_path)
       return True
   ```

4. **Audio Source Management**:

   ```python
   def get_audio_sources(self):
       """Get ffmpeg arguments for audio sources based on configuration"""
       if self.combined and self.system_source and self.mic_source:
           # Return combined recording setup
           return [
               "-f", "pulse", "-i", self.system_source,
               "-f", "pulse", "-i", self.mic_source,
               "-filter_complex", "amix=inputs=2:duration=longest"
           ]
       elif self.system_source:
           # Return system audio only
           return ["-f", "pulse", "-i", self.system_source]
       elif self.mic_source:
           # Return microphone only
           return ["-f", "pulse", "-i", self.mic_source]
       else:
           # Try to auto-detect sources
           system_source = self.find_system_audio_source()
           mic_source = self.find_microphone_source()
           
           if self.combined and system_source and mic_source:
               return [
                   "-f", "pulse", "-i", system_source,
                   "-f", "pulse", "-i", mic_source,
                   "-filter_complex", "amix=inputs=2:duration=longest"
               ]
           elif system_source:
               return ["-f", "pulse", "-i", system_source]
           elif mic_source:
               return ["-f", "pulse", "-i", mic_source]
               
           # Default fallback
           return ["-f", "pulse", "-i", "default"]
   ```

### 3. Command-Line Interface

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record meeting audio from system and/or microphone")
    parser.add_argument("--output-dir", "-o", default="~/Recordings/Meetings", 
                      help="Output directory for recordings")
    parser.add_argument("--format", "-f", default="mp3", choices=["mp3", "wav"], 
                      help="Audio format for recordings")
    parser.add_argument("--bitrate", "-b", default="192k", 
                      help="Bitrate for audio encoding (for mp3)")
    parser.add_argument("--list-sources", "-l", action="store_true",
                      help="List available PulseAudio sources and exit")
    parser.add_argument("--source-system", "-s", help="Specify system audio source")
    parser.add_argument("--source-mic", "-m", help="Specify microphone source")
    parser.add_argument("--system-only", action="store_true",
                      help="Record only system audio (no microphone)")
    parser.add_argument("--mic-only", action="store_true",
                      help="Record only microphone (no system audio)")
    parser.add_argument("--name", "-n", help="Custom name prefix for recordings")
    parser.add_argument("--start", action="store_true",
                      help="Start recording immediately")
                      
    args = parser.parse_args()
    
    if args.list_sources:
        list_audio_sources()
        sys.exit(0)
        
    # Determine recording mode
    combined = not (args.system_only or args.mic_only)
    
    # Create recorder
    recorder = MeetingRecorder(
        output_dir=args.output_dir,
        format=args.format,
        bitrate=args.bitrate,
        source_system=args.source_system if not args.mic_only else None,
        source_mic=args.source_mic if not args.system_only else None,
        combined=combined
    )
    
    # Start interactive mode
    if args.start:
        print("Recording started. Press Ctrl+C to stop.")
        recorder.start_recording(args.name)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping recording...")
            recorder.stop_recording()
    else:
        recorder.interactive_mode()
```

### 4. Utility Functions in `rec_utils.py`

Simplify the utility module to focus on audio source detection:

```python
def list_audio_sources():
    """List available PulseAudio sources, marking system audio vs microphones"""
    try:
        print("Available PulseAudio sources:")
        sources_info = subprocess.run(["pactl", "list", "sources"], 
                                    capture_output=True, text=True).stdout
        
        # Parse sources, identifying monitors (system audio) vs inputs (mics)
        current_source = None
        for line in sources_info.split('\n'):
            if line.startswith('Source #'):
                current_source = {'id': line.split('#')[1].strip()}
                print(f"\nSource {current_source['id']}:")
            elif current_source is not None:
                if 'Name: ' in line:
                    current_source['name'] = line.split('Name: ')[1].strip()
                    print(f"  Name: {current_source['name']}")
                elif 'monitor' in line.lower():
                    current_source['type'] = 'system'
                    print(f"  [SYSTEM AUDIO]")
                elif 'input' in line.lower():
                    current_source['type'] = 'microphone'
                    print(f"  [MICROPHONE]")
                    
        print("\nTo use specific sources:")
        print("  For system audio: --source-system 'source_name'")
        print("  For microphone: --source-mic 'source_name'")
    except Exception as e:
        print(f"Error listing sources: {e}")

def check_dependencies():
    """Check if required tools are installed"""
    tools_missing = False
    
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, capture_output=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        print("Error: ffmpeg is not installed. Please install it with:")
        print("  sudo apt-get install ffmpeg")
        tools_missing = True
    
    try:
        subprocess.run(["pactl", "--version"], check=True, capture_output=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        print("Error: PulseAudio utils not installed. Please install with:")
        print("  sudo apt-get install pulseaudio-utils")
        tools_missing = True
    
    return not tools_missing

def find_system_audio_source():
    """Find the default system audio source"""
    try:
        sources_info = subprocess.run(["pactl", "list", "sources"], 
                                    capture_output=True, text=True).stdout
        
        # Look for monitor sources
        current_source = None
        monitor_sources = []
        
        for line in sources_info.split('\n'):
            if line.startswith('Source #'):
                current_source = {}
            elif current_source is not None:
                if 'Name: ' in line:
                    current_source['name'] = line.split('Name: ')[1].strip()
                elif 'monitor' in line.lower():
                    monitor_sources.append(current_source['name'])
        
        # Return first monitor source found
        if monitor_sources:
            return monitor_sources[0]
    except Exception:
        pass
    
    return None

def find_microphone_source():
    """Find the default microphone source"""
    try:
        sources_info = subprocess.run(["pactl", "list", "sources"], 
                                    capture_output=True, text=True).stdout
        
        # Look for non-monitor sources (likely microphones)
        current_source = None
        mic_sources = []
        
        for line in sources_info.split('\n'):
            if line.startswith('Source #'):
                current_source = {'is_monitor': False}
            elif current_source is not None:
                if 'Name: ' in line:
                    current_source['name'] = line.split('Name: ')[1].strip()
                elif 'monitor' in line.lower():
                    current_source['is_monitor'] = True
                elif 'State: RUNNING' in line:
                    current_source['active'] = True
            
            # End of source block, check if it's a non-monitor and add to list
            if current_source and line.strip() == '' and 'name' in current_source:
                if not current_source['is_monitor']:
                    # Prioritize active mics
                    if current_source.get('active', False):
                        mic_sources.insert(0, current_source['name'])
                    else:
                        mic_sources.append(current_source['name'])
                current_source = None
        
        # Return first microphone source found
        if mic_sources:
            return mic_sources[0]
    except Exception:
        pass
    
    return None
```

## Testing Plan

1. Test basic audio source detection
2. Test recording with system audio only
3. Test recording with microphone only
4. Test combined recording (system + mic)
5. Test manual start/stop functionality
6. Verify output file naming and organization

## Implementation Checklist

1. Create simplified `audio_sources.py` with source detection functions
2. Remove ID3 and smart-cut code from the main recorder class
3. Implement the simplified `MeetingRecorder` class
4. Add combined audio recording capability
5. Create basic CLI interface for recording control
6. Test with different audio sources and recording modes
