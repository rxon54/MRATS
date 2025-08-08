# Meeting Recorder Adaptation Plan

This document outlines the technical approach for converting the Spotirec music recording tool into a meeting recording application.

## Code Structure Analysis

After analyzing the codebase, here are the key components we'll need to modify:

### Core Components to Modify

1. **Class & File Renaming**
   - Rename `NcspotRecorder` to `MeetingRecorder`
   - Rename `ncspot_recorder_simple.py` to `meeting_recorder.py`
   - Update imports and documentation

2. **Meeting Detection & Audio Source**
   - Replace `get_current_track()` with `detect_active_meeting()`
   - Replace `get_track_from_snap()` with `detect_meeting_from_process()`
   - Enhance `get_audio_source()` to detect meeting-specific audio sources
   - Add simultaneous recording capability (system audio + microphone)

3. **Metadata Management**
   - Create a new `meeting_metadata.py` file
   - Replace music metadata (artist, album, title) with meeting metadata
   - Update ID3 tagging to use meeting-appropriate fields
   - Add JSON/YAML metadata export

4. **Recording Logic**
   - Update `start_recording()` to handle meeting context
   - Modify `stop_recording()` to include post-processing hooks
   - Replace `precise_cut_window()` with `silence_detection_window()`
   - Replace `smart_cut_recording()` with speech activity monitoring
   - Update `check_and_record()` for meetings

5. **File Organization**
   - Update file naming and path structure for meetings
   - Implement meeting-specific folder organization

6. **CLI Arguments**
   - Update `argparse` definitions to replace music-specific options with meeting options
   - Add new meeting-specific command line parameters

## Detailed Implementation Changes

### 1. Meeting Detection (`get_current_track()` replacement)

```python
def detect_active_meeting(self):
    """Detect active meeting applications and their status"""
    meeting_info = None
    status = "Inactive"
    
    # Check for various meeting applications
    for platform in ["zoom", "teams", "meet", "webex"]:
        if meeting_info := self.detect_platform_meeting(platform):
            status = "Active"
            break
    
    # If specific detection failed, try process-based detection
    if not meeting_info and (meeting_info := self.detect_meeting_from_process()):
        status = "Active"
    
    # Create standard meeting metadata structure
    if meeting_info:
        # Add duration tracking
        if not self.current_meeting or self.current_meeting["id"] != meeting_info["id"]:
            self.meeting_start_time = datetime.now()
        
        # Calculate duration if we're updating same meeting
        if self.current_meeting and self.current_meeting["id"] == meeting_info["id"]:
            duration = (datetime.now() - self.meeting_start_time).total_seconds()
            meeting_info["duration_sec"] = duration
    
    return meeting_info, status
```

### 2. Audio Source Detection Enhancement

```python
def get_meeting_audio_source(self):
    """Find the best audio source for recording meetings"""
    if self.audio_source:
        return ["-f", "pulse", "-i", self.audio_source]
    
    # First check for platform-specific sources
    platform_source = self.get_platform_specific_source()
    if platform_source:
        return platform_source
    
    # If dual recording mode is enabled (system + mic)
    if self.dual_recording:
        # Get system audio and microphone inputs
        system_source = self.get_system_audio_source()
        mic_source = self.get_microphone_source()
        
        if system_source and mic_source:
            # Use ffmpeg filter to mix both sources
            return [
                *system_source, *mic_source,
                "-filter_complex", "amix=inputs=2:duration=longest"
            ]
    
    # Default to standard source detection
    return self.get_audio_source()
```

### 3. Metadata Handling

The `meeting_metadata.py` file will handle:
- Meeting-specific metadata fields
- Export metadata to JSON/YAML
- Conversion between metadata and ID3 tags
- Integration with calendar systems (future)

### 4. Recording Control Flow

