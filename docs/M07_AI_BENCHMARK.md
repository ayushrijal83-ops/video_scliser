# M07 AI Quality Benchmark - qwen2.5:0.5b vs qwen2.5:3b

All runs: 2026-10-03, Intel Core Ultra 5 125H, CPU only, Ollama 0.32.15, local models only.
Raw per-run results (full model responses included) are written to `output/benchmarks/*.json` (gitignored).
Every number below can be re-derived from those files with
`python -m benchmarks.ai.run_benchmark --summarize output/benchmarks/<file>.json`.

## TL;DR

| | qwen2.5:0.5b (current default) | qwen2.5:3b |
|---|---|---|
| Does semantic selection | **No.** Returns 16 of the 17 segments in chronological order, nearly always with one constant score. Its top-ranked moment matched the task **0/12** times. | **Partly.** Top-1 moment matched the task **9/12** times with the production prompt (funny 3/3, educational 3/3, Q&A 3/3, decision 0/3). |
| Precision (share of returned moments that match the task) | 0.06-0.12, the same as listing everything | 0.00-0.23 (it pads with filler and admin moments) |
| Typical failure | ignores the instruction; copies the prompt's example score `0.91` | correct quote with the **wrong timestamps** (a neighbouring or later segment) |
| AI time per call (150 s transcript) | 18-23 s | 13-46 s (grows with the number of candidates it writes) |
| Real end-to-end, 3 × 10 s "funny moments" | **0/3 succeeded** (invalid or no candidates; one run hit the 120 s Ollama timeout) | **3/3 succeeded**, 92-158 s per job |
| Repeatable at default temperature 0.1 | 3-4/5 identical outputs | 1-4/5 identical outputs |
| Repeatable at temperature 0 + seed 42 | 5/5 identical | 5/5 identical |

**Decision:** the default model was **not** changed (M07 rule). The measured evidence is documented here for the
project's model decision; see "Recommendation" at the end. No prompt change was adopted either; see "Prompt investigation".

## Dataset (`benchmarks/ai/dataset.json`)

A synthetic 150 s team-meeting transcript of 17 segments. Each segment has one known category:

| label | segments | example |
|---|---|---|
| filler | 4 | "Okay, um, can everyone hear me?" |
| admin | 4 | "Please submit your timesheets by Monday." |
| announcement | 2 | "The parking garage on level two is closed..." |
| educational | 2 | "A cache keeps a copy of data we already fetched..." |
| joke | 2 | "Why did the developer go broke? Because he used up all his cache." |
| qa | 2 | a question (77-85 s) and its answer (85-94 s) |
| conclusion | 1 | "So here is the decision: we roll the cache out..." (117-132 s) |

Tasks (instruction → target label): `funny moments` → joke, `educational explanations that teach something` →
educational, `the most important decision or conclusion` → conclusion, `audience questions and their answers` → qa.

The labels are only used to score the output and are never sent to the model. A test checks that
(`tests/test_benchmark_metrics.py::test_dataset_labels_never_reach_the_model`).
The prompt is exactly what M03 sends: `build_prompt` with max 20 candidates, and validation uses M03's own validator.

## Metrics (all computed, none hand-scored)

- **parse ok**: the response parsed with M03's `parse_ai_response`.
- **returned / valid**: raw candidates, and candidates that pass M03 validation (finite, ordered, inside the transcript, score in [0,1], non-empty reason).
- **distinct scores / modal score share**: score diversity. A modal share of 1.00 means every candidate got the same score.
- **near-dup pairs**: candidate pairs with IoU ≥ 0.5.
- **unique reasons**: distinct reason strings / valid candidates.
- **label of a candidate**: the label of the segment it overlaps most.
- **top-1 hit**: the highest-ranked candidate (M03 order) has the target label. Since M05 cuts the top-ranked moments first, this matters most.
- **precision / recall**: share of candidates with the target label / share of target segments ≥ 50 % covered.
- **irrelevant**: share of candidates labelled filler, admin or announcement.
- **M05 10 s clips**: how many distinct 10 s clips the real M05 `select_moments` would accept.
- **evidence in range**: when a reason quotes a segment (≥ 4 shared words), whether that segment overlaps the candidate's own times.
- **run-to-run Jaccard / identical outputs**: similarity of the covered-segment sets across runs / identical raw responses.

## Results - production prompt (v1), 3 runs per cell, temperature 0.1

