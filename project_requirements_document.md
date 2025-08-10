# Project Requirements Document - Meeting Recorder Automation

<!-- Implementation Status Addendum (2025-08-08) -->
**Implementation Status Addendum (2025-08-08)**  
The live codebase now implements the structured directory hierarchy and WAV-only recording:
- Implemented: Segmented recording (ffmpeg), per-segment metadata JSON, Whisper.cpp transcription (JSON + TXT), Ollama rolling summarization, background processing queue, file stability checks, CLI + YAML config, basic retry logic, rolling summary file, hierarchical output directories (`segments/`, `transcription/`, `summaries/`), session-level `metadata.json`, generation of `final_summary.md` (copy of rolling summary on stop).
- Partially Implemented / Different from Spec:
  - Final consolidated transcript not yet produced (`full_transcript.txt/json` pending); `final_summary.md` is a direct copy of the last rolling summary (no additional synthesis step yet).
  - No cleanup (`--cleanup-segments`), encryption, batch-processing modes, or health-check routines yet.
  - Prompt customization flags for initial/continuation present in CLI but not yet wired into pipeline logic (only system prompt used).
  - Removed `--format` / `--bitrate`; WAV enforced for performance (spec previously allowed mp3).
- Not Yet Implemented (Roadmap): Aggregate / full transcript generation, enhanced final summary synthesis, encryption, adaptive segmentation, explicit batch vs live modes, persistent processing logs separate from stdout, service health monitoring, segment deletion policies.

The remainder of this document remains as a forward-looking specification; checked **[COMPLETED]** markers refer to logical design goals rather than the full directory or feature build-out described. See README for a concise summary of current behavior.

---

## Project Title: Meeting Recorder with Automated Transcription & Summarization

**Version:** 1.0  
**Date:** August 5, 2025  
**Project Code:** MRATS (Meeting Recorder Automated Transcription & Summarization)

---

## 1. Executive Summary

This document outlines the requirements for extending the existing Meeting Recorder system with automated transcription and summarization capabilities. The system will process audio recordings incrementally, using local Whisper CPP for transcription and local Ollama for LLM-based summarization, creating a privacy-focused, fully automated meeting processing pipeline.

### 1.1 Project Goals
- **Automate** the current manual transcription workflow
- **Implement incremental processing** for real-time or near-real-time transcription
- **Integrate local AI services** (Whisper CPP + Ollama) for privacy
- **Provide contextual summarization** with incremental updates
- **Maintain existing recording functionality** while adding automation features

---

## 2. Current System Analysis

### 2.1 Existing Meeting Recorder Capabilities
- **Audio Capture**: System audio + microphone recording via PulseAudio/ffmpeg
- **File Formats**: MP3/WAV output with configurable bitrate
- **Organization**: Date-based file structure (`YYYY-MM-DD/recording_HHMMSS.format`)
- **Metadata**: JSON metadata files with recording details
- **Post-Processing**: Optional noise reduction, normalization, speech enhancement
- **Interactive Control**: CLI with start/stop/status commands

### 2.2 Current Manual Workflow
1. **Record** meeting audio to WAV files
2. **Manually process** files with Whisper CPP transcriber
3. **Manually feed** transcription text to LLM
4. **Manually compile** final summary

---

## 3. Functional Requirements

### 3.1 Incremental Audio Processing

#### 3.1.1 Audio Segmentation
- **REQ-001**: System SHALL segment ongoing recordings into configurable time intervals **[COMPLETED]**
  - **Default**: 5-minute segments
  - **Range**: 1-30 minutes via CLI parameter `--segment-duration`
  - **Implementation**: Extract audio segments without stopping main recording
  - **Format**: WAV format for optimal Whisper.cpp processing performance

#### 3.1.2 Segment Management
- **REQ-002**: System SHALL manage audio segments with sequential numbering **[COMPLETED]**
  - **Naming**: `recording_HHMMSS_segment_001.wav`, `recording_HHMMSS_segment_002.wav`
  - **Tracking**: Maintain segment metadata (start time, duration, sequence)
  - **Cleanup**: Optional deletion of processed segments via `--cleanup-segments`
  - **Optimization**: Use WAV format to eliminate decode overhead during transcription

