from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

# Request limits (V1). They protect a CPU-only machine from accidental huge jobs:
# M03 returns at most 20 candidates by default, so more clips could never be distinct.
MAX_CLIP_COUNT = 20
MIN_CLIP_DURATION = 1.0
MAX_CLIP_DURATION = 600.0
MAX_INSTRUCTION_CHARS = 500


class JobStatus(str, Enum):
    VALIDATING = "validating"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    SELECTING = "selecting"
    GENERATING = "generating"
    VALIDATING_OUTPUTS = "validating_outputs"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class ClipJobRequest:
    """'Make clip_count clips of exactly clip_duration seconds about instruction.'"""

    input_path: str
    output_dir: str
    clip_count: int
    clip_duration: float
    instruction: str

    def __post_init__(self) -> None:
        if not self.input_path:
            raise ValueError("input_path cannot be empty")
        if not self.output_dir:
            raise ValueError("output_dir cannot be empty")
        if isinstance(self.clip_count, bool) or not isinstance(self.clip_count, int):
            raise ValueError(f"clip_count must be an integer, got {self.clip_count!r}")  # noqa: TRY004
        if not 1 <= self.clip_count <= MAX_CLIP_COUNT:
            raise ValueError(f"clip_count must be between 1 and {MAX_CLIP_COUNT}, got {self.clip_count}")
        d = self.clip_duration
        if isinstance(d, bool) or not isinstance(d, (int, float)) or not math.isfinite(d):
            raise ValueError(f"clip_duration must be a finite number, got {d!r}")
        if not MIN_CLIP_DURATION <= d <= MAX_CLIP_DURATION:
            raise ValueError(
                f"clip_duration must be between {MIN_CLIP_DURATION} and {MAX_CLIP_DURATION} seconds, got {d}"
            )
        if not isinstance(self.instruction, str) or not self.instruction.strip():
            raise ValueError("instruction cannot be empty")
        if len(self.instruction) > MAX_INSTRUCTION_CHARS:
            raise ValueError(f"instruction must be at most {MAX_INSTRUCTION_CHARS} characters")


@dataclass(frozen=True)
class ClipWindow:
    """Final [start, end) cut in source seconds; end - start == requested duration."""

    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class GeneratedClip:
    index: int
    path: str
    start: float
    end: float
    duration: float
    actual_duration: float
    score: float
    reason: str
    title: str
    candidate_start: float
    candidate_end: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ClipGenerationResult:
    input_path: str
    output_dir: str
    instruction: str
    requested_count: int
    requested_duration: float
    clips: tuple[GeneratedClip, ...]
    candidates_returned: int
    candidates_valid: int
    model_name: str
    status: JobStatus = JobStatus.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data