```python
def check_and_record(self):
    """Check for active meeting and start recording if needed"""
    meeting_info, status = self.detect_active_meeting()
    
    if status == "Active" and meeting_info:
        # If we have a new meeting or no active recording, start recording
        if not self.current_meeting or self.current_meeting["id"] != meeting_info["id"]:
            print("New meeting detected, starting recording")
            if self.recording:
                self.stop_recording()
            time.sleep(0.5)  # Slight delay to ensure meeting audio is flowing
            self.start_recording(meeting_info)
        elif not self.recording:
            # Same meeting but not recording (paused and resumed)
            print("Meeting resumed, starting recording")
            self.start_recording(meeting_info)
            
        # If voice activity detection is enabled, check for long silences
        if self.vad_enabled and self.recording:
            self.check_voice_activity()
            
    elif status != "Active" and self.recording:
        # Stop recording if meeting is not active
        print("Meeting not active, stopping recording")
        self.stop_recording()
```

### 5. CLI Argument Updates

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record online meetings")
    parser.add_argument("--output", "-o", default="~/Meetings/Recordings", 
                        help="Output directory for recordings")
    parser.add_argument("--format", "-f", default="mp3", choices=["mp3", "wav"], 
                        help="Audio format for recordings")
    parser.add_argument("--bitrate", "-b", default="192k", 
                        help="Bitrate for audio encoding (for mp3)")
    parser.add_argument("--source", "-s", help="Specify PulseAudio source directly")
    parser.add_argument("--list-sources", "-l", action="store_true",
                        help="List available PulseAudio sources and exit")
    parser.add_argument("--monitor-interval", "-i", type=int, default=3,
                        help="Check interval in seconds (1-10, default: 3)")
    
    # Meeting-specific options
    parser.add_argument("--meeting-title", "-t", help="Specify meeting title")
    parser.add_argument("--participants", "-p", help="Comma-separated list of participants")
    parser.add_argument("--platform", choices=["zoom", "teams", "meet", "webex", "any"],
                        help="Specify meeting platform to record")
    parser.add_argument("--dual-recording", "-d", action="store_true",
                        help="Record both system audio and microphone")
    
    # Advanced features
    parser.add_argument("--silence-detection", action="store_true", default=True,
                        help="Enable silence detection (default: enabled)")
    parser.add_argument("--no-silence-detection", action="store_false", dest="silence_detection",
                        help="Disable silence detection")
    parser.add_argument("--silence-threshold", type=int, default=30,
                        help="Seconds of silence before segmenting recording (default: 30)")
    parser.add_argument("--auto-segment", action="store_true",
                        help="Automatically create new files on long silences")
    parser.add_argument("--post-process", action="store_true",
                        help="Apply audio post-processing (noise reduction, normalization)")
    parser.add_argument("--no-metadata", action="store_true",
                        help="Disable metadata writing")
    
    args = parser.parse_args()
    # [...]
```

## Technical Challenges

1. **Meeting Detection**
   - Unlike ncspot with MPRIS, meetings don't have a standard interface to detect status
   - Solution: Use a combination of process detection, window titles, and audio activity

2. **Audio Source Selection**
   - Different meeting platforms route audio differently
   - Solution: Create platform-specific detectors and provide manual override options

3. **Voice Activity Detection**
   - Need to identify silence vs. speech to enable smart features
   - Solution: Use webrtcvad or simple amplitude-based detection initially

4. **Metadata Structure**
   - Meeting metadata is fundamentally different from music
   - Solution: Create a flexible schema that can accommodate different meeting types

5. **File Organization**
   - Meetings need a different organization than music tracks
   - Solution: Use date-based organization with customizable templates

## Incremental Development Approach

1. Start with a simple 1:1 replacement of ncspot detection with meeting detection
2. Add basic meeting metadata handling
3. Implement improved audio source detection
4. Add voice activity detection
5. Add post-processing features
6. Add advanced integrations (calendar, transcription)

This incremental approach will allow for continuous testing and validation at each step.
