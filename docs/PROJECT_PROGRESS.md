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

## Current Milestone: **Milestone 04 - Video Processing Engine**

**Status: COMPLETED**

### Architecture

```
app/video/
├── __init__.py      # Public API exports
├── __main__.py      # python -m app.video (exit code propagated)
├── exceptions.py    # VideoProcessingError hierarchy (10 exceptions)
├── models.py        # VideoInfo, ClipRequest, ProcessedVideo (frozen, validated, NaN/inf rejected)
├── ffmpeg.py        # FFmpegRunner - locates ffmpeg/ffprobe, runs argument lists, timeout, stderr tail
├── probe.py         # validate_input_path, parse_ffprobe_output, probe_video
├── service.py       # VideoService.extract_clip / extract, safe_output_path, tolerance rule
└── cli.py           # probe / extract / selftest developer commands
```

Pipeline position: Transcript (M02) -> Qwen candidates (M03) -> **M04 engine** -> M05 automatic clip generation.

### Implementation Details

1. **Probing**: one `ffprobe -show_format -show_streams -of json` call, parsed into `VideoInfo`.
   - Container allowlist: extension (`.mp4/.mkv/.mov/.avi/.webm`) **and** ffprobe demuxer (`mov,mp4`, `matroska,webm`, `avi`).
   - Duration must be finite and > 0. Width/height must be > 0. fps comes from `avg_frame_rate`, falling back to `r_frame_rate`.
   - The video stream is required. Audio is optional, and the first audio stream is detected anywhere in the stream list.
   - Corrupt files, non-zero ffprobe exits, malformed JSON and invalid values all raise `InvalidVideoError`.
2. **Request validation** (before FFmpeg runs): start >= 0, duration > 0, both finite numbers.
   start < source duration, and start + duration <= source duration (1e-6 float slack only).
3. **Extraction**: `ffmpeg -ss S -i IN -t D -map 0:v:0 [-map 0:a:0 | -an] libx264/aac -> temp.mp4`.
4. **Output safety**: `overwrite=False` by default (`OutputAlreadyExistsError`). Output must be `.mp4` and differ from the input.
   Parent dirs are created. The temp file `.partial-*.mp4` sits in the same directory, so `os.replace` is atomic.
   On any failure the temp file is deleted, and an existing output is left untouched.
5. **Path safety**: all paths go through `pathlib`. `safe_output_path(dir, name)` rejects names resolving outside `dir`.

### Exact-Duration Strategy

- **Always re-encode.** Stream copy cuts only at keyframes, so durations are off by up to a GOP (often seconds).
- Input-side `-ss` with re-encoding is frame-accurate in modern FFmpeg, and it avoids decoding from 0.
- Output-side `-t` cuts audio sample-exactly. Video can only end on a frame boundary.
- **Tolerance (V1): `|actual - requested| <= max(0.05 s, 1/fps)`**, i.e. 50 ms, or one frame for sources under 20 fps.
- The output is re-probed after encoding, and anything outside the tolerance raises `OutputValidationError` and is discarded.
- **Measured on FFmpeg 9.0.2:** max error **0.023 s** across 30 fps and 23.976 fps sources and odd starts and durations
  (e.g. 7.777 s -> 7.800 s at 30 fps). Round durations at 30 fps came out exact (5.000000 s).

### Codec / Container Decisions

- Output: MP4, H.264 (`libx264`, preset `medium`, CRF 23, `yuv420p`), AAC 192 kbps, `+faststart`.
  This is the most widely playable combination (browsers, phones, editors, social platforms), and it's all in the free FFmpeg build.
- The source container is not preserved. Output is always `.mp4`.

### Audio Behavior

- Source with audio: the first audio stream is re-encoded to AAC. Validation fails if the output has no audio.
- Source without audio: `-an`, so the output is a valid video-only MP4 and no silent track is invented.

### Concatenation - DEFERRED

Not implemented in M04. Clean concatenation needs stream normalization (resolution, fps, sample rate, audio presence)
across clips. Nothing in the M05 scope ("N clips of D seconds") requires it, so it is deferred rather than shipped fragile.

### Tests (113 new, 227 total)

- `test_video_models.py`: VideoInfo/ClipRequest/ProcessedVideo validation, NaN/inf/negative/zero/non-number/bool rejection, round-trip, frozen.
- `test_video_ffmpeg.py`: ffmpeg missing, ffprobe missing, explicit paths, argument list with hostile filename passed verbatim, no `shell=True`, timeout/OSError wrapping, stderr tail.
- `test_video_probe.py`: parsing with/without audio, audio after subtitle streams, all 5 containers, unsupported container, malformed JSON, N/A/0/negative/NaN/inf duration, bad dimensions/fps, extension allow/deny, missing file, directory, Windows paths with spaces/unicode, corrupt file.
- `test_video_service.py` (fake runner writing real temp files): invalid numbers, start beyond source, clip past end rejected with no FFmpeg call, clip ending exactly at source end, unsupported input, non-mp4 output, audio present/absent args, lost-audio validation, duration outside/inside tolerance, FFmpeg failure cleanup, hidden temp in output dir, parent dir creation, overwrite refused/allowed, failed overwrite keeps the old file, traversal rejection, Windows paths as single arguments.
- `test_video_integration.py`: real FFmpeg selftest. It skips automatically when FFmpeg is not on PATH.

