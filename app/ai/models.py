from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ClipCandidate:
    """A candidate clip moment identified by the AI."""

    start: float
    end: float
    reason: str
    score: float
    title: str = ""
    transcript_text: str = ""
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.start, (int, float)) or self.start < 0:
            raise ValueError(f"start must be >= 0, got {self.start}")
        if not isinstance(self.end, (int, float)) or self.end < 0:
            raise ValueError(f"end must be >= 0, got {self.end}")
        if self.end <= self.start:
            raise ValueError(f"end ({self.end}) must be > start ({self.start})")
        if not self.reason or not self.reason.strip():
            raise ValueError("reason cannot be empty")
        if not isinstance(self.score, (int, float)) or not (0.0 <= self.score <= 1.0):
            raise ValueError(f"score must be in [0.0, 1.0], got {self.score}")
        if not isinstance(self.confidence, (int, float)) or not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"confidence must be in [0.0, 1.0], got {self.confidence}")

    @property
    def duration(self) -> float:
        return self.end - self.start

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "reason": self.reason,
            "score": self.score,
            "title": self.title,
            "transcript_text": self.transcript_text,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ClipCandidate:
        return cls(
            start=float(data["start"]),
            end=float(data["end"]),
            reason=data["reason"],
            score=float(data["score"]),
            title=data.get("title", ""),
            transcript_text=data.get("transcript_text", ""),
            confidence=float(data.get("confidence", 1.0)),
        )


@dataclass
class ClipAnalysisResult:
    """Complete AI analysis result with candidate clip moments."""

    instruction: str
    candidates: list[ClipCandidate]
    model_name: str
    transcript_duration: float
    total_candidates: int = field(init=False)

    def __post_init__(self) -> None:
        if not self.instruction or not self.instruction.strip():
            raise ValueError("instruction cannot be empty")
        if not self.model_name or not self.model_name.strip():
            raise ValueError("model_name cannot be empty")
        if self.transcript_duration < 0:
            raise ValueError(f"transcript_duration must be >= 0, got {self.transcript_duration}")
        self.total_candidates = len(self.candidates)

    @property
    def has_candidates(self) -> bool:
        return len(self.candidates) > 0

    @property
    def top_candidate(self) -> ClipCandidate | None:
        if not self.candidates:
            return None
        return self.candidates[0]

    def to_dict(self) -> dict:
        return {
            "instruction": self.instruction,
            "model_name": self.model_name,
            "transcript_duration": self.transcript_duration,
            "total_candidates": self.total_candidates,
            "candidates": [c.to_dict() for c in self.candidates],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict) -> ClipAnalysisResult:
        candidates = [ClipCandidate.from_dict(c) for c in data.get("candidates", [])]
        return cls(
            instruction=data["instruction"],
            candidates=candidates,
            model_name=data["model_name"],
            transcript_duration=data["transcript_duration"],
        )

    @classmethod
    def from_json(cls, json_str: str) -> ClipAnalysisResult:
        return cls.from_dict(json.loads(json_str))