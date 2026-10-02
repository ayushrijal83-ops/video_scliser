from __future__ import annotations

import json
import pytest
from unittest.mock import Mock, patch, MagicMock

from app.ai.service import AIReasoningService, AIReasoningConfig, analyze_transcript
from app.ai.client import OllamaClient, OllamaConfig
from app.ai.models import ClipCandidate, ClipAnalysisResult
from app.ai.exceptions import (
    OllamaUnavailableError,
    OllamaModelUnavailableError,
    AIInferenceError,
    AIResponseParseError,
    InvalidCandidateError,
    InvalidConfigurationError,
    EmptyTranscriptError,
)
from app.transcription.models import TranscriptSegment, TranscriptionResult


class TestAIReasoningConfig:
    def test_defaults(self) -> None:
        config = AIReasoningConfig.from_env()
        assert config.max_candidates == 20
        assert config.max_transcript_chars == 8000
        assert config.temperature == 0.1
        assert isinstance(config.ollama_config, OllamaConfig)

    def test_custom_values(self) -> None:
        config = AIReasoningConfig(
            ollama_config=OllamaConfig(model="test-model"),
            max_candidates=10,
            max_transcript_chars=4000,
            temperature=0.5,
        )
        assert config.max_candidates == 10
        assert config.max_transcript_chars == 4000
        assert config.temperature == 0.5

    def test_invalid_max_candidates(self) -> None:
        with pytest.raises(InvalidConfigurationError, match="max_candidates must be > 0"):
            AIReasoningConfig(ollama_config=OllamaConfig(), max_candidates=0)

    def test_invalid_max_transcript_chars(self) -> None:
        with pytest.raises(InvalidConfigurationError, match="max_transcript_chars must be > 0"):
            AIReasoningConfig(ollama_config=OllamaConfig(), max_transcript_chars=0)

    def test_invalid_temperature(self) -> None:
        with pytest.raises(InvalidConfigurationError, match="temperature must be in"):
            AIReasoningConfig(ollama_config=OllamaConfig(), temperature=2.5)


