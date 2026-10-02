from __future__ import annotations

import contextlib
import logging
import os
import tempfile
from pathlib import Path

from .exceptions import (
    ClipDurationError,
    InvalidClipRequestError,
    OutputAlreadyExistsError,
    OutputValidationError,
)
from .ffmpeg import FFmpegRunner
from .models import ClipRequest, ProcessedVideo, VideoInfo
from .probe import probe_video, validate_input_path

logger = logging.getLogger(__name__)

# Exact-duration rule (V1): |actual - requested| <= max(0.05 s, one frame).
# Re-encoding cuts audio sample-exactly, but video can only end on a frame
# boundary, so the worst case is one frame (41.7 ms at 23.976 fps). Measured on
# FFmpeg 9.0.2: max error 0.023 s at 30 fps and 23.976 fps.
DURATION_TOLERANCE_SECONDS = 0.05
# Bounds checks only allow float rounding slack, never a real overrun.
_BOUNDS_EPSILON = 1e-6

OUTPUT_SUFFIX = ".mp4"
VIDEO_ARGS = ["-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p"]
AUDIO_ARGS = ["-c:a", "aac", "-b:a", "192k"]


def duration_tolerance(fps: float) -> float:
    return max(DURATION_TOLERANCE_SECONDS, 1.0 / fps)


def safe_output_path(output_dir: str | Path, filename: str) -> Path:
    """Join a generated/user-supplied filename onto output_dir, rejecting traversal."""
    base = Path(output_dir).resolve()
    candidate = (base / filename).resolve()
    if not filename or candidate.parent != base:
        raise InvalidClipRequestError(f"unsafe output filename: {filename!r}")
    return candidate


def build_extract_args(
    input_path: Path, output_path: Path, start: float, duration: float, has_audio: bool
) -> list[str]:
    """FFmpeg argument list for a frame-accurate, re-encoded MP4 clip."""
    # -ss before -i with re-encoding is frame-accurate (decoder discards
    # pre-roll frames) and avoids decoding the whole file up to `start`.
    args = [
        "-hide_banner", "-nostdin", "-v", "error", "-y",
        "-ss", f"{start:.6f}", "-i", str(input_path), "-t", f"{duration:.6f}",
        "-map", "0:v:0",
    ]
    args += ["-map", "0:a:0", *AUDIO_ARGS] if has_audio else ["-an"]
    args += [*VIDEO_ARGS, "-movflags", "+faststart", "-f", "mp4", str(output_path)]
    return args


class VideoService:
    """Clip extraction with strict bounds checks and exact-duration verification."""

    def __init__(self, runner: FFmpegRunner | None = None) -> None:
        self._runner = runner or FFmpegRunner()

    def probe(self, input_path: str | Path) -> VideoInfo:
        return probe_video(validate_input_path(input_path), self._runner)

    def validate_clip_request(self, request: ClipRequest) -> VideoInfo:
        """Check the request against the source; returns the source VideoInfo."""
        source = self.probe(request.input_path)
        if request.start >= source.duration:
            raise InvalidClipRequestError(
                f"start ({request.start}s) must be < source duration ({source.duration}s)"
            )
        if request.end > source.duration + _BOUNDS_EPSILON:
            raise ClipDurationError(request.start, request.duration, source.duration)
        return source

    def extract_clip(
        self,
        input_path: str | Path,
        output_path: str | Path,
        start: float,
        duration: float,
        overwrite: bool = False,
    ) -> ProcessedVideo:
        try:
            request = ClipRequest(str(input_path), str(output_path), start, duration)
        except ValueError as e:
            raise InvalidClipRequestError(str(e)) from e
        return self.extract(request, overwrite=overwrite)

    def extract(self, request: ClipRequest, overwrite: bool = False) -> ProcessedVideo:
        """Extract a clip; the output exists only if it passed validation."""
        source = self.validate_clip_request(request)
        src_path = Path(source.path)
        out_path = Path(request.output_path).resolve()
        if out_path.suffix.lower() != OUTPUT_SUFFIX:
            raise InvalidClipRequestError(f"output must be an {OUTPUT_SUFFIX} file: {out_path}")
        if out_path == src_path:
            raise InvalidClipRequestError("output path must differ from input path")
        if out_path.exists() and not overwrite:
            raise OutputAlreadyExistsError(str(out_path))
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Hidden temp file in the same directory, so os.replace is atomic.
        fd, tmp_name = tempfile.mkstemp(prefix=".partial-", suffix=OUTPUT_SUFFIX, dir=out_path.parent)
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            logger.info("Extracting %.3fs @ %.3fs from %s", request.duration, request.start, src_path.name)
            self._runner.run_ffmpeg(
                build_extract_args(src_path, tmp_path, request.start, request.duration, source.has_audio),
                target=str(src_path),
            )
            result = probe_video(tmp_path, self._runner)
            self._validate_output(request, source, result)
            if out_path.exists() and not overwrite:  # appeared while encoding
                raise OutputAlreadyExistsError(str(out_path))
            os.replace(tmp_path, out_path)
        except BaseException:
            with contextlib.suppress(OSError):
                tmp_path.unlink()
            raise

        return ProcessedVideo(
            input_path=str(src_path),
            output_path=str(out_path),
            start=request.start,
            duration=request.duration,
            actual_duration=result.duration,
            width=result.width,
            height=result.height,
            fps=result.fps,
            video_codec=result.video_codec,
            audio_codec=result.audio_codec,
            file_size=out_path.stat().st_size,
        )

    @staticmethod
    def _validate_output(request: ClipRequest, source: VideoInfo, result: VideoInfo) -> None:
        if source.has_audio and not result.has_audio:
            raise OutputValidationError("source has audio but output has none")
        tolerance = duration_tolerance(source.fps)
        error = abs(result.duration - request.duration)
        if error > tolerance:
            raise OutputValidationError(
                f"output duration {result.duration:.3f}s differs from requested "
                f"{request.duration:.3f}s by {error:.3f}s (tolerance {tolerance:.3f}s)"
            )


def extract_clip(
    input_path: str | Path,
    output_path: str | Path,
    start: float,
    duration: float,
    overwrite: bool = False,
) -> ProcessedVideo:
    """One-off clip extraction using FFmpeg from PATH."""
    return VideoService().extract_clip(input_path, output_path, start, duration, overwrite)
