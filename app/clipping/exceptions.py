from __future__ import annotations

from .models import JobStatus

_MAX_DETAIL_CHARS = 300


def _short(detail: object) -> str:
    """Underlying errors can carry transcripts or model output; keep messages bounded."""
    text = str(detail)
    return text if len(text) <= _MAX_DETAIL_CHARS else text[:_MAX_DETAIL_CHARS] + "..."


class ClipGenerationError(Exception):
    """Base error; `stage` is the pipeline step that failed."""

    stage: JobStatus = JobStatus.VALIDATING

    def __init__(self, message: str) -> None:
        super().__init__(_short(message))


class InvalidJobRequestError(ClipGenerationError):
    """Bad request values, unreadable source, or an output name that already exists."""


class SourceTooShortError(ClipGenerationError):
    def __init__(self, source_duration: float, clip_duration: float) -> None:
        self.source_duration = source_duration
        self.clip_duration = clip_duration
        super().__init__(
            f"source video is {source_duration:.3f}s, shorter than the requested clip duration {clip_duration:.3f}s"
        )


class TranscriptionStageError(ClipGenerationError):
    stage = JobStatus.TRANSCRIBING


class AnalysisStageError(ClipGenerationError):
    stage = JobStatus.ANALYZING


class InsufficientCandidatesError(ClipGenerationError):
    stage = JobStatus.SELECTING

    def __init__(self, found: int, requested: int, returned: int) -> None:
        self.found = found
        self.requested = requested
        self.returned = returned
        super().__init__(
            f"Only {found} sufficiently distinct candidate moments were identified; requested {requested} "
            f"(AI returned {returned} candidates). No clips were generated."
        )


class ClipRenderError(ClipGenerationError):
    """M04 failed to produce a clip; all clips of this job were removed."""

    stage = JobStatus.GENERATING

    def __init__(self, index: int, detail: object) -> None:
        self.index = index
        super().__init__(f"clip {index} failed: {_short(detail)}")


class OutputVerificationError(ClipGenerationError):
    """A produced clip failed final checks; all clips of this job were removed."""

    stage = JobStatus.VALIDATING_OUTPUTS

    def __init__(self, index: int, detail: str) -> None:
        self.index = index
        super().__init__(f"clip {index} failed verification: {detail}")
