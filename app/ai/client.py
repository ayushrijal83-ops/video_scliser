from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Protocol

from ollama import Client, ResponseError

from .exceptions import (
    AIInferenceError,
    OllamaModelUnavailableError,
    OllamaUnavailableError,
)

logger = logging.getLogger(__name__)

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:0.5b"
DEFAULT_TIMEOUT = 120.0


class OllamaClientProtocol(Protocol):
    """Protocol for Ollama client to enable mocking in tests."""

    def generate(
        self,
        model: str,
        prompt: str,
        stream: bool = False,
        options: dict | None = None,
    ) -> dict:
        ...

    def list(self) -> dict:
        ...

    def show(self, model: str) -> dict:
        ...


@dataclass
class OllamaConfig:
    """Configuration for Ollama client."""

    host: str = DEFAULT_HOST
    model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> OllamaConfig:
        return cls(
            host=os.getenv("OLLAMA_HOST", DEFAULT_HOST),
            model=os.getenv("OLLAMA_MODEL", DEFAULT_MODEL),
            timeout=float(os.getenv("OLLAMA_TIMEOUT", str(DEFAULT_TIMEOUT))),
        )


class OllamaClient:
    """Wrapper around Ollama Python client with error handling."""

    def __init__(self, config: OllamaConfig | None = None) -> None:
        self.config = config or OllamaConfig.from_env()
        self._client: Client | None = None

    def _get_client(self) -> Client:
        if self._client is None:
            self._client = Client(host=self.config.host, timeout=self.config.timeout)
        return self._client

    def is_available(self) -> bool:
        """Check if Ollama daemon is reachable."""
        try:
            client = self._get_client()
            client.list()
            return True
        except (ConnectionError, OSError, TimeoutError) as e:
            logger.debug("Ollama not available: %s", e)
            return False

    def is_model_available(self, model: str | None = None) -> bool:
        """Check if the specified model is available."""
        model_name = model or self.config.model
        try:
            client = self._get_client()
            models = client.list()
            # Handle both dict and object response formats
            model_list = models.get("models", []) if isinstance(models, dict) else getattr(models, "models", [])
            # Exact tag match: a "qwen2.5" prefix check would accept qwen2.5:3b when only 0.5b is pulled.
            wanted = model_name if ":" in model_name else f"{model_name}:latest"
            return any(
                (m.get("name", "") if isinstance(m, dict) else getattr(m, "model", "")) in (model_name, wanted)
                for m in model_list
            )
        except (ConnectionError, OSError, TimeoutError, AttributeError) as e:
            logger.debug("Could not check model availability: %s", e)
            return False

    def generate(
        self,
        prompt: str,
        model: str | None = None,
        options: dict | None = None,
        stream: bool = False,
        format: str = "",
    ) -> str:
        """Generate a response from the model. format="json" constrains output to valid JSON."""
        model_name = model or self.config.model
        client = self._get_client()

        try:
            response = client.generate(  # type: ignore[call-overload]
                model=model_name,
                prompt=prompt,
                stream=stream,
                options=options or {},
                format=format,
            )
            return response.get("response", "")
        except ResponseError as e:
            if "not found" in str(e).lower() or "model" in str(e).lower():
                raise OllamaModelUnavailableError(model_name, self.config.host, e) from e
            raise AIInferenceError(f"Ollama response error: {e}", e) from e
        except ConnectionError as e:
            raise OllamaUnavailableError(self.config.host, e) from e
        except Exception as e:
            raise AIInferenceError(f"Unexpected inference error: {e}", e) from e

    def list_models(self) -> list[str]:
        """List available models."""
        try:
            client = self._get_client()
            models = client.list()
            model_list = models.get("models", []) if isinstance(models, dict) else getattr(models, "models", [])
            return [
                m.get("name", "") if isinstance(m, dict) else getattr(m, "model", "")
                for m in model_list
            ]
        except (ConnectionError, OSError, TimeoutError, AttributeError) as e:
            logger.warning("Could not list models: %s", e)
            return []


def create_ollama_client(config: OllamaConfig | None = None) -> OllamaClient:
    """Factory function to create OllamaClient."""
    return OllamaClient(config)