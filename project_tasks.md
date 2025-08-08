# Project Tasks: Converting Spotirec to Meeting Recorder

## Project Overview
We'll be adapting the Spotirec tool to create a simplified meeting recording tool that captures audio from system and microphone sources. This document outlines the key tasks and changes needed.

## Core Changes Needed

### 1. Audio Source Selection & Recording
- [ ] Create direct audio channel recording functionality
- [ ] Implement simplified audio source selection UI
- [ ] Add option to record system audio + microphone simultaneously (for full conversation)
- [ ] Support recording from specific audio devices/channels

### 2. Simple Metadata
- [ ] Create a basic meeting info file (JSON) with recording details (date, time, duration)
- [ ] Remove all ID3 tagging functionality

### 3. File Organization Structure
- [ ] Create simple date-based organization structure:
  - Default: `$output_dir/YYYY-MM-DD/recording_HHMMSS.mp3`
- [ ] Allow custom naming via command-line parameters

### 4. Post-Processing Features (Optional)
- [ ] Add options for basic audio post-processing:
  - Noise reduction
  - Volume normalization
  - Speech enhancement

## Implementation Plan

### Phase 1: Core Recording Functionality
- [ ] Rename the main class and update file structure
- [ ] Simplify the code by removing ID3 tagging and smart cut functions
- [ ] Create manual recording start/stop functionality
- [ ] Implement system audio + microphone simultaneous recording
- [ ] Update CLI parameters for meeting recording context

### Phase 2: Enhancements
- [ ] Add simplified file naming and organization
- [ ] Improve audio source selection interface
- [ ] Add basic recording statistics (duration, file size)
- [ ] Implement optional command-line recording controls

### Phase 3: Optional Features
- [ ] Add basic audio post-processing options if needed
- [ ] Create simple recording log functionality
- [ ] Support for recording scheduling (start/stop at specific times)

## File Structure Changes

```
meeting_recorder.py          # Main script (renamed from ncspot_recorder_simple.py)
rec_utils.py                 # Utility functions (simplified version)
audio_sources.py             # New file for audio source detection/management
README.md                    # Updated documentation
```

## Key Dependencies
- Existing: `ffmpeg`, `pulseaudio-utils`
- Optional: `sox` for audio post-processing

## CLI Options to Add/Change
- `--system-audio` - Record system audio
- `--microphone` - Record from microphone
- `--combined` - Record both system audio and microphone (default)
- `--output-dir` - Specify output directory
- `--name` - Custom recording name prefix
- `--list-sources` - List available audio sources
- `--source-system` - Specify system audio source
- `--source-mic` - Specify microphone source
- `--post-process` - Apply basic audio enhancements (if needed)

## Integration Points
- Direct PulseAudio source management
- Manual recording control (start/stop)
- Basic file naming and organization
- Remove dependency on playerctl and ID3 tagging