### Quality Gates

- Pytest: 227 passed with FFmpeg on PATH (226 passed + 1 skipped without it). All M01-M03 tests still pass.
- Ruff: M04 code and tests clean. 21 pre-existing auto-fixable import warnings remain in M02/M03 test files (untouched, out of scope).
- MyPy: `mypy app` clean, and `mypy --strict app/video tests/test_video_*` clean.

### Manual Verification

`python -m app.video selftest` (FFmpeg 9.0.2, Windows 11) generated synthetic sources locally (no downloads):

| Source | fps | Audio | Requested | Actual | Error |
|---|---|---|---|---|---|
| mp4 | 30 | yes | 5.000 | 5.000000 | 0.0000 |
| mp4 | 30 | yes | 7.777 | 7.800000 | 0.0230 |
| mkv | 23.976 | no | 5.000 | 5.005000 | 0.0050 |
| mkv | 23.976 | no | 7.777 | 7.799458 | 0.0225 |
| mov | 25 | yes | 2.000 | 2.000000 | 0.0000 |
| avi | 25 | yes | 2.000 | 2.000000 | 0.0000 |
| webm | 30 | yes | 2.000 | 2.000000 | 0.0000 |

It also checked that a clip past the source end is rejected with no output written, that an existing output is not overwritten without the flag, that `overwrite=True` works, and that no temp files are left.

### Security

- All FFmpeg/FFprobe calls are `subprocess.run([...], shell=False)` argument lists. A hostile filename is passed as a single argument (tested).
- No model output is executed or turned into arguments; M05 must pass only validated floats and `safe_output_path` results.
- No network access, no downloads, and no new dependencies. Stderr is truncated to its last 500 chars in errors.
- No partial outputs are ever presented as successful (temp file + validation + atomic rename).

### Known Limitations

1. Variable-frame-rate sources are converted using the average frame rate. Validation still guarantees the final duration.
2. Only the first video and first audio streams are kept. Subtitles, data and extra audio tracks are dropped.
3. Duration is validated on the container duration (the max over streams), not per stream.
4. Tolerance below one frame is not achievable with constant-frame-rate video. Sources under 20 fps get a one-frame tolerance.
5. Re-encoding is CPU-bound. There is no hardware encoding, by design.
6. The default timeout is 600 s per FFmpeg call (configurable via `FFmpegRunner(timeout=...)`).
7. Concatenation is deferred (see above).
8. Sessions started before FFmpeg was installed won't see it until a new terminal is opened.

---

## Milestone 03 - AI Reasoning Module

**Status: COMPLETED**

### Completed Work

1. **Dependencies Added**
   - `ollama>=0.3.0` - Official Ollama Python client
   - Transitive: `pydantic>=2.9`

2. **Model Selection**
   - **Model: `qwen2.5:0.5b`** (494M parameters, ~398 MB)
   - **Rationale**: Optimal for 16 GB RAM CPU-only machine
   - `qwen2.5:0.5b` (494M) - Fast, fits easily in 16 GB RAM, good reasoning quality
   - `qwen2.5:3b` (3B) - Slower, ~1.8 GB, better quality
   - `qwen2.5:7b` (7B) - Too slow on CPU, ~4.7 GB, best quality
   - Model pulling is explicit user action (`ollama pull qwen2.5:0.5b`), not automatic

3. **Architecture Created**
   ```
   app/ai/
   ├── __init__.py           # Public API exports
   ├── __main__.py           # CLI entry point
   ├── models.py             # ClipCandidate, ClipAnalysisResult (typed, validated, serializable)
   ├── exceptions.py         # 8 domain-specific exceptions
   ├── client.py             # OllamaClient with lazy connection, error handling
   ├── prompts.py            # System/user prompts, transcript formatting, JSON parsing
   ├── service.py            # AIReasoningService - main orchestration
   └── cli.py                # Developer CLI for manual testing
   ```

4. **Core Features Implemented**
   - **Strict JSON output** - Prompt enforces JSON-only response, no markdown fences
   - **Transcript preparation** - Compact timestamped format, configurable max chars (default 8000)
   - **Timestamp validation** - All candidates validated: numeric, finite, >=0, end>start, within duration
   - **Score validation** - Enforced 0.0-1.0 range, invalid candidates skipped with warning
   - **Deterministic sorting** - By score descending, then start timestamp ascending
   - **Candidate limit** - Configurable max (default 20)
   - **Lazy Ollama connection** - No daemon required for imports or unit tests
   - **Environment configuration** - OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_TIMEOUT, AI_MAX_CANDIDATES, AI_TEMPERATURE

5. **Error Handling**
   - `OllamaUnavailableError` - Daemon not reachable
   - `OllamaModelUnavailableError` - Model not pulled
   - `AIInferenceError` - Generation failure
   - `AIResponseParseError` - Malformed JSON or missing fields
   - `InvalidCandidateError` - Validation failures (logged, candidate skipped)
   - `InvalidConfigurationError` - Bad config values
   - `TranscriptTooLargeError` - Input exceeds max chars
   - `EmptyTranscriptError` - No segments to analyze

