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

## Current Milestone: **Milestone 08 - AI Selection Quality & Timestamp Grounding**

**Status: COMPLETED**

### Objective

M07 found that qwen2.5:3b often picks the right sentence but returns the wrong timestamps. M08 separates the two jobs:

**AI decides WHAT is interesting (reason, score, an exact quote). Python decides WHERE it happened (transcript
timestamps). FFmpeg decides HOW to cut it.**

### Model default change

- `DEFAULT_MODEL` is now **`qwen2.5:3b`** (`app/ai/client.py`), based on the M07 benchmark.
- `OLLAMA_MODEL` still overrides it, and `qwen2.5:0.5b` remains fully supported.
- The AI CLI's `--model` default now honours `OLLAMA_MODEL` too; before, it was hardcoded.
- `DEFAULT_TIMEOUT` rose from 120 s to **600 s**. M07 measured one 3b call at 117 s on a 2.5 min video, so 120 s
  would fail on longer videos. `OLLAMA_TIMEOUT` overrides it.

### Grounding architecture

```
Transcript (M02, word timestamps) ─┐
                                   ├─> M03 prompt -> Qwen -> JSON {start, end, reason, score, quote}
                                   │                              │
                                   └──────────> M03 validation + app/ai/grounding.py (Python, deterministic)
                                                   quote -> transcript position (word-level, else segment-level)
                                                   ungrounded -> rejected with a reason (never the AI time)
                                                                  │
                     ClipCandidate(start/end = grounded transcript times, ai_start/ai_end = model claim)
                                                                  │
          M05 unchanged: normalize -> rank -> IoU dedupe -> exact-duration windows -> M04 FFmpeg -> verify
```

Grounding runs inside M03's existing validation step (`AIReasoningService._validate_and_create_candidates`), right
after the model output is parsed. That is the only place that has both the raw AI candidates and the timestamped
transcript. M05's selection engine is unchanged: it receives candidates whose `start`/`end` are already transcript
times.

Model changes:
- `ClipCandidate` gains `quote`, `ai_start` and `ai_end`. The AI times are diagnostics, and a tie-breaker between identical quotes.
- `ClipAnalysisResult` gains `rejected` (one "reason: quote" line per rejected candidate).
- `GeneratedClip` gains `quote`, `ai_start` and `ai_end`.

### Grounding algorithm (`app/ai/grounding.py`, ~100 lines, stdlib only)

1. **Normalize** both the quote and the transcript into word tokens: NFKC unicode, lower case, curly/straight
   apostrophes unified then dropped (`don't` = `dont`), every other punctuation mark and all whitespace removed
   (`logged-out` = `logged out`, `“Hello,”` = `hello`). The transcript text and timestamps themselves are never modified.
2. **Token stream with real times.** Each Whisper word yields its tokens with that word's `start`/`end`. A segment
   without word timestamps yields its tokens with the segment's `start`/`end`.
3. **Exact contiguous token-sequence search.** The quote must appear as consecutive tokens; a quote may span segments.
   The grounded range is the first token's `start` to the last token's `end`. Example: words at 80.10 … 81.01 for
   "we should change the deployment process" ground to 80.10 → end of "process".