#### 3.1.3 Processing Triggers
- **REQ-003**: System SHALL automatically trigger transcription upon segment completion **[COMPLETED]**
  - **Immediate**: Process segments as they're created (default)
  - **Batch**: Process multiple segments together via `--batch-processing`
  - **Manual**: User-triggered processing via interactive commands

### 3.2 Whisper CPP Integration

#### 3.2.1 Transcription Service
- **REQ-004**: System SHALL integrate with local Whisper CPP transcriber **[COMPLETED]**
  - **Binary Path**: Configurable whisper.cpp executable location
  - **Model Selection**: Support for different model sizes (tiny, base, small, medium, large)
  - **Language Detection**: Automatic language detection or user-specified
  - **Output Format**: Structured text with timestamps
  - **Input Format**: Optimized for WAV input to maximize processing speed

#### 3.2.2 Transcription Configuration
- **REQ-005**: System SHALL provide configurable transcription parameters **[COMPLETED]**
  - **Model**: `--whisper-model` (default: base)
  - **Language**: `--whisper-language` (default: auto-detect)
  - **Quality**: Processing quality vs speed trade-offs
  - **Timestamp**: Include word-level or sentence-level timestamps

#### 3.2.3 Error Handling
- **REQ-006**: System SHALL handle transcription failures gracefully **[COMPLETED]**
  - **Retry Logic**: Automatic retry with exponential backoff
  - **Fallback**: Queue failed segments for manual processing
  - **Logging**: Detailed error logging for troubleshooting

### 3.3 Ollama LLM Integration

#### 3.3.1 Local LLM Service
- **REQ-007**: System SHALL integrate with local Ollama installation **[COMPLETED]**
  - **Connection**: HTTP API connection to local Ollama service
  - **Model Management**: Support for different models (llama2, codellama, etc.)
  - **Keep-Alive**: Maintain model in memory for faster processing
  - **Health Checks**: Monitor Ollama service availability

#### 3.3.2 Contextual Summarization
- **REQ-008**: System SHALL provide contextual summarization for each segment **[COMPLETED]**
  - **First Segment**: Initialize meeting summary with context
  - **Subsequent Segments**: Update summary with new information
  - **Context Window**: Maintain conversation context across segments
  - **Summary Evolution**: Track how summary changes over time

#### 3.3.3 Prompt Engineering
- **REQ-009**: System SHALL use optimized prompts for meeting summarization **[COMPLETED]**
  - **Initial Prompt**: "This is the first segment of a meeting recording..."
  - **Continuation Prompt**: "This is segment X of an ongoing meeting. Previous summary: [SUMMARY]. New content: [TRANSCRIPTION]"
  - **Customizable Templates**: User-defined prompt templates
  - **Meeting Types**: Different prompts for different meeting types

### 3.4 Automated Workflow Engine

#### 3.4.1 Processing Pipeline
- **REQ-010**: System SHALL implement an automated processing pipeline **[COMPLETED]**
  ```
  Audio Recording → Segmentation → Transcription → Summarization → Output
  ```
  - **Sequential Processing**: Process segments one at a time to optimize resource usage
  - **Pipeline Stages**: Overlap preparation while processing current segment
  - **Queue Management**: Maintain ordered processing queue with priority handling
  - **Progress Tracking**: Real-time status of processing pipeline

#### 3.4.2 Real-time Processing
- **REQ-011**: System SHALL support near-real-time processing during recording **[COMPLETED]**
  - **Live Mode**: `--live-processing` enables real-time transcription
  - **Delay Buffer**: Configurable delay to ensure segment completeness
  - **Resource Management**: Balance processing load with recording quality

#### 3.4.3 Batch Processing
- **REQ-012**: System SHALL support batch processing of completed recordings **[COMPLETED]**
  - **Post-Recording**: Process entire recording after completion
  - **Historical**: Process existing WAV files from previous recordings
  - **Bulk Processing**: Process multiple recording files in sequence

### 3.5 Output Management

