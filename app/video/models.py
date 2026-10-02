from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


def _check_number(name: str, value: object, *, allow_zero: bool) -> None:
    """Reject non-numbers, bools, NaN, infinity, negatives (and zero unless allowed)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {value!r}")  # noqa: TRY004 - one error type for callers
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite, got {value}")
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{name} must be {'>= 0' if allow_zero else '> 0'}, got {value}")


@dataclass(frozen=True)
class VideoInfo:
    """Probed media file information (built from ffprobe, never raw output)."""

    path: str
    format: str
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None
    has_video: bool
    has_audio: bool

    def __post_init__(self) -> None:
        if not self.path:
            raise ValueError("path cannot be empty")
        if not self.format:
            raise ValueError("format cannot be empty")
        _check_number("duration", self.duration, allow_zero=False)
        _check_number("width", self.width, allow_zero=True)
        _check_number("height", self.height, allow_zero=True)
        if self.has_video:
            if self.width == 0 or self.height == 0:
                raise ValueError("width/height must be > 0 when has_video is True")
            _check_number("fps", self.fps, allow_zero=False)
            if not self.video_codec:
                raise ValueError("video_codec cannot be empty when has_video is True")
        if self.has_audio and not self.audio_codec:
            raise ValueError("audio_codec cannot be empty when has_audio is True")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VideoInfo:
        return cls(**data)


@dataclass(frozen=True)
class ClipRequest:
    """Request for extracting [start, start + duration) seconds from a video."""

    input_path: str
    output_path: str
    start: float
    duration: float

    def __post_init__(self) -> None:
        if not self.input_path:
            raise ValueError("input_path cannot be empty")
        if not self.output_path:
            raise ValueError("output_path cannot be empty")
        _check_number("start", self.start, allow_zero=True)
        _check_number("duration", self.duration, allow_zero=False)

    @property
    def end(self) -> float:
        return self.start + self.duration

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClipRequest:
        return cls(**data)


@dataclass(frozen=True)
class ProcessedVideo:
    """A validated clip written to output_path."""

    input_path: str
    output_path: str
    start: float
    duration: float
    actual_duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None
    file_size: int

    def __post_init__(self) -> None:
        if not self.input_path:
            raise ValueError("input_path cannot be empty")
        if not self.output_path:
            raise ValueError("output_path cannot be empty")
        _check_number("start", self.start, allow_zero=True)
        _check_number("duration", self.duration, allow_zero=False)
        _check_number("actual_duration", self.actual_duration, allow_zero=False)
        _check_number("file_size", self.file_size, allow_zero=False)

    @property
    def has_audio(self) -> bool:
        return self.audio_codec is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProcessedVideo:
        return cls(**data)
