from __future__ import annotations

import pytest
from unittest.mock import Mock, patch, MagicMock

from app.ai.client import OllamaClient, OllamaConfig, create_ollama_client
from app.ai.exceptions import OllamaUnavailableError, OllamaModelUnavailableError, AIInferenceError


class TestOllamaConfig:
    def test_defaults(self) -> None:
        config = OllamaConfig()
        assert config.host == "http://localhost:11434"
        assert config.model == "qwen2.5:0.5b"
        assert config.timeout == 120.0

    def test_custom_values(self) -> None:
        config = OllamaConfig(host="http://remote:11434", model="qwen2.5:7b", timeout=60.0)
        assert config.host == "http://remote:11434"
        assert config.model == "qwen2.5:7b"
        assert config.timeout == 60.0

    def test_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OLLAMA_HOST", "http://env:11434")
        monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:3b")
        monkeypatch.setenv("OLLAMA_TIMEOUT", "90")
        config = OllamaConfig.from_env()
        assert config.host == "http://env:11434"
        assert config.model == "qwen2.5:3b"
        assert config.timeout == 90.0


class TestOllamaClient:
    def setup_method(self) -> None:
        self.config = OllamaConfig(host="http://test:11434", model="test-model", timeout=30.0)

    @patch("app.ai.client.Client")
    def test_is_available_true(self, mock_client_class: Mock) -> None:
        mock_client = Mock()
        mock_client.list.return_value = {"models": []}
        mock_client_class.return_value = mock_client

        client = OllamaClient(self.config)
        # Override the internal client to use our mock
        client._client = mock_client

        assert client.is_available() is True
        mock_client.list.assert_called_once()

    @patch("app.ai.client.Client")
    def test_is_available_false(self, mock_client_class: Mock) -> None:
        mock_client = Mock()
        mock_client.list.side_effect = ConnectionError("refused")
        mock_client_class.return_value = mock_client

        client = OllamaClient(self.config)
        client._client = mock_client

        assert client.is_available() is False

    @patch("app.ai.client.Client")
    def test_is_model_available_true(self, mock_client_class: Mock) -> None:
        mock_client = Mock()
        mock_client.list.return_value = {"models": [{"name": "qwen2.5:0.5b"}]}
        mock_client_class.return_value = mock_client

        client = OllamaClient(self.config)
        client._client = mock_client

        assert client.is_model_available("qwen2.5:0.5b") is True

    @patch("app.ai.client.Client")
    def test_is_model_available_false(self, mock_client_class: Mock) -> None:
        mock_client = Mock()
        mock_client.list.return_value = {"models": [{"name": "other-model"}]}
        mock_client_class.return_value = mock_client

        client = OllamaClient(self.config)
        client._client = mock_client

        assert client.is_model_available("qwen2.5:0.5b") is False

    @patch("app.ai.client.Client")
    def test_generate_success(self, mock_client_class: Mock) -> None:
        mock_client = Mock()
        mock_client.generate.return_value = {"response": "AI response here"}
        mock_client_class.return_value = mock_client

        client = OllamaClient(self.config)
        client._client = mock_client

        result = client.generate("test prompt")
        assert result == "AI response here"
        mock_client.generate.assert_called_once_with(
            model="test-model",
            prompt="test prompt",
            stream=False,
            options={},
        )

    @patch("app.ai.client.Client")
    def test_generate_model_not_found(self, mock_client_class: Mock) -> None:
        from ollama import ResponseError
        mock_client = Mock()
        mock_client.generate.side_effect = ResponseError("model 'missing' not found")
        mock_client_class.return_value = mock_client

        client = OllamaClient(self.config)
        client._client = mock_client

        with pytest.raises(OllamaModelUnavailableError):
            client.generate("test prompt")

    @patch("app.ai.client.Client")
    def test_generate_connection_error(self, mock_client_class: Mock) -> None:
        mock_client = Mock()
        mock_client.generate.side_effect = ConnectionError("connection refused")
        mock_client_class.return_value = mock_client

        client = OllamaClient(self.config)
        client._client = mock_client

        with pytest.raises(OllamaUnavailableError):
            client.generate("test prompt")

    @patch("app.ai.client.Client")
    def test_generate_other_error(self, mock_client_class: Mock) -> None:
        mock_client = Mock()
        mock_client.generate.side_effect = RuntimeError("unexpected error")
        mock_client_class.return_value = mock_client

        client = OllamaClient(self.config)
        client._client = mock_client

        with pytest.raises(AIInferenceError):
            client.generate("test prompt")

    def test_create_ollama_client_factory(self) -> None:
        client = create_ollama_client(self.config)
        assert isinstance(client, OllamaClient)
        assert client.config == self.config