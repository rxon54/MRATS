# MRATS
Meeting Recorder Automated Transcription &amp; Summarization (MRATS): Automated, privacy-focused meeting recording, transcription (Whisper.cpp), and contextual summarization (Ollama).
## Features

- **Simple Recording Controls**: Start and stop recordings with easy commands
- **Multiple Audio Sources**: Record from system audio, microphone, or both simultaneously
- **Flexible File Organization**: Date-based organization with custom naming options
- **Recording Metadata**: Automatically saves recording details in JSON format
- **Post-Processing**: Optional audio enhancements like noise reduction and normalization
- **Interactive Mode**: Command-line interface for controlling recordings

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

3. Install dependencies:
   ```
   sudo apt install ffmpeg pulseaudio-utils
   ```
   pip install mutagen

## Usage

### Basic Recording

Start an interactive session:
```
python meeting_recorder.py
```

Start recording immediately (default 5 min segments):
```
python meeting_recorder.py --start
```

### CLI Options

- `--output-dir`, `-o`: Output directory for recordings
- `--format`, `-f`: Audio format (always WAV for processing)
- `--bitrate`, `-b`: Bitrate for audio encoding (for mp3, ignored for wav)
- `--list-sources`, `-l`: List available PulseAudio sources and exit
- `--source-system`, `-s`: Specify system audio source
- `--source-mic`, `-m`: Specify microphone source
- `--system-only`: Record only system audio
- `--mic-only`: Record only microphone
- `--name`, `-n`: Custom name prefix for recordings
- `--start`: Start recording immediately
- `--post-process`, `-p`: Apply post-processing after recording stops
- `--segment-duration`: Segment duration in seconds (default: 300, i.e., 5 min)
- `--enable-automation`: Enable automated transcription and summarization pipeline
- `--whisper-path`: Path to Whisper.cpp executable (default: /usr/local/bin/whisper)
- `--whisper-model`: Whisper.cpp model size (tiny|base|small|medium|large)
- `--whisper-language`: Language code for Whisper.cpp (default: auto)
- `--whisper-threads`: CPU threads for Whisper.cpp (default: 4)
- `--ollama-url`: Ollama server URL (default: http://localhost:11434)
- `--ollama-model`: Ollama model name (default: llama2)

## Configuration File Support

You can set default values for all CLI options in a `config.yaml` file in the project directory. Any CLI argument will override the value in `config.yaml`.

Example `config.yaml`:
```yaml
output_dir: ~/Recordings/Meetings
format: wav
bitrate: 192k
segment_duration: 300
name: null
system_only: false
mic_only: false
source_system: null
source_mic: null
post_process: false
enable_automation: false
whisper_path: /usr/local/bin/whisper
whisper_model: base
whisper_language: auto
whisper_threads: 4
ollama_url: http://localhost:11434
ollama_model: llama2
```

To override a value, just pass the CLI option:
```
python meeting_recorder.py --segment-duration 600 --enable-automation
```

### Segmented Recording Output

- All recordings are split into sequentially numbered WAV files of the specified segment duration.
- Example output files:
  - `~/Recordings/Meetings/2024-07-08/meeting_153000_000.wav`
  - `~/Recordings/Meetings/2024-07-08/meeting_153000_001.wav`
- Each segment has a corresponding metadata JSON file.
- All segment paths are logged in `recordings.log` in the output directory.

### Automated Processing Pipeline

- When `--enable-automation` is set, each audio segment is automatically processed:
  1. **Segmentation**: Audio is split into sequential WAV files
  2. **Transcription**: Each segment is transcribed using Whisper.cpp (WAV input, model selection, error handling)
     - Output: `segment_XXX_transcript.txt` (plain text), `segment_XXX_transcript.json` (structured)
  3. **Summarization**: Each transcript is summarized using Ollama (summary saved as `<segment>_summary.md`, rolling summary in `rolling_summary.md`)
  4. **Output**: Results are saved and logged
- The pipeline runs in the background and logs progress for each segment.

## Ollama Summarization Integration

- **New CLI/config options:**
  - `--ollama-url` (default: http://localhost:11434)
  - `--ollama-model` (default: llama2)
- **How it works:**
  - After each segment is transcribed, the transcript is sent to Ollama for summarization.
  - The first segment uses an initial summary prompt; subsequent segments use a rolling summary prompt.
  - Each segment's summary is saved as `<segment>_summary.md`.
  - A rolling summary is updated in `rolling_summary.md` in the segment directory.
- **Requirements:**
  - Ollama must be running locally with the specified model pulled.
  - See https://ollama.com for setup instructions.

### Example: 10-minute Segments
```
python meeting_recorder.py --segment-duration 600 --start
```

## Notes
- Only WAV format is supported for processing and segmentation (optimized for Whisper.cpp).
- Segmentation is handled live using ffmpeg's segment muxer.
- Metadata and logs are updated for each segment as it is created.