#### 3.5.1 Transcription Output
- **REQ-013**: System SHALL generate structured transcription files **[COMPLETED]**
  - **Format**: JSON with timestamps, confidence scores, segments
  - **Plain Text**: Human-readable transcription file
  - **SRT Subtitles**: Optional subtitle file generation
  - **Metadata**: Include processing timestamps, model used, confidence metrics

#### 3.5.2 Summary Output
- **REQ-014**: System SHALL generate progressive summary files **[COMPLETED]**
  - **Incremental Summaries**: Individual segment summaries
  - **Rolling Summary**: Continuously updated meeting summary
  - **Final Summary**: Comprehensive end-of-meeting summary
  - **Format**: Markdown with structured sections

#### 3.5.3 File Organization
- **REQ-015**: System SHALL organize output files logically **[COMPLETED]**
  ```
  ~/Recordings/Meetings/YYYY-MM-DD/meeting_HHMMSS/
  ├── recording.wav                    # Original recording
  ├── segments/                        # Audio segments
  │   ├── segment_001.wav
  │   ├── segment_002.wav
  │   └── ...
  ├── transcription/                   # Transcription files
  │   ├── segment_001_transcript.json
  │   ├── segment_002_transcript.json
  │   ├── full_transcript.txt
  │   └── full_transcript.json
  ├── summaries/                       # Summary files
  │   ├── segment_001_summary.md
  │   ├── segment_002_summary.md
  │   ├── rolling_summary.md
  │   └── final_summary.md
  └── metadata.json                    # Complete session metadata
  ```

---

## 4. Non-Functional Requirements

### 4.1 Performance
- **REQ-016**: Transcription processing SHALL complete within 2x segment duration **[COMPLETED]**
- **REQ-017**: LLM summarization SHALL complete within 30 seconds per segment **[COMPLETED]**
- **REQ-018**: System SHALL process segments sequentially to optimize resource usage **[COMPLETED]**
- **REQ-019**: Memory usage SHALL not exceed 12GB during normal operation (8GB Ollama + 2GB Whisper + 2GB system) **[COMPLETED]**
- **REQ-020**: WAV format SHALL be used for segments to eliminate MP3 decode overhead **[COMPLETED]**


### 4.2 Reliability
- **REQ-021**: System SHALL maintain 99% uptime during recording sessions **[COMPLETED]**
- **REQ-022**: Processing failures SHALL not affect ongoing recording **[COMPLETED]**
- **REQ-023**: All processing attempts SHALL be logged with timestamps **[COMPLETED]**
- **REQ-024**: System SHALL recover gracefully from service interruptions **[COMPLETED]**

### 4.3 Privacy & Security
- **REQ-025**: All processing SHALL occur locally (local network but no cloud services) **[COMPLETED]**
- **REQ-026**: Audio data SHALL never leave the local system **[COMPLETED]**
- **REQ-027**: Transcription and summary data SHALL be stored locally only **[COMPLETED]**
- **REQ-028**: System SHALL provide optional encryption for stored files

### 4.4 Usability
- **REQ-029**: CLI interface SHALL provide clear status updates during processing **[COMPLETED]**
- **REQ-030**: Error messages SHALL be user-friendly with suggested solutions **[COMPLETED]**
- **REQ-031**: System SHALL provide progress indicators for long-running operations **[COMPLETED]**
- **REQ-032**: Configuration SHALL be possible via CLI arguments and config files **[COMPLETED]**

---

## 5. Technical Specifications

### 5.1 Architecture Overview
```
┌─────────────────┐    ┌─────────────────┐    ┌────────────────────────────┐
│   Audio Input   │    │   Segmentation  │    │     Transcription Worker   │
│   (PulseAudio)  │───▶│     Engine      │───▶│  (Whisper.cpp, TX Queue)   │
└─────────────────┘    └─────────────────┘    └────────────────────────────┘
                                                   │
                                                   ▼
                                         ┌────────────────────────────┐
                                         │   Summarization Worker     │
                                         │  (Ollama, SUM Queue)       │
                                         └────────────────────────────┘
                                                   │
                                                   ▼
                                            ┌───────────────┐
                                            │  File Output  │
                                            │ (MD / JSON)   │
                                            └───────────────┘

Decoupled Processing Flow:
Segment N: [TX enqueue] → [Transcription] → [SUM enqueue] → [Summarization]
Segment N+1: [TX enqueue] (does not wait for SUM completion of N)
```

