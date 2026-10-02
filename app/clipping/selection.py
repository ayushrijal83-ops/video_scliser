from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass

from app.ai.models import ClipCandidate

from .exceptions import InsufficientCandidatesError
from .models import ClipWindow
from .windows import compute_window, iou

logger = logging.getLogger(__name__)

# Two final clips may share at most this IoU. For equal-length clips, IoU 0.2
# means they share at most 1/3 of their length (10 s of a 30 s clip).
MAX_WINDOW_IOU = 0.2
_EPSILON = 1e-6


@dataclass(frozen=True)
class SelectedMoment:
    rank: int
    candidate: ClipCandidate
    window: ClipWindow


def _is_valid(c: ClipCandidate, source_duration: float) -> bool:
    values = (c.start, c.end, c.score)
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in values):
        return False
    return (
        0.0 <= c.start < source_duration
        and c.start < c.end <= source_duration + _EPSILON
        and 0.0 <= c.score <= 1.0
    )


def normalize_candidates(candidates: Iterable[ClipCandidate], source_duration: float) -> list[ClipCandidate]:
    """Drop candidates that are invalid against the real source (M03 checks the transcript only)."""
    candidates = list(candidates)
    valid = [c for c in candidates if _is_valid(c, source_duration)]
    if len(valid) < len(candidates):
        logger.warning("Dropped %d invalid AI candidates", len(candidates) - len(valid))
    return valid


def rank_candidates(candidates: Iterable[ClipCandidate], clip_duration: float) -> list[ClipCandidate]:
    """Score desc, then candidate length closest to clip_duration, then start, then end."""
    return sorted(candidates, key=lambda c: (-c.score, abs(c.duration - clip_duration), c.start, c.end))


def select_moments(
    candidates: Iterable[ClipCandidate],
    count: int,
    clip_duration: float,
    source_duration: float,
    max_iou: float = MAX_WINDOW_IOU,
) -> list[SelectedMoment]:
    """Greedily take the best-ranked candidates whose final windows stay distinct.

    Raises InsufficientCandidatesError rather than duplicating or inventing moments.
    """
    candidates = list(candidates)
    ranked = rank_candidates(normalize_candidates(candidates, source_duration), clip_duration)
    selected: list[SelectedMoment] = []
    for cand in ranked:
        window = compute_window(cand.start, cand.end, clip_duration, source_duration)
        if all(iou(window, s.window) <= max_iou for s in selected):
            selected.append(SelectedMoment(rank=len(selected) + 1, candidate=cand, window=window))
            if len(selected) == count:
                return selected
    raise InsufficientCandidatesError(found=len(selected), requested=count, returned=len(candidates))
