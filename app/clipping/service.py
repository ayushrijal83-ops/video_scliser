from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from app.ai.exceptions import AIError
from app.ai.models import ClipAnalysisResult
from app.transcription.exceptions import TranscriptionError
from app.transcription.models import TranscriptionResult
from app.video import (
    VideoProcessingError,
    VideoService,
    duration_tolerance,
    safe_output_path,
)
from app.video.models import ProcessedVideo, VideoInfo

from .exceptions import (
    AnalysisStageError,
    ClipGenerationError,
    ClipRenderError,
    InvalidJobRequestError,
    OutputVerificationError,
    SourceTooShortError,
    TranscriptionStageError,
)
from .models import ClipGenerationResult, ClipJobRequest, GeneratedClip, JobStatus
from .selection import MAX_WINDOW_IOU, SelectedMoment, select_moments

logger = logging.getLogger(__name__)

StatusCallback = Callable[[JobStatus, str], None]


class Transcriber(Protocol):
    def transcribe(self, input_path: str, language: str | None = None) -> TranscriptionResult: ...


class Analyzer(Protocol):
    def analyze(self, transcript: TranscriptionResult, instruction: str) -> ClipAnalysisResult: ...


class VideoEngine(Protocol):
    def probe(self, input_path: str | Path) -> VideoInfo: ...

    def extract_clip(
        self, input_path: str | Path, output_path: str | Path, start: float, duration: float, overwrite: bool = False
    ) -> ProcessedVideo: ...


def clip_filename(index: int) -> str:
    return f"clip_{index:03d}.mp4"


