from __future__ import annotations

from .exceptions import SourceTooShortError
from .models import ClipWindow

# Float slack only; a source genuinely shorter than the clip is an error.
_EPSILON = 1e-6


def compute_window(cand_start: float, cand_end: float, duration: float, source_duration: float) -> ClipWindow:
    """Exact-duration window centered on the candidate, shifted to stay inside the source.

    Shorter candidates gain context evenly on both sides; longer candidates keep
    their middle `duration` seconds. A window that would start before 0 is moved
    forward, one past the end is moved back. The length is never reduced.
    The start is rounded to whole milliseconds (far below one frame) before clamping.
    """
    if duration > source_duration + _EPSILON:
        raise SourceTooShortError(source_duration, duration)
    center = (cand_start + cand_end) / 2.0
    start = min(max(round(center - duration / 2.0, 3), 0.0), source_duration - duration)
    start = max(start, 0.0)  # source_duration within epsilon of duration
    return ClipWindow(start=start, end=start + duration)


def iou(a: ClipWindow, b: ClipWindow) -> float:
    """Intersection over union of two time ranges (0 = disjoint, 1 = identical)."""
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    union = a.duration + b.duration - inter
    return inter / union if union > 0 else 0.0
