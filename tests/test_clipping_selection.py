from __future__ import annotations

import math
from typing import Any

import pytest

from app.ai.models import ClipCandidate
from app.clipping.exceptions import InsufficientCandidatesError, SourceTooShortError
from app.clipping.models import (
    MAX_CLIP_COUNT,
    MAX_INSTRUCTION_CHARS,
    ClipJobRequest,
    ClipWindow,
)
from app.clipping.selection import normalize_candidates, rank_candidates, select_moments
from app.clipping.windows import compute_window, iou


def cand(start: float, end: float, score: float = 0.5, reason: str = "r") -> ClipCandidate:
    return ClipCandidate(start=start, end=end, reason=reason, score=score)


def bad_cand(**values: Any) -> ClipCandidate:
    """Bypass ClipCandidate validation to model what a buggy upstream could hand us."""
    c = cand(1.0, 2.0)
    for k, v in values.items():
        object.__setattr__(c, k, v)
    return c


class TestRequest:
    def req(self, **kw: Any) -> ClipJobRequest:
        data: dict[str, Any] = {"input_path": "in.mp4", "output_dir": "out", "clip_count": 3,
                                "clip_duration": 30.0, "instruction": "funny moments"}
        data.update(kw)
        return ClipJobRequest(**data)

    def test_valid(self) -> None:
        assert self.req().clip_count == 3

    def test_bounds_accepted(self) -> None:
        assert self.req(clip_count=MAX_CLIP_COUNT, clip_duration=1.0, instruction="x" * MAX_INSTRUCTION_CHARS)

    @pytest.mark.parametrize("count", [0, -1, MAX_CLIP_COUNT + 1, 10_000, 2.0, True, "3"])
    def test_bad_count(self, count: Any) -> None:
        with pytest.raises(ValueError, match="clip_count"):
            self.req(clip_count=count)

    @pytest.mark.parametrize("duration", [0.0, -5.0, math.nan, math.inf, -math.inf, 0.5, 601.0, "30", None])
    def test_bad_duration(self, duration: Any) -> None:
        with pytest.raises(ValueError, match="clip_duration"):
            self.req(clip_duration=duration)

    @pytest.mark.parametrize("instruction", ["", "   ", "x" * (MAX_INSTRUCTION_CHARS + 1)])
    def test_bad_instruction(self, instruction: str) -> None:
        with pytest.raises(ValueError, match="instruction"):
            self.req(instruction=instruction)

    def test_empty_paths(self) -> None:
        with pytest.raises(ValueError):
            self.req(input_path="")
        with pytest.raises(ValueError):
            self.req(output_dir="")


class TestWindow:
    def test_centered_on_candidate(self) -> None:
        w = compute_window(72.5, 91.2, 30.0, 600.0)
        assert w.start == pytest.approx(66.85) and w.end == pytest.approx(96.85)
        assert w.duration == pytest.approx(30.0)

    def test_start_rounded_to_milliseconds(self) -> None:
        # (2.5 + 10.6) / 2 - 5 = 1.5499999999999998 in binary floating point
        w = compute_window(2.5, 10.6, 10.0, 70.0)
        assert w.start == 1.55 and w.end == pytest.approx(11.55)

    def test_short_candidate_gets_context_both_sides(self) -> None:
        w = compute_window(100.0, 104.0, 30.0, 600.0)
        assert (w.start, w.end) == (87.0, 117.0)

    def test_long_candidate_keeps_middle(self) -> None:
        w = compute_window(100.0, 200.0, 30.0, 600.0)
        assert (w.start, w.end) == (135.0, 165.0)

    def test_near_start_shifts_forward(self) -> None:
        assert compute_window(0.0, 10.0, 30.0, 100.0) == ClipWindow(0.0, 30.0)

    def test_near_end_shifts_back(self) -> None:
        assert compute_window(90.0, 100.0, 30.0, 100.0) == ClipWindow(70.0, 100.0)

    def test_source_exactly_clip_length(self) -> None:
        assert compute_window(10.0, 20.0, 30.0, 30.0) == ClipWindow(0.0, 30.0)

    def test_source_shorter_than_clip_fails(self) -> None:
        with pytest.raises(SourceTooShortError):
            compute_window(0.0, 5.0, 30.0, 29.9)

    @pytest.mark.parametrize("source", [100.0, 59.999999, 33.333333333])
    def test_float_windows_stay_inside_source_with_exact_length(self, source: float) -> None:
        for start in (0.0, 0.1, 13.7, source / 3, source - 0.3):
            w = compute_window(start, min(start + 0.2, source), 30.0 if source >= 30 else source, source)
            assert w.start >= 0.0
            assert w.end <= source + 1e-9
            assert w.duration == pytest.approx(30.0 if source >= 30 else source, abs=1e-9)


class TestIoU:
    def test_values(self) -> None:
        a = ClipWindow(0.0, 30.0)
        assert iou(a, ClipWindow(30.0, 60.0)) == 0.0
        assert iou(a, a) == 1.0
        assert iou(a, ClipWindow(15.0, 45.0)) == pytest.approx(15 / 45)


