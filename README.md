# Local AI Video Clipper

A completely free, local AI-powered automatic video clipper. **$0 cost, no cloud dependencies, runs entirely on your machine.**

## Hard Requirements

- ✅ **$0 cost** - No paid APIs, no subscriptions, no cloud AI
- ✅ **Local-only** - All AI processing runs locally
- ✅ **No paid GPU required** - Works on CPU (slower but functional)
- ✅ **No mandatory external SaaS** - Fully self-contained

## Planned Architecture

```
ai-video-clipper/
├── app/
│   ├── transcription/    # Speech-to-text (faster-whisper) ✅
│   ├── ai/               # LLM reasoning (Ollama + Qwen) ✅
│   ├── video/            # Video processing engine (FFmpeg/FFprobe) ✅
│   ├── clipping/         # Automatic clip selection & generation pipeline ✅
│   └── ui/               # Local web UI (Flask)
├── tests/                # Unit & integration tests
├── input/                # Input videos
├── output/               # Generated clips
├── docs/                 # Documentation
└── requirements.txt
```

## Current Milestone: **Milestone 05 - Automatic Clip Selection & Generation** ✅

- [x] Project structure created
- [x] Python virtual environment
- [x] Basic dependencies installed (pytest, ruff, mypy, python-dotenv)
- [x] Git repository initialized
- [x] README.md created
- [x] PROJECT_PROGRESS.md created
- [x] faster-whisper integration with CPU support
- [x] FFmpeg audio extraction (safe subprocess)
- [x] Timestamped transcription with word-level timestamps
- [x] Structured data models (TranscriptSegment, WordTimestamp, TranscriptionResult)
- [x] Comprehensive error handling
- [x] 46 unit tests passing
- [x] Lint (ruff) and type check (mypy) clean
- [x] Developer CLI for manual testing
- [x] Ollama integration for local LLM inference
- [x] qwen2.5:0.5b model for clip selection reasoning
- [x] Strict JSON output with timestamp validation
- [x] Deterministic candidate sorting (score desc, start asc)
- [x] Configurable candidate limit (default 20)
- [x] Transcript truncation for context window management
- [x] 68 AI module tests (114 total) - all mocked, no Ollama required
- [x] Manual integration test verified with real Ollama
- [x] FFprobe media probing (MP4, MKV, MOV, AVI, WebM) into typed `VideoInfo`
- [x] Exact-duration clip extraction (re-encode, verified by re-probing the output)
- [x] Strict bounds: clips past the source end fail, never silently shortened
- [x] Atomic output (temp file → validate → rename), no overwrite by default
- [x] 113 video tests (227 total) - unit tests mock FFmpeg; 1 real-FFmpeg test auto-skips if FFmpeg is absent
- [x] End-to-end pipeline: video + count + duration + instruction → exactly N exact-duration clips
- [x] Deterministic ranking, IoU overlap filtering, boundary-aware exact-duration windows
- [x] All-or-nothing jobs: insufficient moments or any failed clip → clear error, no leftover clips
- [x] 82 clipping tests (310 total) - fake M02/M03/M04, no Ollama/Whisper/FFmpeg needed
- [x] Real end-to-end run verified (faster-whisper small + qwen2.5:0.5b + FFmpeg)

## Future Milestones

| Milestone | Focus |
|-----------|-------|
| **06** | Local web UI (Flask) |
| **07** | End-to-end integration & testing |

## Development Setup

```bash
# Clone & enter
git clone <repo-url>
cd ai-video-clipper

# Create & activate venv
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/macOS

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest

# Lint & type check
ruff check .
mypy app/
```

## External Dependencies Required

| Tool | Purpose | Install |
|------|---------|---------|
| **FFmpeg** | Video/audio processing | `winget install FFmpeg` (Windows) / `brew install ffmpeg` (macOS) / `apt install ffmpeg` (Linux) |
| **Ollama** | Local LLM inference (M03+) | https://ollama.ai/download |
| **Python 3.10+** | Runtime | https://python.org |

> **Note:** FFmpeg and Ollama are NOT installed by this project. You must install them separately.

