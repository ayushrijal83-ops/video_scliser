# M07 AI Quality Benchmark - qwen2.5:0.5b vs qwen2.5:3b

All runs: 2026-10-03, Intel Core Ultra 5 125H, CPU only, Ollama 0.32.15, local models only.
Raw per-run results (full model responses included) are written to `output/benchmarks/*.json` (gitignored).
Every number below can be re-derived from those files with
`python -m benchmarks.ai.run_benchmark --summarize output/benchmarks/<file>.json`.

> **M08 update:** the default model is now `qwen2.5:3b`, and clip locations come from Python quote grounding.
> See "M08 update - timestamp grounding" at the end of this document.

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

---

# M08 update - timestamp grounding (2026-10-03)

M08 made **qwen2.5:3b the default** and changed who decides where a clip is. The model now also returns a `quote`.
Python locates that quote in the timestamped transcript (`app/ai/grounding.py`), and the model's own start/end are no
longer the clip location. Same dataset, tasks, 3 runs per cell and temperature 0.1 as M07. M03 now also caps output
at 3072 tokens (`num_predict`); that only affects runaway replies, and M07-style replies are far below it.

Variants (all in `benchmarks/ai/run_benchmark.py`):
- **v1**: the M07 production prompt, AI times trusted. Re-run in this session as the baseline.
- **m08**: the production prompt. The M07 prompt verbatim, plus a quote rule and a `quote` field asked for last
  with a placeholder example. Graded with the live M03 grounding.
- **m08-sentence / m08-rules / m08-first**: earlier M08 revisions, measured and rejected (see below).

New columns:
- **quoted**: raw candidates with a quote.
- **not found / ambiguous / too short**: rejected by grounding.
- **AI time wrong**: grounded candidates whose claimed times do not overlap where the quote really is. Each of these
  is a clip that M07 would have cut in the wrong place.

