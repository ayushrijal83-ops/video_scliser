from __future__ import annotations

from .exceptions import (
    AudioExtractionError,
    EmptyAudioError,
    FFmpegExecutionError,
    FFmpegNotFoundError,
    InputFileNotFoundError,
    InvalidModelConfigurationError,
    ModelNotAvailableError,
    TranscriptionError,
    TranscriptionFailedError,
    UnsupportedMediaFormatError,
)
from .models import TranscriptionResult, TranscriptSegment, WordTimestamp
from .service import TranscriptionService, transcribe_file

__all__ = [
    "AudioExtractionError",
    "EmptyAudioError",
    "FFmpegExecutionError",
    "FFmpegNotFoundError",
    "InputFileNotFoundError",
    "InvalidModelConfigurationError",
    "ModelNotAvailableError",
    "TranscriptSegment",
    "TranscriptionError",
    "TranscriptionFailedError",
    "TranscriptionResult",
    "TranscriptionService",
    "UnsupportedMediaFormatError",
    "WordTimestamp",
    "transcribe_file",
]

__version__ = "0.2.0"