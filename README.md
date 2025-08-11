# MRATS
Meeting Recorder Automated Transcription & Summarization (MRATS): Automated, privacy-focused meeting recording, transcription (Whisper.cpp), and contextual summarization (Ollama).

## Status Note (Current Implementation vs Plans)
UPDATED (2025-08-11): The processing pipeline now uses decoupled queues with independent workers for transcription and summarization. Multiple Whisper.cpp backend options are available including HTTP server backend for distributed processing. Critical race condition and truncation issues have been resolved.

**Recent Fixes (2025-08-11)**:
- ✅ **Final Summary & Transcript Always Generated**: `final_summary.md` and `final_transcript.txt`/`.json` are now always produced at session end, even on abrupt stop.
- ✅ **Batch Summarization**: Summaries are now generated in batches (see `--summary-batch-size`), with a true final summary synthesized from all batch summaries.
- ✅ **Token Metrics**: Metrics files now include approximate token counts for each transcript, batch, and final summary.
- ✅ **Race Condition Fix**: Enhanced file stability checking with audio duration verification prevents processing incomplete segments
- ✅ **Server Backend**: Full HTTP API integration with Whisper.cpp server for distributed processing  
- ✅ **Truncation Retry**: Automatic retry mechanism for server responses with early truncation
- ✅ **Segment Timing**: Resolved VS Code task configuration issues causing incorrect segment durations

**Current Features**:
- Whisper.cpp backend options: CLI (default), in-process `pywhispercpp`, or HTTP server
- Race condition protection: waits for complete segment duration before processing
- Server backend retry logic: handles inconsistent response formats and truncation
- Enhanced file stability checks with audio duration validation
- Decoupled pipeline stages: separate transcription and summarization queues/workers
- **Batch Summarization**: Use `--summary-batch-size N` to concatenate N segment transcripts for each summarization batch. Batch summaries are written as `batch_XXX_summary.md`. Any leftover segments are summarized at the end. The final summary is synthesized from all batch summaries.
- **Final Summary & Transcript**: At session end, a true final summary (`final_summary.md`) and aggregate transcript (`final_transcript.txt`/`.json`) are always generated, even if the session is stopped abruptly.
- **Token Metrics**: Metrics files now include approximate token counts (chars/4) for each transcript, batch, and final summary.

Removed / Changed:
- Removed `--format` (WAV is mandatory for Whisper.cpp performance).
- Removed `--bitrate` (only applied to MP3, no longer relevant).
- Decoupled pipeline stages: separate transcription and summarization queues/workers.
- Enhanced: Multiple transcription backends (CLI, pywhispercpp, server).
- Enhanced: Trailing silence padding per segment (`--pad-silence-ms`, default 300 ms) to mitigate boundary truncation.
- Enhanced: Pre-roll context (`--pre-roll-ms`, default 300 ms) using the previous segment's tail to improve continuity across boundaries.
- Enhanced: JSON-guided trimming for transcripts to remove pre-roll and clamp to the current segment duration; automatic retry with larger pad if truncation detected.
- Enhanced: Server backend with retry mechanism for robust distributed processing.

Still Pending (Roadmap):
- Segment cleanup / retention policies.
- Encryption options.
- Custom initial/continuation prompt wiring (flags reserved).
- Enhanced final summary (structured sections, decisions, action items).

## Features

- **Segmented Recording**: Continuous capture split into fixed-length WAV segments.
- **Structured Output Hierarchy**: Date/session folder with organized subdirectories.
- **Session Metadata**: `metadata.json` at session root summarizing session properties.
- **Per-Segment Metadata**: JSON next to each WAV segment in `segments/`.
- **Local Transcription**: Multiple Whisper.cpp backends (JSON + plain text per segment) into `transcription/`.
  - Backend options: CLI (default), in-process `pywhispercpp`, or HTTP server
  - Server backend: Distributed processing with retry logic for reliability
- **Race Condition Protection**: Enhanced file stability checks with audio duration verification
  - Waits for complete segment duration before processing (prevents truncated transcripts)
  - Automatic timeout adjustment based on segment duration
- **Boundary Mitigation**:
  - Append trailing silence to each segment (`--pad-silence-ms`), default 300 ms.
  - Prepend the previous segment’s tail as pre-roll (`--pre-roll-ms`), default 300 ms.
  - Build a context WAV (prev tail + current + silence pad) for transcription.
  - Parse whisper JSON to trim out pre-roll text and clamp to the current segment window.
  - If last local timestamp is far from segment end, automatically retry once with larger pad.
- **Local Summarization**: Ollama per-segment summaries + rolling summary in `summaries/`.
- **Final Summary**: `final_summary.md` created at stop (current copy of rolling summary) after draining pipeline.
- **Rolling Summary**: Maintains evolving meeting context.
- **Decoupled Workers**: Independent queues for transcription and summarization allow Whisper and Ollama to run on different machines without blocking.
- **Enhanced File Stability**: Ensures complete segment closure before processing with audio duration validation.
- **Robust Retry Logic**: Multiple retry mechanisms for reliability:
  - Whisper retries on failure; truncation heuristic and optional padding improve robustness
  - Server backend handles response format variations and automatic retry on truncation
  - Race condition protection prevents processing incomplete segments