## Automatic Clip Generation (M05)

```
video + clip count + clip duration + instruction
  │ validating          request limits, probe source (must have audio, be >= clip duration),
  │                     output names clip_001.mp4.. must not exist
  │ transcribing        M02 faster-whisper (TranscriptionService)
  │ analyzing           M03 Ollama + Qwen (AIReasoningService) → candidate moments
  │ selecting           Python: validate vs real source → rank → exact-duration windows → IoU filter
  │ generating          M04 VideoService.extract_clip per window (sequential)
  │ validating_outputs  re-check every clip: exists, duration within tolerance, video + audio present
  ▼ completed           ClipGenerationResult with exactly N GeneratedClip entries
```

**AI suggests, Python decides, FFmpeg executes.** Qwen output only ever becomes validated floats.
It never becomes commands, filenames or paths.

### Usage

```bash
python -m app.clipping input/meeting.mp4 -n 3 -d 30 -i "funny moments"
python -m app.clipping input/meeting.mp4 -n 3 -d 30 -i "funny moments" -o output/my_job --language en --whisper-model small
```

```python
from app.clipping import ClipGenerationService, ClipJobRequest

result = ClipGenerationService().generate(
    ClipJobRequest("input/meeting.mp4", "output/job1", clip_count=3, clip_duration=30.0,
                   instruction="funny moments"))
for clip in result.clips:
    print(clip.index, clip.path, clip.start, clip.end, clip.score, clip.reason)
```

Progress goes to stderr (`[time] status detail`), and the JSON result goes to stdout. The exit code is 0 on success, 1 on job failure and 2 on bad input.

### Input parameters

| Parameter | Limit | Why |
|---|---|---|
| `clip_count` | integer 1-20 | M03 returns at most 20 candidates, so more could never be distinct |
| `clip_duration` | 1-600 s, finite | protects a CPU-only machine from runaway jobs |
| `instruction` | 1-500 chars | it's inserted into the LLM prompt as data |
| source video | `.mp4 .mkv .mov .avi .webm`, must contain audio | moments are found from speech |

### Output

```
output/<video>_<YYYYmmdd-HHMMSS>/     (or --output-dir)
├── clip_001.mp4    best-ranked moment
├── clip_002.mp4
└── ...
```

Each `GeneratedClip` records `index, path, start, end, duration, actual_duration, score, reason, title,
candidate_start, candidate_end`. Existing `clip_NNN.mp4` files are never overwritten: the job refuses to start.

### Selection behavior

1. **Validate** each AI candidate against the probed source. Rejected: non-finite values, negative times, end <= start,
   start or end beyond the source, and scores outside [0, 1].
2. **Rank** by score descending. Ties go to the candidate whose length is closest to the requested duration, then the earliest start.
   There is no randomness and no second LLM pass.
3. **Window**: centered on the candidate, exactly `clip_duration` long. Shorter candidates gain context on both sides,
   and longer ones keep their middle. A window that would start before 0 shifts forward, and one past the end shifts back.
   The start is rounded to whole milliseconds.
4. **Overlap**: walking down the ranking, a window is kept only if its IoU with every already-kept window is
   ≤ **0.2**. For equal-length clips that means sharing at most 1/3 of their length. Duplicates (IoU 1.0) always collapse to the stronger one.
5. **Count**: once `clip_count` windows are kept, rendering starts.

### Insufficient candidates

If fewer distinct moments exist than requested, the job fails **before rendering anything**, for example:
`Only 5 sufficiently distinct candidate moments were identified; requested 6 (AI returned 8 candidates). No clips were generated.`
Nothing is duplicated or invented, and no short list is passed off as success. Run again (Qwen output varies), lower the count,
or use a larger model.

### Exact duration and failures

Every clip goes through M04 (re-encode + re-probe, tolerance `max(0.05 s, 1 frame)`), and M05 then re-checks the result.
Jobs are **all-or-nothing**: if clip 7 fails to render or verify, clips 1-6 of that job are deleted, and
`ClipRenderError` / `OutputVerificationError` reports the clip index and stage. Unrelated files in the folder are untouched.

### Requirements and performance

