from __future__ import annotations

import logging
import math
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
from .grounding import ground_quote, transcript_tokens
from .models import ClipAnalysisResult, ClipCandidate
from .prompts import build_prompt, parse_ai_response

logger = logging.getLogger(__name__)

DEFAULT_MAX_CANDIDATES = 20
DEFAULT_MAX_TRANSCRIPT_CHARS = 8000
DEFAULT_TEMPERATURE = 0.1
# Ollama num_predict cap. qwen2.5:0.5b was seen repeating one candidate until the request timed out
# (M08 benchmark); 20 quoted candidates need ~1,600 tokens. A capped reply that is cut off fails JSON
# parsing and becomes a clean AIResponseParseError instead of a 10-minute hang.
DEFAULT_MAX_OUTPUT_TOKENS = 3072


@dataclass
class AIReasoningConfig:
    """Configuration for AI reasoning service."""

    ollama_config: OllamaConfig
    max_candidates: int = DEFAULT_MAX_CANDIDATES
    max_transcript_chars: int = DEFAULT_MAX_TRANSCRIPT_CHARS
    temperature: float = DEFAULT_TEMPERATURE
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS

    def __post_init__(self) -> None:
        if self.max_candidates <= 0:
            raise InvalidConfigurationError("max_candidates must be > 0")
        if self.max_transcript_chars <= 0:
            raise InvalidConfigurationError("max_transcript_chars must be > 0")
        if not 0.0 <= self.temperature <= 2.0:
            raise InvalidConfigurationError("temperature must be in [0.0, 2.0]")
        if self.max_output_tokens <= 0:
            raise InvalidConfigurationError("max_output_tokens must be > 0")

    @classmethod
    def from_env(cls) -> AIReasoningConfig:
        return cls(
            ollama_config=OllamaConfig.from_env(),
            max_candidates=int(__import__("os").getenv("AI_MAX_CANDIDATES", str(DEFAULT_MAX_CANDIDATES))),
            max_transcript_chars=int(__import__("os").getenv("AI_MAX_TRANSCRIPT_CHARS", str(DEFAULT_MAX_TRANSCRIPT_CHARS))),
            temperature=float(__import__("os").getenv("AI_TEMPERATURE", str(DEFAULT_TEMPERATURE))),
            max_output_tokens=int(__import__("os").getenv("AI_MAX_OUTPUT_TOKENS", str(DEFAULT_MAX_OUTPUT_TOKENS))),
        )


def _number(value: object) -> float | None:
    """A finite float, or None. AI times are optional hints and never fail a candidate."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        f = float(value)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


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
        transcript: TranscriptionResult,
    ) -> tuple[list[ClipCandidate], list[str]]:
        """Validate AI output and ground every quote in the transcript.

        Returns (grounded candidates, one "reason: quote" line per rejected candidate). The clip
        location is the quote's transcript position; the model's own start/end are kept only as
        ai_start/ai_end (and may break a tie between identical quotes, see ground_quote).
        """
        tokens = transcript_tokens(transcript)
        validated: list[ClipCandidate] = []
        rejected: list[str] = []

        for i, c in enumerate(raw_candidates):
            quote = ""
            try:
                reason = str(c.get("reason", "")).strip()
                score = float(c.get("score", -1))
                quote = str(c.get("quote", "")).strip()
                if not reason:
                    raise InvalidCandidateError(c, "reason cannot be empty")
                if not (0.0 <= score <= 1.0):
                    raise InvalidCandidateError(c, f"score must be in [0.0, 1.0], got {score}")
                if not quote:
                    raise InvalidCandidateError(c, "no quote to locate the moment")

                ai_start, ai_end = _number(c.get("start")), _number(c.get("end"))
                grounding = ground_quote(quote, tokens, ai_start, ai_end)
                if not grounding.ok:
                    raise InvalidCandidateError(c, grounding.reason)
                assert grounding.start is not None and grounding.end is not None

                confidence = float(c.get("confidence", 1.0))
                validated.append(
                    ClipCandidate(
                        start=grounding.start,
                        end=grounding.end,
                        reason=reason,
                        score=score,
                        title=str(c.get("title", "")).strip(),
                        transcript_text=grounding.text,
                        confidence=confidence if 0.0 <= confidence <= 1.0 else 1.0,
                        quote=quote,
                        ai_start=ai_start,
                        ai_end=ai_end,
                    )
                )
            except (ValueError, TypeError, KeyError, AttributeError, InvalidCandidateError) as e:
                message = e.reason if isinstance(e, InvalidCandidateError) else str(e)
                logger.warning("Skipping AI candidate %d: %s", i, message)
                rejected.append(f"{message}: {quote[:80]!r}")

        # Sort by score descending, then by start ascending for deterministic ordering
        validated.sort(key=lambda x: (-x.score, x.start))
        return validated, rejected

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
                options={"temperature": self.config.temperature, "num_predict": self.config.max_output_tokens},
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
        candidates, rejected = self._validate_and_create_candidates(raw_candidates, transcript)

        logger.info("AI analysis complete: %d grounded candidates, %d rejected", len(candidates), len(rejected))

        return ClipAnalysisResult(
            instruction=instruction,
            candidates=candidates,
            model_name=model_name,
            transcript_duration=transcript.duration,
            rejected=rejected,
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