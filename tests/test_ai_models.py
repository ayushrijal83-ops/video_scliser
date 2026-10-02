from __future__ import annotations

import pytest
import json

from app.ai.models import ClipCandidate, ClipAnalysisResult
from app.ai.exceptions import (
    AIError,
    OllamaUnavailableError,
    OllamaModelUnavailableError,
    AIInferenceError,
    AIResponseParseError,
    InvalidCandidateError,
    InvalidConfigurationError,
    TranscriptTooLargeError,
    EmptyTranscriptError,
)


class TestClipCandidate:
    def test_valid_creation(self) -> None:
        c = ClipCandidate(start=10.0, end=20.0, reason="Great moment", score=0.9)
        assert c.start == 10.0
        assert c.end == 20.0
        assert c.reason == "Great moment"
        assert c.score == 0.9
        assert c.duration == 10.0

    def test_valid_with_optional_fields(self) -> None:
        c = ClipCandidate(
            start=5.0,
            end=15.0,
            reason="Educational segment",
            score=0.85,
            title="Tips for beginners",
            transcript_text="Here are some tips...",
            confidence=0.9,
        )
        assert c.title == "Tips for beginners"
        assert c.transcript_text == "Here are some tips..."
        assert c.confidence == 0.9

    def test_invalid_negative_start(self) -> None:
        with pytest.raises(ValueError, match="start must be >= 0"):
            ClipCandidate(start=-1.0, end=10.0, reason="test", score=0.5)

    def test_invalid_negative_end(self) -> None:
        with pytest.raises(ValueError, match="end must be >= 0"):
            ClipCandidate(start=0.0, end=-1.0, reason="test", score=0.5)

    def test_invalid_end_not_greater_than_start(self) -> None:
        with pytest.raises(ValueError, match="end.*must be > start"):
            ClipCandidate(start=10.0, end=10.0, reason="test", score=0.5)

    def test_invalid_end_less_than_start(self) -> None:
        with pytest.raises(ValueError, match="end.*must be > start"):
            ClipCandidate(start=15.0, end=10.0, reason="test", score=0.5)

    def test_invalid_empty_reason(self) -> None:
        with pytest.raises(ValueError, match="reason cannot be empty"):
            ClipCandidate(start=0.0, end=10.0, reason="", score=0.5)

    def test_invalid_score_above_one(self) -> None:
        with pytest.raises(ValueError, match="score must be in \\[0.0, 1.0\\]"):
            ClipCandidate(start=0.0, end=10.0, reason="test", score=1.5)

    def test_invalid_score_below_zero(self) -> None:
        with pytest.raises(ValueError, match="score must be in \\[0.0, 1.0\\]"):
            ClipCandidate(start=0.0, end=10.0, reason="test", score=-0.1)

    def test_invalid_confidence(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in \\[0.0, 1.0\\]"):
            ClipCandidate(start=0.0, end=10.0, reason="test", score=0.5, confidence=1.5)

    def test_serialization_roundtrip(self) -> None:
        original = ClipCandidate(
            start=12.5,
            end=25.0,
            reason="Amazing insight",
            score=0.92,
            title="Key insight",
            transcript_text="This is the key insight...",
            confidence=0.95,
        )
        data = original.to_dict()
        restored = ClipCandidate.from_dict(data)
        assert restored.start == original.start
        assert restored.end == original.end
        assert restored.reason == original.reason
        assert restored.score == original.score
        assert restored.title == original.title
        assert restored.transcript_text == original.transcript_text
        assert restored.confidence == original.confidence


class TestClipAnalysisResult:
    def test_valid_creation(self) -> None:
        candidates = [
            ClipCandidate(start=0.0, end=10.0, reason="First", score=0.9),
            ClipCandidate(start=15.0, end=25.0, reason="Second", score=0.8),
        ]
        result = ClipAnalysisResult(
            instruction="Find interesting moments",
            candidates=candidates,
            model_name="qwen2.5:0.5b",
            transcript_duration=120.0,
        )
        assert result.instruction == "Find interesting moments"
        assert result.model_name == "qwen2.5:0.5b"
        assert result.transcript_duration == 120.0
        assert result.total_candidates == 2
        assert result.has_candidates is True
        assert result.top_candidate is not None
        assert result.top_candidate.score == 0.9

    def test_empty_candidates(self) -> None:
        result = ClipAnalysisResult(
            instruction="Find moments",
            candidates=[],
            model_name="qwen2.5:0.5b",
            transcript_duration=60.0,
        )
        assert result.total_candidates == 0
        assert result.has_candidates is False
        assert result.top_candidate is None

    def test_invalid_empty_instruction(self) -> None:
        with pytest.raises(ValueError, match="instruction cannot be empty"):
            ClipAnalysisResult(
                instruction="",
                candidates=[],
                model_name="qwen2.5:0.5b",
                transcript_duration=60.0,
            )

    def test_invalid_negative_duration(self) -> None:
        with pytest.raises(ValueError, match="transcript_duration must be >= 0"):
            ClipAnalysisResult(
                instruction="Find moments",
                candidates=[],
                model_name="qwen2.5:0.5b",
                transcript_duration=-1.0,
            )

    def test_serialization_roundtrip(self) -> None:
        candidates = [ClipCandidate(start=0.0, end=10.0, reason="Test", score=0.9)]
        original = ClipAnalysisResult(
            instruction="Find moments",
            candidates=candidates,
            model_name="qwen2.5:0.5b",
            transcript_duration=60.0,
        )
        data = original.to_dict()
        restored = ClipAnalysisResult.from_dict(data)
        assert restored.instruction == original.instruction
        assert restored.model_name == original.model_name
        assert restored.transcript_duration == original.transcript_duration
        assert len(restored.candidates) == 1
        assert restored.candidates[0].reason == "Test"

    def test_json_roundtrip(self) -> None:
        candidates = [ClipCandidate(start=0.0, end=10.0, reason="Test", score=0.9)]
        original = ClipAnalysisResult(
            instruction="Find moments",
            candidates=candidates,
            model_name="qwen2.5:0.5b",
            transcript_duration=60.0,
        )
        json_str = original.to_json()
        restored = ClipAnalysisResult.from_json(json_str)
        assert restored.instruction == original.instruction
        assert restored.candidates[0].reason == "Test"


class TestExceptions:
    def test_exception_hierarchy(self) -> None:
        assert issubclass(OllamaUnavailableError, AIError)
        assert issubclass(OllamaModelUnavailableError, AIError)
        assert issubclass(AIInferenceError, AIError)
        assert issubclass(AIResponseParseError, AIError)
        assert issubclass(InvalidCandidateError, AIError)
        assert issubclass(InvalidConfigurationError, AIError)
        assert issubclass(TranscriptTooLargeError, AIError)
        assert issubclass(EmptyTranscriptError, AIError)

    def test_ollama_unavailable_error(self) -> None:
        err = OllamaUnavailableError("http://localhost:11434", ConnectionError("refused"))
        assert err.host == "http://localhost:11434"
        assert "unavailable" in str(err).lower()

    def test_invalid_candidate_error(self) -> None:
        err = InvalidCandidateError({"start": 1, "end": 2}, "bad score")
        assert "bad score" in str(err)
        assert err.candidate_data == {"start": 1, "end": 2}

    def test_transcript_too_large_error(self) -> None:
        err = TranscriptTooLargeError(10000, 8000)
        assert err.transcript_chars == 10000
        assert err.max_chars == 8000
        assert "10000" in str(err)
        assert "8000" in str(err)