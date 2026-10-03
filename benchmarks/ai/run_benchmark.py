"""Local AI quality benchmark (M07, extended in M08): same transcript and tasks, several models / prompts / runs.

Usage (Ollama running, models pulled):
    python -m benchmarks.ai.run_benchmark --models qwen2.5:0.5b qwen2.5:3b --runs 3     # v1 vs m08
    python -m benchmarks.ai.run_benchmark --tasks funny --runs 5 --temperature 0 --seed 42

Raw results go to output/benchmarks/ (gitignored); a Markdown summary is printed to stdout.
The dataset labels are only used for scoring here; the model sees the plain transcript.
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
import statistics
import time
from pathlib import Path
from typing import Any

from app.ai import prompts
from app.ai.client import OllamaClient, OllamaConfig
from app.ai.exceptions import AIError
from app.ai.models import ClipCandidate
from app.ai.service import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    AIReasoningConfig,
    AIReasoningService,
)
from app.clipping import InsufficientCandidatesError, iou, select_moments
from app.clipping.models import ClipWindow
from app.transcription.models import TranscriptionResult, TranscriptSegment

DATASET = Path(__file__).with_name("dataset.json")
OUT_DIR = Path("output/benchmarks")

# Variants:
#   v1   the M07 production prompt (verbatim copy) with M07 validation: the model's times are the clip location.
#   m08  the live production prompt (asks for a quote) with the live M03 validation: quotes grounded in Python.
#   v2*  the M07 prompt experiment (not adopted, see docs/M07_AI_BENCHMARK.md), M07 validation.
PROMPT_M07 = """You are an expert video content analyzer. Your task is to identify the most interesting, self-contained moments in a timestamped video transcript based on a user's instruction.

RULES:
1. Return ONLY valid JSON. No markdown, no extra text, no explanations.
2. Identify self-contained moments that make sense as standalone clips.
3. Use ONLY timestamps from the provided transcript. Do not invent timestamps.
4. Each candidate must have: start (float), end (float), reason (string), score (float 0-1).
5. Scores represent how well the moment matches the instruction (1.0 = perfect match).
6. Sort candidates by score descending.
7. Avoid overlapping candidates when possible.
8. Respect the user's instruction precisely.
9. Maximum candidates: {max_candidates}.

JSON FORMAT:
{{
  "candidates": [
    {{
      "start": 72.5,
      "end": 105.2,
      "reason": "Clear standalone explanation with a strong hook about the topic.",
      "score": 0.91
    }}
  ]
}}"""

PROMPT_V2 = """You are a video editor choosing short clips from a timestamped transcript.
Judge the meaning of what is said, not individual keywords.

RULES:
1. Return ONLY a JSON object of the form {{"candidates": [...]}}. No markdown, no commentary.
2. A candidate is one self-contained moment made of one or more consecutive transcript segments.
   "start" is the start time of its first segment and "end" is the end time of its last segment,
   copied exactly from the transcript. Never use times outside the transcript.
3. "reason": one specific sentence that quotes a few key words from the moment and explains how
   they match the instruction. Do not repeat a reason.
4. Use the times of the segment(s) whose words you quote; do not shift text to a neighbouring segment.
5. "score" from 0.0 to 1.0: how strongly the moment matches the instruction compared with the other moments.
   Clear match 0.8-1.0, partial match 0.4-0.7, weak match below 0.4. Different moments deserve different scores.
6. Leave out moments that do not match the instruction, such as greetings, logistics, scheduling,
   reminders and filler, unless the instruction asks for them.
7. Candidates must not overlap. Order them by score, highest first.
8. Return at most {max_candidates} candidates. Return fewer rather than padding with weak moments.