6. **Tests (68 new tests, 114 total passing)**
   - Model validation (timestamps, scores, serialization, edge cases)
   - Prompt building and JSON parsing (valid, markdown fences, malformed, limits)
   - Client (config, availability, model check, generation, errors)
   - Service (success, empty transcript, unavailable, model missing, inference error, parse error, invalid candidates, deterministic ordering, candidate limit, optional fields)
   - All tests mock Ollama - no daemon required

7. **Code Quality**
   - Ruff: ✅ All checks passed
   - MyPy: ✅ No issues (18 source files)
   - Pytest: ✅ 114/114 passed

8. **Manual Integration Verification**
   - Ollama daemon running
   - `qwen2.5:0.5b` model pulled
   - CLI test with sample transcript JSON
   - Returns valid candidates with timestamps, scores, reasons

---

## Environment Status

| Component | Status | Version/Details |
|-----------|--------|-----------------|
| Python | ✅ Available | 3.10.11 |
| Virtual Env | ✅ Created | `.venv/` |
| Pip | ✅ Upgraded | 26.2.1 |
| Git | ✅ Initialized | Clean, main branch |
| FFmpeg | ✅ Available | 9.0.2 (winget, in PATH) |
| Ollama | ✅ Running | 0.32.15, `qwen2.5:0.5b` pulled |
| Dependencies | ✅ Installed | 24 packages |

---

## Tests Performed

| Test | Result |
|------|--------|
| Python environment activation | ✅ PASS |
| Package imports (ollama, pydantic, faster-whisper, torch) | ✅ PASS |
| All unit tests (114 tests) | ✅ PASS |
| Ruff linting | ✅ PASS |
| MyPy type checking | ✅ PASS |
| CLI help command | ✅ PASS |
| Manual AI reasoning test | ✅ PASS |

---

## Security Considerations

- ✅ No shell injection - subprocess uses arg lists
- ✅ No arbitrary command execution
- ✅ No external API calls - only local Ollama HTTP
- ✅ No hardcoded credentials
- ✅ No secrets
- ✅ No unsafe temp file handling
- ✅ User-provided paths validated
- ✅ Input file extension allowlist
- ✅ LLM output validated before use (JSON parsing, timestamp validation, score bounds)
- ✅ Untrusted inputs (instruction, transcript, LLM output) all validated
- ✅ No execution of model output

---

## Known Limitations

1. **Model downloads require explicit user action** - `ollama pull qwen2.5:0.5b`
2. **CPU-only inference** - Slower than GPU (expected for $0 cost)
3. **Context window limit** - Transcript truncated at 8000 chars (configurable)
4. **Single model instance** - Service reuses model connection
5. **No real integration test in CI** - Requires Ollama daemon + model
6. **qwen2.5:0.5b reasoning quality** - Smaller model, may miss nuance vs larger models

---

## Important Decisions

1. **Model: `qwen2.5:0.5b`** - Best balance for 16 GB RAM CPU
2. **Strict JSON prompts** - No natural language parsing, deterministic output
3. **Lazy Ollama connection** - Tests run without daemon
6. **Graceful candidate skipping** - Invalid candidates logged and skipped, not fatal
7. **Deterministic ordering** - Score desc, then start asc
8. **Environment-based config** - No hardcoded values

---

## Next Milestone: **Milestone 05 - Automatic Clip Selection/Generation**

### Scope
- Connect the transcript (M02) and Qwen candidates (M03) to the M04 engine (`VideoService.extract_clip`)
- Honour the requested number of clips and the exact duration per clip
- Fit/expand candidate windows to the requested duration within source bounds
- Name outputs via `safe_output_path`

### Dependencies to Add
- None expected

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
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── models.py
│   │   ├── exceptions.py
│   │   ├── client.py
│   │   ├── prompts.py
│   │   ├── service.py
│   │   └── cli.py
│   ├── video/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── exceptions.py
│   │   ├── models.py
│   │   ├── ffmpeg.py
│   │   ├── probe.py
│   │   ├── service.py
│   │   └── cli.py
│   ├── clipping/
│   │   └── __init__.py
│   └── ui/
│       └── __init__.py
├── tests/
│   ├── __init__.py
│   ├── test_transcription_models.py
│   ├── test_transcription_service.py
│   ├── test_ai_models.py
│   ├── test_ai_prompts.py
│   ├── test_ai_client.py
│   ├── test_ai_service.py
│   ├── test_video_models.py
│   ├── test_video_ffmpeg.py
│   ├── test_video_probe.py
│   ├── test_video_service.py
│   └── test_video_integration.py
├── input/
├── output/
├── docs/
│   └── PROJECT_PROGRESS.md
├── readme.txt             # Original file (preserved)
├── README.md
├── requirements.txt
└── .gitignore
```

**Git Commit:** `feat: add FFmpeg video processing engine`

---

*Last Updated: 2026-10-02 | Milestone 04 Complete*