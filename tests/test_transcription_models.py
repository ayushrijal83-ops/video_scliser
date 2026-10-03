from __future__ import annotations

import pytest

from app.transcription.exceptions import (
    FFmpegNotFoundError,
    InputFileNotFoundError,
    InvalidModelConfigurationError,
    TranscriptionError,
    UnsupportedMediaFormatError,
)
from app.transcription.models import (
    TranscriptionResult,
    TranscriptSegment,
    WordTimestamp,
)


class TestWordTimestamp:
    def test_valid_creation(self) -> None:
        w = WordTimestamp(start=1.0, end=1.5, word="hello", probability=0.95)
        assert w.start == 1.0
        assert w.end == 1.5
        assert w.word == "hello"
        assert w.probability == 0.95

    def test_default_probability(self) -> None:
        w = WordTimestamp(start=0.0, end=0.5, word="test")
        assert w.probability == 1.0

    def test_invalid_negative_start(self) -> None:
        with pytest.raises(ValueError, match="start must be >= 0"):
            WordTimestamp(start=-0.1, end=1.0, word="test")

    def test_invalid_negative_end(self) -> None:
        with pytest.raises(ValueError, match="end must be >= 0"):
            WordTimestamp(start=0.0, end=-0.1, word="test")

    def test_invalid_end_before_start(self) -> None:
        with pytest.raises(ValueError, match="end.*must be >= start"):
            WordTimestamp(start=2.0, end=1.0, word="test")

    def test_invalid_empty_word(self) -> None:
        with pytest.raises(ValueError, match="word cannot be empty"):
            WordTimestamp(start=0.0, end=1.0, word="")

    def test_invalid_probability_above_one(self) -> None:
        with pytest.raises(ValueError, match="probability must be in \\[0, 1\\]"):
            WordTimestamp(start=0.0, end=1.0, word="test", probability=1.5)

    def test_invalid_probability_below_zero(self) -> None:
        with pytest.raises(ValueError, match="probability must be in \\[0, 1\\]"):
            WordTimestamp(start=0.0, end=1.0, word="test", probability=-0.1)

    def test_serialization_roundtrip(self) -> None:
        original = WordTimestamp(start=1.23, end=1.78, word="world", probability=0.88)
        data = original.to_dict()
        restored = WordTimestamp.from_dict(data)
        assert restored.start == original.start
        assert restored.end == original.end
        assert restored.word == original.word
        assert restored.probability == original.probability


class TestTranscriptSegment:
    def test_valid_creation(self) -> None:
        words = [WordTimestamp(start=0.0, end=0.5, word="hello"), WordTimestamp(start=0.5, end=1.0, word="world")]
        seg = TranscriptSegment(start=0.0, end=1.0, text="hello world", words=words)
        assert seg.start == 0.0
        assert seg.end == 1.0
        assert seg.text == "hello world"
        assert seg.words == words

    def test_default_empty_words(self) -> None:
        seg = TranscriptSegment(start=0.0, end=1.0, text="hello")
        assert seg.words == []

    def test_duration_property(self) -> None:
        seg = TranscriptSegment(start=5.0, end=12.5, text="test")
        assert seg.duration == 7.5

    def test_invalid_negative_start(self) -> None:
        with pytest.raises(ValueError, match="start must be >= 0"):
            TranscriptSegment(start=-1.0, end=1.0, text="test")

    def test_invalid_end_before_start(self) -> None:
        with pytest.raises(ValueError, match="end.*must be >= start"):
            TranscriptSegment(start=5.0, end=3.0, text="test")

    def test_invalid_empty_text(self) -> None:
        with pytest.raises(ValueError, match="text cannot be empty"):
            TranscriptSegment(start=0.0, end=1.0, text="")

    def test_invalid_whitespace_only_text(self) -> None:
        with pytest.raises(ValueError, match="text cannot be empty"):
            TranscriptSegment(start=0.0, end=1.0, text="   ")

    def test_serialization_roundtrip(self) -> None:
        words = [WordTimestamp(start=0.0, end=0.5, word="hello")]
        original = TranscriptSegment(start=0.0, end=1.0, text="hello world", words=words)
        data = original.to_dict()
        restored = TranscriptSegment.from_dict(data)
        assert restored.start == original.start
        assert restored.end == original.end
        assert restored.text == original.text
        assert len(restored.words) == 1
        assert restored.words[0].word == "hello"