| model | task | parse ok | s/run | valid | distinct scores | modal share | unique reasons | top-1 hit | precision | recall | irrelevant | evidence in range |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.5b | decision | 3/3 | 17.6 | 16.0 | 1.0 | 1.00 | 0.19 | 0/3 | 0.06 | 1.00 | 0.56 | 3/33 |
| 0.5b | educational | 3/3 | 20.8 | 16.0 | 6.0 | 0.69 | 0.33 | 0/3 | 0.12 | 1.00 | 0.56 | 3/4 |
| 0.5b | funny | 3/3 | 22.5 | 16.0 | 1.0 | 1.00 | 0.21 | 0/3 | 0.12 | 1.00 | 0.56 | 3/31 |
| 0.5b | qa | 3/3 | 20.7 | 16.0 | 1.3 | 0.98 | 0.17 | 0/3 | 0.12 | 1.00 | 0.56 | 3/18 |
| 3b | decision | 3/3 | 12.7 | 2.0 | 2.0 | 0.50 | 1.00 | 0/3 | 0.00 | 0.00 | 1.00 | 0/3 |
| 3b | educational | 3/3 | 45.7 | 8.7 | 2.0 | 0.53 | 0.72 | 3/3 | 0.23 | 1.00 | 0.35 | 3/5 |
| 3b | funny | 3/3 | 30.3 | 4.3 | 4.3 | 0.23 | 1.00 | 3/3 | 0.23 | 0.50 | 0.53 | 5/5 |
| 3b | qa | 3/3 | 44.6 | 10.0 | 10.0 | 0.15 | 0.87 | 3/3 | 0.18 | 0.67 | 0.58 | 0/3 |

Timestamp validity: every candidate in this table passed M03 validation (valid = returned), and all of them except
3 of 30 3b Q&A candidates started and ended exactly on segment boundaries. The weakness is not invalid times. It is **valid times that belong to the wrong
segment**: for 0.5b on decision, 3 of 33 quoted segments were inside the candidate's own times.

### What the numbers mean

**qwen2.5:0.5b** treats the task as "list the transcript". In every run it returned 16 of the 17 segments (all but the first)
in chronological order, so recall is trivially 1.00 and precision equals the base rate of the target label. The first
candidate is always ranked highest, which is why top-1 is 0/12. Scores are constant (often the prompt's example `0.91`,
then `0.88` for the rest). Reasons repeat (19-33 % unique), and they often describe a different segment from the one
whose times they carry. M05 then "succeeds" because 16 distinct segments always exist, but the clips are effectively
chosen at random. This explains the M05 known limitation "identical scores/reasons, weak moments".

**qwen2.5:3b** clearly reads the content. Its top choice is right for funny, educational and Q&A in 9/9 runs, and its
scores and reasons vary. Two problems remain:
1. It **pads** the list with announcements and admin lines (35-58 % irrelevant). Each one gets a plausible-sounding
   reason ("adds a lighthearted note to the meeting").
2. It **attaches times from a different segment** to a correct quote. On the decision task it quoted the decision sentence
   (117-132 s) in 3/3 runs but returned 132-141 s, the next segment, so top-1 is 0/3 even though the choice was right.

## Prompt investigation (D)

The current M03 prompt (v1) has two properties that plausibly hurt small models:
- Its JSON example contains concrete values (`"score": 0.91`, a fixed reason). 0.5b copies them.
- It never asks for evidence, a score spread, or for times to match the quoted text.

A general-purpose v2 prompt was written and measured. It has no content words, no timestamps and no special-case
scoring; a test checks for this (`test_v2_experiment_prompt_is_general_purpose`). It uses:
- placeholders (`<number>`) instead of example values
- a reason that quotes a few words of the moment
- a score spread ("different moments deserve different scores")
- times that must come from the quoted segment(s)
- "leave out greetings, logistics, scheduling, reminders and filler unless asked"
- "return fewer rather than padding"

Two delivery options were tested with it: Ollama JSON mode (`format="json"`, grammar-constrained output), and keyed
transcript lines (`start=117.0 end=132.0 text="..."` instead of `[117.0-132.0] ...`). The keyed lines came from a
format experiment: with `[s-e] text`, 3b returned the *next* segment's times for 5 of 11 matched quotes.

Variants: **v2** = new prompt + keyed lines + JSON mode; **v2-free** = without JSON mode; **v2-bracket** = with the
production `[s-e]` lines. 3 runs per cell. The full table is in the raw results; the 3b summary over all 4 tasks:

| 3b variant | top-1 hit | mean precision | mean irrelevant | evidence in range |
|---|---|---|---|---|
| **v1 (production)** | **9/12** | 0.16 | 0.62 | 8/16 |
| v2 | 6/12 (decision 3/3, funny 3/3, educational 0/3, qa 0/3) | **0.40** | **0.46** | 26/40 |
| v2-free | 6/12 | 0.37 | 0.52 | 40/57 |
| v2-bracket | 6/12 (decision 0/3, qa 0/3) | 0.26 | 0.58 | 42/53 |

For 0.5b, nothing helped: top-1 was 0/12 in every variant. v2 parsed 11/12 with JSON mode, but only **3/12 without it**,
because 0.5b breaks the JSON when asked to quote. Even with JSON mode, 0.5b sometimes writes the list and then emits
whitespace until the output is cut off, deterministically under a fixed seed (0/5 parsed on "funny").

