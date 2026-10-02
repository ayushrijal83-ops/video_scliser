from __future__ import annotations

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from app.transcription.service import TranscriptionService, transcribe_file
from app.transcription.exceptions import (
    InputFileNotFoundError,
    UnsupportedMediaFormatError,
    FFmpegNotFoundError,
    FFmpegExecutionError,
    InvalidModelConfigurationError,
    ModelNotAvailableError,
    TranscriptionFailedError,
    EmptyAudioError,
    AudioExtractionError,
)
from app.transcription.models import TranscriptSegment, WordTimestamp


class TestTranscriptionServiceInit:
    def test_valid_default_init(self) -> None:
        service = TranscriptionService()
        assert service.model_name == "small"
        assert service.device == "cpu"
        assert service.compute_type == "int8"

    def test_valid_custom_init(self) -> None:
        service = TranscriptionService(model_name="base", device="cpu", compute_type="float32")
        assert service.model_name == "base"
        assert service.device == "cpu"
        assert service.compute_type == "float32"

    def test_invalid_model_name(self) -> None:
        with pytest.raises(InvalidModelConfigurationError, match="Invalid model"):
            TranscriptionService(model_name="invalid-model")

    def test_invalid_device(self) -> None:
        with pytest.raises(InvalidModelConfigurationError, match="Invalid device"):
            TranscriptionService(device="invalid")

    def test_invalid_compute_type(self) -> None:
        with pytest.raises(InvalidModelConfigurationError, match="Invalid compute_type"):
            TranscriptionService(compute_type="invalid")

    def test_cpu_float16_fallback(self) -> None:
        with patch("app.transcription.service.logger") as mock_logger:
            service = TranscriptionService(device="cpu", compute_type="float16")
            assert service.compute_type == "int8"
            mock_logger.warning.assert_called_once()


class TestTranscriptionServiceValidateInput:
    def setup_method(self) -> None:
        self.service = TranscriptionService()

    def test_nonexistent_file(self) -> None:
        with pytest.raises(InputFileNotFoundError):
            self.service._validate_input_file("/nonexistent/path/video.mp4")

    def test_directory_not_file(self, tmp_path: Path) -> None:
        with pytest.raises(UnsupportedMediaFormatError):
            self.service._validate_input_file(str(tmp_path))

    def test_unsupported_extension(self, tmp_path: Path) -> None:
        test_file = tmp_path / "video.xyz"
        test_file.write_text("test")
        with pytest.raises(UnsupportedMediaFormatError, match="unsupported extension"):
            self.service._validate_input_file(str(test_file))

    def test_supported_extensions(self, tmp_path: Path) -> None:
        for ext in [".mp4", ".mkv", ".mov", ".avi", ".webm", ".mp3", ".wav"]:
            test_file = tmp_path / f"video{ext}"
            test_file.write_text("test")
            result = self.service._validate_input_file(str(test_file))
            assert result == test_file.resolve()


class TestTranscriptionServiceExtractAudio:
    def setup_method(self) -> None:
        self.service = TranscriptionService()

    @patch("app.transcription.service.shutil.which")
    def test_ffmpeg_not_found(self, mock_which: Mock) -> None:
        mock_which.return_value = None
        with pytest.raises(FFmpegNotFoundError):
            self.service._check_ffmpeg()

    @patch("app.transcription.service.shutil.which")
    @patch("app.transcription.service.subprocess.run")
    def test_ffmpeg_execution_error(self, mock_run: Mock, mock_which: Mock, tmp_path: Path) -> None:
        mock_which.return_value = "/usr/bin/ffmpeg"
        mock_run.return_value = Mock(returncode=1, stderr="Invalid data found")
        input_path = tmp_path / "input.mp4"
        input_path.write_text("fake")
        output_path = tmp_path / "output.wav"
        with pytest.raises(FFmpegExecutionError):
            self.service._extract_audio(input_path, output_path)

    @patch("app.transcription.service.shutil.which")
    @patch("app.transcription.service.subprocess.run")
    def test_ffmpeg_timeout(self, mock_run: Mock, mock_which: Mock, tmp_path: Path) -> None:
        import subprocess
        mock_which.return_value = "/usr/bin/ffmpeg"
        mock_run.side_effect = subprocess.TimeoutExpired("ffmpeg", 300)
        input_path = tmp_path / "input.mp4"
        input_path.write_text("fake")
        output_path = tmp_path / "output.wav"
        with pytest.raises(AudioExtractionError, match="timeout"):
            self.service._extract_audio(input_path, output_path)