OUTPUT SCHEMA (types only; replace every placeholder with real values):
{{"candidates": [{{"start": <number>, "end": <number>, "reason": "<quoted words and why they match>", "score": <number between 0 and 1>}}]}}"""
# Earlier M08 prompt revisions, kept so their documented results stay reproducible (not used in production):
# m08-sentence  quote example was a sentence; qwen2.5:3b copied it into every candidate on a real transcript.
# m08-rules     angle-bracket placeholder plus reworded quote rule; grounding worked, but 3b top-1 fell to 3/12.
PROMPT_M08_SENTENCE = """You are an expert video content analyzer. Your task is to identify the most interesting, self-contained moments in a timestamped video transcript based on a user's instruction.

RULES:
1. Return ONLY valid JSON. No markdown, no extra text, no explanations.
2. Identify self-contained moments that make sense as standalone clips.
3. For each moment, "quote" must be a short passage copied word for word from the transcript text (about 5 to 20 words).
   Copy the exact words: do not paraphrase, do not invent text, do not shorten it with "...".
   Choose words that appear only once in the transcript, so the quote identifies exactly this moment.
   Choosing the right moment and quoting it exactly matters more than the timestamps.
4. Each candidate must have: quote (string), start (float), end (float), reason (string), score (float 0-1).
   start and end are your best estimate of where the quote is, using timestamps from the transcript.
5. Scores represent how well the moment matches the instruction (1.0 = perfect match).
6. Sort candidates by score descending.
7. Avoid overlapping candidates when possible.
8. Respect the user's instruction precisely.
9. Maximum candidates: {max_candidates}.

JSON FORMAT:
{{
  "candidates": [
    {{
      "quote": "the exact words copied from the transcript",
      "start": 72.5,
      "end": 105.2,
      "reason": "Clear standalone explanation with a strong hook about the topic.",
      "score": 0.91
    }}
  ]
}}"""
PROMPT_M08_PLACEHOLDER_RULES = """You are an expert video content analyzer. Your task is to identify the most interesting, self-contained moments in a timestamped video transcript based on a user's instruction.

RULES:
1. Return ONLY valid JSON. No markdown, no extra text, no explanations.
2. Identify self-contained moments that make sense as standalone clips.
3. For each moment, "quote" must be 5 to 20 consecutive words copied exactly from the TRANSCRIPT SEGMENTS
   (the text after a [start-end] time; it may continue into the next line).
   Copy the exact words: do not paraphrase, do not invent text, do not shorten it with "...".
   Every candidate needs its own quote taken from its own moment. Never copy the example below.
   Choose words that appear only once in the transcript, so the quote identifies exactly this moment.
   Choosing the right moment and quoting it exactly matters more than the timestamps.
4. Each candidate must have: quote (string), start (float), end (float), reason (string), score (float 0-1).
   start and end are your best estimate of where the quote is, using timestamps from the transcript.
5. Scores represent how well the moment matches the instruction (1.0 = perfect match).
6. Sort candidates by score descending.
7. Avoid overlapping candidates when possible.
8. Respect the user's instruction precisely.
9. Maximum candidates: {max_candidates}.

JSON FORMAT:
{{
  "candidates": [
    {{
      "quote": "<5-20 words copied from one transcript line>",
      "start": 72.5,
      "end": 105.2,
      "reason": "Clear standalone explanation with a strong hook about the topic.",
      "score": 0.91
    }}
  ]
}}"""

# m08-first    quote first + placeholder (M07 rule wording otherwise); 3b top-1 also 3/12.
PROMPT_M08_QUOTE_FIRST = """You are an expert video content analyzer. Your task is to identify the most interesting, self-contained moments in a timestamped video transcript based on a user's instruction.

RULES:
1. Return ONLY valid JSON. No markdown, no extra text, no explanations.
2. Identify self-contained moments that make sense as standalone clips.
3. For each moment, "quote" must be a short passage copied word for word from the transcript text (about 5 to 20 words).
   Copy the exact words: do not paraphrase, do not invent text, do not shorten it with "...".
   Choose words that appear only once in the transcript, so the quote identifies exactly this moment.
   Choosing the right moment and quoting it exactly matters more than the timestamps.