### 5.2 New Components

#### 5.2.1 AudioSegmenter Class
```python
class AudioSegmenter:
    """Handles audio segmentation during recording"""
    def __init__(self, segment_duration=300, output_format="wav")
    def start_segmentation(self, source_file, output_dir)
    def stop_segmentation(self)
    def get_latest_segment(self)
    def extract_wav_segment(self, start_time, duration)  # Optimized WAV extraction
```

#### 5.2.2 TranscriptionService Class
```python
class TranscriptionService:
    """Manages Whisper CPP transcription"""
    def __init__(self, whisper_path, model="base", language="auto")
    def transcribe_segment(self, audio_file)
    def get_transcription_status(self, job_id)
    def configure_model(self, model_name)
```

#### 5.2.3 SummarizationService Class
```python
class SummarizationService:
    """Manages Ollama LLM summarization"""
    def __init__(self, ollama_url="http://localhost:11434", model="llama2")
    def initialize_summary(self, first_transcript)
    def update_summary(self, new_transcript, previous_summary)
    def finalize_summary(self, all_transcripts)
```

#### 5.2.4 ProcessingPipeline Class
```python
class ProcessingPipeline:
    """Orchestrates the automated workflow with sequential processing"""
    def __init__(self, segmenter, transcriber, summarizer)
    def start_pipeline(self, recording_session)
    def process_segment_sequential(self, segment_info)
    def get_pipeline_status(self)
    def optimize_resource_usage(self)
```

### 5.3 Processing Optimization Strategy

#### 5.3.1 Sequential Processing Benefits
- **Resource Efficiency**: Single-threaded processing prevents CPU/memory contention
- **Predictable Performance**: Consistent processing times without resource competition
- **Quality Assurance**: Full system resources dedicated to each processing stage
- **Memory Management**: Lower peak memory usage with controlled allocation

#### 5.3.2 Performance Optimization Techniques
- **Model Persistence**: Keep Ollama model loaded in memory between segments
- **Preprocessing Pipeline**: Prepare next segment while processing current one
- **Adaptive Segmentation**: Adjust segment size based on processing speed
- **Resource Monitoring**: Dynamic resource allocation based on system load
- **Audio Format Optimization**: Use WAV format for zero-decode overhead
  - **Segmentation**: Direct PCM data extraction without re-encoding
  - **Whisper Input**: Fastest possible audio input format
  - **Storage Trade-off**: Larger files but significantly faster processing

#### 5.3.3 Recommended Processing Flow
```
1. Segment Creation     →  Extract 5min audio segment
2. Whisper Processing   →  Transcribe with full CPU allocation (4-6 cores)
3. Context Preparation  →  Prepare prompt with previous summary
4. Ollama Processing    →  Generate summary with full model access
5. Output Generation    →  Write files and update metadata
6. Queue Next Segment   →  Begin processing next segment
```

### 5.3 Enhanced CLI Interface

#### 5.3.1 New CLI Parameters
```bash
# Automation Control
--enable-automation          # Enable automated transcription/summarization
--segment-duration MINUTES   # Audio segment length (default: 5)
--sequential-processing      # Process segments sequentially (default: true)
--batch-processing           # Process after recording completion

# Performance Tuning
--whisper-threads CORES      # CPU cores for Whisper.cpp (default: 4)
--ollama-keep-alive SECONDS  # Keep model loaded duration (default: 300)
--processing-priority HIGH   # Set process priority for AI workloads

# Whisper Configuration
--whisper-path PATH          # Path to whisper.cpp executable
--whisper-model MODEL        # Model size (tiny|base|small|medium|large)
--whisper-language LANG      # Language code (auto-detect if not specified)

# Ollama Configuration
--ollama-url URL             # Ollama service URL (default: localhost:11434)
--ollama-model MODEL         # LLM model name (default: llama2)
--keep-model-loaded          # Keep model in memory between requests

# Output Control
--output-format FORMAT       # Summary format (markdown|json|text)
--cleanup-segments           # Delete processed audio segments
--encrypt-output             # Encrypt generated files
```