4. **Rejected, never guessed:**
   - fewer than 3 tokens (`MIN_QUOTE_TOKENS`)
   - not found (one word differs, words reordered, paraphrased, the prompt's placeholder copied)
   - a zero-length span
5. **Ambiguous (the same quote occurs several times):** the model's own start/end may pick an occurrence only if it
   overlaps **exactly one** of them. The final times are still that occurrence's transcript times. If the AI time is
   missing, invalid, or overlaps none or several occurrences, the candidate is rejected as ambiguous.
6. Rejections are logged and returned in `ClipAnalysisResult.rejected`, and the remaining candidates continue.
   - M05 now reports honest counts: `candidates_returned` includes rejected ones (the M07 "AI returned 0" limitation).
   - The insufficient-candidates error says how many were rejected as ungrounded.

**Cost:** 26 ms to build the token stream of a synthetic 2-hour transcript (16,303 words), plus about 6 ms per
quote. That's negligible next to 1-8 minutes of AI time.

### Prompt (M03)

The M07 prompt is kept verbatim, plus one rule and a `quote` field asked for **last**, with a placeholder example. The
rule says: copy 5-20 consecutive words exactly, no paraphrase, no invented words, no "...", words that appear only
once, and picking the right moment matters more than exact timestamps. No content words or test-specific hints are
in it (tested).

Four revisions were measured on 3b. The earlier ones are kept as benchmark variants (`m08-sentence`, `m08-rules`,
`m08-first`):

| 3b prompt revision | top-1 (12) | real Whisper transcript |
|---|---|---|
| quote first, sentence-like example | 8 | **0 grounded:** 3b copied the example quote into every candidate |
| quote first, placeholder, reworded rule | 3 | works |
| quote first, placeholder | 3 | works, but 3b listed 10-19 candidates and ranked worse |
| **quote last, placeholder (production)** | **9** | works; top picks are the two jokes for "funny moments" |

### Robustness fixes found by the measurements

- **Output token cap.** qwen2.5:0.5b got stuck repeating one candidate until the request timed out (600 s).
  M03 now sends `num_predict` (default 3072, `AI_MAX_OUTPUT_TOKENS`). A runaway reply is cut off, fails JSON parsing,
  and becomes a clean `AIResponseParseError`. 3072 tokens ≈ 7 min for 3b on this CPU, inside the timeout.
- **numpy floats.** faster-whisper word times are numpy floats. Grounding now returns plain floats, which fixed a JSON
  crash in the E2E harness report.

### Tests (487 collected: 486 passed, 1 opt-in skipped)

- **`tests/test_grounding.py` (32).** Covers:
  - normalization; exact, case, punctuation/quote-mark and whitespace differences; a sub-span of a segment
  - a quote spanning segments; word-level timestamps; word-level across segments with a hyphen and an apostrophe;
    segment-level fallback
  - not found (one word differs, out of order, runs past the text, hostile shell/path text); token boundaries
    (`cat` ≠ `category`); a short quote
  - ambiguous without an AI time; a repeated quote resolved by the AI time (both occurrences); 5 unresolvable hints; determinism
  - the regression from the brief: quote at 40-45 s, AI claims 90-95 s → candidate 40-45 s, 10 s window 37.5-47.5 s
  - correct quote with no usable AI time; ungrounded candidates rejected while others continue
  - multiple grounded candidates ranked and windowed exactly; grounded overlap deduplicated by M05; a repeated quote end to end
  - numpy word times
- **Updated for the new contract:**
  - `test_ai_service.py`: bad AI times are ignored when the quote grounds; a missing quote, bad score or missing
    reason is rejected with that reason; output-token cap.
  - `test_e2e_pipeline.py`: the fake model sends real quotes; a new real-FFmpeg test shows wrong AI times are ignored
    and an invented quote is rejected.
  - `test_clipping_service.py`: honest counts; the ungrounded count in the insufficient message; quote on results.
  - `test_ai_client.py`: default `qwen2.5:3b`, `OLLAMA_MODEL` override, 600 s timeout.
  - `test_ai_prompts.py`: the M08 quote rules, placeholder-last, M07 rules verbatim, no content hints.
  - `test_benchmark_metrics.py`: m08 scoring uses live grounding; v1 uses M07 validation.
- All M02-M07 suites still pass. Ruff is clean repo-wide, and `mypy app benchmarks` is clean.

### Benchmark (same dataset, tasks and 3 runs as M07; full table in `docs/M07_AI_BENCHMARK.md` → "M08")

| | qwen2.5:3b v1 (M07: AI times trusted) | **qwen2.5:3b m08 (grounded)** | qwen2.5:0.5b v1 | qwen2.5:0.5b m08 |
|---|---|---|---|---|
| top-1 moment matches the task | 9/12 | **9/12** | 0/12 | 0/12 |
| mean precision | 0.17 | 0.23 | 0.10 | 0.17 |
| mean irrelevant rate | 0.63 | **0.45** | 0.60 | 0.41 |
| quotes grounded | - | **113/113** (0 not found, 0 ambiguous) | - | 173/174 |
| grounded candidates whose AI time was wrong | - | **42/113 (37 %)**, each one corrected | - | 131/173 |
| AI time per call | 43 s | 85 s | 16 s | 43 s |

On the decision task 3b quoted the line *after* the decision (the line at its own claimed time), so top-1 there
stays 0/3. Grounding corrects "right words, wrong time", not "wrong words".

### Real end-to-end (qwen2.5:3b, faster-whisper small, FFmpeg 9.0.2; local only)

`python -m benchmarks.e2e.run_real_e2e --synthesize ...` on the 146.7 s locally synthesized speech video:

| run | result | clips (probed) | grounding evidence |
|---|---|---|---|
| funny moments, 3 × 10 s | success | 10.000000 / 10.000000 / 10.000000 s, h264 + aac | top 2 = the two jokes; **clip 3: quote grounded 124.00-130.04 s, AI claimed 114.9-116.0 s; the cut 122.02-132.02 s follows the transcript** |
| funny moments, 3 × 10 s | success | 3 × 10.000000 s, h264 + aac | top 2 = the two jokes; AI times agreed with grounding |
| decision exposure, 1 × 10 s | success | 10.000000 s, h264 + aac | the decision sentence grounded at 118.46-123.06 s; the cut 115.76-125.76 s contains it |

In every run each cut contains its grounded quote, no partial or temporary files remained, and rejections were
only 2-word fillers ("Bye bye.", "See you.").

### Performance (Intel Core Ultra 5 125H, CPU only; 146.7 s video)

| stage | measured |
|---|---|
| transcription (incl. Whisper load) | 39.6-41.4 s |
| AI reasoning (3b) | 70.9 / 167.5 / 481.4 s (UI run: 72 s) |
| grounding | < 0.1 s (26 ms + ~6 ms per quote even for a 2-hour transcript) |
| selection | < 10 ms |
| FFmpeg + verification | 0.48 s (1 clip), 1.68 s (3 clips) |
| total | 113-209 s for 3 clips; 523 s for the decision run |

AI time is the bottleneck. The quote adds output tokens, and on the decision task 3b listed nearly every line (~20
candidates), producing a reply close to the 3072-token cap.

### UI regression (real browser, qwen2.5:3b)

The M06 UI was **unchanged**. In Chrome at `http://127.0.0.1:5000/`: upload `meeting_speech.mp4`, 2 × 10 s, "funny
moments" → the real stage progress → "2 clips ready" in 106 s (AI 72 s).
- Both downloads returned 200, and the files probe at 10.000000 s, h264 + aac.
- Traversal and `/download?path=` returned 404. The page shows no internal paths, rejection reasons or AI times.
- The upload folder was empty afterwards.
- Model choice: clip 2 was the intern joke. Clip 1 was the office-closing announcement, which 3b scored as funny.

### Security

- The quote is untrusted text. It is only tokenized and compared; it never becomes a path, a command, a filename or a
  timestamp (a hostile-quote test checks this).
- Final times always come from transcript data.
- No new subprocess, network call or dependency. Grounding is stdlib only, and still only the local Ollama is contacted.
- Output paths are still `clip_NNN.mp4` via M04 `safe_output_path`.
- M06 upload and download protections were re-verified in the browser. AI output is autoescaped in the UI.
- The output-token cap prevents a looping model from occupying the local server until the timeout.

### Decisions

1. **Default model `qwen2.5:3b`**, overridable with `OLLAMA_MODEL`.
2. **Grounding lives in M03's validation step**, so M05's selection engine is unchanged.
3. **No fuzzy matching.** Exact token sequences after harmless normalization only, so a paraphrase is rejected
   rather than mapped to a guessed place.
4. **The AI time is used only to choose between identical quotes**, and only when it overlaps exactly one of them.
5. **Quote asked for last,** with a placeholder example (measured, see the table above).
6. Default Ollama timeout 600 s; output cap 3072 tokens.

### Known limitations

1. Grounding fixes "right words, wrong time", not wrong choices. When 3b quotes the wrong line (the decision task,
   the announcement-as-funny UI run), the clip faithfully shows that line.
2. With the quote asked last, the quote sometimes follows the model's own (shifted) time. Quote-first prompts fix more
   timestamps but cost ranking accuracy (3/12 vs 9/12).
3. A paraphrased quote is rejected. Number words vs digits (`forty` vs `40`) and Whisper spelling differences are not
   equated, but the model quotes the transcript text, so this has not mattered in practice.
4. Quotes under 3 words are rejected (2-word lines like "Bye bye." cannot be clips).
5. Repeated identical quotes need an AI time that overlaps exactly one occurrence; otherwise they are rejected.
6. Segment-level fallback (no word timestamps) gives whole-segment spans. Real M02 output always has words.
7. 3b AI time is 71-481 s per job on this CPU and dominates the pipeline. `AI_MAX_CANDIDATES` (default 20) is the
   main lever.
8. The benchmark is one synthetic 150 s transcript with 3 runs per cell: indicative, not conclusive.

---

## Milestone 07 - End-to-End Integration, Reliability & AI Quality Evaluation


**Status: COMPLETED**

### Objective

Make V1 measurable and more reliable end-to-end, and investigate the known AI-quality weakness with evidence
rather than guesses. The architecture is unchanged: **AI suggests, Python validates and decides, FFmpeg executes.**
The default model was not changed.

### Completed work

| Area | Result |
|---|---|
| A. Regression layer | `tests/test_e2e_pipeline.py` (24 tests): real FFmpeg/FFprobe, M04, M05, M03 parsing and validation, and the M06 app; only Whisper and the Ollama daemon are faked. It auto-skips without FFmpeg. |
| B. Real E2E harness | `benchmarks/e2e/run_real_e2e.py`, plus the opt-in `tests/test_real_e2e.py` (`CLIPPER_REAL_E2E=1`). |
| C. Model benchmark | `benchmarks/ai/run_benchmark.py` with the labelled dataset `benchmarks/ai/dataset.json`. Results are in `docs/M07_AI_BENCHMARK.md`. |
| D. Prompt investigation | A general-purpose v2 prompt and two delivery options were measured. The result was a trade-off, so **not adopted**. |
| E. Repeatability | Variation comes from model sampling only. Temperature 0 + seed gives 5/5 identical outputs but no better ones. Not adopted. |
| F. Audio-duration warning | **Real bug, fixed** (M02). |
| G. Performance | Measured per stage on this machine (below). |
| H. Security | No regression (below). |

**Bugs found and fixed. Each was the smallest safe change, and each has a regression test:**

1. **M02 `Could not determine audio duration`, which fired on every job.** `_get_audio_duration` ran
   `ffmpeg -v error -i audio.wav -f null -` and parsed `time=` from stderr. But `-v error` suppresses that stats line, so
   the result was **always 0.0**. The unit test hid this because it mocked stderr with a `time=` line that real FFmpeg
   never prints at that log level.
   - **Impact:** `TranscriptionResult.duration` silently fell back to the last speech segment's end. M03 then told the
     model the wrong duration and rejected valid candidates in trailing non-speech. M05 itself was unaffected, because
     it uses the probed video duration.
   - **Fix:** read the exact duration from the WAV header that `_extract_audio` writes, using stdlib `wave`. This
     removes one FFmpeg subprocess per job. On the real test video the old code returned 0.0 s; the fixed code
     returns 145.197 s (FFprobe container: 146.733 s, since the audio is shorter than the video track).
   - Tests: real WAV header, corrupt WAV → 0.0, no subprocess.
2. **M03 wrong-shape JSON escaped as a bare `TypeError`.** For example, `[1,2]` or `{"candidates":"none"}`.
   `parse_ai_response` raises `TypeError` for these, but `AIReasoningService` caught only `ValueError`, and M05 catches
   `(AIError, ValueError)`. So the error crashed the CLI and showed as "unexpected error" in the UI, instead of a clean
   `AnalysisStageError`. The fix catches `(ValueError, TypeError)` and raises `AIResponseParseError`.
   - Tests: 5 shapes in M03, 4 through the full pipeline.
3. **M03 `is_model_available` prefix match.** It compared the name with `startswith("qwen2.5")`, so `qwen2.5:3b` was
   reported as installed when only `0.5b` was pulled. The check now requires an exact tag match (`name` or
   `name:latest`). Found while preparing the 3b benchmark. Tests: 4 cases.

**Supporting change:** `OllamaClient.generate(..., format="")` passes Ollama's `format` through. The default `""` is
Ollama's own default, so M03 behaviour is unchanged. It is used only by the benchmark's JSON-mode variants.

**Ruff hygiene:** the 21 pre-existing unused/unsorted-import warnings in M02/M03 test files were auto-fixed. Those
files were edited in this milestone, and `ruff check .` is now clean repo-wide.

### Tests (440 collected: 439 passed, 1 opt-in skipped)

New:
- `test_e2e_pipeline.py` (24). Covers:
  - valid 3 × 4 s request on a real 20 s video, independently re-probed: exact durations, h264 + aac, full status sequence
  - video-only source rejected by M05, and no invented audio in M04 extraction
  - boundaries: near the start, near the end, exact source length, just below the source length, source too short
  - ranking follows AI scores; duplicate and overlapping candidates collapse; insufficient candidates render nothing;
    AI timestamps past the source are dropped
  - failures: transcription failure, Ollama unavailable, invalid AI output (4 shapes), real FFmpeg failure on clip 2,
    output-verification failure. In each, the real `clip_001.mp4` is removed and the user's file is kept.
  - success keeps the outputs and pre-existing files; an existing clip name is never overwritten
  - M06 upload → real M05 + M04 → download → re-probe at 3.000 s with audio; traversal returns 404; non-video rejected by the real probe
- `test_benchmark_metrics.py` (9): metrics, the dataset labels never reaching the model, v1 equal to the live prompt,
  v2 general-purpose, and the evidence metric.
- `test_real_e2e.py` (1, opt-in): real Whisper + Ollama + FFmpeg.

Regression tests were also added in `test_ai_client.py` (+4), `test_ai_service.py` (+5) and
`test_transcription_service.py` (+2 net).

Suites: transcription 48, AI 78, video 113, clipping 82, UI 85, E2E 24, benchmark 9, real-opt-in 1.

### Real end-to-end results

`python -m benchmarks.e2e.run_real_e2e --synthesize -n 3 -d 10 -i "funny moments" [--model ...]`. The source is a
146.7 s 640x360 speech video, synthesized locally (Windows SAPI reading the benchmark transcript, over FFmpeg `testsrc`).

| model | runs | success | notes |
|---|---|---|---|
| qwen2.5:3b | 3 | **3/3** | every clip probed **10.000 s**, h264 + aac; picks ranged from the explanation/Q&A segments to the intern joke |
| qwen2.5:0.5b | 3 | **0/3** | 2 runs: zero valid candidates (e.g. three `1.0-1.0` zero-length moments, rejected by M03 → clean `InsufficientCandidatesError`); 1 run: Ollama 120 s timeout after an 18× slower transcription (outlier, cause unknown) |

No run logged `Could not determine audio duration` after the fix.

### Benchmark results (full detail in `docs/M07_AI_BENCHMARK.md`)

Same transcript, same 4 tasks, 3 runs per cell, M03's own prompt, parser and validator.

| | qwen2.5:0.5b | qwen2.5:3b |
|---|---|---|
| top-1 moment matches the task | **0/12** | **9/12** (funny, educational and Q&A 3/3; decision 0/3) |
| behaviour | lists 16 of 17 segments in order, one constant score (often the prompt's example 0.91), repeated reasons | reads the content; varied scores and reasons; pads with admin/announcements (35-58 % irrelevant) |
| timestamp validity | all valid and segment-aligned, but **attached to the wrong segment** (3/33 quotes in range on "decision") | all valid; a correct quote with times from a neighbouring/later segment (decision task: 3/3) |
| AI time per call | 18-23 s | 13-46 s |

### Model comparison

qwen2.5:3b is the only change measured to make selection meaningful: 9/12 vs 0/12 top-1, and 3/3 vs 0/3 real E2E.
It costs 1.9 GB of disk and 4-9× more AI time (51-117 s per real job). **The default stays `qwen2.5:0.5b`**, per the
M07 rule. Switching is a project decision; it is already possible with `OLLAMA_MODEL=qwen2.5:3b` and needs no code change.

### Prompt investigation

The v2 prompt is general-purpose: placeholders instead of example values, quoted evidence, a score spread, times from
the quoted segment, "leave out logistics/filler unless asked", and "return fewer rather than pad". It was measured with
JSON mode and keyed transcript lines, plus two ablations.

For 3b it raised precision (0.16 → 0.40) and lowered irrelevant picks (0.62 → 0.46), but lowered top-1 (9/12 → 6/12).
The timestamp mis-mapping moved from the decision task to the educational/Q&A tasks.

For 0.5b nothing helped. Without JSON mode it parsed only 3/12, because quoting broke its JSON.

Since M05 cuts the top-ranked moments first, **no prompt or format change was adopted**. v2 stays in
`benchmarks/ai/run_benchmark.py` as a measured experiment.

### Repeatability

Production prompt, 5 identical runs:
- At M03's default temperature 0.1: 1-4/5 identical outputs (3b "funny": covered-set Jaccard 0.67).
- At temperature 0 + seed 42: **5/5 identical in every cell**, with the same top-1 and precision.

**Source of variation:**
- **Ollama sampling only.**
- M03 validation and M05 selection are deterministic functions of the response: rescoring identical responses gives
  identical results.
- The prompt is fixed.

**Not adopted:** it would not improve quality, and it would make "run again" (the only recovery from insufficient
candidates) useless. `AI_TEMPERATURE=0` already exists for users who want it.

### Performance (Intel Core Ultra 5 125H, CPU only; 146.7 s video, 3 × 10 s clips)

| stage | measured |
|---|---|
| transcription (faster-whisper small, incl. model load) | 37.0-39.3 s (~0.26× real time) |
| AI reasoning | 0.5b 9.9-12.7 s; 3b 51.3-117.3 s |
| selection | < 10 ms |
| FFmpeg generation + verification | 1.67-1.71 s for 3 clips (~0.56 s per clip) |
| total (3b, successful) | 92-158 s |

### Security / architecture regression

- **Local-only:** no new network calls. The benchmark and harness talk only to the local Ollama (`OLLAMA_HOST`, default localhost).
- **No new dependencies.**
- **Subprocess safety:** M02 lost one FFmpeg subprocess (now stdlib `wave`). The harness uses argument lists only; the
  synthesis script gets its paths via environment variables, never interpolated into the command.
- **No AI output is executed.** `format` is passed only as the literal `""`/`"json"` from code.
- **M06 is untouched.** Upload validation and download security are re-verified against the real M05 + M04
  (traversal → 404; non-video rejected by the real probe).
- **Validation gates stayed in place:** M03 validation, M05 normalization, output isolation, all-or-nothing cleanup,
  and M04 exact-duration verification were unchanged and are now exercised with real FFmpeg.
- **Generated data stays out of git:** benchmark and E2E output go to `output/` (gitignored). No secrets.

### Decisions

1. **Default model stays `qwen2.5:0.5b`.** The evidence for 3b is documented, and the switch is left to the project.
2. **Production prompt and transcript format unchanged.** v2 was measured as a trade-off.
3. **No fixed seed.** Repeatability without a quality gain, at the cost of retries.
4. **Fixed only the real bugs** found by measurement (M02 duration, M03 TypeError, M03 model tag), each with a regression test.
5. **Real-model tests are opt-in.** Normal `pytest` never needs Ollama or Whisper; FFmpeg tests auto-skip.

### Known limitations

1. qwen2.5:0.5b does not perform semantic selection (0/12). V1 clip choice with the default model is effectively arbitrary.
2. qwen2.5:3b attaches correct quotes to wrong timestamps in some tasks, and pads its lists with irrelevant moments.
3. Model output varies run to run at the default temperature, so a request can succeed once and fail later.
4. One AI pass; no retry or second pass when there are too few candidates.
5. The Whisper model still loads once per job (~part of the 37-39 s; not optimized, by design).
6. `ClipGenerationResult.candidates_returned` reports M03's *valid* count; candidates rejected by M03 are invisible to M05 ("AI returned 0").
7. The benchmark dataset is one synthetic 150 s English meeting with 3 runs per cell: indicative, not statistically strong.
8. `--synthesize` for the real E2E harness is Windows-only (SAPI). Elsewhere, pass `--video` with any local speech video.
9. One unexplained slow run (689 s transcription) was observed during the real E2E series.

---

## Milestone 06 - Local Web UI


**Status: COMPLETED**

### Architecture

```
Browser ──HTTP (127.0.0.1)──> Flask UI (app/ui) ──ClipJobRequest──> M05 ClipGenerationService ──> M02 + M03 + M04 ──> clips

app/ui/
├── __init__.py      # exports create_app, UIConfig
├── __main__.py      # python -m app.ui (warns if bound beyond localhost)
├── config.py        # UIConfig: host, port, upload/output dirs, max upload MB, debug; CLIPPER_* env overrides
├── app.py           # create_app() factory, routes, upload/form validation, safe downloads, error pages
├── jobs.py          # Job, JobStore (one running job), run_job worker, friendly_error mapping
├── templates/       # base, index, progress, result, error (Jinja, autoescaped)
└── static/style.css
```

The suggested `routes.py` / `forms.py` were not split out: the routes and form parsing fit in `app.py`, and the form
validation is M05's own `ClipJobRequest`. The UI contains no Whisper, Ollama, prompt, selection, overlap, window or FFmpeg
logic, and a test greps the UI sources to enforce that. The UI only builds a `ClipJobRequest`, calls
`ClipGenerationService.generate` and renders the `ClipGenerationResult`.

**Sync vs async.** M05 stays synchronous. The UI runs one `generate()` call in a single daemon thread per job, so the
browser does not wait minutes on one request (Firefox drops responses after 300 s). This is not a queue: one job runs at
a time, and a second submit gets HTTP 409 "Another job is still running". The progress page refreshes itself every 3 s
(`<meta refresh>`, no JavaScript polling) and shows the **real** M05 stage reported through `on_status`. It shows no
percentages and no M05 detail strings, because those can contain paths.

### Routes

| Route | Purpose |
|---|---|
| `GET /` | form: video, number of clips, duration, focus (optional, default "interesting moments") |
| `POST /jobs` | validate, store the upload, probe it, start the job, `303` → `/jobs/<id>`; invalid input returns 400 with the form re-filled |
| `GET /jobs/<id>` | progress page while running, result page when completed, error page when failed |
| `GET /jobs/<id>/clips/<name>` | download one generated clip (attachment) |
| `/static/style.css` | stylesheet |

There is no generic `?path=` endpoint.

### Validation (all before M05 starts)

1. The `video` part is present and its filename is non-empty after stripping any client-side directories.
2. The extension is in M04's `SUPPORTED_EXTENSIONS` (`.mp4 .mkv .mov .avi .webm`). The browser MIME type is ignored.
3. Count is parsed as `int` and duration as `float`, with a friendly message on garbage. **`ClipJobRequest`** then enforces
   1-20 clips, 1-600 s, finite values and focus ≤ 500 chars, so no business rules are duplicated.
4. Size: `MAX_CONTENT_LENGTH` = 2048 MB (configurable) → 413 page. The file must not be empty.
5. **M04 probe** (`VideoService.probe`): the file must be a real video in an allowed container, otherwise the user sees
   "could not be read as a supported video". M05's first stage still checks for a too-short video or no audio and reports
   both as friendly errors within seconds.

### Upload & storage

- `job_id = uuid4().hex`. Upload: `<upload_dir>/<job_id>/source<.ext>`. Output: `<output_dir>/<job_id>/`. Both roots are resolved at startup.
- The client filename is never used as a path. It is only displayed (escaped, at most 120 chars, basename only).
- Werkzeug streams the upload to disk (`FileStorage.save`), and the video is never loaded into RAM.

### Download security

All of these must hold, otherwise the response is 404:
- `job_id` matches `^[0-9a-f]{32}$` and names a completed job in memory.
- `name` matches `^clip_\d{3}\.mp4$` **and** is one of that job's result clips.
- The resolved path stays inside `<output_dir>/<job_id>`.

`send_from_directory` re-checks the join and also returns 404 for missing files.

### Errors

`friendly_error()` maps exceptions to fixed user text. The raw exception message is never rendered, because M05 messages
can contain absolute paths or FFmpeg output. Mapped cases:
- video shorter than the clip
- "Only N sufficiently distinct moments were found, but M were requested"
- transcription failed
- Ollama not running
- Qwen model unavailable (`ollama pull <model>`)
- AI analysis failed
- video processing failed at clip N
- no audio
- unreadable video
- FFmpeg missing
- unexpected error

Technical details go to the server log (`logger.warning` / `logger.exception`). Flask debug is off, so no tracebacks are shown.

### Cleanup policy

- The upload directory is **always** deleted when the job ends, successful or failed (the clips are already cut by then).
- On a failed job, M05 removes its partial clips and the UI also removes `<output_dir>/<job_id>`.
- On a validation failure, the upload directory is removed immediately.
- At startup, leftover `<upload_dir>/<uuid-hex>/` folders from a server stopped mid-job are removed. Other folders are left alone.
- Successful clips stay in `output/ui_jobs/<job_id>/` until the user deletes them. There is no automatic expiry.

### Configuration

| Variable | Default |
|---|---|
| `CLIPPER_HOST` | `127.0.0.1` |
| `CLIPPER_PORT` | 5000 |
| `CLIPPER_UPLOAD_DIR` | `input/ui_uploads` |
| `CLIPPER_OUTPUT_DIR` | `output/ui_jobs` |
| `CLIPPER_MAX_UPLOAD_MB` | 2048 |
| `CLIPPER_DEBUG` | off |

Binding beyond localhost requires setting `CLIPPER_HOST` explicitly, and it logs a warning.

### Dependencies

`flask>=3.0` (3.1.3 installed; brings Werkzeug, Jinja2, itsdangerous, click, blinker). No JS framework, database, Redis or Celery.

### Tests (85 new, 395 total) - `tests/test_ui.py`

The tests use the Flask test client. M05 is replaced by a fake service that writes real files or raises, and the probe is
injected. No Ollama, Whisper, FFmpeg, browser or network is needed. Covered:
- **App and config:** factory (independent apps), upload-limit config, local-binding defaults, debug off by default, env overrides.
- **Pages:** home page (GET, labels, form fields), static CSS.
- **Upload validation:** missing upload, empty filename, 5 unsupported extensions, empty file, malformed file (probe),
  ffprobe missing, oversized upload (413), 5 traversal filenames.
- **Form validation:** 6 invalid counts, 8 invalid durations, too-long focus, blank focus default, form values kept after an error.
- **Generation:** valid upload → M05 request, success redirect, upload deleted after success.
- **Result and progress pages:** result metadata (timecodes, score, escaped AI reason, download links), no internal paths
  on the page, progress page shows the real stage with no percentages, concurrent submit → 409.
- **Failures:** 8 M05 failure types → friendly text with no paths or tracebacks, **and cleanup on the failed job**;
  Ollama-down, model-missing and unreadable-source messages.
- **Downloads:** valid download, nonexistent clip, deleted file, 9 arbitrary-path/traversal attempts, job ID validation,
  unknown job, output-path traversal via a tampered result, downloads only for completed jobs.
- **Other:** stale-upload cleanup, timecode, no subprocess from the UI, no pipeline logic in the UI sources,
  no secrets or external URLs in templates.

### Quality Gates

- Pytest: **395 passed** (M02, M03, M04 and M05 suites all green).
- Ruff: `app/ui` and `tests/test_ui.py` are clean. The 21 pre-existing import warnings in M02/M03 test files are unchanged.
- MyPy: `mypy app` is clean. `mypy --strict app/ui tests/test_ui.py` reports no errors in the new files.

### Real Local UI Verification (Chrome, 2026-10-03)

The source was synthesized locally from a Windows SAPI TTS script containing two jokes, muxed with FFmpeg `testsrc` into
`meeting.mp4` (41.7 s, 640x360, h264/aac). Nothing was downloaded. The server ran with `python -m app.ui` on `http://127.0.0.1:5000/`.

1. The home page opened with the form and the format/limit hints.
2. Uploading `notes.txt` showed the inline error "Unsupported file type. Allowed formats: AVI, MKV, MOV, MP4, WEBM.", and the form kept its values.
3. `meeting.mp4`, 2 clips × 10 s, "funny moments", with **Ollama stopped**: the processing page showed "Checking the video ✓ →
   Transcribing speech (in progress)", then "Finding moments ... (in progress)". It ended with **"Ollama is not running. Start Ollama
   and try again."**, and `input/ui_uploads` and `output/ui_jobs` were empty afterwards.
4. With Ollama started (`qwen2.5:0.5b`), the same request completed in **34 s**. The result page showed: meeting.mp4, 2 requested,
   10.000 sec, qwen2.5:0.5b (9 valid candidates). Clip 1: 00:00:06.500 → 00:00:16.500, score 0.91, reason "A joke about the printer
   fix and the developer's financial situation". Clip 2 followed.
5. Both download links returned 200 as attachments (188 KB and 180 KB). The downloaded files probe as **10.000000 s, h264 + aac**.
   `/jobs/<id>/clips/..%2F..%2F..%2FREADME.md` and `/download?path=C:\Windows\win.ini` both returned 404.
6. After the successful job the upload folder was empty, and only `output/ui_jobs/<id>/clip_001.mp4` and `clip_002.mp4` remained.

### Security

- Localhost binding and debug off by default. No `SECRET_KEY`, sessions, cookies or credentials are needed or present.
- Generated storage names, UUID job IDs, `pathlib` resolution with containment checks, extension allowlist plus FFprobe check, and a size limit.
- Downloads are limited to regex-valid names listed in a completed job's in-memory result.
- No subprocess or shell in the UI (test-enforced). The focus text reaches M05 only as data (it goes into the LLM prompt), and AI output is rendered autoescaped.
- No external network calls, CDN assets or fonts.

### Known Limitations

1. Job state is in memory. A server restart forgets the result pages (the clips stay on disk) and loses any in-flight job
   (its upload is cleaned up on the next start).
2. One job at a time, and no cancellation from the browser. Stopping the server stops the job.
3. No CSRF token and no Host-header check. That is acceptable for a localhost-only single-user tool, but not if the server is exposed on a network.
4. The progress page shows stages, not percentages, because M05 reports nothing finer.
5. The UI runs on the Werkzeug development server, which is fine for local single-user use. An upload over the limit may show as a
   connection reset in some browsers before the 413 page renders.
6. There is no in-browser preview player; clips must be downloaded.
7. Each job builds fresh M02/M03 services, so the Whisper model is reloaded for every job (a few seconds).
8. Selection quality is still bounded by qwen2.5:0.5b (see M05).

---

## Milestone 05 - Automatic Clip Selection & Generation

**Status: COMPLETED** - first complete product pipeline (core V1).

### Architecture

```
app/clipping/
├── __init__.py      # Public API exports
├── __main__.py      # python -m app.clipping (exit code propagated)
├── models.py        # ClipJobRequest (limits), ClipWindow, GeneratedClip, ClipGenerationResult, JobStatus
├── exceptions.py    # ClipGenerationError(.stage) + 7 stage-specific errors, messages bounded to 300 chars
├── windows.py       # compute_window (exact-duration, boundary shifting), iou
├── selection.py     # normalize_candidates, rank_candidates, select_moments (greedy IoU filter)
├── service.py       # ClipGenerationService - sequential orchestration, all-or-nothing rendering
└── cli.py           # developer/user CLI with status lines on stderr, JSON result on stdout
```

`pipeline.py` was not created separately. The orchestration in `ClipGenerationService` is split into one small method per
stage (`_probe_source`, `_plan_outputs`, `_transcribe`, `_analyze`, `_render`, `_verify`), and the pure
decision logic lives in `windows.py`/`selection.py`.

M02/M03/M04 are used only through their public APIs (`TranscriptionService.transcribe`,
`AIReasoningService.analyze`, `VideoService.probe/extract_clip`). They are typed as `Protocol`s so tests inject fakes,
and the real services are created lazily.

### Pipeline

| Status | Work | Failure |
|---|---|---|
| validating | request limits; probe source; source >= clip duration; source has audio; `clip_NNN.mp4` names free | `InvalidJobRequestError`, `SourceTooShortError` |
| transcribing | M02 | `TranscriptionStageError` |
| analyzing | M03 | `AnalysisStageError` |
| selecting | validate, rank, window, IoU filter | `InsufficientCandidatesError` |
| generating | M04 per window, sequential, `overwrite=False` | `ClipRenderError(index)` |
| validating_outputs | file exists and non-empty; duration within M04 tolerance; video present; audio kept | `OutputVerificationError(index)` |
| completed / failed | `on_status(status, detail)` callback + log | - |

All cheap checks (limits, probe, length, audio, name conflicts) run **before** the expensive transcription.

### Request model (`ClipJobRequest`)

- `clip_count`: int, 1..20 (`MAX_CLIP_COUNT`; M03's default candidate cap is 20). Bools and floats are rejected.
- `clip_duration`: finite, 1..600 s (`MIN/MAX_CLIP_DURATION`).
- `instruction`: non-blank, ≤ 500 chars (`MAX_INSTRUCTION_CHARS`).
- `input_path`, `output_dir`: non-empty. The input is validated by M04 probing.

### Candidate selection strategy

1. **Normalize**: every candidate is re-validated against the *probed source duration*, because M03 only checks against the
   transcript duration and does not reject NaN. Rejected: non-finite values or bools, start < 0, end <= start, start >= source,
   end > source, score outside [0, 1].
2. **Rank** (deterministic): score desc → |candidate length − requested duration| asc → start asc → end asc.
3. **Window**, then **filter** greedily down the ranking. Stops at exactly `clip_count`.
4. Clip numbering follows the ranking (`clip_001.mp4` = strongest moment).

### Exact-duration window strategy

`start = clamp(round(center − D/2, 3), 0, source − D)` and `end = start + D`, where `center = (cand.start + cand.end) / 2`.
- A short candidate gains equal context on both sides. A long candidate keeps its middle D seconds.
- Shifted forward at the video start and backward at the end; the length is never reduced.
- source < D → `SourceTooShortError` (1e-6 float slack only).
- The start is rounded to ms. The real E2E run showed `1.5499999999999998` before rounding was added.
- M04 cuts and verifies the window. M05 re-verifies `|actual − D| <= max(0.05 s, 1/fps)` before reporting success.

### Overlap strategy

Applied to the **final windows** (what the viewer sees), not the raw candidates: two distinct 4-second jokes 8 s apart
would still produce nearly identical 30-second clips. A window is kept only if its IoU with every kept window is
≤ **0.2** (`MAX_WINDOW_IOU`). For equal-length clips that means sharing ≤ 1/3 of their length (10 s of a 30 s clip).
The stronger-ranked window always wins, and exact duplicates (IoU 1) collapse to one.

### Insufficient candidates

No duplication, no fabricated moments, no silent short results: `InsufficientCandidatesError(found, requested,
returned)` is raised before any rendering. The service is built so a future pass can ask M03 for more
(`select_moments` takes any candidate iterable), but M05 makes one honest pass.

### Atomic output behavior

Output is all-or-nothing per job. On any render or verification failure (or interrupt), every clip this job produced is deleted.
The job directory is removed too if this job created it and it is empty. Files that were already in the folder are never touched.
Pre-existing `clip_NNN.mp4` names stop the job before any work.

### M03 fix (minimal, necessary)

The real E2E run hit `AIResponseParseError: Invalid control character` because qwen2.5:0.5b emitted a raw newline inside a JSON
string. `app/ai/prompts.py` now uses `json.loads(response, strict=False)`, with a regression test added to `test_ai_prompts.py`.
Nothing else in M02/M03/M04 was changed.

### Tests (82 new + 1 M03 regression, 310 total)

- `test_clipping_selection.py`: request validation (valid, bounds, 0/negative/huge/float/bool count, 0/negative/NaN/±inf/
  out-of-range/non-number duration, empty/blank/too-long instruction, empty paths); windows (centered, ms rounding,
  short/long candidate, near start, near end, exact source length, source too short, float stays in bounds); IoU;
  normalization (12 invalid shapes); ranking (score, equal-score tie-breaks, order independence); selection
  (exact count, no/partial/heavy overlap, duplicates, deterministic tie, insufficient message, no candidates, invalid
  candidates do not count, exact window length).
- `test_clipping_service.py` (fake M02/M03/M04 writing real files): successful orchestration and status sequence, exact count,
  existing dir without conflicts, missing source, source too short (no transcription run), no audio, existing clip not
  overwritten (no work run), output dir is a file, transcription failure, AI failures, insufficient candidates (nothing
  rendered), no fabricated duplicates, render failure on clip 1 (created dir removed), partial failure at clip 3
  (earlier clips removed, user file kept), duration verification failure, lost audio, within-tolerance accepted,
  hostile model/instruction text never reaches the video engine, fixed safe filenames, no subprocess/shell in the pipeline,
  bounded error messages and logs.

### Quality Gates

- Pytest: **310 passed** (M02, M03 and M04 suites all still green).
- Ruff: M05 code/tests clean. The 21 pre-existing import warnings in M02/M03 test files are unchanged.
- MyPy: `mypy app` clean. `mypy --strict` reports 0 errors in `app/clipping` and its tests (19 strict-only errors remain in imported M02/M03 modules, which pass the project's normal mypy settings).

### Real End-to-End Verification

The source was synthesized locally (no media download): Windows SAPI TTS (`Microsoft David Desktop`) read a 65 s meeting script
containing two jokes and dull filler. FFmpeg muxed it with `testsrc` into a 70 s 640x360 30 fps H.264/AAC `meeting.mp4`.
faster-whisper `small` was downloaded once (user-approved, ~480 MB). Ollama `qwen2.5:0.5b`, FFmpeg 9.0.2.

```
python -m app.clipping meeting.mp4 -n 2 -d 10 -i "funny moments" -o job1
python -m app.clipping meeting.mp4 -n 6 -d 10 -i "funny moments" -o job_insuff_a   (and _b)
python -m app.clipping meeting.mp4 -n 3 -d 15 -i "funny moments" -o job_final
```

| Run | AI candidates | Result | Probed outputs |
|---|---|---|---|
| 2 × 10 s (cold, incl. model download) | 5 | completed in 72.9 s | 2 × 10.000000 s, h264 + aac |
| 6 × 10 s (a) | 8 | **failed clearly**: "Only 5 sufficiently distinct ... requested 6"; no dir created | - |
| 6 × 10 s (b) | 18 | completed in 43.1 s | 6 × 10.000000 s, video + audio |
| 3 × 15 s (final code) | 18 | completed in 41.2 s; clip 1 shifted to 0.0-15.0 at the video start | 3 × 15.000000 s, video + audio |
| (earlier, before M03 fix) 6 × 10 s | - | failed clearly at `analyzing` with the JSON control-character error | - |

Timing on an Intel Core Ultra 5 125H, CPU only (warm): transcription ~17 s for 70 s of audio, Qwen 11-22 s, FFmpeg ~0.7 s per clip.

### Security

- Untrusted input: the user instruction (goes only into the LLM prompt), the transcript, and AI output (only validated floats and score/reason
  *data* leave the selection step).
- Output paths come only from `clip_filename(i)` via M04 `safe_output_path`. There is no user/AI-controlled filename, and no traversal.
- No subprocess in M05 (asserted by a test); all media work goes through M04's argument-list FFmpeg calls.
- Never overwrites: the job pre-checks names and M04 is called with `overwrite=False`.
- No network beyond the local Ollama daemon and the one-time, user-approved Whisper model download (M02 behavior).
  No uploads, no cloud APIs, no new dependencies.
- Error messages are capped at 300 chars, so transcripts and model dumps don't leak into logs.

### Known Limitations

1. **Selection quality is bounded by qwen2.5:0.5b.** In the E2E runs it gave identical reasons and a 0.91 score to all
   18 candidates and called a printer announcement humorous. M05 follows the AI ranking deterministically, so a larger model
   (`qwen2.5:3b`) is the quality lever.
2. Qwen output varies run to run (temperature 0.1), so the same request can succeed or fail with insufficient candidates.
3. One analysis pass only; there is no automatic second pass to find more candidates.
4. Speech is required: sources without audio are rejected. Moments come from the transcript only, not visuals.
5. M03 truncates transcripts at 8000 chars, so later parts of long videos may never be considered.
6. M02 logs `Could not determine audio duration, using 0.0` with FFmpeg 9.0.2 and falls back to the last segment end. M05 is
   unaffected because it uses the probed video duration, but M03 rejects candidates after the last speech segment.
7. All-or-nothing jobs discard already-rendered clips if a later clip fails.
8. Synchronous only: no job queue, no cancellation beyond Ctrl+C (which still cleans up).

---

## Milestone 04 - Video Processing Engine

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
| Ollama | ✅ Installed | 0.32.15, `qwen2.5:3b` (default since M08) and `qwen2.5:0.5b` (still supported) |
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

## Next Milestone: **Milestone 09 - AI Inference Performance: Candidate Budget** (recommended)

M08 made clip *locations* reliable. AI reasoning is now the measured bottleneck: 71-481 s per job with qwen2.5:3b,
against ~40 s transcription and < 2 s FFmpeg. Recommended scope, to be confirmed by the project architect:
- Ask the model for a candidate budget derived from the requested clip count (for example 2-3× `clip_count`,
  bounded), instead of a fixed 20. Today the prompt always allows 20 candidates, and 3b sometimes writes nearly every line.
- Re-measure AI time, top-1 accuracy and insufficient-candidate failures with `benchmarks/ai/run_benchmark.py`
  and the real E2E harness. Keep the M08 grounding and the M07/M08 baselines for comparison.
- Out of scope: captions, reframing and the other future features listed in M07/M08.

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
│   │   ├── grounding.py      # M08: quote -> transcript timestamps
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
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── models.py
│   │   ├── exceptions.py
│   │   ├── windows.py
│   │   ├── selection.py
│   │   ├── service.py
│   │   └── cli.py
│   └── ui/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py
│       ├── app.py
│       ├── jobs.py
│       ├── templates/     # base, index, progress, result, error
│       └── static/style.css
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
│   ├── test_video_integration.py
│   ├── test_clipping_selection.py
│   ├── test_clipping_service.py
│   ├── test_ui.py
│   ├── test_e2e_pipeline.py      # M07 deterministic E2E (real FFmpeg, fake Whisper/Ollama)
│   ├── test_benchmark_metrics.py
│   ├── test_grounding.py         # M08 timestamp grounding
│   └── test_real_e2e.py          # opt-in: CLIPPER_REAL_E2E=1
├── benchmarks/
│   ├── ai/
│   │   ├── dataset.json          # labelled 150 s benchmark transcript
│   │   └── run_benchmark.py      # model / prompt / repeatability benchmark
│   └── e2e/
│       └── run_real_e2e.py       # real Whisper + Ollama + FFmpeg harness with stage timings
├── input/
├── output/
├── docs/
│   ├── PROJECT_PROGRESS.md
│   └── M07_AI_BENCHMARK.md
├── readme.txt             # Original file (preserved)
├── README.md
├── requirements.txt
└── .gitignore
```

**Git Commit:** `feat: improve ai selection with timestamp grounding`

---

*Last Updated: 2026-10-02 | Milestone 05 Complete*