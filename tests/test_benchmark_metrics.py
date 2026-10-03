from __future__ import annotations

from app.ai.models import ClipCandidate
from app.ai.prompts import SYSTEM_PROMPT
from benchmarks.ai.run_benchmark import (
    JSON_MODE,
    PROMPT_V2,
    PROMPTS,
    build_full_prompt,
    covered_segments,
    evidence_in_range,
    jaccard,
    label_of,
    load_dataset,
    m05_distinct,
    mean_pairwise,
    score_run,
    to_transcript,
)

SEGS = [
    {"start": 0.0, "end": 10.0, "label": "filler", "text": "um okay let me share my screen"},
    {"start": 10.0, "end": 20.0, "label": "joke", "text": "why did the chicken cross the road"},
    {"start": 20.0, "end": 30.0, "label": "admin", "text": "the budget is unchanged this quarter"},
]
DATA = {"duration": 30.0, "segments": SEGS, "irrelevant_labels": ["filler", "admin"]}


def c(start: float, end: float, score: float = 0.5, reason: str = "r") -> ClipCandidate:
    return ClipCandidate(start=start, end=end, reason=reason, score=score)


def test_label_of_uses_largest_overlap() -> None:
    assert label_of(c(8, 18), SEGS) == "joke"
    assert label_of(c(0, 4), SEGS) == "filler"


def test_covered_segments_needs_half() -> None:
    assert covered_segments([c(14, 26)], SEGS) == {1, 2}
    assert covered_segments([c(16, 24)], SEGS) == set()


def test_jaccard_and_pairwise() -> None:
    assert jaccard({1, 2}, {2, 3}) == 1 / 3
    assert jaccard(set(), set()) == 1.0
    assert mean_pairwise([{1}]) is None
    assert mean_pairwise([{1}, {1}, {2}]) == 1 / 3


def test_score_run_metrics() -> None:
    valid = [c(10, 20, 0.9, "funny bit"), c(10, 19, 0.9, "funny bit"), c(20, 30, 0.4, "the budget")]
    m = score_run([{}] * 4, valid, DATA, "joke")
    assert (m["returned"], m["valid"]) == (4, 3)
    assert m["distinct_scores"] == 2 and m["modal_score_share"] == 2 / 3
    assert m["near_duplicates"] == 1
    assert m["unique_reason_ratio"] == 2 / 3
    assert m["top1_hit"] is True
    assert m["precision"] == 2 / 3 and m["recall"] == 1.0 and m["irrelevant_rate"] == 1 / 3
    assert m["aligned"] == 2  # 10-19 does not end on a segment boundary
    assert m["evidence"] == [None, None, None]  # reasons quote no segment


def test_score_run_empty() -> None:
    m = score_run([], [], DATA, "joke")
    assert m["valid"] == 0 and m["precision"] is None and m["top1_hit"] is False


def test_m05_distinct_uses_real_selection() -> None:
    assert m05_distinct([c(10, 12), c(10.5, 12.5), c(25, 27)], 30.0) == 2
    assert m05_distinct([], 30.0) == 0


def test_dataset_labels_never_reach_the_model() -> None:
    data = load_dataset()
    assert {s["label"] for s in data["segments"]} >= {t["target"] for t in data["tasks"]}
    prompt = build_full_prompt("v2", to_transcript(data), "funny moments", 20)
    assert '"label"' not in prompt and "target" not in prompt
    assert data["segments"][4]["text"] in prompt
    assert set(PROMPTS) == set(JSON_MODE) == {"v1", "v2", "v2-free", "v2-bracket"}
    assert 'start=23.0 end=34.0 text="So, quick' in prompt
    production = build_full_prompt("v1", to_transcript(data), "funny moments", 20)
    assert production.startswith(SYSTEM_PROMPT.format(max_candidates=20))  # v1 is the live M03 prompt
    assert "[23.0-34.0] So, quick" in production
    assert "[23.0-34.0] So, quick" in build_full_prompt("v2-bracket", to_transcript(data), "x", 20)


def test_v2_experiment_prompt_is_general_purpose() -> None:
    p = PROMPT_V2.lower()
    for word in ("joke", "printer", "cache", "intern", "funny", "laugh", "decision"):
        assert word not in p
    assert "0.91" not in PROMPT_V2 and "<number>" in PROMPT_V2


def test_evidence_in_range() -> None:
    segs = [{"start": 0.0, "end": 10.0, "label": "a", "text": "the quick brown fox jumps over"},
            {"start": 10.0, "end": 20.0, "label": "b", "text": "a lazy dog sleeps in the sun"}]
    assert evidence_in_range(c(0, 10, reason="quote: the quick brown fox jumps"), segs) is True
    assert evidence_in_range(c(10, 20, reason="quote: the quick brown fox jumps"), segs) is False
    assert evidence_in_range(c(0, 10, reason="something unrelated"), segs) is None