class TestAIReasoningService:
    def setup_method(self) -> None:
        self.ollama_config = OllamaConfig(host="http://test:11434", model="qwen2.5:0.5b")
        self.config = AIReasoningConfig(ollama_config=self.ollama_config, max_candidates=10)
        self.mock_client = Mock(spec=OllamaClient)
        self.service = AIReasoningService(config=self.config, client=self.mock_client)

    def _make_transcript(self, segments: list[TranscriptSegment] | None = None, duration: float = 120.0) -> TranscriptionResult:
        if segments is None:
            segments = [
                TranscriptSegment(start=0.0, end=30.0, text="Introduction to the topic"),
                TranscriptSegment(start=30.0, end=60.0, text="Deep dive into details"),
                TranscriptSegment(start=60.0, end=90.0, text="Practical examples and tips"),
                TranscriptSegment(start=90.0, end=120.0, text="Conclusion and summary"),
            ]
        return TranscriptionResult(
            source_file="test.mp4",
            language="en",
            language_probability=0.98,
            duration=duration,
            segments=segments,
            model_name="small",
        )

    def test_analyze_success(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = json.dumps({
            "candidates": [
                {"start": 30.0, "end": 60.0, "reason": "Deep dive with great insights", "score": 0.92},
                {"start": 60.0, "end": 90.0, "reason": "Practical tips section", "score": 0.88},
            ]
        })

        transcript = self._make_transcript()
        result = self.service.analyze(transcript, "Find educational moments")

        assert isinstance(result, ClipAnalysisResult)
        assert result.instruction == "Find educational moments"
        assert result.model_name == "qwen2.5:0.5b"
        assert result.total_candidates == 2
        assert result.candidates[0].start == 30.0
        assert result.candidates[0].score == 0.92
        assert result.candidates[1].score == 0.88
        # Verify sorted by score descending
        assert result.candidates[0].score >= result.candidates[1].score

    def test_analyze_empty_transcript(self) -> None:
        transcript = self._make_transcript(segments=[])
        with pytest.raises(EmptyTranscriptError):
            self.service.analyze(transcript, "Find moments")

    def test_analyze_empty_instruction(self) -> None:
        transcript = self._make_transcript()
        with pytest.raises(InvalidConfigurationError, match="instruction cannot be empty"):
            self.service.analyze(transcript, "")

    def test_analyze_ollama_unavailable(self) -> None:
        self.mock_client.is_available.return_value = False
        transcript = self._make_transcript()
        with pytest.raises(OllamaUnavailableError):
            self.service.analyze(transcript, "Find moments")

    def test_analyze_model_unavailable(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = False
        transcript = self._make_transcript()
        with pytest.raises(OllamaModelUnavailableError):
            self.service.analyze(transcript, "Find moments")

    def test_analyze_inference_error(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.side_effect = AIInferenceError("Inference failed")
        transcript = self._make_transcript()
        with pytest.raises(AIInferenceError):
            self.service.analyze(transcript, "Find moments")

    def test_analyze_malformed_json(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = "not valid json {"
        transcript = self._make_transcript()
        with pytest.raises(AIResponseParseError):
            self.service.analyze(transcript, "Find moments")

    def test_analyze_empty_candidates(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = json.dumps({"candidates": []})
        transcript = self._make_transcript()
        result = self.service.analyze(transcript, "Find moments")
        assert result.total_candidates == 0
        assert result.has_candidates is False

    def test_analyze_invalid_candidate_negative_timestamp(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = json.dumps({
            "candidates": [{"start": -5.0, "end": 10.0, "reason": "test", "score": 0.9}]
        })
        transcript = self._make_transcript()
        result = self.service.analyze(transcript, "Find moments")
        # Invalid candidate should be skipped
        assert result.total_candidates == 0

    def test_analyze_invalid_candidate_end_before_start(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = json.dumps({
            "candidates": [{"start": 20.0, "end": 10.0, "reason": "test", "score": 0.9}]
        })
        transcript = self._make_transcript()
        result = self.service.analyze(transcript, "Find moments")
        assert result.total_candidates == 0

    def test_analyze_candidate_exceeds_duration(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = json.dumps({
            "candidates": [{"start": 100.0, "end": 200.0, "reason": "test", "score": 0.9}]
        })
        transcript = self._make_transcript(duration=120.0)
        result = self.service.analyze(transcript, "Find moments")
        assert result.total_candidates == 0

    def test_analyze_invalid_score(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = json.dumps({
            "candidates": [{"start": 10.0, "end": 20.0, "reason": "test", "score": 1.5}]
        })
        transcript = self._make_transcript()
        result = self.service.analyze(transcript, "Find moments")
        assert result.total_candidates == 0

    def test_analyze_missing_reason(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = json.dumps({
            "candidates": [{"start": 10.0, "end": 20.0, "score": 0.9}]
        })
        transcript = self._make_transcript()
        result = self.service.analyze(transcript, "Find moments")
        assert result.total_candidates == 0

    def test_analyze_deterministic_ordering(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = json.dumps({
            "candidates": [
                {"start": 30.0, "end": 40.0, "reason": "B", "score": 0.8},
                {"start": 10.0, "end": 20.0, "reason": "A", "score": 0.8},
                {"start": 50.0, "end": 60.0, "reason": "C", "score": 0.9},
            ]
        })
        transcript = self._make_transcript()
        result = self.service.analyze(transcript, "Find moments")
        # Should be sorted by score desc, then start asc
        assert result.candidates[0].score == 0.9
        assert result.candidates[1].start == 10.0  # Same score 0.8, earlier start first
        assert result.candidates[2].start == 30.0

    def test_analyze_candidate_limit(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        candidates = [{"start": i, "end": i + 1, "reason": f"r{i}", "score": 0.9} for i in range(50)]
        self.mock_client.generate.return_value = json.dumps({"candidates": candidates})
        transcript = self._make_transcript(duration=100.0)
        result = self.service.analyze(transcript, "Find moments")
        assert result.total_candidates == 10  # max_candidates=10

    def test_analyze_with_optional_fields(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = json.dumps({
            "candidates": [{
                "start": 10.0,
                "end": 20.0,
                "reason": "Great moment",
                "score": 0.9,
                "title": "Key insight",
                "transcript_text": "This is the key part",
                "confidence": 0.95,
            }]
        })
        transcript = self._make_transcript()
        result = self.service.analyze(transcript, "Find moments")
        assert result.total_candidates == 1
        assert result.candidates[0].title == "Key insight"
        assert result.candidates[0].transcript_text == "This is the key part"
        assert result.candidates[0].confidence == 0.95


class TestAnalyzeTranscriptConvenience:
    @patch("app.ai.service.AIReasoningService")
    def test_analyze_transcript_calls_service(self, mock_service_class: Mock) -> None:
        mock_service = Mock()
        mock_result = Mock(spec=ClipAnalysisResult)
        mock_service.analyze.return_value = mock_result
        mock_service_class.return_value = mock_service

        transcript = TranscriptionResult(
            source_file="test.mp4",
            language="en",
            language_probability=0.98,
            duration=60.0,
            segments=[TranscriptSegment(start=0.0, end=60.0, text="test")],
            model_name="small",
        )
        result = analyze_transcript(transcript, "Find moments", model="qwen2.5:7b", max_candidates=5)

        assert result == mock_result
        mock_service.analyze.assert_called_once_with(transcript, "Find moments")