FFmpeg on PATH, the Ollama daemon running with `qwen2.5:0.5b` pulled, and the faster-whisper model.
The `small` model is downloaded once from Hugging Face on first use (~480 MB) and cached after that.
Measured on an Intel Core Ultra 5 125H (CPU only) with a 70 s 640x360 video: transcription ~17 s, Qwen ~11-22 s,
FFmpeg ~0.7 s per 10-15 s clip, **~41 s per job**. Transcription grows with speech length and rendering with resolution × clip duration.
All stages run sequentially, so only one model is busy at a time.

## Video Processing Engine (M04)

```
VideoService.extract_clip(input, output, start, duration, overwrite=False)
  1. validate request     start >= 0, duration > 0, both finite
  2. probe source         ffprobe -show_format -show_streams -of json
  3. bounds check         start < source duration, start + duration <= source duration
  4. encode to temp       <output dir>/.partial-XXXX.mp4
  5. probe + validate     duration within tolerance, audio kept if source had it
  6. os.replace           temp -> final output (atomic)
```

### Requirements

FFmpeg **and** FFprobe on `PATH` (one install provides both). On Windows: `winget install Gyan.FFmpeg`,
then open a **new** terminal so the updated `PATH` is picked up. Explicit paths can be passed via
`FFmpegRunner(ffmpeg_path=..., ffprobe_path=...)`.

### Inputs and output

| | |
|---|---|
| Input containers | `.mp4`, `.mkv`, `.mov`, `.avi`, `.webm` (extension and ffprobe container both checked) |
| Output | `.mp4` only - H.264 (`libx264`, preset `medium`, CRF 23, `yuv420p`) + AAC 192k, `+faststart` |
| Why | H.264/AAC MP4 plays everywhere (browsers, phones, editors, social uploads) |

### Exact-duration behavior

- Clips are always **re-encoded**. Stream copy can only cut on keyframes, so its durations are unpredictable.
- `-ss` before `-i` with re-encoding is frame-accurate and does not decode the whole file up to `start`.
- After encoding, the output is probed again and rejected if `|actual - requested| > max(0.05 s, 1 frame)`.
  Audio is cut sample-exactly, but video can only end on a frame boundary (one frame = 41.7 ms at 23.976 fps).
- **Measured** on FFmpeg 9.0.2: maximum error **0.023 s** (30 fps and 23.976 fps sources); many clips are exact.
- A clip extending past the source end raises `ClipDurationError`. It is **never** silently shortened.
- Re-encoding is CPU-bound (expected for a $0 local tool). Only the requested span is encoded, and FFmpeg streams the media, so nothing is loaded into Python memory.

### Audio

- Source has audio: the first audio stream is kept (AAC). If the output loses it, validation fails.
- Source has no audio: the output is a valid video-only MP4. No silent track is invented.

### Usage

```python
from app.video import VideoService, safe_output_path

svc = VideoService()
info = svc.probe("input/talk.mkv")              # VideoInfo(duration=..., has_audio=...)
clip = svc.extract_clip("input/talk.mkv", safe_output_path("output", "clip_01.mp4"),
                        start=12.5, duration=30.0)  # ProcessedVideo(actual_duration=30.0, ...)
```

`safe_output_path(dir, name)` rejects generated/user-supplied names that would escape `dir` (`../x.mp4`, `C:\x.mp4`, `sub/x.mp4`).

### CLI and manual verification

```bash
python -m app.video probe input/talk.mkv
python -m app.video extract input/talk.mkv output/clip.mp4 --start 12.5 --duration 30 [--overwrite]
python -m app.video selftest   # real FFmpeg check with synthetic videos (no downloads)
```

`selftest` generates small synthetic videos in all five containers (with and without audio, 30 and 23.976 fps).
It then extracts clips and checks the duration error, out-of-range rejection, overwrite protection and temp-file cleanup.
`pytest` runs the same check (`tests/test_video_integration.py`) whenever FFmpeg is on `PATH`.

## AI Reasoning Module Usage

### As a Library

