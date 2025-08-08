# Copilot Instructions for Spotirec (ncspot Recording Tool)

## Project Overview
- Spotirec is a Python utility for automatically recording tracks played by ncspot (terminal Spotify client).
- Main script: `ncspot_recorder_simple.py` (all logic is here; helpers in `rec_utils.py`).
- No build system; run directly with Python 3.
- No tests or CI/CD workflows present.

## Architecture & Data Flow
- **Single-process, event-driven:**
  - Monitors ncspot via MPRIS using `playerctl`.
  - Records audio output using `ffmpeg` and PulseAudio.
  - Uses track metadata (artist, title, album, length) to name files and control recording duration.
  - Adds ID3 tags to MP3 files using the `mutagen` library.
  - Supports two output modes:
    - Default: `$output_dir/Artist/Album/Artist - Title.mp3`
    - Playlist mode: `$output_dir/YYYYMMDD_HHMMSS/Artist - Title.mp3`
- **Smart Cut Logic:**
  - Uses track length to schedule a precise cut window (last 2s of track).
  - Polls MPRIS every 100ms for track change to stop recording within ~100ms of transition.
  - Avoids rewinding tracks to minimize Spotify server traces.

## Developer Workflows
- **Run:**
  - `python ncspot_recorder_simple.py [options]`
- **Dependencies:**
  - Requires: `playerctl`, `ffmpeg`, `pulseaudio-utils`, `ncspot` (external, not managed here)
  - Optional: `mutagen` Python library for ID3 tagging (pip install mutagen)
- **Debugging:**
  - Debug/info messages are timestamped, printed to stdout.
  - All recorded file paths are appended to `$output_dir/recorded_tracks.log` (never overwritten).
- **Configuration:**
  - All options via CLI; see `README.md` for details.
  - Playlist mode: `-p` or `--playlist-mode`.
  - Smart cut: enabled by default, can be disabled with `--no-smart-cut`.

## Project-Specific Patterns
- **No class-based separation for helpers:**
  - Utility functions are in `rec_utils.py`, imported directly.
- **No test framework or test files.**
- **No config files; all config is CLI-driven.**
- **No external API calls except subprocesses to system tools.**
- **No database or persistent state except the log file.**

## Integration Points
- **External tools:**
  - `playerctl` for MPRIS metadata/control
  - `ffmpeg` for audio recording
  - `pulseaudio-utils` for source detection
- **ncspot:**
  - Must be running for the recorder to work
  - Snap package compatibility is handled automatically

## Examples
- To record with playlist mode:
  ```bash
  python ncspot_recorder_simple.py -p
  ```
- To specify a PulseAudio source:
  ```bash
  python ncspot_recorder_simple.py --source alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
  ```

## Key Files
- `ncspot_recorder_simple.py`: Main logic, CLI, recording, smart cut
- `rec_utils.py`: Helper functions for dependency/source checks
- `README.md`: Usage, options, troubleshooting

---
**If you add new features, document CLI options and output structure in both `README.md` and this file.**

## Meeting Recorder Segmentation (2024-07-08)

### New CLI Option
- `--segment-duration`: Segment duration in seconds (default: 300, i.e., 5 min)

### Output Structure
- All recordings are split into sequentially numbered WAV files of the specified segment duration.
- Example output files:
  - `$output_dir/YYYY-MM-DD/meeting_153000_000.wav`
  - `$output_dir/YYYY-MM-DD/meeting_153000_001.wav`
- Each segment has a corresponding metadata JSON file.
- All segment paths are logged in `recordings.log` in the output directory.

### Notes
- Only WAV format is supported for processing and segmentation (optimized for Whisper.cpp).
- Segmentation is handled live using ffmpeg's segment muxer.
- Metadata and logs are updated for each segment as it is created.

## Ollama Summarization (2025-08-07)

### New CLI/Config Options
- `--ollama-url`: Ollama server URL (default: http://localhost:11434)
- `--ollama-model`: Model name (default: llama2)

### Output Structure
- Each segment's summary is saved as `<segment>_summary.md`.
- A rolling summary is updated in `rolling_summary.md` in the segment directory.
- Summarization uses prompt engineering for incremental/rolling context.

### Notes
- Ollama must be running locally with the specified model available.
- Summarization is called after each segment is transcribed.
