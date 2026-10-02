from __future__ import annotations


class TranscriptionError(Exception):
    """Base exception for transcription errors."""



class InputFileNotFoundError(TranscriptionError):
    """Raised when the input media file does not exist."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"Input file not found: {path}")


class UnsupportedMediaFormatError(TranscriptionError):
    """Raised when the media format is not supported or corrupt."""

    def __init__(self, path: str, reason: str = "") -> None:
        self.path = path
        msg = f"Unsupported or corrupt media format: {path}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


class FFmpegNotFoundError(TranscriptionError):
    """Raised when FFmpeg is not available in PATH."""

    def __init__(self) -> None:
        super().__init__(
            "FFmpeg not found in PATH. Please install FFmpeg and ensure it's accessible."
        )


class FFmpegExecutionError(TranscriptionError):
    """Raised when FFmpeg fails to process the media file."""

    def __init__(self, path: str, stderr: str, returncode: int) -> None:
        self.path = path
        self.stderr = stderr
        self.returncode = returncode
        super().__init__(
            f"FFmpeg failed (exit code {returncode}) for {path}: {stderr[:500]}"
        )


class ModelNotAvailableError(TranscriptionError):
    """Raised when the transcription model is not available."""

    def __init__(self, model_name: str, reason: str = "") -> None:
        self.model_name = model_name
        msg = f"Transcription model not available: {model_name}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)


class InvalidModelConfigurationError(TranscriptionError):
    """Raised when the model configuration is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Invalid model configuration: {message}")


class TranscriptionFailedError(TranscriptionError):
    """Raised when transcription fails unexpectedly."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        self.original_error = original_error
        msg = f"Transcription failed: {message}"
        if original_error:
            msg += f" (caused by: {original_error})"
        super().__init__(msg)


class EmptyAudioError(TranscriptionError):
    """Raised when the audio contains no speech or is empty."""

    def __init__(self, path: str) -> None:
        self.path = path
        super().__init__(f"No speech detected in audio: {path}")


class AudioExtractionError(TranscriptionError):
    """Raised when audio extraction from video fails."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        super().__init__(f"Audio extraction failed for {path}: {reason}")