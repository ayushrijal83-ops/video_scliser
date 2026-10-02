from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TranscriptSegment:
    """A single transcribed segment with timestamps."""

    start: float
    end: float
    text: str
    words: list[WordTimestamp] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"start must be >= 0, got {self.start}")
        if self.end < 0:
            raise ValueError(f"end must be >= 0, got {self.end}")
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) must be >= start ({self.start})")
        if not self.text or not self.text.strip():
            raise ValueError("text cannot be empty")

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "words": [w.to_dict() for w in self.words],
        }

    @classmethod
    def from_dict(cls, data: dict) -> TranscriptSegment:
        words = [WordTimestamp.from_dict(w) for w in data.get("words", [])]
        return cls(start=data["start"], end=data["end"], text=data["text"], words=words)


@dataclass(frozen=True)
class WordTimestamp:
    """Word-level timestamp within a segment."""

    start: float
    end: float
    word: str
    probability: float = 1.0

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"start must be >= 0, got {self.start}")
        if self.end < 0:
            raise ValueError(f"end must be >= 0, got {self.end}")
        if self.end < self.start:
            raise ValueError(f"end ({self.end}) must be >= start ({self.start})")
        if not self.word or not self.word.strip():
            raise ValueError("word cannot be empty")
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError(f"probability must be in [0, 1], got {self.probability}")

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "word": self.word,
            "probability": self.probability,
        }

    @classmethod
    def from_dict(cls, data: dict) -> WordTimestamp:
        return cls(
            start=data["start"],
            end=data["end"],
            word=data["word"],
            probability=data.get("probability", 1.0),
        )


@dataclass
class TranscriptionResult:
    """Complete transcription result with metadata."""

    source_file: str
    language: str
    language_probability: float
    duration: float
    segments: list[TranscriptSegment]
    model_name: str

    def __post_init__(self) -> None:
        if not self.source_file:
            raise ValueError("source_file cannot be empty")
        if not self.language:
            raise ValueError("language cannot be empty")
        if not 0.0 <= self.language_probability <= 1.0:
            raise ValueError(f"language_probability must be in [0, 1], got {self.language_probability}")
        if self.duration < 0:
            raise ValueError(f"duration must be >= 0, got {self.duration}")
        if not self.model_name:
            raise ValueError("model_name cannot be empty")

    @property
    def full_text(self) -> str:
        return " ".join(seg.text for seg in self.segments)

    @property
    def segment_count(self) -> int:
        return len(self.segments)

    @property
    def total_words(self) -> int:
        return sum(len(seg.words) for seg in self.segments)

    def to_dict(self) -> dict:
        return {
            "source_file": self.source_file,
            "language": self.language,
            "language_probability": self.language_probability,
            "duration": self.duration,
            "model_name": self.model_name,
            "segments": [seg.to_dict() for seg in self.segments],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> TranscriptionResult:
        segments = [TranscriptSegment.from_dict(s) for s in data.get("segments", [])]
        return cls(
            source_file=data["source_file"],
            language=data["language"],
            language_probability=data["language_probability"],
            duration=data["duration"],
            segments=segments,
            model_name=data["model_name"],
        )

    @classmethod
    def from_json(cls, json_str: str) -> TranscriptionResult:
        return cls.from_dict(json.loads(json_str))