```python
from app.transcription import TranscriptionResult
from app.ai import AIReasoningService, AIReasoningConfig, ClipAnalysisResult

# Load transcript (from transcription module)
transcript: TranscriptionResult = ...

# Configure AI service
config = AIReasoningConfig.from_env()  # Reads OLLAMA_HOST, OLLAMA_MODEL, etc.
service = AIReasoningService(config)

# Analyze transcript with user instruction
result: ClipAnalysisResult = service.analyze(
    transcript,
    instruction="Find the most educational moments"
)

print(f"Found {result.total_candidates} candidates")
for c in result.candidates:
    print(f"  [{c.start:.1f}-{c.end:.1f}] score={c.score:.2f} - {c.reason}")
```

### CLI

```bash
# Analyze existing transcript JSON
python -m app.ai transcript.json "Find the most interesting moments"

# Transcribe and analyze in one step
python -m app.ai input/video.mp4 "Find funny moments" --transcribe

# With options
python -m app.ai transcript.json "Find educational moments" --model qwen2.5:0.5b --max-candidates 10 --temperature 0.1 -o results.json
```

### Output Format

```json
{
  "instruction": "Find the most educational moments",
  "model_name": "qwen2.5:0.5b",
  "transcript_duration": 120.5,
  "total_candidates": 3,
  "candidates": [
    {
      "start": 35.0,
      "end": 55.0,
      "reason": "Clear explanation of data types with examples",
      "score": 0.92,
      "title": "",
      "transcript_text": "",
      "confidence": 1.0
    }
  ]
}
```

### Configuration (Environment Variables)

```bash
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:0.5b
OLLAMA_TIMEOUT=120
AI_MAX_CANDIDATES=20
AI_TEMPERATURE=0.1
```

## Transcription Module Usage

### As a Library

```python
from app.transcription import TranscriptionService, TranscriptionResult

service = TranscriptionService(model_name="small", device="cpu", compute_type="int8")
result: TranscriptionResult = service.transcribe("input/video.mp4")

print(f"Language: {result.language} ({result.language_probability:.2f})")
print(f"Duration: {result.duration:.2f}s")
print(f"Segments: {result.segment_count}")

for seg in result.segments:
    print(f"  [{seg.start:.2f} - {seg.end:.2f}] {seg.text}")
```

### CLI

```bash
# Basic transcription
python -m app.transcription input/video.mp4

# With options
python -m app.transcription input/video.mp4 --model base --language en --output transcript.json

# Verbose logging
python -m app.transcription input/video.mp4 -v
```

### Output Format

```json
{
  "source_file": "input/video.mp4",
  "language": "en",
  "language_probability": 0.98,
  "duration": 120.5,
  "model_name": "small",
  "segments": [
    {
      "start": 0.0,
      "end": 5.2,
      "text": "Hello and welcome to this tutorial.",
      "words": [
        {"start": 0.0, "end": 0.5, "word": "Hello", "probability": 0.99},
        {"start": 0.5, "end": 1.2, "word": "and", "probability": 0.95}
      ]
    }
  ]
}
```

## Model Selection

### Transcription (faster-whisper)

Default model: **`small`** (244M parameters, ~488 MB)

| Model | Parameters | Size | CPU Speed | Accuracy |
|-------|------------|------|-----------|----------|
| tiny | 39M | 75 MB | Fastest | Low |
| base | 74M | 142 MB | Fast | Basic |
| **small** | **244M** | **488 MB** | **Good** | **Good** |
| medium | 769M | 1.5 GB | Slow | Better |
| large | 1550M | 3 GB | Very Slow | Best |

### AI Reasoning (Ollama)

Default model: **`qwen2.5:0.5b`** (494M parameters, ~398 MB)

| Model | Parameters | Size | CPU Speed | Quality |
|-------|------------|------|-----------|---------|
| **qwen2.5:0.5b** | **494M** | **398 MB** | **Fast** | **Good** |
| qwen2.5:3b | 3B | 1.8 GB | Slow | Better |
| qwen2.5:7b | 7B | 4.7 GB | Very Slow | Best |

Models download manually via `ollama pull <model>`.

## License

MIT License - Free for personal and commercial use.