class ClipGenerationService:
    """M02 transcribe -> M03 suggest -> Python select -> M04 cut, run sequentially.

    AI suggests, Python decides, FFmpeg executes: only validated floats and
    generated filenames ever reach the video engine.
    """

    def __init__(
        self,
        transcriber: Transcriber | None = None,
        analyzer: Analyzer | None = None,
        video: VideoEngine | None = None,
        on_status: StatusCallback | None = None,
        language: str | None = None,
        max_window_iou: float = MAX_WINDOW_IOU,
    ) -> None:
        # Real services are created lazily so construction never loads models.
        self._transcriber = transcriber
        self._analyzer = analyzer
        self._video = video
        self._on_status = on_status
        self._language = language
        self._max_window_iou = max_window_iou

    def generate(self, request: ClipJobRequest) -> ClipGenerationResult:
        try:
            return self._run(request)
        except ClipGenerationError as e:
            self._status(JobStatus.FAILED, f"{e.stage.value}: {e}")
            raise

    def _run(self, request: ClipJobRequest) -> ClipGenerationResult:
        self._status(JobStatus.VALIDATING, "checking source and output paths")
        source = self._probe_source(request)
        out_dir = Path(request.output_dir).resolve()
        paths = self._plan_outputs(out_dir, request.clip_count)

        self._status(JobStatus.TRANSCRIBING, Path(source.path).name)
        transcript = self._transcribe(source.path)

        self._status(JobStatus.ANALYZING, f"{transcript.segment_count} transcript segments")
        analysis = self._analyze(transcript, request.instruction)

        self._status(JobStatus.SELECTING, f"{analysis.total_candidates} AI candidates")
        moments = select_moments(
            analysis.candidates, request.clip_count, request.clip_duration, source.duration, self._max_window_iou
        )

        clips = self._render(request, source, out_dir, paths, moments)
        self._status(JobStatus.COMPLETED, f"{len(clips)} clips in {out_dir}")
        return ClipGenerationResult(
            input_path=source.path,
            output_dir=str(out_dir),
            instruction=request.instruction,
            requested_count=request.clip_count,
            requested_duration=request.clip_duration,
            clips=tuple(clips),
            candidates_returned=analysis.total_candidates,
            candidates_valid=len(analysis.candidates),
            model_name=analysis.model_name,
        )

    def _probe_source(self, request: ClipJobRequest) -> VideoInfo:
        try:
            source = self._video_engine().probe(request.input_path)
        except VideoProcessingError as e:
            raise InvalidJobRequestError(f"cannot use source video: {e}") from e
        if request.clip_duration > source.duration:
            raise SourceTooShortError(source.duration, request.clip_duration)
        if not source.has_audio:
            raise InvalidJobRequestError("source video has no audio track; speech is needed to find moments")
        return source

    @staticmethod
    def _plan_outputs(out_dir: Path, count: int) -> list[Path]:
        if out_dir.exists() and not out_dir.is_dir():
            raise InvalidJobRequestError(f"output_dir is not a directory: {out_dir}")
        paths = [safe_output_path(out_dir, clip_filename(i)) for i in range(1, count + 1)]
        taken = [p.name for p in paths if p.exists()]
        if taken:
            raise InvalidJobRequestError(f"output files already exist in {out_dir}: {', '.join(taken)}")
        return paths

    def _transcribe(self, path: str) -> TranscriptionResult:
        try:
            return self._transcription_service().transcribe(path, language=self._language)
        except (TranscriptionError, OSError, ValueError) as e:
            raise TranscriptionStageError(f"transcription failed: {e}") from e

    def _analyze(self, transcript: TranscriptionResult, instruction: str) -> ClipAnalysisResult:
        try:
            return self._analysis_service().analyze(transcript, instruction)
        except (AIError, ValueError) as e:
            raise AnalysisStageError(f"AI analysis failed: {e}") from e

    def _render(
        self,
        request: ClipJobRequest,
        source: VideoInfo,
        out_dir: Path,
        paths: list[Path],
        moments: list[SelectedMoment],
    ) -> list[GeneratedClip]:
        """All-or-nothing: on any failure every clip of this job is removed."""
        dir_existed = out_dir.exists()
        produced: list[ProcessedVideo] = []
        try:
            self._status(JobStatus.GENERATING, f"{len(moments)} clips x {request.clip_duration}s")
            for path, moment in zip(paths, moments):
                logger.info("Clip %d/%d: %.3fs-%.3fs", moment.rank, len(moments), moment.window.start, moment.window.end)
                try:
                    produced.append(
                        self._video_engine().extract_clip(
                            source.path, path, moment.window.start, request.clip_duration, overwrite=False
                        )
                    )
                except VideoProcessingError as e:
                    raise ClipRenderError(moment.rank, e) from e

            self._status(JobStatus.VALIDATING_OUTPUTS, f"{len(produced)} clips")
            for moment, out in zip(moments, produced):
                self._verify(moment.rank, out, request.clip_duration, source)
        except BaseException:
            # Only files M04 reported as written by this job; M04 removes its own temp files.
            for out in produced:
                with contextlib.suppress(OSError):
                    Path(out.output_path).unlink(missing_ok=True)
            if not dir_existed:
                with contextlib.suppress(OSError):
                    out_dir.rmdir()  # only succeeds if we left it empty
            raise

        return [
            GeneratedClip(
                index=m.rank,
                path=out.output_path,
                start=m.window.start,
                end=m.window.end,
                duration=request.clip_duration,
                actual_duration=out.actual_duration,
                score=m.candidate.score,
                reason=m.candidate.reason,
                title=m.candidate.title,
                candidate_start=m.candidate.start,
                candidate_end=m.candidate.end,
            )
            for m, out in zip(moments, produced)
        ]

    @staticmethod
    def _verify(index: int, out: ProcessedVideo, duration: float, source: VideoInfo) -> None:
        """Re-check M04's result at the pipeline boundary before reporting success."""
        path = Path(out.output_path)
        if not path.is_file() or path.stat().st_size == 0:
            raise OutputVerificationError(index, f"missing or empty output {path.name}")
        tolerance = duration_tolerance(source.fps)
        if abs(out.actual_duration - duration) > tolerance:
            raise OutputVerificationError(
                index, f"duration {out.actual_duration:.3f}s vs requested {duration:.3f}s (tolerance {tolerance:.3f}s)"
            )
        if out.width <= 0 or out.height <= 0 or not out.video_codec:
            raise OutputVerificationError(index, "no video stream")
        if source.has_audio and out.audio_codec is None:
            raise OutputVerificationError(index, "audio missing")

    def _status(self, status: JobStatus, detail: str) -> None:
        logger.info("[%s] %s", status.value, detail)
        if self._on_status:
            self._on_status(status, detail)

    def _video_engine(self) -> VideoEngine:
        if self._video is None:
            try:
                self._video = VideoService()
            except VideoProcessingError as e:
                raise InvalidJobRequestError(str(e)) from e
        return self._video

    def _transcription_service(self) -> Transcriber:
        if self._transcriber is None:
            from app.transcription import TranscriptionService

            self._transcriber = TranscriptionService()
        return self._transcriber

    def _analysis_service(self) -> Analyzer:
        if self._analyzer is None:
            from app.ai import AIReasoningService

            self._analyzer = AIReasoningService()
        return self._analyzer