| model | prompt | task | runs | parse ok | s/run | valid | top-1 hit | precision | irrelevant | quoted | not found | ambiguous | too short | AI time wrong |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|------|
| qwen2.5:0.5b | m08 | decision | 3 | 3/3 | 37.7 | 15.3 | 0/3 | 0.07 | 0.42 | 46 | 0 | 0 | 0 | 32/46 |
| qwen2.5:0.5b | m08 | educational | 3 | 3/3 | 41.3 | 16.0 | 0/3 | 0.10 | 0.44 | 48 | 0 | 0 | 0 | 37/48 |
| qwen2.5:0.5b | m08 | funny | 3 | 2/3 | 54.7 | 10.7 | 0/3 | 0.47 | 0.34 | 32 | 0 | 0 | 0 | 26/32 |
| qwen2.5:0.5b | m08 | qa | 3 | 3/3 | 38.7 | 15.7 | 0/3 | 0.04 | 0.44 | 48 | 1 | 0 | 0 | 36/47 |
| qwen2.5:0.5b | m08-rules | decision | 3 | 0/3 | 118.3 | 0.0 | 0/3 | - | - | 0 | 0 | 0 | 0 | 0/0 |
| qwen2.5:0.5b | m08-rules | educational | 3 | 0/3 | 114.2 | 0.0 | 0/3 | - | - | 0 | 0 | 0 | 0 | 0/0 |
| qwen2.5:0.5b | m08-rules | funny | 3 | 0/3 | 115.0 | 0.0 | 0/3 | - | - | 0 | 0 | 0 | 0 | 0/0 |
| qwen2.5:0.5b | m08-rules | qa | 3 | 0/3 | 118.1 | 0.0 | 0/3 | - | - | 0 | 0 | 0 | 0 | 0/0 |
| qwen2.5:0.5b | m08-sentence | decision | 3 | 1/3 | 50.7 | 1.0 | 0/3 | 0.00 | 0.67 | 4 | 1 | 0 | 0 | 3/3 |
| qwen2.5:0.5b | m08-sentence | educational | 3 | 1/3 | 51.1 | 1.0 | 0/3 | 0.00 | 1.00 | 7 | 4 | 0 | 0 | 3/3 |
| qwen2.5:0.5b | m08-sentence | funny | 3 | 3/3 | 5.1 | 2.0 | 0/3 | 0.00 | 0.50 | 9 | 3 | 0 | 0 | 6/6 |
| qwen2.5:0.5b | m08-sentence | qa | 3 | 1/3 | 51.3 | 1.0 | 1/3 | 0.33 | 0.67 | 5 | 2 | 0 | 0 | 3/3 |
| qwen2.5:0.5b | v1 | decision | 3 | 3/3 | 12.0 | 11.3 | 0/3 | 0.04 | 0.71 | 0 | 0 | 0 | 0 | 0/0 |
| qwen2.5:0.5b | v1 | educational | 3 | 3/3 | 19.4 | 16.0 | 0/3 | 0.12 | 0.56 | 0 | 0 | 0 | 0 | 0/0 |
| qwen2.5:0.5b | v1 | funny | 3 | 3/3 | 18.0 | 16.0 | 0/3 | 0.12 | 0.56 | 0 | 0 | 0 | 0 | 0/0 |
| qwen2.5:0.5b | v1 | qa | 3 | 3/3 | 15.9 | 16.0 | 0/3 | 0.12 | 0.56 | 0 | 0 | 0 | 0 | 0/0 |
| qwen2.5:3b | m08 | decision | 3 | 3/3 | 161.4 | 19.7 | 0/3 | 0.02 | 0.68 | 59 | 0 | 0 | 0 | 29/59 |
| qwen2.5:3b | m08 | educational | 3 | 3/3 | 92.7 | 9.3 | 3/3 | 0.23 | 0.41 | 28 | 0 | 0 | 0 | 3/28 |
| qwen2.5:3b | m08 | funny | 3 | 3/3 | 60.8 | 6.0 | 3/3 | 0.25 | 0.53 | 18 | 0 | 0 | 0 | 5/18 |
| qwen2.5:3b | m08 | qa | 3 | 3/3 | 26.6 | 2.7 | 3/3 | 0.42 | 0.17 | 8 | 0 | 0 | 0 | 5/8 |
| qwen2.5:3b | m08-first | decision | 3 | 3/3 | 101.4 | 10.3 | 0/3 | 0.11 | 0.62 | 31 | 0 | 0 | 0 | 28/31 |
| qwen2.5:3b | m08-first | educational | 3 | 3/3 | 197.2 | 18.7 | 3/3 | 0.58 | 0.36 | 56 | 0 | 0 | 0 | 50/56 |
| qwen2.5:3b | m08-first | funny | 3 | 3/3 | 142.0 | 14.3 | 0/3 | 0.20 | 0.66 | 43 | 0 | 0 | 0 | 24/43 |
| qwen2.5:3b | m08-first | qa | 3 | 3/3 | 210.4 | 19.0 | 0/3 | 0.04 | 0.51 | 57 | 0 | 0 | 0 | 45/57 |
| qwen2.5:3b | m08-rules | decision | 3 | 3/3 | 82.1 | 7.7 | 1/3 | 0.30 | 0.33 | 23 | 0 | 0 | 0 | 21/23 |
| qwen2.5:3b | m08-rules | educational | 3 | 3/3 | 157.4 | 15.3 | 1/3 | 0.23 | 0.64 | 48 | 2 | 0 | 0 | 37/46 |
| qwen2.5:3b | m08-rules | funny | 3 | 3/3 | 60.3 | 5.0 | 1/3 | 0.26 | 0.52 | 15 | 0 | 0 | 0 | 9/15 |
| qwen2.5:3b | m08-rules | qa | 3 | 3/3 | 128.2 | 13.0 | 0/3 | 0.15 | 0.44 | 40 | 1 | 0 | 0 | 34/39 |
| qwen2.5:3b | m08-sentence | decision | 3 | 3/3 | 28.1 | 2.0 | 2/3 | 0.50 | 0.00 | 6 | 0 | 0 | 0 | 6/6 |
| qwen2.5:3b | m08-sentence | educational | 3 | 3/3 | 179.5 | 18.0 | 3/3 | 0.15 | 0.72 | 54 | 0 | 0 | 0 | 37/54 |
| qwen2.5:3b | m08-sentence | funny | 3 | 3/3 | 123.7 | 12.7 | 2/3 | 0.29 | 0.28 | 42 | 4 | 0 | 0 | 22/38 |
| qwen2.5:3b | m08-sentence | qa | 3 | 3/3 | 81.4 | 8.0 | 1/3 | 0.03 | 0.23 | 25 | 1 | 0 | 0 | 21/24 |
| qwen2.5:3b | v1 | decision | 3 | 3/3 | 18.8 | 2.0 | 0/3 | 0.00 | 1.00 | 0 | 0 | 0 | 0 | 0/0 |
| qwen2.5:3b | v1 | educational | 3 | 3/3 | 54.9 | 8.7 | 3/3 | 0.23 | 0.35 | 0 | 0 | 0 | 0 | 0/0 |
| qwen2.5:3b | v1 | funny | 3 | 3/3 | 35.2 | 5.0 | 3/3 | 0.20 | 0.60 | 0 | 0 | 0 | 0 | 0/0 |
| qwen2.5:3b | v1 | qa | 3 | 3/3 | 61.9 | 6.3 | 3/3 | 0.24 | 0.55 | 0 | 0 | 0 | 0 | 0/0 |

