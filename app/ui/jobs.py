from __future__ import annotations

import logging
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from app.ai.exceptions import OllamaModelUnavailableError, OllamaUnavailableError
from app.clipping import (
    AnalysisStageError,
    ClipGenerationError,
    ClipGenerationResult,
    ClipJobRequest,
    ClipRenderError,
    InsufficientCandidatesError,
    InvalidJobRequestError,
    JobStatus,
    OutputVerificationError,
    SourceTooShortError,
    TranscriptionStageError,
)
from app.video import FFmpegNotFoundError, FFprobeNotFoundError, VideoProcessingError

logger = logging.getLogger(__name__)

JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
CLIP_NAME_RE = re.compile(r"^clip_\d{3}\.mp4$")


class ClipService(Protocol):
    def generate(self, request: ClipJobRequest) -> ClipGenerationResult: ...


# Builds an M05 service that reports its stages to the given callback.
ServiceFactory = Callable[[Callable[[JobStatus, str], None]], ClipService]


def new_job_id() -> str:
    return uuid.uuid4().hex


def is_job_id(value: str) -> bool:
    return bool(JOB_ID_RE.match(value))


@dataclass
class Job:
    id: str
    original_name: str
    status: JobStatus = JobStatus.VALIDATING
    error: str | None = None
    result: ClipGenerationResult | None = None
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    thread: threading.Thread | None = None

    @property
    def done(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED)

    @property
    def elapsed(self) -> float:
        return (self.finished or time.monotonic()) - self.started

    def clip_names(self) -> set[str]:
        return {Path(c.path).name for c in self.result.clips} if self.result else set()


class JobStore:
    """In-memory job table. One job runs at a time: the CPU pipeline is sequential anyway."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def add_if_idle(self, job: Job) -> bool:
        with self._lock:
            if any(not j.done for j in self._jobs.values()):
                return False
            self._jobs[job.id] = job
            return True


def run_job(
    job: Job, request: ClipJobRequest, upload_dir: Path, output_dir: Path, factory: ServiceFactory
) -> None:
    """Run M05 for one job. The upload is always deleted; a failed job leaves no output dir."""

    def on_status(status: JobStatus, detail: str) -> None:
        if status not in (JobStatus.COMPLETED, JobStatus.FAILED):  # set below, together with result/error
            job.status = status

    try:
        job.result = factory(on_status).generate(request)
        job.status = JobStatus.COMPLETED
    except Exception as e:
        if isinstance(e, ClipGenerationError):
            logger.warning("Job %s failed during %s: %s", job.id, e.stage.value, e)
        else:
            logger.exception("Job %s crashed", job.id)
        job.error = friendly_error(e)
        job.status = JobStatus.FAILED
        shutil.rmtree(output_dir, ignore_errors=True)
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)
        job.finished = time.monotonic()


def friendly_error(e: BaseException) -> str:
    """User-facing text only: never paths, tracebacks or raw tool output."""
    cause = e.__cause__
    if isinstance(e, SourceTooShortError):
        return (
            f"The video is {e.source_duration:.1f} seconds long, shorter than the requested "
            f"clip duration of {e.clip_duration:g} seconds."
        )
    if isinstance(e, InsufficientCandidatesError):
        return (
            f"Only {e.found} sufficiently distinct moments were found, but {e.requested} were requested. "
            "Try fewer clips, a shorter duration or a broader focus. No clips were generated."
        )
    if isinstance(e, TranscriptionStageError):
        return "Transcription failed. Check that the video has clear speech and that faster-whisper is installed."
    if isinstance(e, AnalysisStageError):
        if isinstance(cause, OllamaModelUnavailableError):
            return f"The Qwen model is unavailable. Run: ollama pull {cause.model_name}"
        if isinstance(cause, OllamaUnavailableError):
            return "Ollama is not running. Start Ollama and try again."
        return "The local AI analysis failed. Please try again."
    if isinstance(e, (ClipRenderError, OutputVerificationError)):
        return f"Video processing failed while generating clip {e.index}. No clips were kept."
    if isinstance(e, InvalidJobRequestError):
        if cause:
            return friendly_video_error(cause)
        if "no audio" in str(e):
            return "The video has no audio track. Speech is needed to find moments."
        return "The request could not be processed. Please check the video and try again."
    if isinstance(e, VideoProcessingError):
        return friendly_video_error(e)
    return "An unexpected error occurred. See the server log for details."


def friendly_video_error(e: BaseException) -> str:
    if isinstance(e, (FFmpegNotFoundError, FFprobeNotFoundError)):
        return "FFmpeg is not installed or not on PATH."
    return "The uploaded file could not be read as a supported video (MP4, MKV, MOV, AVI, WebM)."
