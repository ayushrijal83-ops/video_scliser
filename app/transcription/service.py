from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from faster_whisper import WhisperModel  # type: ignore[import-untyped]

from .exceptions import (
    AudioExtractionError,
    EmptyAudioError,
    FFmpegExecutionError,
    FFmpegNotFoundError,
    InputFileNotFoundError,
    InvalidModelConfigurationError,
    ModelNotAvailableError,
    TranscriptionFailedError,
    UnsupportedMediaFormatError,
)
from .models import TranscriptionResult, TranscriptSegment, WordTimestamp

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".mp3", ".wav", ".m4a", ".flac", ".ogg"}

DEFAULT_MODEL = "small"
VALID_MODELS = {"tiny", "base", "small", "medium", "large-v1", "large-v2", "large-v3", "large"}

WHISPER_MODEL_DIR = Path.home() / ".cache" / "huggingface" / "hub"


class TranscriptionService:
    """Service for transcribing video/audio files with timestamped segments."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: str = "cpu",
        compute_type: str = "int8",
        download_root: str | None = None,
    ) -> None:
        if model_name not in VALID_MODELS:
            raise InvalidModelConfigurationError(
                f"Invalid model '{model_name}'. Valid options: {', '.join(sorted(VALID_MODELS))}"
            )
        if device not in ("cpu", "cuda"):
            raise InvalidModelConfigurationError(f"Invalid device '{device}'. Use 'cpu' or 'cuda'.")
        if compute_type not in ("int8", "int8_float16", "float16", "float32"):
            raise InvalidModelConfigurationError(
                f"Invalid compute_type '{compute_type}'. Use 'int8', 'int8_float16', 'float16', or 'float32'."
            )
        if device == "cpu" and compute_type in ("float16", "int8_float16"):
            logger.warning("compute_type %s not optimal for CPU, falling back to int8", compute_type)
            compute_type = "int8"

        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root or str(WHISPER_MODEL_DIR)
        self._model: WhisperModel | None = None

    def _ensure_model_loaded(self) -> WhisperModel:
        if self._model is None:
            logger.info("Loading Whisper model: %s (device=%s, compute_type=%s)", self.model_name, self.device, self.compute_type)
            try:
                self._model = WhisperModel(
                    self.model_name,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=self.download_root,
                )
            except Exception as e:
                raise ModelNotAvailableError(self.model_name, str(e)) from e
        return self._model

    def _check_ffmpeg(self) -> str:
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise FFmpegNotFoundError()
        return ffmpeg_path

    def _validate_input_file(self, path: str) -> Path:
        input_path = Path(path).resolve()
        if not input_path.exists():
            raise InputFileNotFoundError(str(input_path))
        if not input_path.is_file():
            raise UnsupportedMediaFormatError(str(input_path), "not a file")
        if input_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise UnsupportedMediaFormatError(str(input_path), f"unsupported extension {input_path.suffix}")
        return input_path

    def _extract_audio(self, input_path: Path, output_path: Path) -> None:
        ffmpeg = self._check_ffmpeg()
        cmd = [
            ffmpeg,
            "-v", "error",
            "-y",
            "-i", str(input_path),
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-c:a", "pcm_s16le",
            str(output_path),
        ]
        logger.debug("Running FFmpeg: %s", " ".join(cmd))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
        except subprocess.TimeoutExpired as e:
            raise AudioExtractionError(str(input_path), f"timeout after 300s: {e}") from e
        except OSError as e:
            raise AudioExtractionError(str(input_path), str(e)) from e

        if result.returncode != 0:
            raise FFmpegExecutionError(str(input_path), result.stderr, result.returncode)

        if not output_path.exists() or output_path.stat().st_size == 0:
            raise AudioExtractionError(str(input_path), "output file is empty")

    def _get_audio_duration(self, audio_path: Path) -> float:
        ffmpeg = self._check_ffmpeg()
        cmd = [
            ffmpeg,
            "-v", "error",
            "-i", str(audio_path),
            "-f", "null",
            "-",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.SubprocessError) as e:
            logger.warning("Could not determine audio duration: %s", e)
            return 0.0

        if result.returncode != 0:
            return 0.0

        import re
        duration_match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", result.stderr)
        if duration_match:
            h, m, s = duration_match.groups()
            return int(h) * 3600 + int(m) * 60 + float(s)
        return 0.0

    def transcribe(self, input_path: str, language: str | None = None) -> TranscriptionResult:
        validated_path = self._validate_input_file(input_path)

        with tempfile.TemporaryDirectory() as tmpdir:
            audio_path = Path(tmpdir) / "audio.wav"
            self._extract_audio(validated_path, audio_path)

            duration = self._get_audio_duration(audio_path)
            if duration == 0.0:
                logger.warning("Could not determine audio duration, using 0.0")

            model = self._ensure_model_loaded()

            logger.info("Starting transcription of %s", validated_path)
            try:
                segments, info = model.transcribe(
                    str(audio_path),
                    language=language,
                    beam_size=5,
                    best_of=5,
                    patience=1.0,
                    temperature=0.0,
                    condition_on_previous_text=True,
                    word_timestamps=True,
                )
            except Exception as e:
                raise TranscriptionFailedError(f"Whisper transcription failed: {e}", e) from e

            if info.language_probability < 0.1 and not language:
                logger.warning("Low language detection confidence: %s (%.2f)", info.language, info.language_probability)

            transcript_segments: list[TranscriptSegment] = []
            for seg in segments:
                words = [
                    WordTimestamp(start=w.start, end=w.end, word=w.word, probability=w.probability)
                    for w in (seg.words or [])
                ]
                transcript_segments.append(
                    TranscriptSegment(start=seg.start, end=seg.end, text=seg.text.strip(), words=words)
                )

            if not transcript_segments:
                raise EmptyAudioError(str(validated_path))

            result = TranscriptionResult(
                source_file=str(validated_path),
                language=info.language,
                language_probability=info.language_probability,
                duration=duration or transcript_segments[-1].end,
                segments=transcript_segments,
                model_name=self.model_name,
            )

            logger.info(
                "Transcription complete: %d segments, %.2fs, language=%s (%.2f)",
                result.segment_count,
                result.duration,
                result.language,
                result.language_probability,
            )
            return result


def transcribe_file(
    input_path: str,
    model_name: str = DEFAULT_MODEL,
    device: str = "cpu",
    compute_type: str = "int8",
    language: str | None = None,
) -> TranscriptionResult:
    """Convenience function for one-off transcription."""
    service = TranscriptionService(model_name=model_name, device=device, compute_type=compute_type)
    return service.transcribe(input_path, language=language)