from __future__ import annotations


class VideoProcessingError(Exception):
    """Base exception for video processing errors."""


class FFmpegNotFoundError(VideoProcessingError):
    """Raised when FFmpeg is not available in PATH."""

    def __init__(self) -> None:
        super().__init__(
            "FFmpeg not found in PATH. Please install FFmpeg and ensure it's accessible."
        )


class FFprobeNotFoundError(VideoProcessingError):
    """Raised when FFprobe is not available in PATH."""

    def __init__(self) -> None:
        super().__init__(
            "FFprobe not found in PATH. Please install FFmpeg (includes ffprobe) and ensure it's accessible."
        )


class InvalidVideoError(VideoProcessingError):
    """Raised when the video file is invalid, corrupt, or unsupported."""

    def __init__(self, path: str, reason: str = "") -> None:
        self.path = path
        msg = f"Invalid video file: {path}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


class InvalidClipRequestError(VideoProcessingError):
    """Raised when a clip request has invalid parameters."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Invalid clip request: {message}")


class ClipDurationError(VideoProcessingError):
    """Raised when the requested clip duration exceeds the source video duration."""

    def __init__(self, requested_start: float, requested_duration: float, source_duration: float) -> None:
        self.requested_start = requested_start
        self.requested_duration = requested_duration
        self.source_duration = source_duration
        super().__init__(
            f"Clip exceeds source duration: start={requested_start}, duration={requested_duration}, "
            f"source_duration={source_duration}"
        )


class OutputValidationError(VideoProcessingError):
    """Raised when the output video does not meet validation criteria."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Output validation failed: {message}")


class FFmpegExecutionError(VideoProcessingError):
    """Raised when FFmpeg fails to process the video."""

    def __init__(self, path: str, stderr: str, returncode: int) -> None:
        self.path = path
        self.stderr = stderr
        self.returncode = returncode
        super().__init__(
            # FFmpeg prints the actual error last; keep the tail only.
            f"FFmpeg failed (exit code {returncode}) for {path}: {stderr.strip()[-500:]}"
        )


class OutputAlreadyExistsError(VideoProcessingError):
    """Raised when output file already exists and overwrite is not allowed."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(
            f"Output file already exists: {path}. Use overwrite=True to replace."
        )


class UnsupportedFormatError(VideoProcessingError):
    """Raised when the video format is not supported."""

    def __init__(self, path: str, format_name: str = "") -> None:
        self.path = path
        self.format_name = format_name
        msg = f"Unsupported video format: {path}"
        if format_name:
            msg += f" (detected: {format_name})"
        super().__init__(msg)