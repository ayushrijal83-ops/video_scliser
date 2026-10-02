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
│   ├── transcription/    # Speech-to-text (faster-whisper)
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

## Current Milestone: **Milestone 01 - Foundation** ✅

- [x] Project structure created
- [x] Python virtual environment
- [x] Basic dependencies installed (pytest, ruff, mypy, python-dotenv)
- [x] Git repository initialized
- [x] README.md created
- [x] PROJECT_PROGRESS.md created

## Future Milestones

| Milestone | Focus |
|-----------|-------|
| **02** | Transcription module (faster-whisper integration) |
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
```

## External Dependencies Required

| Tool | Purpose | Install |
|------|---------|---------|
| **FFmpeg** | Video/audio processing | `winget install FFmpeg` (Windows) / `brew install ffmpeg` (macOS) / `apt install ffmpeg` (Linux) |
| **Ollama** | Local LLM inference | https://ollama.ai/download |
| **Python 3.10+** | Runtime | https://python.org |

> **Note:** FFmpeg and Ollama are NOT installed by this project. You must install them separately.

## License

MIT License - Free for personal and commercial use.