class TestNormalize:
    def test_keeps_valid(self) -> None:
        assert normalize_candidates([cand(1, 2), cand(99, 100)], 100.0) == [cand(1, 2), cand(99, 100)]

    @pytest.mark.parametrize(
        "values",
        [
            {"start": -1.0}, {"start": math.nan}, {"start": math.inf}, {"end": math.nan},
            {"end": 1.0}, {"end": 0.5}, {"start": 100.0, "end": 101.0}, {"end": 100.5},
            {"score": 1.5}, {"score": -0.1}, {"score": math.nan}, {"start": True},
        ],
    )
    def test_rejects_invalid(self, values: dict[str, Any]) -> None:
        assert normalize_candidates([bad_cand(**values)], 100.0) == []


class TestRanking:
    def test_score_descending(self) -> None:
        ranked = rank_candidates([cand(0, 10, 0.2), cand(50, 60, 0.9), cand(100, 110, 0.5)], 10.0)
        assert [c.score for c in ranked] == [0.9, 0.5, 0.2]

    def test_equal_scores_prefer_length_closest_to_request_then_start(self) -> None:
        a, b, c = cand(200, 230, 0.7), cand(0, 5, 0.7), cand(100, 130, 0.7)
        assert rank_candidates([a, b, c], 30.0) == [c, a, b]

    def test_deterministic_regardless_of_input_order(self) -> None:
        cands = [cand(i * 40, i * 40 + 10 + i % 3, round(0.1 * (i % 4), 1)) for i in range(12)]
        expected = rank_candidates(cands, 30.0)
        assert rank_candidates(list(reversed(cands)), 30.0) == expected
        assert rank_candidates(sorted(cands, key=lambda c: c.reason + str(c.end)), 30.0) == expected


class TestSelection:
    def test_exact_count_from_distinct_candidates(self) -> None:
        cands = [cand(i * 60 + 10, i * 60 + 20, 0.5 + i / 100) for i in range(8)]
        picked = select_moments(cands, 5, 30.0, 600.0)
        assert len(picked) == 5
        assert [m.rank for m in picked] == [1, 2, 3, 4, 5]
        assert [m.candidate.score for m in picked] == sorted((c.score for c in cands), reverse=True)[:5]

    def test_no_overlap_all_kept(self) -> None:
        picked = select_moments([cand(0, 30), cand(30, 60), cand(60, 90)], 3, 30.0, 90.0)
        assert len(picked) == 3

    def test_partial_overlap_within_threshold_kept(self) -> None:
        # windows 0-30 and 25-55 share 5 s: IoU 5/55 = 0.09
        picked = select_moments([cand(0, 30, 0.9), cand(25, 55, 0.8)], 2, 30.0, 100.0)
        assert len(picked) == 2

    def test_heavy_overlap_keeps_stronger(self) -> None:
        a, b, c = cand(60, 90, 0.7), cand(65, 95, 0.9), cand(70, 100, 0.8)
        with pytest.raises(InsufficientCandidatesError) as exc:
            select_moments([a, b, c], 2, 30.0, 200.0)
        assert exc.value.found == 1
        assert select_moments([a, b, c], 1, 30.0, 200.0)[0].candidate == b

    def test_duplicates_never_produce_two_clips(self) -> None:
        dup = [cand(40, 50, 0.9), cand(40, 50, 0.9), cand(40, 50, 0.9)]
        with pytest.raises(InsufficientCandidatesError) as exc:
            select_moments(dup, 2, 30.0, 300.0)
        assert (exc.value.found, exc.value.requested, exc.value.returned) == (1, 2, 3)

    def test_overlap_tie_broken_deterministically(self) -> None:
        a, b = cand(100, 130, 0.8), cand(105, 135, 0.8)  # same score and length
        assert select_moments([b, a], 1, 30.0, 300.0)[0].candidate == a  # earlier start wins

    def test_insufficient_candidates_message(self) -> None:
        with pytest.raises(InsufficientCandidatesError, match="Only 2 sufficiently distinct .* requested 10"):
            select_moments([cand(0, 10), cand(100, 110)], 10, 30.0, 300.0)

    def test_no_candidates(self) -> None:
        with pytest.raises(InsufficientCandidatesError):
            select_moments([], 1, 30.0, 300.0)

    def test_invalid_candidates_do_not_count(self) -> None:
        with pytest.raises(InsufficientCandidatesError) as exc:
            select_moments([cand(10, 20), bad_cand(end=math.nan)], 2, 30.0, 300.0)
        assert exc.value.found == 1

    def test_windows_have_exact_requested_length(self) -> None:
        for m in select_moments([cand(0, 3), cand(290, 300), cand(140, 260)], 3, 45.5, 300.0):
            assert m.window.duration == pytest.approx(45.5)
            assert 0 <= m.window.start and m.window.end <= 300.0 + 1e-9
