# PROJECT_PROGRESS.md

**Local AI Video Clipper - Central Source of Truth**

---

## Project Objective

Build a completely free, local AI-powered automatic video clipper that:
- Takes a video file + desired clip duration + number of clips + optional instruction
- Analyzes video using local AI (speech-to-text + LLM reasoning)
- Generates clips with EXACT requested duration
- **$0 cost** - No paid APIs, no subscriptions, no cloud AI, no paid GPU, no mandatory external SaaS

---

## Hard $0-Cost Requirement

| Constraint | Status |
|------------|--------|
| No paid APIs | ✅ Enforced |
| No subscriptions | ✅ Enforced |
| No cloud AI | ✅ Enforced |
| No paid GPU required | ✅ Enforced (CPU fallback) |
| No mandatory external SaaS | ✅ Enforced |
| All AI runs locally | ✅ Enforced |

---

## Current Milestone: **Milestone 02 - Transcription Engine**

**Status: COMPLETED**

### Completed Work

1. **Dependencies Added**
   - `faster-whisper>=1.1.0` - Local speech-to-text
   - `torch>=2.4.0` (CPU variant via `--index-url https://download.pytorch.org/whl/cpu`)
   - Dependencies: `ctranslate2`, `huggingface-hub`, `tokenizers`, `onnxruntime`, `av`, `numpy`, `tqdm`, `pyyaml`

2. **Model Selection**
   - **Model: `small`** (244M parameters, ~488 MB)
   - **Rationale**: Good accuracy/speed tradeoff for 16 GB RAM CPU machine
   - `tiny` (39M) - too low accuracy
   - `base` (74M) - better but still limited
   - `small` (244M) - sweet spot for CPU
   - `medium` (769M) - slower, ~1.5 GB
   - `large` (1550M) - too heavy for 16 GB RAM
   - Model downloads on first use (lazy loading), not during installation

3. **Architecture Created**
   ```
   app/transcription/
   ├── __init__.py           # Public API exports
   ├── __main__.py           # CLI entry point
   ├── models.py             # Typed data models (TranscriptSegment, WordTimestamp, TranscriptionResult)
   ├── exceptions.py         # Domain-specific exceptions
   ├── service.py            # TranscriptionService with FFmpeg audio extraction
   └── cli.py                # Developer CLI for manual testing
   ```

4. **Core Features Implemented**
   - **Audio extraction**: FFmpeg subprocess (safe arg lists, no shell injection)
   - **Transcription**: faster-whisper with word-level timestamps
   - **Language detection**: Automatic with probability scores
   - **Supported formats**: MP4, MKV, MOV, AVI, WebM, MP3, WAV, M4A, FLAC, OGG
   - **CPU-only execution**: `device="cpu"`, `compute_type="int8"`
   - **Lazy model loading**: Model loads on first transcription call
   - **Structured output**: JSON-serializable dataclasses with full timestamps

5. **Error Handling**
   - `InputFileNotFoundError` - missing file
   - `UnsupportedMediaFormatError` - invalid/corrupt media
   - `FFmpegNotFoundError` - FFmpeg not in PATH
   - `FFmpegExecutionError` - FFmpeg processing failure
   - `ModelNotAvailableError` - model download/load failure
   - `InvalidModelConfigurationError` - bad model/device/compute config
   - `TranscriptionFailedError` - Whisper runtime error
   - `EmptyAudioError` - no speech detected
   - `AudioExtractionError` - audio extraction failure

6. **Tests (46 passing)**
   - Model validation (timestamps, serialization, edge cases)
   - Service initialization (valid/invalid configs)
   - Input validation (missing files, dirs, extensions)
   - FFmpeg error handling (not found, execution error, timeout)
   - Transcription flow (success, empty audio, model failure, wrapped errors)

7. **Code Quality**
   - Ruff: ✅ All checks passed
   - MyPy: ✅ No issues (10 source files)
   - Pytest: ✅ 46/46 passed

8. **CLI Verification**
   - `python -m app.transcription --help` works
   - `python -m app.transcription <video>` ready for manual testing

---

## Environment Status

