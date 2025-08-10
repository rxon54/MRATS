# Copilot Instructions for MRATS (Meeting Recorder Automated Transcription & Summarization)

## Project Overview
- MRATS is a Python utility for automated meeting recording, transcription (Whisper.cpp), and summarization (Ollama).
- Main script: `meeting_recorder.py` (all logic is here; helpers in `rec_utils.py`, pipeline in `processing_pipeline.py`).
- No build system; run directly with Python 3.
- Comprehensive documentation and testing framework present.

## Architecture & Data Flow
- **Multi-threaded, queue-based:**
  - Records system/microphone audio using `ffmpeg` and PulseAudio.
  - Segments recordings into fixed-duration WAV files for processing.
  - Uses decoupled workers for transcription and summarization.
  - Transcription: Whisper.cpp (CLI, pywhispercpp, or HTTP server backends).
  - Summarization: Ollama with rolling context and prompt engineering.
  - Race condition protection: Enhanced file stability checks with audio duration verification.
  - Automatic retry mechanisms for robust production use.
- **Processing Pipeline:**
  - Audio segments → Transcription Queue → Whisper.cpp → Transcripts
  - Transcripts → Summarization Queue → Ollama → Rolling summaries
  - All stages operate independently with comprehensive error handling
- **Output Structure:**
  - Hierarchical directories: `segments/`, `transcription/`, `summaries/`
  - Session metadata and per-segment JSON files
  - Final summary generation with pipeline draining

## Developer Workflows
- **Run:**
  - `python meeting_recorder.py [options]`
- **Dependencies:**
  - Requires: `ffmpeg`, `pulseaudio-utils`, `whisper.cpp` (external)
  - Optional: `requests`, `pyyaml`, `pywhispercpp`, `ollama` (pip install)
- **Debugging:**
  - Debug/info messages are timestamped, printed to stdout.
  - Comprehensive logging with session directories and metrics.
  - Multiple test scripts for different scenarios.
- **Configuration:**
  - CLI arguments, YAML config files, VS Code tasks.
  - Multiple backend options for transcription.
  - Extensive automation and quality settings.

## Project-Specific Patterns
- **Class-based architecture:**
  - `MeetingRecorder` class handles recording and session management.
  - `ProcessingPipeline` class manages transcription and summarization queues.
  - Utility functions are in `rec_utils.py`, imported directly.
- **Comprehensive testing:**
  - Multiple test scripts for different scenarios and backends.
  - Race condition and truncation testing.
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
- **No config files; all config is CLI-driven or YAML-based.**
- **No external API calls except subprocesses to system tools.**
- **No database or persistent state except session metadata and logs.**

## Integration Points
- **External tools:**
  - `ffmpeg` for audio recording and processing
  - `pulseaudio-utils` for source detection
  - Whisper.cpp for transcription (multiple backends)
  - Ollama for summarization
- **Backend Options:**
  - CLI: Direct whisper.cpp executable calls
  - pywhispercpp: In-process Python binding
  - server: HTTP API to whisper.cpp server

## Examples
- To record with automation:
  ```bash
  python meeting_recorder.py --start --enable-automation --segment-duration 30
  ```
- To use server backend:
  ```bash
  python meeting_recorder.py --start --enable-automation --whisper-backend server --whisper-server-url http://127.0.0.1:8080
  ```

## Key Files
- `meeting_recorder.py`: Main logic, CLI, recording, session management
- `processing_pipeline.py`: Transcription and summarization automation
- `rec_utils.py`: Helper functions for dependency/source checks
- `README.md`: Usage, options, troubleshooting
- `CHANGELOG.md`: Version history and recent fixes

---
**If you add new features, document CLI options and output structure in both `README.md` and this file.**

## Recent Major Updates (2025-08-10)

### Race Condition Fix
- **File Stability**: Enhanced checking with audio duration verification
- **Timeout Management**: Automatic adjustment based on segment duration
- **Debug Logging**: Clear progress tracking for segment completion

### Whisper.cpp Server Backend (2025-08-09)
- **Backend Selection**: `--whisper-backend server`
- **Server Integration**: HTTP API with multipart form data
- **Retry Logic**: Automatic retry on truncated responses
- **Response Compatibility**: Handles both text and segments formats

### CLI Options (Current)
- `--whisper-backend`: `cli`, `pywhispercpp`, or `server`
- `--whisper-server-url`: Server URL (default: http://127.0.0.1:8080)
- `--whisper-server-timeout`: Request timeout in seconds (default: 120)

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

## Transcription Backend and Padding (2025-08-09)

### New CLI/Config Options
- `--whisper-backend`: `cli` (default), `pywhispercpp` for in-process transcription, or `server` for HTTP API.
- `--whisper-server-url`: Whisper.cpp server URL (default: http://127.0.0.1:8080).
- `--whisper-server-timeout`: Server request timeout in seconds (default: 120).
- `--pad-silence-ms`: Milliseconds of trailing silence appended to each segment prior to transcription (default: 300; set 0 to disable).

### Notes
- `pywhispercpp` backend reduces CLI spawning overhead and can improve robustness at segment boundaries. Install with `pip install pywhispercpp` or build from source for GPU support per upstream docs.
- `server` backend uses HTTP API to communicate with whisper.cpp server for distributed processing and better resource management.
- Padding helps mitigate truncation near segment boundaries.

## Boundary Mitigation & Pre-roll (2025-08-09)

### New CLI/Config Options
- `--pre-roll-ms`: Milliseconds of pre-roll context taken from the previous segment tail to prepend during transcription (default: 300; set 0 to disable).

### Behavior
- The pipeline constructs a context WAV: `[prev_tail <= pre_roll_ms] + [current segment] + [pad_silence_ms]`.
- Whisper runs on the context WAV to improve recognition at segment boundaries.
- The resulting transcript is trimmed using JSON timestamps to remove pre-roll and clamp content to the current segment duration.
- If the last local timestamp remains far from the end of the current segment, the pipeline retries once with a larger pad to avoid truncation.

### Notes
- Works for both CLI and `pywhispercpp` backends.
- TXT remains the authoritative transcript; JSON is used for trimming and diagnostics.
