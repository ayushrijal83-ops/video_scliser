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
│   ├── ai/               # LLM reasoning (Ollama + Qwen)
│   ├── video/            # Video processing (FFmpeg, OpenCV)
│   ├── clipping/         # Clip selection & generation logic
│   └── ui/               # Local web UI (Flask)
├── tests/                # Unit & integration tests
├── input/                # Input videos
├── output/               # Generated clips
├── docs/                 # Documentation
└── requirements.txt
```

## Current Milestone: **Milestone 02 - Transcription Engine** ✅

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

## Future Milestones

| Milestone | Focus |
|-----------|-------|
| **03** | AI reasoning module (Ollama + Qwen for clip selection) |
| **04** | Video processing module (FFmpeg wrapper) |
| **05** | Clipping logic (timestamp selection → exact duration clips) |
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

# Test transcription (requires video file)
python -m app.transcription input/video.mp4
```

## External Dependencies Required

| Tool | Purpose | Install |
|------|---------|---------|
| **FFmpeg** | Video/audio processing | `winget install FFmpeg` (Windows) / `brew install ffmpeg` (macOS) / `apt install ffmpeg` (Linux) |
| **Ollama** | Local LLM inference (M03+) | https://ollama.ai/download |
| **Python 3.10+** | Runtime | https://python.org |

> **Note:** FFmpeg and Ollama are NOT installed by this project. You must install them separately.

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

Default model: **`small`** (244M parameters, ~488 MB)

| Model | Parameters | Size | CPU Speed | Accuracy |
|-------|------------|------|-----------|----------|
| tiny | 39M | 75 MB | Fastest | Low |
| base | 74M | 142 MB | Fast | Basic |
| **small** | **244M** | **488 MB** | **Good** | **Good** |
| medium | 769M | 1.5 GB | Slow | Better |
| large | 1550M | 3 GB | Very Slow | Best |

Models download automatically on first use from Hugging Face Hub.

## License

MIT License - Free for personal and commercial use.