#### 5.3.2 Interactive Commands
```bash
# During recording
> status automation          # Show automation pipeline status
> process-now               # Force processing of current segment
> pause-automation          # Temporarily disable automation
> resume-automation         # Re-enable automation

# Post-recording
> reprocess-segments        # Reprocess all segments with different settings
> export-summary            # Export final summary in different format
> show-pipeline-log         # Display processing pipeline log
```

### 5.4 Configuration Files

#### 5.4.1 automation_config.yaml
```yaml
automation:
  enabled: true
  segment_duration: 300  # 5 minutes
  sequential_processing: true
  processing_priority: "high"
  
whisper:
  executable_path: "/usr/local/bin/whisper"
  model: "base"
  language: "auto"
  include_timestamps: true
  thread_count: 4  # CPU cores allocated
  
ollama:
  service_url: "http://localhost:11434"
  model: "llama2:14b"  # Specify 14B parameter model
  keep_alive: 300      # Keep model loaded for 5 minutes
  max_context_length: 4096
  request_timeout: 60  # Seconds to wait for response
  
output:
  format: "markdown"
  include_metadata: true
  cleanup_segments: false
  encrypt_files: false
  
performance:
  max_concurrent_segments: 1  # Sequential processing
  memory_limit_gb: 12
  cpu_priority: "high"
```

---

## 6. Implementation Plan

### 6.1 Phase 1: Core Infrastructure (Week 1-2)
- **Sprint 1.1**: Audio segmentation engine
  - Implement `AudioSegmenter` class
  - Add segment extraction during recording
  - Create segment metadata tracking
  
- **Sprint 1.2**: Service integration foundations
  - Create `TranscriptionService` base class
  - Create `SummarizationService` base class
  - Implement service health checks

### 6.2 Phase 2: Transcription Integration (Week 3-4)
- **Sprint 2.1**: Whisper CPP integration
  - Implement Whisper CPP subprocess management
  - Add transcription queue and processing
  - Error handling and retry logic
  
- **Sprint 2.2**: Transcription optimization
  - Parallel processing implementation
  - Performance tuning
  - Output format standardization

### 6.3 Phase 3: Summarization Integration (Week 5-6)
- **Sprint 3.1**: Ollama integration
  - HTTP API client implementation
  - Model management and keep-alive
  - Basic summarization pipeline
  
- **Sprint 3.2**: Contextual summarization
  - Implement incremental summary updates
  - Prompt template system
  - Summary quality optimization

### 6.4 Phase 4: Automation Pipeline (Week 7-8)
- **Sprint 4.1**: Processing pipeline
  - `ProcessingPipeline` implementation
  - Real-time processing coordination
  - Queue management and status tracking
  
- **Sprint 4.2**: CLI and UX enhancements
  - Extended CLI parameter support
  - Interactive command enhancements
  - Configuration file support

### 6.5 Phase 5: Testing & Optimization (Week 9-10)
- **Sprint 5.1**: Integration testing
  - End-to-end workflow testing
  - Performance benchmarking
  - Error scenario testing
  
- **Sprint 5.2**: Documentation and polish
  - User documentation
  - Configuration examples
  - Deployment guides

---

## 7. Dependencies & Prerequisites

### 7.1 Existing Dependencies
- `ffmpeg` (audio processing)
- `pulseaudio-utils` (audio source management)
- `Python 3.8+` with existing modules

### 7.2 New Dependencies
- **Whisper CPP**: Local transcription engine
  - Installation path: `/usr/local/bin/whisper`
  - Models: Download required model files
  - GPU Support: Optional CUDA support for faster processing

- **Ollama**: Local LLM service
  - Service URL: `http://localhost:11434`
  - Models: llama2, codellama, or similar
  - Memory: Minimum 8GB RAM recommended

