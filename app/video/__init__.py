from __future__ import annotations

from .exceptions import (
    ClipDurationError,
    FFmpegExecutionError,
    FFmpegNotFoundError,
    FFprobeNotFoundError,
    InvalidClipRequestError,
    InvalidVideoError,
    OutputAlreadyExistsError,
    OutputValidationError,
    UnsupportedFormatError,
    VideoProcessingError,
)
from .ffmpeg import FFmpegRunner
from .models import ClipRequest, ProcessedVideo, VideoInfo
from .probe import SUPPORTED_EXTENSIONS, probe_video
from .service import (
    DURATION_TOLERANCE_SECONDS,
    VideoService,
    duration_tolerance,
    extract_clip,
    safe_output_path,
)

__all__ = [
    "DURATION_TOLERANCE_SECONDS",
    "SUPPORTED_EXTENSIONS",
    "ClipDurationError",
    "ClipRequest",
    "FFmpegExecutionError",
    "FFmpegNotFoundError",
    "FFmpegRunner",
    "FFprobeNotFoundError",
    "InvalidClipRequestError",
    "InvalidVideoError",
    "OutputAlreadyExistsError",
    "OutputValidationError",
    "ProcessedVideo",
    "UnsupportedFormatError",
    "VideoInfo",
    "VideoProcessingError",
    "VideoService",
    "duration_tolerance",
    "extract_clip",
    "probe_video",
    "safe_output_path",
]