| Component | Status | Version/Details |
|-----------|--------|-----------------|
| Python | ✅ Available | 3.10.11 |
| Virtual Env | ✅ Created | `.venv/` |
| Pip | ✅ Upgraded | 26.2.1 |
| Git | ✅ Initialized | Clean, main branch |
| FFmpeg | ✅ Available | 9.0.2 (winget, added to user PATH) |
| Ollama | ⚠️ Installed, not running | Client v0.32.15 |
| Dependencies | ✅ Installed | 20+ packages |

---

## Tests Performed

| Test | Result |
|------|--------|
| Python environment activation | ✅ PASS |
| Package imports (faster-whisper, torch, etc.) | ✅ PASS |
| All unit tests (46 tests) | ✅ PASS |
| Ruff linting | ✅ PASS |
| MyPy type checking | ✅ PASS |
| CLI help command | ✅ PASS |
| Model loading (dry run) | ✅ PASS |

---

## Security Considerations

- ✅ No shell injection - subprocess uses arg lists
- ✅ No arbitrary command execution
- ✅ No network API calls in transcription (only model download from HF on first use)
- ✅ No hardcoded credentials
- ✅ No secrets
- ✅ No unsafe temp file handling (uses `tempfile.TemporaryDirectory`)
- ✅ User-provided paths validated and resolved
- ✅ Input file extension allowlist
- ✅ FFmpeg binary located via `shutil.which()` (PATH only)

---

## Known Limitations

1. **Model downloads on first use** - Requires internet for initial model fetch (~488 MB for `small`)
2. **CPU-only** - Transcription slower than GPU (expected for $0 cost)
3. **No VAD** - No voice activity detection preprocessing (Whisper handles silence)
4. **Single model instance** - Service reuses loaded model (good for batch, not for multi-model)
5. **No real integration test** - No test video in repo; manual test requires user-provided media

---

## Important Decisions

1. **Model: `small`** - Best balance for 16 GB RAM CPU
2. **Direct FFmpeg subprocess** - No `ffmpeg-python` dependency, safer
3. **Lazy model loading** - No surprise downloads during import
4. **Word-level timestamps** - Enabled for future clip selection precision
5. **compute_type=int8** - Optimal for CPU inference speed/memory
6. **Structured exceptions** - Domain-specific, actionable errors
7. **JSON serializable models** - Easy for AI module consumption

---

## Next Milestone: **Milestone 03 - AI Reasoning Module (Ollama + Qwen)**

### Scope
- Integrate Ollama for local LLM inference
- Use Qwen model (e.g., `qwen2.5:7b` or `qwen2.5:3b`) for clip selection reasoning
- Create AI service that takes transcript segments + user instruction → clip timestamps
- Structured output: list of (start, end, reason) for clip candidates

### Dependencies to Add
- `ollama>=0.3.0` (Python client)

### Prerequisites
- Ollama daemon running (`ollama serve`)
- Qwen model pulled (`ollama pull qwen2.5:7b`)

### Deliverables
- `app/ai/service.py` - AI reasoning service
- `app/ai/models.py` - Clip candidate data models
- Unit tests for AI service (mocked Ollama)
- Updated `requirements.txt`
- Updated `PROJECT_PROGRESS.md`

---

## Exact Current Project State

```
D:\video_scliser\
├── .git/
├── .venv/                 # Python 3.10.11 virtual env
├── app/
│   ├── __init__.py
│   ├── transcription/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── models.py
│   │   ├── exceptions.py
│   │   ├── service.py
│   │   └── cli.py
│   ├── ai/
│   │   └── __init__.py
│   ├── video/
│   │   └── __init__.py
│   ├── clipping/
│   │   └── __init__.py
│   └── ui/
│       └── __init__.py
├── tests/
│   ├── __init__.py
│   ├── test_transcription_models.py
│   └── test_transcription_service.py
├── input/
├── output/
├── docs/
│   └── PROJECT_PROGRESS.md
├── readme.txt             # Original file (preserved)
├── README.md
├── requirements.txt
└── .gitignore
```

**Git Commit (to be created):** `feat: add local timestamped transcription engine`

---

*Last Updated: 2026-10-02 | Milestone 02 Complete*