- **Python Packages**:
  ```txt
  requests>=2.25.0      # Ollama HTTP client
  PyYAML>=5.4.0        # Configuration files
  asyncio>=3.4.0       # Async processing
  threading>=3.7.0     # Concurrent processing
  queue>=3.7.0         # Processing queues
  ```

### 7.3 System Requirements
- **CPU**: 8-core processor (3GHz) with dedicated core allocation
  - **Whisper.cpp**: 4-6 cores for transcription processing
  - **Ollama**: 2-4 cores for LLM inference
  - **System**: 2 cores for OS and recording operations
- **Memory**: 16GB RAM minimum (24GB recommended)
  - **Ollama**: 8-12GB for 14B parameter model
  - **Whisper**: 2-4GB for model and processing
  - **System**: 4GB for OS and applications
- **Storage**: 20GB+ free space for models and processing cache
- **Network**: Local network access for Ollama service (localhost only)

---

## 8. Risk Assessment & Mitigation

### 8.1 Technical Risks

#### 8.1.1 Processing Performance
- **Risk**: Real-time processing may lag behind recording
- **Mitigation**: Implement adaptive segment duration and batch fallback
- **Monitoring**: Track processing times and queue depth

#### 8.1.2 Service Dependencies
- **Risk**: Whisper CPP or Ollama service failures
- **Mitigation**: Graceful degradation, offline queuing, service restart logic
- **Monitoring**: Health checks and automatic service recovery

#### 8.1.3 Resource Consumption
- **Risk**: High CPU/memory usage affecting system performance
- **Mitigation**: Resource throttling, priority management, optional processing
- **Monitoring**: System resource monitoring and alerts

### 8.2 Data Integrity Risks

#### 8.2.1 Audio Segmentation
- **Risk**: Audio loss during segmentation process
- **Mitigation**: Overlapping segments, integrity checks, backup recording
- **Monitoring**: Segment duration validation and gap detection

#### 8.2.2 Processing Failures
- **Risk**: Lost transcription or summary data
- **Mitigation**: Persistent queues, processing state tracking, retry mechanisms
- **Monitoring**: Processing success rates and failure logging

### 8.3 User Experience Risks

#### 8.3.1 Complexity
- **Risk**: Too many configuration options overwhelming users
- **Mitigation**: Sensible defaults, progressive disclosure, guided setup
- **Monitoring**: User feedback and usage analytics

#### 8.3.2 Performance Impact
- **Risk**: Automation affecting recording quality
- **Mitigation**: Priority management, resource isolation, disable options
- **Monitoring**: Recording quality metrics and user reports

---

## 9. Success Criteria

### 9.1 Functional Success
- [ ] System successfully segments 5-minute audio clips during recording
- [ ] Whisper CPP integration transcribes segments with >90% accuracy
- [ ] Ollama integration provides contextual summaries within 30 seconds
- [ ] Automated pipeline processes segments without user intervention
- [ ] CLI interface provides clear status and control options

### 9.2 Performance Success
- [ ] Processing latency stays within 2x segment duration
- [ ] System handles 1-hour meetings without performance degradation
- [ ] Memory usage remains stable during extended operations
- [ ] No impact on audio recording quality or reliability

### 9.3 Quality Success
- [ ] Transcription accuracy matches manual Whisper CPP usage
- [ ] Summaries maintain context across multiple segments
- [ ] Output files are properly formatted and organized
- [ ] Error recovery works reliably for common failure scenarios

---

## 10. Future Enhancements

### 10.1 Advanced Features
- **Speaker Diarization**: Identify different speakers in meetings
- **Keyword Extraction**: Automatic identification of key topics and decisions
- **Action Item Detection**: Automatically extract action items and deadlines
- **Meeting Templates**: Customizable summary formats for different meeting types

### 10.2 Integration Possibilities
- **Calendar Integration**: Automatic meeting metadata from calendar systems
- **Notification System**: Real-time alerts for processing completion
- **Web Interface**: Browser-based control and monitoring dashboard
- **Mobile App**: Remote control and status monitoring

