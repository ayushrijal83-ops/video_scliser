# 🧑‍💻 Usage Guide

Every way to drive the clipper: the web UI, the five CLIs, and the Python API. It also covers the input limits,
the output formats, and how to choose a model.

> Setup first? See [SETUP.md](SETUP.md). All commands assume the virtual environment is active and you're in the
> project folder.

- [Web UI](#-web-ui)
- [Pipeline CLI: `app.clipping`](#-pipeline-cli-appclipping)
- [Transcription: `app.transcription`](#-transcription-apptranscription)
- [AI reasoning: `app.ai`](#-ai-reasoning-appai)
- [Video engine: `app.video`](#-video-engine-appvideo)
- [Python API](#-python-api)
- [Input limits](#-input-limits)
- [Choosing models](#-choosing-models)
- [Environment variables](#-environment-variables)
- [Tips for good results](#-tips-for-good-results)

---

## 🌐 Web UI

```bash
python -m app.ui            # or double-click start.bat on Windows
```

Open **<http://127.0.0.1:5000/>**.

| Step | Page | What you see |
|---|---|---|
| 1 | **Generate clips** | Pick a video, the clip count, the seconds per clip and an optional focus. The button locks while the upload runs |
| 2 | **Processing …** | The real pipeline stage, refreshed every 3 s: *Checking the video → Transcribing speech (Whisper) → Finding moments with local AI (Qwen) → Selecting distinct moments → Cutting clips (FFmpeg) → Verifying clips* |
| 3 | **N clips ready** | Summary (video, request, model, valid candidates, processing time). Each clip shows its duration, `start → end` timecode, score, reason and a **Download** button |
| ✗ | **Generation failed** | A plain-language reason. The upload and any partial clips are removed |

| | |
|---|---|
| Formats | MP4, MKV, MOV, AVI, WebM. Checked by extension **and** by FFprobe; the browser's MIME type is ignored |
| Upload limit | 2048 MB (`CLIPPER_MAX_UPLOAD_MB`). Uploads stream to disk, never into RAM |
| Concurrency | One job at a time. A second submit is asked to wait |
| Clips | `output/ui_jobs/<job-id>/clip_001.mp4 …`, kept until you delete them |
| Upload copy | `input/ui_uploads/<job-id>/`, **deleted when the job ends** (success or failure). Leftovers from a crash are removed on the next start |
| Job status | Kept in memory. After a restart the result pages are gone, but the clip files stay on disk |

---

## ⌨️ Pipeline CLI: `app.clipping`

The same pipeline as the UI, from the terminal.

```bash
python -m app.clipping input/meeting.mp4 -n 3 -d 30 -i "funny moments"
python -m app.clipping input/meeting.mp4 -n 3 -d 30 -i "funny moments" -o output/my_job --language en --whisper-model small
```

| Flag | Required | Default | Meaning |
|---|---|---|---|
| `input` | ✅ | | Source video |
| `-n, --count` | ✅ | | Number of clips (1-20) |
| `-d, --duration` | ✅ | | Seconds per clip (1-600) |
| `-i, --instruction` | ✅ | | What to look for (1-500 chars) |
| `-o, --output-dir` | | `output/<video>_<YYYYmmdd-HHMMSS>/` | Where the clips go |
| `--whisper-model` | | `small` | `tiny` `base` `small` `medium` `large` |
| `--language` | | auto-detect | e.g. `en` (skips detection) |
| `-v, --verbose` | | off | Debug logging |

**Output.** Progress goes to **stderr** as `[time] status detail`. The JSON result goes to **stdout**, so you can
redirect it: `... > result.json`.
**Exit codes:** `0` success · `1` the job failed · `2` bad input.

```
output/meeting_20261003-153000/
├── clip_001.mp4    best-ranked moment
├── clip_002.mp4
└── clip_003.mp4
```

Each clip in the JSON has: `index, path, start, end, duration, actual_duration, score, reason, title,
candidate_start, candidate_end, quote, ai_start, ai_end`.

Existing `clip_NNN.mp4` files are **never overwritten**. If any are already present, the job refuses to start.

---

## 🎙️ Transcription: `app.transcription`

```bash
python -m app.transcription input/video.mp4
python -m app.transcription input/video.mp4 --model base --language en --output transcript.json -v
```

| Flag | Default | Meaning |
|---|---|---|
| `--model` | `small` | Whisper model size |
| `--device` | `cpu` | Inference device |
| `--compute-type` | `int8` | Quantization (fast on CPU) |
| `--language` | auto | Language code |
| `--output` | stdout | JSON file to write |
| `-v, --verbose` | off | Debug logging |

**Output format**

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

---

## 🧠 AI reasoning: `app.ai`

Ask the local LLM for candidate moments in a transcript, without cutting anything.

```bash
python -m app.ai transcript.json "Find the most interesting moments"
python -m app.ai input/video.mp4 "Find funny moments" --transcribe
python -m app.ai transcript.json "Find educational moments" --model qwen2.5:0.5b --max-candidates 10 --temperature 0.1 -o results.json
```

| Flag | Default | Meaning |
|---|---|---|
| `--transcribe` | off | `input` is a video: transcribe it first |
| `--model` | `$OLLAMA_MODEL` or `qwen2.5:3b` | Ollama model |
| `--host` | `http://localhost:11434` | Ollama address |
| `--max-candidates` | `20` | Maximum moments returned |
| `--temperature` | `0.1` | Sampling temperature |
| `-o, --output` | stdout | JSON file to write |
| `-v, --verbose` | off | Debug logging |

**Output format**

```json
{
  "instruction": "Find the most educational moments",
  "model_name": "qwen2.5:3b",
  "transcript_duration": 120.5,
  "total_candidates": 1,
  "candidates": [
    {
      "start": 35.2,
      "end": 41.8,
      "reason": "Clear explanation of data types with examples",
      "score": 0.92,
      "title": "",
      "transcript_text": "a variable has a type that decides what you can do with it",
      "confidence": 1.0,
      "quote": "A variable has a type that decides what you can do with it",
      "ai_start": 50.0,
      "ai_end": 58.0
    }
  ],
  "rejected": ["quote not found in transcript: 'types are like boxes'"]
}
```

`start`/`end` are the **grounded** transcript times of `quote`. `ai_start`/`ai_end` are what the model claimed, kept
only for diagnostics (note how far off they can be). `rejected` lists the suggestions that couldn't be found in the
transcript. See [ARCHITECTURE.md → Timestamp grounding](ARCHITECTURE.md#-timestamp-grounding).

---

## 🎞️ Video engine: `app.video`

```bash
python -m app.video probe input/talk.mkv
python -m app.video extract input/talk.mkv output/clip.mp4 --start 12.5 --duration 30 [--overwrite]
python -m app.video selftest
```

- **`probe`** prints container, duration, resolution, fps, codecs and audio presence as JSON.
- **`extract`** cuts one exact-duration clip. The output is always H.264/AAC MP4.
- **`selftest`** generates small synthetic videos in all five containers (with and without audio, 30 and
  23.976 fps). It then checks duration accuracy, out-of-range rejection, overwrite protection and temp-file cleanup.
  No downloads are needed.

---

## 🐍 Python API

**Whole pipeline**

```python
from app.clipping import ClipGenerationService, ClipJobRequest

result = ClipGenerationService().generate(
    ClipJobRequest("input/meeting.mp4", "output/job1", clip_count=3, clip_duration=30.0,
                   instruction="funny moments"))
for clip in result.clips:
    print(clip.index, clip.path, clip.start, clip.end, clip.score, clip.reason)
```

**Transcription**

```python
from app.transcription import TranscriptionService

result = TranscriptionService(model_name="small", device="cpu", compute_type="int8").transcribe("input/video.mp4")
print(result.language, result.duration, result.segment_count)
for seg in result.segments:
    print(f"[{seg.start:.2f} - {seg.end:.2f}] {seg.text}")
```

**AI reasoning**

```python
from app.ai import AIReasoningService, AIReasoningConfig

service = AIReasoningService(AIReasoningConfig.from_env())   # reads OLLAMA_* / AI_* variables
analysis = service.analyze(transcript, instruction="Find the most educational moments")
for c in analysis.candidates:
    print(f"[{c.start:.1f}-{c.end:.1f}] score={c.score:.2f} {c.reason!r} quote={c.quote!r}")
```

**Video**

```python
from app.video import VideoService, safe_output_path

svc = VideoService()
info = svc.probe("input/talk.mkv")                       # VideoInfo(duration=..., has_audio=...)
clip = svc.extract_clip("input/talk.mkv", safe_output_path("output", "clip_01.mp4"),
                        start=12.5, duration=30.0)       # ProcessedVideo(actual_duration=30.0, ...)
```

`safe_output_path(dir, name)` rejects names that would escape `dir` (`../x.mp4`, `C:\x.mp4`, `sub/x.mp4`).
Explicit tool paths: `FFmpegRunner(ffmpeg_path=..., ffprobe_path=...)`.

All errors derive from one base exception per module: `TranscriptionError`, `AIError`, `VideoProcessingError`,
`ClipGenerationError`.

---

## 📏 Input limits

| Parameter | Limit | Why |
|---|---|---|
| Clip count | integer 1-20 | The AI returns at most 20 candidates, so more could never be distinct |
| Clip duration | 1-600 s, finite | Protects a CPU-only machine from runaway jobs |
| Instruction / focus | 1-500 chars | It's inserted into the LLM prompt as data |
| Source video | `.mp4 .mkv .mov .avi .webm`, must have audio, must be ≥ the clip duration | Moments are found from speech |

---

## 🤖 Choosing models

### Speech-to-text (faster-whisper)

| Model | Size | CPU speed | Accuracy |
|---|---|---|---|
| tiny | 75 MB | Fastest | Low |
| base | 142 MB | Fast | Basic |
| **small (default)** | 488 MB | Good | Good |
| medium | 1.5 GB | Slow | Better |
| large | 3 GB | Very slow | Best |

Downloaded automatically from Hugging Face on first use, then cached.

### Moment finding (Ollama)

| Model | Size | AI time per job (laptop CPU) | Quality |
|---|---|---|---|
| qwen2.5:0.5b | 398 MB | ~10-25 s | **Weak**: top-1 moment correct 0/12, real E2E 0/3 |
| **qwen2.5:3b (default)** | 1.9 GB | ~1-8 min | **Good**: top-1 moment correct 9-10/12, real E2E 3/3 |
| qwen2.5:7b | 4.7 GB | Very slow | Likely better (not benchmarked) |

Models are downloaded **only** by you (`ollama pull <model>`). Switch with `OLLAMA_MODEL`:

```powershell
$env:OLLAMA_MODEL = "qwen2.5:0.5b"; python -m app.ui      # PowerShell
```
```bash
OLLAMA_MODEL=qwen2.5:0.5b python -m app.ui                 # bash
```

---

## ⚙️ Environment variables

| Variable | Default | Used by |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | AI |
| `OLLAMA_MODEL` | `qwen2.5:3b` | AI |
| `OLLAMA_TIMEOUT` | `600` | AI: seconds per call |
| `AI_MAX_OUTPUT_TOKENS` | `3072` | AI: Ollama `num_predict` cap; stops a model that loops |
| `AI_MAX_CANDIDATES` | `20` | AI |
| `AI_TEMPERATURE` | `0.1` | AI |
| `CLIPPER_HOST` | `127.0.0.1` | UI |
| `CLIPPER_PORT` | `5000` | UI |
| `CLIPPER_UPLOAD_DIR` | `input/ui_uploads` | UI |
| `CLIPPER_OUTPUT_DIR` | `output/ui_jobs` | UI |
| `CLIPPER_MAX_UPLOAD_MB` | `2048` | UI |
| `CLIPPER_DEBUG` | off | UI (`1`/`true`; never on a non-local host) |

Variables are read from the process environment only. The app doesn't load a `.env` file.

---

## 💡 Tips for good results

- **Be specific with the focus:** *"moments where someone tells a joke"* works better than *"good parts"*.
- **Clear speech matters most.** Moments are found from the transcript. Music, silence and visuals are invisible to the AI.
- **"Only N distinct moments"?** Lower the count or the duration. Clips may overlap by at most ~1/3 of their length,
  so long clips in a short video run out of room quickly.
- **Want repeatable results?** `AI_TEMPERATURE=0` makes runs much more consistent. At the default 0.1, the same video can give different clips.
- **Very long videos:** transcription grows with speech length. Try `--whisper-model base` for a quick first pass.