4. Each candidate must have: quote (string), start (float), end (float), reason (string), score (float 0-1).
   start and end are your best estimate of where the quote is, using timestamps from the transcript.
5. Scores represent how well the moment matches the instruction (1.0 = perfect match).
6. Sort candidates by score descending.
7. Avoid overlapping candidates when possible.
8. Respect the user's instruction precisely.
9. Maximum candidates: {max_candidates}.

JSON FORMAT:
{{
  "candidates": [
    {{
      "quote": "<5-20 words copied from one transcript line>",
      "start": 72.5,
      "end": 105.2,
      "reason": "Clear standalone explanation with a strong hook about the topic.",
      "score": 0.91
    }}
  ]
}}"""

V1_EXAMPLE_REASON = "Clear standalone explanation with a strong hook about the topic."
PROMPTS = {"v1": PROMPT_M07, "m08": prompts.SYSTEM_PROMPT, "m08-sentence": PROMPT_M08_SENTENCE,
           "m08-rules": PROMPT_M08_PLACEHOLDER_RULES,
           "m08-first": PROMPT_M08_QUOTE_FIRST, "v2": PROMPT_V2, "v2-free": PROMPT_V2, "v2-bracket": PROMPT_V2}
GROUNDED = {"m08", "m08-sentence", "m08-rules", "m08-first"}
# Ablations: v2-free = v2 without Ollama JSON mode; v2-bracket = v2 with the production transcript lines.
JSON_MODE = {"v1": False, "m08": False, "m08-sentence": False, "m08-rules": False, "m08-first": False, "v2": True, "v2-free": False,
             "v2-bracket": True}
KEYED_LINES = {"v2", "v2-free"}
M05_CLIP_SECONDS = 10.0  # window length used to count how many distinct clips M05 could cut


def load_dataset(path: Path = DATASET) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def to_transcript(data: dict[str, Any]) -> TranscriptionResult:
    segments = [TranscriptSegment(start=s["start"], end=s["end"], text=s["text"]) for s in data["segments"]]
    return TranscriptionResult("benchmark.json", "en", 1.0, data["duration"], segments, "benchmark")


def keyed_transcript_lines(transcript: TranscriptionResult) -> str:
    """Experimental v2 line format: explicit keys instead of "[start-end] text"."""
    return "\n".join(
        f"start={seg.start:.1f} end={seg.end:.1f} text={json.dumps(seg.text, ensure_ascii=False)}"
        for seg in transcript.segments
    )


def build_full_prompt(variant: str, transcript: TranscriptionResult, instruction: str, max_candidates: int) -> str:
    _, user, _ = prompts.build_prompt(transcript, instruction, max_candidates)  # production format
    if variant in KEYED_LINES:
        user = prompts.USER_PROMPT_TEMPLATE.format(
            instruction=instruction, duration=transcript.duration,
            transcript_text=keyed_transcript_lines(transcript), max_candidates=max_candidates,
        )
    return PROMPTS[variant].format(max_candidates=max_candidates) + "\n\n" + user


# --- metrics (pure, unit tested) --------------------------------------------------------


def label_of(c: ClipCandidate, segments: list[dict[str, Any]]) -> str:
    """Label of the segment the candidate overlaps most (ties: earliest)."""
    best, best_overlap = "none", 0.0
    for s in segments:
        overlap = min(c.end, s["end"]) - max(c.start, s["start"])
        if overlap > best_overlap + 1e-9:
            best, best_overlap = s["label"], overlap
    return best


def covered_segments(cands: list[ClipCandidate], segments: list[dict[str, Any]]) -> set[int]:
    """Indices of segments at least half covered by some candidate."""
    out = set()
    for i, s in enumerate(segments):
        length = s["end"] - s["start"]
        if any(min(c.end, s["end"]) - max(c.start, s["start"]) >= 0.5 * length for c in cands):
            out.add(i)
    return out


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9']+", text.lower()))


def jaccard(a: set[Any], b: set[Any]) -> float:
    return len(a & b) / len(a | b) if a | b else 1.0


def mean_pairwise(values: list[set[Any]]) -> float | None:
    pairs = list(itertools.combinations(values, 2))
    return statistics.fmean(jaccard(a, b) for a, b in pairs) if pairs else None


def aligned(c: ClipCandidate, segments: list[dict[str, Any]], tol: float = 0.05) -> bool:
    starts = [s["start"] for s in segments]
    ends = [s["end"] for s in segments]
    return any(abs(c.start - x) <= tol for x in starts) and any(abs(c.end - x) <= tol for x in ends)


def evidence_in_range(c: ClipCandidate, segments: list[dict[str, Any]], min_words: int = 4) -> bool | None:
    """Does the segment whose words the candidate quotes overlap the candidate's own times?

    Uses the quote field when present (M08), else the reason. None when nothing quotes a segment
    (fewer than min_words shared words with every segment).
    """
    words = _tokens(c.quote or c.reason)
    shared = [len(words & _tokens(s["text"])) for s in segments]
    best = max(range(len(segments)), key=lambda i: shared[i] / max(len(_tokens(segments[i]["text"])), 1))
    if shared[best] < min_words:
        return None
    s = segments[best]
    return min(c.end, s["end"]) - max(c.start, s["start"]) > 0


def m05_distinct(cands: list[ClipCandidate], duration: float) -> int:
    """How many distinct clips of M05_CLIP_SECONDS the real M05 selector would accept."""
    if not cands:
        return 0
    try:
        return len(select_moments(cands, len(cands), M05_CLIP_SECONDS, duration))
    except InsufficientCandidatesError as e:
        return e.found


def score_run(
    raw: list[dict[str, Any]], valid: list[ClipCandidate], data: dict[str, Any], target: str
) -> dict[str, Any]:
    segs = data["segments"]
    labels = [label_of(c, segs) for c in valid]
    target_idx = {i for i, s in enumerate(segs) if s["label"] == target}
    covered = covered_segments(valid, segs)
    scores = [c.score for c in valid]
    reasons = [c.reason.strip().lower() for c in valid]
    windows = [ClipWindow(c.start, c.end) for c in valid]
    n = len(valid)
    return {
        "returned": len(raw),
        "valid": n,
        "aligned": sum(aligned(c, segs) for c in valid),
        "scores": scores,
        "distinct_scores": len(set(scores)),
        "modal_score_share": (max(scores.count(x) for x in scores) / n) if n else None,
        "near_duplicates": sum(iou(a, b) >= 0.5 for a, b in itertools.combinations(windows, 2)),
        "unique_reason_ratio": len(set(reasons)) / n if n else None,
        "reason_similarity": mean_pairwise([_tokens(r) for r in reasons]),
        "copied_example": sum(r == V1_EXAMPLE_REASON.lower() for r in reasons),
        "labels": labels,
        "top1_hit": bool(labels) and labels[0] == target,
        "precision": labels.count(target) / n if n else None,
        "recall": len(covered & target_idx) / len(target_idx) if target_idx else None,
        "irrelevant_rate": sum(lb in data["irrelevant_labels"] for lb in labels) / n if n else None,
        "covered": sorted(covered),
        "m05_distinct_10s": m05_distinct(valid, data["duration"]),
        "evidence": [evidence_in_range(c, segs) for c in valid],
    }


# --- runner -----------------------------------------------------------------------------


def run_once(
    client: OllamaClient,
    model: str,
    variant: str,
    task: dict[str, Any],
    data: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    transcript = to_transcript(data)
    prompt = build_full_prompt(variant, transcript, task["instruction"], 20)
    started = time.perf_counter()
    try:
        response = client.generate(prompt, model=model, options=options, format="json" if JSON_MODE[variant] else "")
    except AIError as e:  # e.g. timeout: recorded as a failed run, the benchmark continues
        response = f"<inference error: {e}>"
    seconds = time.perf_counter() - started
    record: dict[str, Any] = {"model": model, "variant": variant, "task": task["id"], "seconds": seconds,
                              "response": response}
    return score_response(record, data)


def score_response(record: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """(Re)compute all metrics from the raw model response, so saved results can be rescored."""
    record = {k: record[k] for k in ("model", "variant", "task", "seconds", "response")}
    target = next(t["target"] for t in data["tasks"] if t["id"] == record["task"])
    try:
        raw = prompts.parse_ai_response(record["response"], 20)
    except (ValueError, TypeError) as e:
        record.update(parse_error=str(e)[:200], returned=0, valid=0)
        return record
    if record["variant"] in GROUNDED:
        validator = AIReasoningService(AIReasoningConfig(OllamaConfig(model=record["model"])))
        valid, rejected = validator._validate_and_create_candidates(raw, to_transcript(data))  # live M03
    else:
        valid, rejected = legacy_validate(raw, data["duration"]), []
    record.update(score_run(raw, valid, data, target))
    record.update(grounding_stats(raw, valid, rejected))
    return record


def legacy_validate(raw: list[dict[str, Any]], duration: float) -> list[ClipCandidate]:
    """M07 M03 validation, for the pre-grounding variants: the model's own times are the location."""
    out = []
    for c in raw:
        try:
            start, end, score = float(c.get("start", -1)), float(c.get("end", -1)), float(c.get("score", -1))
            reason = str(c.get("reason", "")).strip()
            if 0 <= start < end <= duration and reason and 0.0 <= score <= 1.0:
                out.append(ClipCandidate(start=start, end=end, reason=reason, score=score))
        except (ValueError, TypeError, AttributeError):
            continue
    return sorted(out, key=lambda x: (-x.score, x.start))