class TestTranscriptionResult:
    def test_valid_creation(self) -> None:
        segments = [
            TranscriptSegment(start=0.0, end=2.0, text="Hello world"),
            TranscriptSegment(start=2.0, end=5.0, text="This is a test"),
        ]
        result = TranscriptionResult(
            source_file="/path/video.mp4",
            language="en",
            language_probability=0.98,
            duration=5.0,
            segments=segments,
            model_name="small",
        )
        assert result.source_file == "/path/video.mp4"
        assert result.language == "en"
        assert result.language_probability == 0.98
        assert result.duration == 5.0
        assert result.model_name == "small"
        assert result.segment_count == 2
        assert result.total_words == 0

    def test_full_text_property(self) -> None:
        segments = [
            TranscriptSegment(start=0.0, end=2.0, text="Hello world"),
            TranscriptSegment(start=2.0, end=5.0, text="This is a test"),
        ]
        result = TranscriptionResult(
            source_file="test.mp4",
            language="en",
            language_probability=0.98,
            duration=5.0,
            segments=segments,
            model_name="small",
        )
        assert result.full_text == "Hello world This is a test"

    def test_invalid_empty_source_file(self) -> None:
        with pytest.raises(ValueError, match="source_file cannot be empty"):
            TranscriptionResult(
                source_file="",
                language="en",
                language_probability=0.98,
                duration=5.0,
                segments=[],
                model_name="small",
            )

    def test_invalid_language_probability(self) -> None:
        with pytest.raises(ValueError, match="language_probability must be in \\[0, 1\\]"):
            TranscriptionResult(
                source_file="test.mp4",
                language="en",
                language_probability=1.5,
                duration=5.0,
                segments=[],
                model_name="small",
            )

    def test_invalid_negative_duration(self) -> None:
        with pytest.raises(ValueError, match="duration must be >= 0"):
            TranscriptionResult(
                source_file="test.mp4",
                language="en",
                language_probability=0.98,
                duration=-1.0,
                segments=[],
                model_name="small",
            )

    def test_serialization_roundtrip(self) -> None:
        segments = [
            TranscriptSegment(start=0.0, end=2.0, text="Hello world", words=[WordTimestamp(start=0.0, end=0.5, word="Hello")]),
        ]
        original = TranscriptionResult(
            source_file="test.mp4",
            language="en",
            language_probability=0.98,
            duration=2.0,
            segments=segments,
            model_name="small",
        )
        data = original.to_dict()
        restored = TranscriptionResult.from_dict(data)
        assert restored.source_file == original.source_file
        assert restored.language == original.language
        assert restored.language_probability == original.language_probability
        assert restored.duration == original.duration
        assert restored.model_name == original.model_name
        assert len(restored.segments) == 1
        assert restored.segments[0].text == "Hello world"

    def test_json_roundtrip(self) -> None:
        segments = [TranscriptSegment(start=0.0, end=1.0, text="Test")]
        original = TranscriptionResult(
            source_file="test.mp4",
            language="en",
            language_probability=0.95,
            duration=1.0,
            segments=segments,
            model_name="small",
        )
        json_str = original.to_json()
        restored = TranscriptionResult.from_json(json_str)
        assert restored.source_file == original.source_file
        assert restored.segments[0].text == "Test"


class TestExceptions:
    def test_exception_hierarchy(self) -> None:
        assert issubclass(InputFileNotFoundError, TranscriptionError)
        assert issubclass(UnsupportedMediaFormatError, TranscriptionError)
        assert issubclass(FFmpegNotFoundError, TranscriptionError)
        assert issubclass(InvalidModelConfigurationError, TranscriptionError)

    def test_input_file_not_found_error(self) -> None:
        err = InputFileNotFoundError("/path/to/missing.mp4")
        assert err.path == "/path/to/missing.mp4"
        assert "not found" in str(err)

    def test_invalid_model_config_error(self) -> None:
        err = InvalidModelConfigurationError("invalid model name")
        assert "invalid model name" in str(err)