**Conclusion: v2 is a trade-off, not an improvement.**
- It cuts padding (irrelevant 0.62 → 0.46) and raises precision (0.16 → 0.40) for 3b.
- It fixes the decision task's timestamp shift.
- But it loses the right top-1 on educational and Q&A, where 3b again quoted the right text with the times of a
  later segment.

Changing the transcript format moved *which* task suffers from wrong timestamps, but did not remove the problem. Since
M05 cuts the top-ranked moments first, losing top-1 matters more than gaining precision. **The production prompt and
transcript format were left unchanged.** v2 is kept in `benchmarks/ai/run_benchmark.py` as a documented experiment.

The root problem that remains is **timestamp grounding**: the 3b model picks the right words but not reliably the right
times. That is a mapping problem rather than a judgement problem. A possible future step is to have the model cite the
quoted words and let Python locate them verbatim in the transcript; it is not implemented here.

## Repeatability (E)

Same input, same task, 5 runs each. Production prompt (v1):

| model | task | temperature 0.1 (M03 default): identical outputs | covered-set Jaccard | temperature 0 + seed 42: identical outputs |
|---|---|---|---|---|
| 0.5b | decision | 4/5 | 1.00 | 5/5 |
| 0.5b | funny | 3/5 | 1.00 | 5/5 |
| 3b | decision | 4/5 | 1.00 | 5/5 |
| 3b | funny | 1/5 | 0.67 | 5/5 |

The v2 experiment showed the same pattern: 1-5/5 identical at default settings, and 5/5 with the seed in every cell.

**Where variation comes from:**
- **Model generation randomness, only.** With temperature 0 + a fixed seed, every response was byte-identical.
- **Not candidate validation or selection.** Rescoring identical responses gives identical results. M03 validation and
  M05 selection are pure functions of the response (covered by the M05 determinism tests and `--summarize`).
- **Not the prompt.** The prompt is fixed text, identical across runs.

**Was a deterministic setting adopted? No.**
- It makes outputs repeatable but **does not improve them**: top-1 and precision were identical between seeded and
  unseeded runs.
- It removes the only current recovery for an "insufficient candidates" failure, which is running again. A
  deterministic failure, like 0.5b's 0/5 above, would then fail on every retry.
- Users who want repeatability can already set `AI_TEMPERATURE=0`. A seed option would be a one-line addition if the
  project decides it wants repeatability over retries.

## Performance on this machine

Text-only AI time per call (150 s transcript, from the benchmark): 0.5b 18-23 s; 3b 13-46 s, depending on how many
candidates it writes.

Real end-to-end runs: `python -m benchmarks.e2e.run_real_e2e --synthesize -n 3 -d 10 -i "funny moments"`, on a
146.7 s 640x360 speech video synthesized locally with Windows SAPI from the benchmark transcript. Times in seconds:

| model | result | transcription (Whisper small, incl. model load) | AI reasoning | selection | FFmpeg (3 × 10 s clips) | total |
|---|---|---|---|---|---|---|
| 3b run 1 | success | 37.0 | 78.2 | 0.00 | 1.67 | 117.1 |
| 3b run 2 | success | 39.0 | 51.3 | 0.00 | 1.71 | 92.3 |
| 3b run 3 | success | 38.8 | 117.3 | 0.00 | 1.69 | 158.1 |
| 0.5b run 1 | failed: 0 valid candidates (three zero-length 1.0-1.0 candidates) | 39.3 | 12.7 | 0.00 | - | 52.1 |
| 0.5b run 3 | failed: 0 valid candidates | 37.3 | 9.9 | 0.00 | - | 47.3 |
| 0.5b run 2 (outlier) | failed: Ollama 120 s timeout | 688.7 | 122.1 | - | - | 810.9 |

The 0.5b run 2 transcription took 18× longer than the five other runs on the same file, and its AI call then timed out.
No other job from this session was running at the time. The cause is unknown; the run is reported but excluded from the typical figures.

- **Typical (3b, 3 × 10 s):** transcription ~38 s (0.26× real time), AI 51-117 s, selection < 10 ms, FFmpeg ~0.56 s
  per clip. Total **~1.5-2.6 min**.
- Every successful clip probed at **10.000 s**, h264 + aac.

## Recommendation for the project decision (not applied)

On this evidence qwen2.5:0.5b cannot do the M03 task: 0/12 top-1, 0/3 real end-to-end successes. qwen2.5:3b does
it partially: 9/12 top-1, 3/3 real successes.

The cost of 3b is about 1.9 GB of disk and longer AI time: 51-117 s vs 10-13 s for 0.5b in the real runs (4-9×), so about 1.5-2.6 min per job on this CPU.

Switching the default to `qwen2.5:3b` is the one change measured to matter. Today it is a configuration choice
(`OLLAMA_MODEL=qwen2.5:3b`), and it should be decided explicitly by the project, together with the
timestamp-grounding follow-up above.