## Summary (qwen2.5:3b, 4 tasks × 3 runs)

| variant | top-1 | mean precision | mean irrelevant | s/call | quotes grounded | AI time wrong (corrected) | real Whisper transcript |
|---|---|---|---|---|---|---|---|
| v1 (M07, AI times trusted) | 9/12 | 0.17 | 0.63 | 43 | - | - | - |
| m08-sentence | 8/12 | 0.24 | 0.31 | 103 | 122/127 | 86/122 | **0 grounded**: the example quote was copied into every candidate |
| m08-rules | 3/12 | 0.24 | 0.48 | 107 | 123/126 | 101/123 | works |
| m08-first | 3/12 | 0.23 | 0.54 | 163 | 187/187 | 147/187 | works |
| **m08 (production)** | **9/12** | 0.23 | **0.45** | 85 | **113/113** | **42/113** | works; top picks are the two jokes |

qwen2.5:0.5b with m08: 11/12 parsed, 173/174 quotes grounded, but **top-1 still 0/12**. The 0.5b problem is
selection, not location. Under the earlier quote-first prompts it looped until the output cap (0/12 parsed with m08-rules).

## What grounding fixed, and what it cannot

- **Fixed: right words, wrong time.** Over the four M08 revisions, 37-82 % of 3b's grounded candidates carried a
  claimed time that missed their own quote. Examples:
  - "So here is the decision…", grounded at 117-132 s; 3b claimed 132-141 s.
  - "Our intern tried to fix the printer…", grounded at 34-44 s; 3b claimed 44-51 s.
  Every final cut now comes from the quote's transcript position. In a real run (below) it corrected a clip from
  114.9-116.0 s to 124.0-130.0 s.
- **Not fixed: wrong words.** On the decision task the production prompt's 3b quoted "The next meeting is the same
  time next week" (the line after the decision). Grounding places exactly what the model quoted.
- **Quote position matters.** Asking for the quote *first* made 3b scan line by line: 10-20 candidates, slower, top-1
  3/12. But its time errors got corrected more often, and the decision task scored 1-2/3. Asking for it *last* keeps
  M07's ranking (9/12), but the quote sometimes follows the model's own shifted time, so fewer errors show up to correct.
- **Placeholder vs example.** A sentence-like example quote was copied verbatim by 3b on a real 40-segment Whisper
  transcript (all 6-10 quotes rejected, so no clips). The angle-bracket placeholder is never copied.

## Real end-to-end (qwen2.5:3b, production prompt)

| run | result | probed clips | AI | total |
|---|---|---|---|---|
| funny moments 3 × 10 s | success; the two jokes are clips 1-2; clip 3 grounded 124.00-130.04 s vs AI 114.9-116.0 s | 3 × 10.000000 s, h264 + aac | 167.5 s | 209.1 s |
| funny moments 3 × 10 s | success; the two jokes are clips 1-2 | 3 × 10.000000 s | 70.9 s | 113.1 s |
| decision 1 × 10 s | success; the decision sentence grounded 118.46-123.06 s | 10.000000 s | 481.4 s | 523.4 s |
| browser UI, funny 2 × 10 s | success; intern joke + office announcement | 2 × 10.000000 s | 72 s | 106 s |

Grounding itself costs 26 ms plus ~6 ms per quote, even for a 2-hour transcript. AI inference is the bottleneck.
