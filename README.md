# MRATS
Meeting Recorder Automated Transcription & Summarization (MRATS): Automated, privacy-focused meeting recording, transcription (Whisper.cpp), and contextual summarization (Ollama).

## Status Note (Current Implementation vs Plans)
UPDATED (2025-08-08): The structured directory hierarchy is now IMPLEMENTED. Each recording session creates a session directory under a date folder with `segments/`, `transcription/`, and `summaries/` subdirectories plus a session-level `metadata.json`. A `final_summary.md` is generated on stop (copy of rolling summary). The previous flat layout description has been superseded.

Removed / Changed:
- Removed `--format` (WAV is mandatory for Whisper.cpp performance).
- Removed `--bitrate` (only applied to MP3, no longer relevant).

Still Pending (Roadmap):
- Aggregate full transcript file (`full_transcript.txt/.json`).
- Segment cleanup / retention policies.
- Encryption options.
- Custom initial/continuation prompt wiring (flags reserved).
- Final aggregate summary improvements beyond copy of rolling summary.

## Features

- **Segmented Recording**: Continuous capture split into fixed-length WAV segments.
- **Structured Output Hierarchy**: Date/session folder with organized subdirectories.
- **Session Metadata**: `metadata.json` at session root summarizing session properties.
- **Per-Segment Metadata**: JSON next to each WAV segment in `segments/`.
- **Local Transcription**: Whisper.cpp (JSON + plain text per segment) into `transcription/`.
- **Local Summarization**: Ollama per-segment summaries + rolling summary in `summaries/`.
- **Final Summary**: `final_summary.md` created at stop (current copy of rolling summary).
- **Rolling Summary**: Maintains evolving meeting context.
- **File Stability Checks**: Ensures segment closure before processing.
- **Retry Logic**: Whisper retries on failure.
- **Config + CLI**: YAML config + arguments.

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
- `--whisper-path`: Path to whisper.cpp executable
- `--whisper-model`: Path or size identifier (tiny|base|small|medium|large or absolute path)
- `--whisper-language`: Language code (auto = detect)
- `--whisper-threads`: CPU threads for whisper.cpp
- `--ollama-url`: Ollama server URL (default http://localhost:11434)
- `--ollama-model`: Ollama model name (default llama2)
- `--ollama-system-prompt`: System (persona/context) prompt
- `--ollama-prompt-initial`: (Reserved) Custom initial summary prompt (not yet wired)
- `--ollama-prompt-continuation`: (Reserved) Custom continuation summary prompt (not yet wired)

(Deprecated/Removed: `--format`, `--bitrate`)

### Configuration File Support
Place a `config.yaml` in project root; keys map 1:1 to CLI options (removed ones ignored). CLI overrides config.

Example:
```yaml
override_example: false
output_dir: ~/Recordings/Meetings
segment_duration: 300
enable_automation: true
whisper_path: /usr/local/bin/whisper
whisper_model: base
whisper_language: auto
whisper_threads: 4
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
2. Whisper.cpp transcription → JSON + TXT into `transcription/`
3. Ollama summarization → per-segment summary + rolling summary in `summaries/`
4. On session stop: `final_summary.md` created from `rolling_summary.md`

### Ollama Summarization
- First segment: Introductory summarization prompt.
- Subsequent segments: Rolling summary used as context.
- System prompt (if provided) prepends each request.

### Post-Processing
Currently not applied automatically in the new hierarchy; manual per-file processing (if re-introduced) would operate on `segments/` WAV files.

## Limitations / Known Gaps
- No aggregate full transcript (`full_transcript.txt/json`).
- No cleanup or retention policies yet.
- No encryption.
- Prompt customization flags not yet wired into summarization logic.
- `final_summary.md` is currently identical to last rolling summary state.
- Metrics currently segment-level only (no batch accumulation yet).

## Troubleshooting Quick Tips
| Symptom | Cause | Action |
|---------|-------|--------|
| No audio captured | Wrong PulseAudio source | Use `pactl list short sources` and specify with `--source-system`/`--source-mic` |
| Whisper fails | Wrong path/model | Verify binary & model paths, permissions |
| Empty transcript | Silence / low volume | Increase source volume, test with known audio |
| Summarization skipped | Empty transcript | Confirm audio content present |
| Slow processing | Large model size | Use smaller Whisper / Ollama models |

## Roadmap (Planned Enhancements)
- Full session aggregate transcript file(s).
- Segment cleanup / retention policies.
- Encryption of outputs.
- Configurable prompt templates (initial / continuation).
- Enhanced final summary (structured sections, decisions, action items).
- Optional per-segment post-processing.

## License
Add appropriate license section here (not yet specified).

---
This document reflects the active codebase; planning documents remain for future reference.
