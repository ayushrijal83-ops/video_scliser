from __future__ import annotations


class AIError(Exception):
    """Base exception for AI reasoning errors."""



class OllamaUnavailableError(AIError):
    """Raised when Ollama daemon is not reachable."""

    def __init__(self, host: str = "http://localhost:11434", original_error: Exception | None = None) -> None:
        self.host = host
        self.original_error = original_error
        msg = f"Ollama unavailable at {host}"
        if original_error:
            msg += f" ({original_error})"
        super().__init__(msg)


class OllamaModelUnavailableError(AIError):
    """Raised when the requested model is not available in Ollama."""

    def __init__(self, model_name: str, host: str = "http://localhost:11434", original_error: Exception | None = None) -> None:
        self.model_name = model_name
        self.host = host
        self.original_error = original_error
        msg = f"Model '{model_name}' not available in Ollama at {host}"
        if original_error:
            msg += f" ({original_error})"
        super().__init__(msg)


class AIInferenceError(AIError):
    """Raised when Ollama inference fails."""

    def __init__(self, message: str, original_error: Exception | None = None) -> None:
        self.original_error = original_error
        msg = f"AI inference failed: {message}"
        if original_error:
            msg += f" (caused by: {original_error})"
        super().__init__(msg)


class AIResponseParseError(AIError):
    """Raised when the AI response cannot be parsed as valid JSON."""

    def __init__(self, response_text: str, message: str = "", original_error: Exception | None = None) -> None:
        self.response_text = response_text
        self.original_error = original_error
        msg = "Failed to parse AI response"
        if message:
            msg += f": {message}"
        if original_error:
            msg += f" ({original_error})"
        super().__init__(msg)


class InvalidCandidateError(AIError):
    """Raised when a candidate fails validation."""

    def __init__(self, candidate_data: dict, message: str) -> None:
        self.candidate_data = candidate_data
        super().__init__(f"Invalid candidate {candidate_data}: {message}")


class InvalidConfigurationError(AIError):
    """Raised when AI service configuration is invalid."""

    def __init__(self, message: str) -> None:
        super().__init__(f"Invalid AI configuration: {message}")


class TranscriptTooLargeError(AIError):
    """Raised when transcript exceeds maximum input size."""

    def __init__(self, transcript_chars: int, max_chars: int) -> None:
        self.transcript_chars = transcript_chars
        self.max_chars = max_chars
        super().__init__(f"Transcript too large: {transcript_chars} chars (max {max_chars})")


class EmptyTranscriptError(AIError):
    """Raised when transcript has no content."""

    def __init__(self) -> None:
        super().__init__("Transcript has no segments to analyze")