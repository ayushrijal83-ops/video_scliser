# 🧪 Development Guide

For anyone changing the code: the repo layout, quality gates, tests, benchmarks and conventions.
Install first with [SETUP.md](SETUP.md) (steps 1-5).

---

## 📁 Repository layout

```
video_scliser/
├── app/                      application code (~3,500 lines)
│   ├── transcription/        M02 faster-whisper engine
│   ├── ai/                   M03 Ollama client, prompts, grounding
│   ├── video/                M04 FFprobe/FFmpeg engine
│   ├── clipping/             M05 end-to-end pipeline + selection
│   └── ui/                   M06 Flask app, templates, CSS
├── benchmarks/
│   ├── ai/                   labelled dataset + AI quality benchmark
│   └── e2e/                  real end-to-end harness (real Whisper + Ollama + FFmpeg)
├── tests/                    pytest suite, one file per module/concern
├── docs/                     documentation + images/ (screenshots)
├── input/  output/           runtime data (git-ignored)
├── requirements.txt          runtime + dev dependencies (CPU-only torch)
└── start.bat                 Windows one-click launcher
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for what each module does.

---

## ✅ Quality gates

Run all three before every commit. They are the definition of "done" for every milestone.

```bash
pytest -q                 # 487 passed, 1 skipped (opt-in real-model test)
ruff check .              # lint
mypy app benchmarks       # type check
```

---

## 🧪 Tests

| File | Covers | Needs |
|---|---|---|
| `test_transcription_*.py` | models, service (Whisper + FFmpeg mocked) | nothing |
| `test_ai_*.py`, `test_grounding.py` | client, prompts, parsing, validation, grounding | nothing (Ollama mocked) |
| `test_video_models/probe/service/ffmpeg.py` | probing, bounds, atomic output, arguments | nothing (FFmpeg mocked) |
| `test_video_integration.py` | real exact-duration cutting on synthetic videos | FFmpeg (auto-skips without it) |
| `test_clipping_*.py` | selection, windows, IoU, all-or-nothing | nothing (fake engines) |
| `test_e2e_pipeline.py` | whole pipeline with **real FFmpeg**, fake Whisper/Ollama | FFmpeg (auto-skips) |
| `test_ui.py` | routes, uploads, validation, download security, errors | nothing (Flask test client) |
| `test_benchmark_metrics.py` | benchmark scoring math | nothing |
| `test_real_e2e.py` | **real** Whisper + Ollama + FFmpeg | opt-in: `CLIPPER_REAL_E2E=1` |

```bash
pytest tests/test_grounding.py -q          # one file
pytest -k "overlap" -q                      # by name
pytest --cov=app --cov-report=term-missing  # coverage
CLIPPER_REAL_E2E=1 pytest tests/test_real_e2e.py -s   # real models (slow, local only)
```

**Rule:** the normal `pytest` run never needs Ollama, Whisper or a network connection. New code that touches an
engine should go behind the existing `Protocol`s (`Transcriber`, `Analyzer`, `VideoEngine`, `ClipService`), so it
can be faked.

---

## 📊 Benchmarks

### Real end-to-end harness

```bash
python -m benchmarks.e2e.run_real_e2e --synthesize -n 3 -d 10 -i "funny moments"   # Windows: synthesizes a speech video
python -m benchmarks.e2e.run_real_e2e --synthesize --model qwen2.5:0.5b
python -m benchmarks.e2e.run_real_e2e --video input/talk.mp4 -n 2 -d 15            # any speech video, any OS
```

Prints per-stage timings and writes `output/e2e/<timestamp>/report.json` plus the clips. For each clip the report
gives the quote, its grounded span, the AI's claimed times, and whether the cut contains the quote. It also lists
every rejected candidate. Exit code `0` = exactly N clips, each within tolerance, with audio.

### AI quality benchmark

```bash
python -m benchmarks.ai.run_benchmark --models qwen2.5:0.5b qwen2.5:3b --runs 3     # ~1 h on CPU
python -m benchmarks.ai.run_benchmark --tasks funny --runs 5 --temperature 0 --seed 42
python -m benchmarks.ai.run_benchmark --budgets 8 20 --models qwen2.5:3b             # candidate-budget study
python -m benchmarks.ai.run_benchmark --summarize output/benchmarks/<file>.json      # rescore saved runs
```

`benchmarks/ai/dataset.json` is a labelled synthetic transcript. **The labels are never sent to the model.**
Metrics (top-1 hit, precision, `ok_N`, `hits_N`, …) are computed, not hand-scored. Raw results go to
`output/benchmarks/` (git-ignored). Findings are in [M07_AI_BENCHMARK.md](M07_AI_BENCHMARK.md).

> **Prompt changes need both checks.** In M09 the synthetic benchmark and the real transcript disagreed, and the
> real transcript was right.

---

## 🧭 Conventions

- **Typing:** every function is annotated, and models are `@dataclass(frozen=True)`. `mypy` must stay clean.
- **Errors:** one base exception per package (`exceptions.py`). Wrap with `raise X from e` to keep the cause. User-facing
  text lives only in `app/ui/jobs.py:friendly_error`.
- **Subprocess:** argument lists only, never `shell=True`, never anything built from model output.
- **Paths:** generated names only. Use `safe_output_path()` for anything under an output directory.
- **LLM output is untrusted:** parse as JSON → validate → ground. It never becomes a path, command or filename.
- **Config:** environment variables with safe defaults (`AIReasoningConfig.from_env()`, `UIConfig`).
- **Dependencies:** think twice. The whole app needs four runtime packages (faster-whisper, torch, ollama, flask).
- **Commits:** Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), one milestone or change per commit.
- **Docs:** update `README.md` and the relevant `docs/` page in the same commit as the behaviour change.
  `PROJECT_PROGRESS.md` gets the measurements and decisions.

---

## 🖼️ Updating the screenshots

The images in `docs/images/` come from a real run, captured with headless Chrome:

```bash
python -m app.ui    # in one terminal (with Ollama running)
# in another:
chrome --headless=new --hide-scrollbars --window-size=900,660 --screenshot=docs/images/01-upload-form.png http://127.0.0.1:5000/
# submit a job in the browser, then capture /jobs/<id> while it runs (02-processing.png),
# when it completes (03-results.png), and a failed job (04-error.png).
```