- **Config + CLI**: YAML config + arguments.
- **Batch Summarization**: Use `--summary-batch-size N` to concatenate N segment transcripts for each summarization batch. Batch summaries are written as `batch_XXX_summary.md`. Any leftover segments are summarized at the end. The final summary is synthesized from all batch summaries.
- **Token Metrics**: Metrics files now include approximate token counts (chars/4) for each transcript, batch, and final summary.

## Installation

1. Clone the repository:
   ```
   git clone <repository-url>
   cd meeting-recorder
   ```
2. Make the script executable:
   ```
   chmod +x meeting_recorder.py
   ```
3. Install system dependencies:
   ```
   sudo apt install ffmpeg pulseaudio-utils
   ```
4. (Optional) Install Python packages used by automation:
   ```
   pip install requests pyyaml
   ```
5. (Optional) Build / install whisper.cpp & pull model:
   ```
   # Example paths; adapt to your environment
   ~/projects/whisper.cpp/build/bin/whisper-cli -m ~/projects/whisper.cpp/models/ggml-base.bin -h
   ```
6. (Optional) Install & run Ollama (see https://ollama.com):
   ```
   ollama run llama2  # pulls and warms model
   ```
7. (Optional) In-process backend (pywhispercpp):
   - Default CPU wheels: `pip install pywhispercpp`
   - For best performance or GPU backends, follow upstream README (CUDA: `GGML_CUDA=1 pip install git+https://github.com/absadiki/pywhispercpp`).

## Usage

### Basic Recording
Interactive session:
```
python meeting_recorder.py
```
Immediate segmented recording (default 5 min segments):
```
python meeting_recorder.py --start
```
Short test (10‑second segments) with automation:
```
python meeting_recorder.py --start --enable-automation --segment-duration 10 --system-only \
  --whisper-path ~/projects/whisper.cpp/build/bin/whisper-cli \
  --whisper-model ~/projects/whisper.cpp/models/ggml-base.bin
```

Use `pywhispercpp` backend and adjust padding:
```
python meeting_recorder.py --start --enable-automation --system-only \
  --whisper-backend pywhispercpp --whisper-model base.en --pad-silence-ms 300 --pre-roll-ms 300
```

Use Whisper.cpp HTTP server backend (distributed processing):
```
# Start Whisper.cpp server (in separate terminal)
~/projects/whisper.cpp/build/bin/server -m ~/projects/whisper.cpp/models/ggml-base.bin --port 8080

# Use server backend for recording
python meeting_recorder.py --start --enable-automation --system-only \
  --whisper-backend server --whisper-server-url http://127.0.0.1:8080 --whisper-server-timeout 120
```

### CLI Options (Current)

- `--output-dir`, `-o`: Output directory root for recordings
- `--list-sources`, `-l`: List PulseAudio sources and exit
- `--source-system`, `-s`: Specify system audio source
- `--source-mic`, `-m`: Specify microphone source
- `--system-only`: Record only system audio
- `--mic-only`: Record only microphone
- `--name`, `-n`: Custom session name prefix
- `--start`: Start recording immediately
- `--segment-duration`: Segment length seconds (default 300)
- `--enable-automation`: Enable transcription + summarization pipeline
- `--metrics-enabled`: Enable metrics collection (timings, backlog) -> writes NDJSON to session `metrics/metrics.ndjson`
- `--metrics-dir`: Override metrics directory name under session root (default: metrics)
- `--whisper-backend`: `cli` (default), `pywhispercpp`, or `server`
- `--whisper-path`: Path to whisper.cpp executable (CLI backend)
- `--whisper-model`: Path or size identifier (tiny|base|small|medium|large or absolute path)
- `--whisper-language`: Language code (auto = detect)
- `--whisper-threads`: CPU threads for whisper backend
- `--whisper-server-url`: Whisper.cpp server URL (default: http://127.0.0.1:8080)
- `--whisper-server-timeout`: Server request timeout in seconds (default: 120)
- `--pad-silence-ms`: Milliseconds of trailing silence to append before transcription (default 300, set 0 to disable)
- `--pre-roll-ms`: Milliseconds from previous segment to prepend as context (default 300, set 0 to disable)
- `--ollama-url`: Ollama server URL (default http://localhost:11434)
- `--ollama-model`: Ollama model name (default llama2)
- `--ollama-system-prompt`: System (persona/context) prompt
- `--ollama-prompt-initial`: (Reserved) Custom initial summary prompt (not yet wired)
- `--ollama-prompt-continuation`: (Reserved) Custom continuation summary prompt (not yet wired)
- `--summary-batch-size N`  Number of transcription segments to concatenate for each summarization batch (default: 1, i.e., per-segment)

(Deprecated/Removed: `--format`, `--bitrate`)

### Configuration File Support
Place a `config.yaml` in project root; keys map 1:1 to CLI options (removed ones ignored). CLI overrides config.

Example:
```yaml
override_example: false
output_dir: ~/Recordings/Meetings
segment_duration: 300
enable_automation: true
whisper_backend: cli
whisper_path: /usr/local/bin/whisper
whisper_model: base
whisper_language: auto
whisper_threads: 4
pad_silence_ms: 300
pre_roll_ms: 300
ollama_url: http://localhost:11434
ollama_model: llama2
ollama_system_prompt: "You are an expert meeting summarizer."
```

### Output Directory Structure (Current)
```
~/Recordings/Meetings/YYYY-MM-DD/meeting_HHMMSS/            # Session root
  metadata.json                                             # Session-level metadata
  segments/                                                 # Raw audio segments (WAV + per-segment metadata)
  transcription/                                            # Transcription artifacts
  summaries/                                                # Summaries & rolling/final summary
  metrics/                                                  # (If metrics enabled)
    metrics.ndjson                                          # Per-segment timing/backlog metrics
recordings.log                                               # Global log (in root output_dir)
```

### Automated Processing Pipeline
When `--enable-automation`:
1. Segment file closed & stable
2. Transcription worker enqueues/transcribes via Whisper backend → JSON + TXT into `transcription/` (TX queue)
3. Summarization worker consumes transcripts → per-segment summary + rolling summary in `summaries/` (SUM queue)
4. Workers are independent; transcription does not wait for summarization.
5. On session stop: pipeline drains both queues; **a true `final_summary.md` and `final_transcript.txt`/`.json` are always generated from all batch summaries and transcripts, even if the session is stopped abruptly.**

### Ollama Summarization
- First segment: Introductory summarization prompt.
- Subsequent segments: Rolling summary used as context.
- System prompt (if provided) prepends each request.

### Post-Processing
Currently not applied automatically in the new hierarchy; manual per-file processing (if re-introduced) would operate on `segments/` WAV files.

## Limitations / Known Gaps
- No cleanup or retention policies yet.
- No encryption.
- Prompt customization flags not yet wired into summarization logic.
- Enhanced final summary structure (sections, action items) still planned.

## Fixed Issue: Whisper.cpp early output/truncation on longer segments (RESOLVED)

**Status: RESOLVED** ✅ (2025-08-09)

### What was the issue?
When using longer segment durations (e.g., `--segment-duration 40`), Whisper.cpp sometimes produced transcript outputs that covered only ~8–9 seconds even though the input segment was ~40 seconds. This was caused by context WAV construction producing truncated files.

### How was it fixed?
Complete rewrite of the context WAV construction logic:
- **Replaced filter_complex with concat demuxer** for more reliable concatenation
- **Added duration validation and automatic fallback** to raw segment if context WAV is truncated
- **Enhanced error logging** with dedicated `*_ctx_ffmpeg.log` files
- **Improved metrics collection** to track context build success/failure
- **Better cleanup** of temporary files used in context construction

### Verification
The fix has been thoroughly tested with:
- Unit tests (`test_context_wav_issue.py`) ✅
- Integration tests (`test_integration.py`) ✅  
- Segments from 10s to 60s duration ✅
- Both with and without pre-roll/padding ✅

### Result
- ✅ Context WAVs now consistently match expected durations
- ✅ Automatic fallback prevents processing delays
- ✅ Enhanced debugging when issues occur
- ✅ No performance regression

---

## Troubleshooting Quick Tips
| Symptom | Cause | Action |
|---------|-------|--------|
| No audio captured | Wrong PulseAudio source | Use `pactl list short sources` and specify with `--source-system`/`--source-mic` |
| Whisper fails | Wrong path/model | Verify binary & model paths, permissions |
| Empty transcript | Silence / low volume | Increase source volume, test with known audio |
| Summarization skipped | Empty transcript | Confirm audio content present |
| Slow processing | Large model size | Use smaller Whisper / Ollama models |
| Truncated transcript (boundary) | Segment boundary cut | Increase `--pad-silence-ms` and/or `--pre-roll-ms`, or use `pywhispercpp` backend |
| Truncated transcript (early/short) | Context WAV built short or decode stopped early | Disable pre-roll/pad; try `pywhispercpp`; reduce segment duration; await guard fix |

## Roadmap (Planned Enhancements)
- Segment cleanup / retention policies.
- Encryption of outputs.
- Configurable prompt templates (initial / continuation).
- Enhanced final summary (structured sections, decisions, action items).
- Optional per-segment post-processing.

## License
Add appropriate license section here (not yet specified).

---
This document reflects the active codebase; planning documents remain for future reference.
