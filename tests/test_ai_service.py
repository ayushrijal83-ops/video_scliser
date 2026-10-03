from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from app.ai.client import OllamaClient, OllamaConfig
from app.ai.exceptions import (
    AIInferenceError,
    AIResponseParseError,
    EmptyTranscriptError,
    InvalidConfigurationError,
    OllamaModelUnavailableError,
    OllamaUnavailableError,
)
from app.ai.models import ClipAnalysisResult
from app.ai.service import AIReasoningConfig, AIReasoningService, analyze_transcript
from app.transcription.models import TranscriptionResult, TranscriptSegment


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
                {"start": 30.0, "end": 60.0, "reason": "Deep dive with great insights", "score": 0.92,
                 "quote": "Deep dive into details"},
                {"start": 60.0, "end": 90.0, "reason": "Practical tips section", "score": 0.88,
                 "quote": "Practical examples and tips"},
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

    @pytest.mark.parametrize(
        "response", ['[1, 2]', '"text"', '{"candidates": "none"}', '{"candidates": [1]}', '{"other": []}']
    )
    def test_analyze_wrong_shape_json_is_parse_error(self, response: str) -> None:
        """Regression (M07): valid JSON of the wrong shape used to escape as a bare TypeError."""
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = response
        with pytest.raises(AIResponseParseError):
            self.service.analyze(self._make_transcript(), "Find moments")

    def test_analyze_empty_candidates(self) -> None:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = json.dumps({"candidates": []})
        transcript = self._make_transcript()
        result = self.service.analyze(transcript, "Find moments")
        assert result.total_candidates == 0
        assert result.has_candidates is False

    def _analyze(self, *candidates: dict, duration: float = 120.0) -> ClipAnalysisResult:
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        self.mock_client.generate.return_value = json.dumps({"candidates": list(candidates)})
        return self.service.analyze(self._make_transcript(duration=duration), "Find moments")

    @pytest.mark.parametrize(
        ("start", "end"), [(-5.0, 10.0), (20.0, 10.0), (100.0, 200.0), ("x", None), (float("nan"), 3.0)]
    )
    def test_bad_ai_times_do_not_matter_when_quote_grounds(self, start: object, end: object) -> None:
        """M08: AI times are hints; the location comes from the quote's place in the transcript."""
        cand = {"start": start, "end": end, "reason": "test", "score": 0.9, "quote": "deep dive into details"}
        result = self._analyze(cand)
        assert result.total_candidates == 1
        assert (result.candidates[0].start, result.candidates[0].end) == (30.0, 60.0)
        assert result.candidates[0].transcript_text == "deep dive into details"

    def test_missing_ai_times_still_grounded(self) -> None:
        result = self._analyze({"reason": "test", "score": 0.9, "quote": "Practical examples and tips"})
        assert (result.candidates[0].start, result.candidates[0].end) == (60.0, 90.0)
        assert result.candidates[0].ai_start is None and result.candidates[0].ai_end is None

    def test_analyze_invalid_score(self) -> None:
        result = self._analyze({"start": 30.0, "end": 60.0, "reason": "t", "score": 1.5, "quote": "deep dive into details"})
        assert result.total_candidates == 0
        assert result.rejected[0].startswith("score must be in [0.0, 1.0]")

    def test_analyze_missing_reason(self) -> None:
        result = self._analyze({"start": 30.0, "end": 60.0, "score": 0.9, "quote": "deep dive into details"})
        assert result.total_candidates == 0 and result.rejected[0].startswith("reason cannot be empty")

    def test_missing_quote_rejected_never_falls_back_to_ai_time(self) -> None:
        result = self._analyze({"start": 30.0, "end": 60.0, "reason": "valid times, no quote", "score": 0.9})
        assert result.total_candidates == 0
        assert result.rejected == ["no quote to locate the moment: ''"]

    def test_ungrounded_quote_rejected_with_reason(self) -> None:
        result = self._analyze(
            {"start": 30.0, "end": 60.0, "reason": "r", "score": 0.9, "quote": "words the speaker never said"},
            {"start": 0.0, "end": 30.0, "reason": "r", "score": 0.8, "quote": "Introduction to the topic"},
        )
        assert [c.start for c in result.candidates] == [0.0]  # the other candidate still flows through
        assert result.rejected == ["quote not found in transcript: 'words the speaker never said'"]

    def test_analyze_deterministic_ordering(self) -> None:
        result = self._analyze(
            {"reason": "B", "score": 0.8, "quote": "Practical examples and tips"},
            {"reason": "A", "score": 0.8, "quote": "Deep dive into details"},
            {"reason": "C", "score": 0.9, "quote": "Conclusion and summary"},
        )
        # Sorted by score desc, then grounded start asc
        assert [c.reason for c in result.candidates] == ["C", "A", "B"]
        assert [c.start for c in result.candidates] == [90.0, 30.0, 60.0]

    def test_analyze_candidate_limit(self) -> None:
        segs = [TranscriptSegment(start=float(i), end=i + 1.0, text=f"unique sentence number {i}") for i in range(50)]
        self.mock_client.is_available.return_value = True
        self.mock_client.is_model_available.return_value = True
        candidates = [{"reason": f"r{i}", "score": 0.9, "quote": f"sentence number {i}"} for i in range(50)]
        self.mock_client.generate.return_value = json.dumps({"candidates": candidates})
        result = self.service.analyze(self._make_transcript(segs, duration=100.0), "Find moments")
        assert result.total_candidates == 10  # max_candidates=10

    def test_analyze_with_optional_fields(self) -> None:
        result = self._analyze({
            "start": 10.0, "end": 20.0, "reason": "Great moment", "score": 0.9, "title": "Key insight",
            "quote": "“Introduction to the Topic.”", "confidence": 0.95,
        })
        c = result.candidates[0]
        assert (c.title, c.confidence, c.start, c.end) == ("Key insight", 0.95, 0.0, 30.0)
        assert c.quote == "“Introduction to the Topic.”"
        assert c.transcript_text == "introduction to the topic"
        assert (c.ai_start, c.ai_end) == (10.0, 20.0)


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


def test_output_token_cap_sent_to_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    """M08: a looping model must stop at a token cap instead of running until the timeout."""
    monkeypatch.delenv("AI_MAX_OUTPUT_TOKENS", raising=False)
    assert AIReasoningConfig.from_env().max_output_tokens == 3072
    monkeypatch.setenv("AI_MAX_OUTPUT_TOKENS", "500")
    config = AIReasoningConfig.from_env()
    client = Mock(spec=OllamaClient)
    client.is_available.return_value = True
    client.is_model_available.return_value = True
    client.generate.return_value = '{"candidates": [{"quote": "unterminated'  # what a capped loop returns
    seg = TranscriptSegment(start=0.0, end=5.0, text="hello there world")
    with pytest.raises(AIResponseParseError):
        AIReasoningService(config, client=client).analyze(
            TranscriptionResult("t.mp4", "en", 1.0, 5.0, [seg], "small"), "funny")
    assert client.generate.call_args.kwargs["options"] == {"temperature": 0.1, "num_predict": 500}
    with pytest.raises(InvalidConfigurationError):
        AIReasoningConfig(ollama_config=OllamaConfig(), max_output_tokens=0)