def grounding_stats(raw: list[dict[str, Any]], valid: list[ClipCandidate], rejected: list[str]) -> dict[str, Any]:
    """How quotes fared, and how often the model's own times disagreed with the grounded location."""
    with_ai_time = [c for c in valid if c.ai_start is not None and c.ai_end is not None]
    return {
        "quoted": sum(bool(str(c.get("quote", "")).strip()) for c in raw if isinstance(c, dict)),
        "not_found": sum(r.startswith("quote not found") for r in rejected),
        "ambiguous": sum(r.startswith("ambiguous") for r in rejected),
        "too_short": sum(r.startswith("quote too short") for r in rejected),
        "rejected": len(rejected),
        # Grounded candidates whose claimed times miss the quote's real position (what M08 corrects).
        "ai_time_wrong": sum(not (c.ai_start < c.end and c.start < c.ai_end) for c in with_ai_time),  # type: ignore[operator]
        "ai_time_checked": len(with_ai_time),
    }


def _mean(values: list[Any]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    return statistics.fmean(nums) if nums else None


def _fmt(value: float | None, digits: int = 2) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _sum(records: list[dict[str, Any]], key: str) -> int:
    return sum(r.get(key, 0) for r in records)


def _evidence(records: list[dict[str, Any]]) -> str:
    checked = [e for r in records for e in r.get("evidence", []) if e is not None]
    return f"{sum(checked)}/{len(checked)}" if checked else "-"


def summarize(records: list[dict[str, Any]]) -> str:
    rows = [
        (
            "| model | prompt | task | runs | parse ok | s/run | returned | valid | aligned | distinct scores "
            "| modal score share | near-dup pairs | unique reasons | top-1 hit | precision | recall | irrelevant "
            "| M05 10 s clips | evidence in range | run-to-run Jaccard | identical outputs "
            "| quoted | not found | ambiguous | too short | AI time wrong |"
        ),
        "|" + "---|" * 26,
    ]
    key = lambda r: (r["model"], r["variant"], r["task"])
    for (model, variant, task), group in itertools.groupby(sorted(records, key=key), key=key):
        runs = list(group)
        ok = [r for r in runs if "parse_error" not in r]
        responses = [r["response"] for r in runs]
        identical = max(responses.count(x) for x in responses)
        rows.append(
            f"| {model} | {variant} | {task} | {len(runs)} | {len(ok)}/{len(runs)} "
            f"| {_fmt(_mean([r['seconds'] for r in runs]), 1)} "
            f"| {_fmt(_mean([r['returned'] for r in runs]), 1)} | {_fmt(_mean([r['valid'] for r in runs]), 1)} "
            f"| {_fmt(_mean([r['aligned'] for r in ok]), 1)} | {_fmt(_mean([r['distinct_scores'] for r in ok]), 1)} "
            f"| {_fmt(_mean([r['modal_score_share'] for r in ok]))} "
            f"| {_fmt(_mean([r['near_duplicates'] for r in ok]), 1)} "
            f"| {_fmt(_mean([r['unique_reason_ratio'] for r in ok]))} "
            f"| {sum(r['top1_hit'] for r in ok)}/{len(runs)} | {_fmt(_mean([r['precision'] for r in ok]))} "
            f"| {_fmt(_mean([r['recall'] for r in ok]))} | {_fmt(_mean([r['irrelevant_rate'] for r in ok]))} "
            f"| {_fmt(_mean([r['m05_distinct_10s'] for r in ok]), 1)} | {_evidence(ok)} "
            f"| {_fmt(mean_pairwise([set(r['covered']) for r in ok]))} | {identical}/{len(runs)} "
            f"| {_sum(ok, 'quoted')} | {_sum(ok, 'not_found')} | {_sum(ok, 'ambiguous')} | {_sum(ok, 'too_short')} "
            f"| {_sum(ok, 'ai_time_wrong')}/{_sum(ok, 'ai_time_checked')} |"
        )
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", nargs="+", default=["qwen2.5:0.5b", "qwen2.5:3b"])
    parser.add_argument("--variants", nargs="+", default=["v1", "m08"], choices=sorted(PROMPTS))
    parser.add_argument("--tasks", nargs="+", help="task ids from dataset.json (default: all)")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.1, help="M03 default is 0.1")
    parser.add_argument("--seed", type=int, help="fixed Ollama seed (default: none, like M03)")
    parser.add_argument("--label", default="run", help="name for the raw results file")
    parser.add_argument("--summarize", nargs="+", type=Path, metavar="RESULTS_JSON",
                        help="rescore saved result files instead of running models")
    args = parser.parse_args()

    data = load_dataset()
    if args.summarize:
        saved = [r for f in args.summarize for r in json.loads(f.read_text(encoding="utf-8"))["records"]]
        print(summarize([score_response(r, data) for r in saved]))
        return
    tasks = [t for t in data["tasks"] if not args.tasks or t["id"] in args.tasks]
    # Same generation options as M03 (num_predict cap since M08).
    options: dict[str, Any] = {"temperature": args.temperature, "num_predict": DEFAULT_MAX_OUTPUT_TOKENS}
    if args.seed is not None:
        options["seed"] = args.seed
    client = OllamaClient(OllamaConfig.from_env())
    records = []
    for model, variant, task in itertools.product(args.models, args.variants, tasks):
        for i in range(args.runs):
            record = run_once(client, model, variant, task, data, options)
            records.append(record)
            print(f"{model} {variant} {task['id']} run {i + 1}: {record['seconds']:.1f}s "
                  f"valid={record.get('valid')} labels={record.get('labels', record.get('parse_error'))}", flush=True)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{args.label}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"options": options, "records": records}, indent=2), encoding="utf-8")
    print(f"\nRaw results: {out}\n\n{summarize(records)}")


if __name__ == "__main__":
    main()
