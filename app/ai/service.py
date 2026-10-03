from __future__ import annotations

import logging
from dataclasses import dataclass

from app.transcription.models import TranscriptionResult

from .client import OllamaClient, OllamaConfig, create_ollama_client
from .exceptions import (
    AIInferenceError,
    AIResponseParseError,
    EmptyTranscriptError,
    InvalidCandidateError,
    InvalidConfigurationError,
    OllamaModelUnavailableError,
    OllamaUnavailableError,
)
from .models import ClipAnalysisResult, ClipCandidate
from .prompts import build_prompt, parse_ai_response

logger = logging.getLogger(__name__)

DEFAULT_MAX_CANDIDATES = 20
DEFAULT_MAX_TRANSCRIPT_CHARS = 8000
DEFAULT_TEMPERATURE = 0.1


@dataclass
class AIReasoningConfig:
    """Configuration for AI reasoning service."""

    ollama_config: OllamaConfig
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    max_transcript_chars: int = DEFAULT_MAX_TRANSCRIPT_CHARS
    temperature: float = DEFAULT_TEMPERATURE

    def __post_init__(self) -> None:
        if self.max_candidates <= 0:
            raise InvalidConfigurationError("max_candidates must be > 0")
        if self.max_transcript_chars <= 0:
            raise InvalidConfigurationError("max_transcript_chars must be > 0")
        if not 0.0 <= self.temperature <= 2.0:
            raise InvalidConfigurationError("temperature must be in [0.0, 2.0]")

    @classmethod
    def from_env(cls) -> AIReasoningConfig:
        return cls(
            ollama_config=OllamaConfig.from_env(),
            max_candidates=int(__import__("os").getenv("AI_MAX_CANDIDATES", str(DEFAULT_MAX_CANDIDATES))),
            max_transcript_chars=int(__import__("os").getenv("AI_MAX_TRANSCRIPT_CHARS", str(DEFAULT_MAX_TRANSCRIPT_CHARS))),
            temperature=float(__import__("os").getenv("AI_TEMPERATURE", str(DEFAULT_TEMPERATURE))),
        )


class AIReasoningService:
    """Service for analyzing transcripts and identifying clip candidates using local LLM."""

    def __init__(
        self,
        config: AIReasoningConfig | None = None,
        client: OllamaClient | None = None,
    ) -> None:
        self.config = config or AIReasoningConfig.from_env()
        self._client = client

    def _get_client(self) -> OllamaClient:
        if self._client is None:
            self._client = create_ollama_client(self.config.ollama_config)
        return self._client

    def _validate_transcript(self, result: TranscriptionResult) -> None:
        if not result.segments:
            raise EmptyTranscriptError()

    def _validate_and_create_candidates(
        self,
        raw_candidates: list[dict],
        transcript_duration: float,
    ) -> list[ClipCandidate]:
        validated = []

        for i, c in enumerate(raw_candidates):
            try:
                start = float(c.get("start", -1))
                end = float(c.get("end", -1))
                reason = str(c.get("reason", "")).strip()
                score = float(c.get("score", -1))

                if start < 0 or end < 0:
                    raise InvalidCandidateError(c, "timestamps must be >= 0")
                if end <= start:
                    raise InvalidCandidateError(c, f"end ({end}) must be > start ({start})")
                if start > transcript_duration:
                    raise InvalidCandidateError(c, f"start ({start}) exceeds transcript duration ({transcript_duration})")
                if end > transcript_duration:
                    raise InvalidCandidateError(c, f"end ({end}) exceeds transcript duration ({transcript_duration})")
                if not reason:
                    raise InvalidCandidateError(c, "reason cannot be empty")
                if not (0.0 <= score <= 1.0):
                    raise InvalidCandidateError(c, f"score must be in [0.0, 1.0], got {score}")

                title = str(c.get("title", "")).strip()
                transcript_text = str(c.get("transcript_text", "")).strip()
                confidence = float(c.get("confidence", 1.0))
                if not (0.0 <= confidence <= 1.0):
                    confidence = 1.0

                candidate = ClipCandidate(
                    start=start,
                    end=end,
                    reason=reason,
                    score=score,
                    title=title,
                    transcript_text=transcript_text,
                    confidence=confidence,
                )
                validated.append(candidate)

            except (ValueError, TypeError, KeyError, InvalidCandidateError) as e:
                logger.warning("Skipping invalid candidate %d: %s", i, e)
                continue

        # Sort by score descending, then by start ascending for deterministic ordering
        validated.sort(key=lambda x: (-x.score, x.start))
        return validated

    def analyze(
        self,
        transcript: TranscriptionResult,
        instruction: str,
    ) -> ClipAnalysisResult:
        """Analyze transcript and return clip candidates matching the instruction."""
        if not instruction or not instruction.strip():
            raise InvalidConfigurationError("instruction cannot be empty")

        self._validate_transcript(transcript)

        client = self._get_client()

        # Check Ollama availability lazily (only when actually analyzing)
        if not client.is_available():
            raise OllamaUnavailableError(self.config.ollama_config.host)

        model_name = self.config.ollama_config.model
        if not client.is_model_available(model_name):
            raise OllamaModelUnavailableError(model_name, self.config.ollama_config.host)

        # Build prompt
        system_prompt, user_prompt, was_truncated = build_prompt(
            transcript,
            instruction,
            max_candidates=self.config.max_candidates,
            max_transcript_chars=self.config.max_transcript_chars,
        )

        if was_truncated:
            logger.warning("Transcript truncated to %d chars for prompt", self.config.max_transcript_chars)

        full_prompt = f"{system_prompt}\n\n{user_prompt}"

        # Generate response
        logger.info("Requesting AI analysis (model=%s, instruction=%s)", model_name, instruction[:50])
        try:
            response_text = client.generate(
                prompt=full_prompt,
                model=model_name,
                options={"temperature": self.config.temperature},
            )
        except (OllamaUnavailableError, OllamaModelUnavailableError, AIInferenceError):
            raise
        except Exception as e:
            raise AIInferenceError(f"Failed to generate response: {e}", e) from e

        # Parse response
        try:
            raw_candidates = parse_ai_response(response_text, self.config.max_candidates)
        except (ValueError, TypeError) as e:  # TypeError: valid JSON of the wrong shape
            raise AIResponseParseError(response_text, str(e)) from e

        if not raw_candidates:
            logger.info("AI returned no candidates")
            return ClipAnalysisResult(
                instruction=instruction,
                candidates=[],
                model_name=model_name,
                transcript_duration=transcript.duration,
            )

        # Validate and create candidates
        candidates = self._validate_and_create_candidates(raw_candidates, transcript.duration)

        logger.info("AI analysis complete: %d valid candidates", len(candidates))

        return ClipAnalysisResult(
            instruction=instruction,
            candidates=candidates,
            model_name=model_name,
            transcript_duration=transcript.duration,
        )


def analyze_transcript(
    transcript: TranscriptionResult,
    instruction: str,
    model: str | None = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> ClipAnalysisResult:
    """Convenience function for one-off analysis."""
    config = AIReasoningConfig.from_env()
    if model:
        config.ollama_config.model = model
    config.max_candidates = max_candidates
    service = AIReasoningService(config)
    return service.analyze(transcript, instruction)