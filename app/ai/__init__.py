from __future__ import annotations

from .client import OllamaClient, OllamaConfig, create_ollama_client
from .exceptions import (
    AIError,
    AIInferenceError,
    AIResponseParseError,
    EmptyTranscriptError,
    InvalidCandidateError,
    InvalidConfigurationError,
    OllamaModelUnavailableError,
    OllamaUnavailableError,
    TranscriptTooLargeError,
)
from .models import ClipAnalysisResult, ClipCandidate
from .service import AIReasoningConfig, AIReasoningService, analyze_transcript

__all__ = [
    "AIError",
    "AIInferenceError",
    "AIReasoningConfig",
    "AIReasoningService",
    "AIResponseParseError",
    "ClipAnalysisResult",
    "ClipCandidate",
    "EmptyTranscriptError",
    "InvalidCandidateError",
    "InvalidConfigurationError",
    "OllamaClient",
    "OllamaConfig",
    "OllamaModelUnavailableError",
    "OllamaUnavailableError",
    "TranscriptTooLargeError",
    "analyze_transcript",
    "create_ollama_client",
]

__version__ = "0.3.0"