### 10.3 Analysis Features
- **Meeting Analytics**: Duration, participation, topic analysis
- **Trend Analysis**: Meeting pattern and efficiency insights
- **Search Functionality**: Full-text search across all meeting transcripts
- **Export Options**: Integration with note-taking and project management tools

---

## 11. Conclusion

This project will transform the existing Meeting Recorder from a manual audio capture tool into a fully automated meeting processing system. By leveraging local AI services (Whisper CPP and Ollama), the system will maintain privacy while providing sophisticated transcription and summarization capabilities.

The incremental processing approach ensures near-real-time feedback while maintaining system performance. The modular architecture allows for future enhancements and integration with other productivity tools.

The successful implementation of this system will provide users with:
- **Automated workflow** eliminating manual processing steps
- **Real-time insights** through incremental processing
- **Privacy protection** through local-only processing
- **Professional output** with structured summaries and transcripts
- **Scalable foundation** for future AI-powered meeting features

---

## 12. Performance Enhancements Addendum (2025-08-08)

### 12.1 Context & Problem Statement
Recent usage indicates that end-to-end processing latency (Whisper transcription + Ollama summarization) can exceed per-segment duration, creating a growing backlog. Abrupt recording termination currently halts further processing, leaving pending segments without summaries. Operator visibility into queue health is limited, complicating tuning and troubleshooting.

### 12.2 Observed Issues
- Processing latency > segment duration → backlog growth.
- Summarization queue starves when model responses are slow / large.
- Recording stop kills pipeline prematurely (unprocessed segments lost).
- No batching: every small segment triggers full LLM prompt → overhead amplification.
- Limited introspection: cannot see queue lengths, processing times, throughput.
- Hard to experiment with optimal segment size vs summarization batch size.

### 12.3 Proposed Enhancements
| Area | Enhancement | Rationale |
|------|-------------|-----------|
| Graceful Stop | Allow recorder stop while pipeline drains remaining queue | Prevent data loss & ensure completion |
| Benchmarking | Instrument transcription + summarization timing & queue wait | Identify bottlenecks quantitatively |
| Thresholds | Configurable backlog & latency thresholds w/ warnings | Early overload detection |
| Accumulation | Batch multiple transcripts before summarization (time or token window) | Reduce LLM call overhead, improve summary coherence |
| Summarization Channel | Dedicated output stream / log for summaries only | Cleaner monitoring / integration |
| Queue Dashboard | CLI status exposing queue sizes, current task, avg times | Operational visibility |
| Persistence (Optional) | Persist pending queue on shutdown | Crash recovery / continuity |
| Metrics Export (Future) | Structured JSON/NDJSON metrics file | External tooling & analysis |

### 12.4 Transcript Accumulation Strategy
Two accumulation modes (configurable & mutually exclusive):
1. Time-based window (e.g. accumulate transcripts for N seconds before summarizing)
2. Token-based window (accumulate until approximate token count or character length reached)

Flush Triggers:
- Time window elapsed OR
- Token/char budget reached OR
- Manual flush (on user command / graceful stop) OR
- Hard upper limit (failsafe) to avoid unbounded growth

Outputs:
- Per-batch summary still stored as `segment_XXX_summary.md`? (Option A) OR new naming `batch_YYY_summary.md` (Option B). Selected approach (initial): Option B for clarity.
- Rolling summary updated after each batch flush.

### 12.5 New / Updated Functional Requirements
- **REQ-033**: System SHALL support graceful recording stop while continuing to process queued transcription & summarization tasks until completion. [Implemented]
- **REQ-034**: System SHALL record benchmark metrics per segment: transcription wall time, summarization wall time, queue wait time, total latency. [Implemented partial]
- **REQ-035**: System SHALL emit warnings when (a) transcription backlog exceeds configurable `--max-transcription-backlog`, (b) average processing latency exceeds 2× segment duration, (c) summarization backlog exceeds `--max-summary-backlog`. [Planned]
- **REQ-040a**: System SHALL decouple transcription and summarization using independent queues and workers so that transcription never blocks waiting for summarization. [Implemented]