class TestTranscriptionServiceTranscribe:
    def setup_method(self) -> None:
        self.service = TranscriptionService()

    @patch("app.transcription.service.TranscriptionService._extract_audio")
    @patch("app.transcription.service.TranscriptionService._get_audio_duration")
    @patch("app.transcription.service.WhisperModel")
    def test_successful_transcription(
        self,
        mock_whisper_class: Mock,
        mock_get_duration: Mock,
        mock_extract: Mock,
        tmp_path: Path,
    ) -> None:
        mock_get_duration.return_value = 5.0

        mock_model = Mock()
        mock_segment = Mock()
        mock_segment.start = 0.0
        mock_segment.end = 2.0
        mock_segment.text = "Hello world"
        mock_word = Mock()
        mock_word.start = 0.0
        mock_word.end = 0.5
        mock_word.word = "Hello"
        mock_word.probability = 0.95
        mock_segment.words = [mock_word]
        mock_model.transcribe.return_value = ([mock_segment], Mock(language="en", language_probability=0.98))
        mock_whisper_class.return_value = mock_model

        input_path = tmp_path / "video.mp4"
        input_path.write_text("fake")

        result = self.service.transcribe(str(input_path))

        from app.transcription.models import TranscriptionResult
        assert isinstance(result, TranscriptionResult)
        assert result.segment_count == 1
        assert result.segments[0].text == "Hello world"
        assert result.language == "en"
        mock_extract.assert_called_once()
        mock_model.transcribe.assert_called_once()

    @patch("app.transcription.service.TranscriptionService._extract_audio")
    @patch("app.transcription.service.TranscriptionService._get_audio_duration")
    @patch("app.transcription.service.WhisperModel")
    def test_empty_audio_raises_error(
        self,
        mock_whisper_class: Mock,
        mock_get_duration: Mock,
        mock_extract: Mock,
        tmp_path: Path,
    ) -> None:
        mock_get_duration.return_value = 0.0
        mock_model = Mock()
        mock_model.transcribe.return_value = ([], Mock(language="en", language_probability=0.98))
        mock_whisper_class.return_value = mock_model

        input_path = tmp_path / "video.mp4"
        input_path.write_text("fake")

        with pytest.raises(EmptyAudioError):
            self.service.transcribe(str(input_path))

    @patch("app.transcription.service.TranscriptionService._extract_audio")
    @patch("app.transcription.service.TranscriptionService._get_audio_duration")
    @patch("app.transcription.service.WhisperModel")
    def test_transcription_failed_wraps_error(
        self,
        mock_whisper_class: Mock,
        mock_get_duration: Mock,
        mock_extract: Mock,
        tmp_path: Path,
    ) -> None:
        mock_get_duration.return_value = 5.0
        mock_model = Mock()
        mock_model.transcribe.side_effect = RuntimeError("CUDA out of memory")
        mock_whisper_class.return_value = mock_model

        input_path = tmp_path / "video.mp4"
        input_path.write_text("fake")

        with pytest.raises(TranscriptionFailedError) as exc_info:
            self.service.transcribe(str(input_path))
        assert "CUDA out of memory" in str(exc_info.value)

    @patch("app.transcription.service.WhisperModel")
    def test_model_load_failure(self, mock_whisper_class: Mock) -> None:
        mock_whisper_class.side_effect = OSError("Model not found")
        with pytest.raises(ModelNotAvailableError):
            self.service._ensure_model_loaded()


class TestTranscribeFileConvenience:
    @patch("app.transcription.service.TranscriptionService.transcribe")
    def test_transcribe_file_calls_service(self, mock_transcribe: Mock, tmp_path: Path) -> None:
        mock_result = Mock()
        mock_transcribe.return_value = mock_result
        input_path = tmp_path / "video.mp4"
        input_path.write_text("fake")

        result = transcribe_file(str(input_path), model_name="base", language="en")

        assert result == mock_result
        mock_transcribe.assert_called_once_with(str(input_path), language="en")


class TestGetAudioDuration:
    @patch("app.transcription.service.shutil.which")
    @patch("app.transcription.service.subprocess.run")
    def test_duration_parsing(self, mock_run: Mock, mock_which: Mock, tmp_path: Path) -> None:
        mock_which.return_value = "/usr/bin/ffmpeg"
        mock_run.return_value = Mock(
            returncode=0,
            stderr="time=00:00:05.50 bitrate=...",
        )
        service = TranscriptionService()
        audio_path = tmp_path / "audio.wav"
        audio_path.write_text("fake")
        duration = service._get_audio_duration(audio_path)
        assert duration == 5.5