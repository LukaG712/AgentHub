"""Tests for the Ollama integration module and API endpoints."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hub import ollama
from hub.ollama import OllamaClient, OllamaError, get_ollama_client


class TestOllamaClientInit:
    """Test OllamaClient initialization and configuration."""

    def test_default_init(self):
        """Client should initialize with default values."""
        client = OllamaClient()
        assert client.base_url == "http://localhost:11434"
        assert client.model == "llama3"
        assert client.timeout == 60

    def test_custom_init(self):
        """Client should accept custom values."""
        client = OllamaClient(
            base_url="http://custom:11435",
            model="mistral",
            timeout=120,
        )
        assert client.base_url == "http://custom:11435"
        assert client.model == "mistral"
        assert client.timeout == 120

    def test_base_url_strips_trailing_slash(self):
        """Base URL should not have trailing slash."""
        client = OllamaClient(base_url="http://localhost:11434/")
        assert client.base_url == "http://localhost:11434"


class TestOllamaClientAvailability:
    """Test Ollama availability checking."""

    @patch("hub.ollama.requests.get")
    def test_is_available_not_configured(self, mock_get):
        """Client should report unavailable when Ollama is not running."""
        import requests
        mock_get.side_effect = requests.ConnectionError("Connection refused")
        client = OllamaClient()
        assert client.is_available() is False

    @patch("hub.ollama.requests.get")
    def test_is_available_with_server(self, mock_get):
        """Client should report available when Ollama responds."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "llama3:latest"}]
        }
        mock_get.return_value = mock_resp

        client = OllamaClient()
        assert client.is_available() is True

    @patch("hub.ollama.requests.get")
    def test_is_available_wrong_model(self, mock_get):
        """Client should report unavailable when model is not found."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "mistral:latest"}]
        }
        mock_get.return_value = mock_resp

        client = OllamaClient(model="llama3")
        assert client.is_available() is False

    @patch("hub.ollama.requests.get")
    def test_is_available_caches_result(self, mock_get):
        """Availability check should be cached."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "models": [{"name": "llama3:latest"}]
        }
        mock_get.return_value = mock_resp

        client = OllamaClient()
        client.is_available()
        client.is_available()
        # Should only call once due to caching
        assert mock_get.call_count == 1


class TestRefinePrompt:
    """Test prompt refinement."""

    @patch.object(OllamaClient, "is_available", return_value=False)
    def test_refine_prompt_unavailable_returns_original(self, mock_available):
        """Refinement should return original prompt when Ollama is unavailable."""
        client = OllamaClient()
        original = "Fix the bug"
        result = client.refine_prompt(original)
        assert result == original

    @patch.object(OllamaClient, "is_available", return_value=True)
    @patch("hub.ollama.requests.post")
    def test_refine_prompt_success(self, mock_post, mock_available):
        """Refinement should return refined prompt on success."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": "Fix the bug in the authentication module by adding null checks"}
        }
        mock_post.return_value = mock_resp

        client = OllamaClient()
        result = client.refine_prompt("Fix the bug")
        assert "authentication" in result
        assert result != "Fix the bug"

    @patch.object(OllamaClient, "is_available", return_value=True)
    @patch("hub.ollama.requests.post")
    def test_refine_prompt_with_context(self, mock_post, mock_available):
        """Refinement should include context when provided."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": "Refined with context"}
        }
        mock_post.return_value = mock_resp

        client = OllamaClient()
        result = client.refine_prompt(
            "Fix the bug",
            context="The project uses FastAPI",
        )
        # Verify the request included context
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        user_msg = payload["messages"][1]["content"]
        assert "FastAPI" in user_msg

    @patch.object(OllamaClient, "is_available", return_value=True)
    @patch("hub.ollama.requests.post")
    def test_refine_prompt_failure_returns_original(self, mock_post, mock_available):
        """Refinement should return original on API failure."""
        import requests
        mock_post.side_effect = requests.RequestException("Connection error")

        client = OllamaClient()
        result = client.refine_prompt("Fix the bug")
        assert result == "Fix the bug"


class TestSummarize:
    """Test text summarization."""

    def test_summarize_unavailable_truncates(self):
        """Summarization should truncate when Ollama is unavailable."""
        client = OllamaClient()
        long_text = "A" * 1000
        result = client.summarize(long_text, max_length=100)
        assert len(result) <= 100
        assert result.endswith("...")

    def test_summarize_unavailable_short_text(self):
        """Short text should be returned as-is when unavailable."""
        client = OllamaClient()
        short_text = "Hello"
        result = client.summarize(short_text, max_length=100)
        assert result == short_text

    @patch.object(OllamaClient, "is_available", return_value=True)
    @patch("hub.ollama.requests.post")
    def test_summarize_success(self, mock_post, mock_available):
        """Summarization should return summary on success."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": "This is a summary"}
        }
        mock_post.return_value = mock_resp

        client = OllamaClient()
        result = client.summarize("A" * 1000)
        assert result == "This is a summary"

    @patch.object(OllamaClient, "is_available", return_value=True)
    @patch("hub.ollama.requests.post")
    def test_summarize_enforces_max_length(self, mock_post, mock_available):
        """Summary should be truncated if Ollama returns too long text."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": "A" * 1000}
        }
        mock_post.return_value = mock_resp

        client = OllamaClient()
        result = client.summarize("B" * 1000, max_length=100)
        assert len(result) <= 100


class TestDecomposeTask:
    """Test task decomposition."""

    def test_decompose_unavailable_returns_single_step(self):
        """Decomposition should return single step when unavailable."""
        client = OllamaClient()
        result = client.decompose_task("Build a feature")
        assert len(result) == 1
        assert result[0]["description"] == "Build a feature"

    @patch.object(OllamaClient, "is_available", return_value=True)
    @patch("hub.ollama.requests.post")
    def test_decompose_success(self, mock_post, mock_available):
        """Decomposition should return subtasks on success."""
        subtasks = [
            {"step": "1", "description": "Plan", "dependencies": []},
            {"step": "2", "description": "Implement", "dependencies": ["1"]},
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": json.dumps(subtasks)}
        }
        mock_post.return_value = mock_resp

        client = OllamaClient()
        result = client.decompose_task("Build a feature")
        assert len(result) == 2
        assert result[0]["description"] == "Plan"

    @patch.object(OllamaClient, "is_available", return_value=True)
    @patch("hub.ollama.requests.post")
    def test_decompose_code_block(self, mock_post, mock_available):
        """Decomposition should handle JSON in code blocks."""
        subtasks = [{"step": "1", "description": "Step 1", "dependencies": []}]
        json_str = json.dumps(subtasks)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": f"```json\n{json_str}\n```"}
        }
        mock_post.return_value = mock_resp

        client = OllamaClient()
        result = client.decompose_task("Build a feature")
        assert len(result) == 1
        assert result[0]["description"] == "Step 1"

    @patch.object(OllamaClient, "is_available", return_value=True)
    @patch("hub.ollama.requests.post")
    def test_decompose_invalid_json_fallback(self, mock_post, mock_available):
        """Decomposition should fallback on invalid JSON."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": "Not valid JSON"}
        }
        mock_post.return_value = mock_resp

        client = OllamaClient()
        result = client.decompose_task("Build a feature")
        assert len(result) == 1
        assert result[0]["description"] == "Build a feature"


class TestExtractKeyPoints:
    """Test key point extraction."""

    def test_extract_unavailable_returns_empty(self):
        """Extraction should return empty list when unavailable."""
        client = OllamaClient()
        result = client.extract_key_points("Some text")
        assert result == []

    @patch.object(OllamaClient, "is_available", return_value=True)
    @patch("hub.ollama.requests.post")
    def test_extract_success(self, mock_post, mock_available):
        """Extraction should return key points on success."""
        points = ["Point 1", "Point 2", "Point 3"]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": json.dumps(points)}
        }
        mock_post.return_value = mock_resp

        client = OllamaClient()
        result = client.extract_key_points("Some text")
        assert len(result) == 3
        assert "Point 1" in result

    @patch.object(OllamaClient, "is_available", return_value=True)
    @patch("hub.ollama.requests.post")
    def test_extract_limits_points(self, mock_post, mock_available):
        """Extraction should respect max_points limit."""
        points = [f"Point {i}" for i in range(20)]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": {"content": json.dumps(points)}
        }
        mock_post.return_value = mock_resp

        client = OllamaClient()
        result = client.extract_key_points("Some text", max_points=5)
        assert len(result) == 5


class TestGetOllamaClient:
    """Test get_ollama_client config function."""

    def test_not_configured_returns_none(self):
        """Should return None when Ollama is not configured."""
        with patch("hub.ollama.load_config") as mock_config:
            mock_config.return_value = {}
            client = get_ollama_client()
            assert client is None

    def test_disabled_returns_none(self):
        """Should return None when Ollama is disabled."""
        with patch("hub.ollama.load_config") as mock_config:
            mock_config.return_value = {"ollama": {"enabled": False}}
            client = get_ollama_client()
            assert client is None

    def test_enabled_returns_client(self):
        """Should return client when Ollama is enabled."""
        with patch("hub.ollama.load_config") as mock_config:
            mock_config.return_value = {
                "ollama": {
                    "enabled": True,
                    "base_url": "http://custom:11434",
                    "model": "mistral",
                }
            }
            client = get_ollama_client()
            assert client is not None
            assert client.base_url == "http://custom:11434"
            assert client.model == "mistral"


class TestOllamaAPI:
    """Test Ollama API endpoints."""

    def test_ollama_status_not_configured(self, client):
        """Ollama status should return enabled=false when not configured."""
        resp = client.get("/api/ollama/status", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is False

    def test_ollama_refine_not_configured(self, client):
        """Refine should fail when Ollama is not configured."""
        resp = client.post(
            "/api/ollama/refine",
            headers=HEADERS,
            json={"prompt": "Fix the bug"},
        )
        assert resp.status_code == 400

    def test_ollama_summarize_not_configured(self, client):
        """Summarize should fail when Ollama is not configured."""
        resp = client.post(
            "/api/ollama/summarize",
            headers=HEADERS,
            json={"text": "Some long text"},
        )
        assert resp.status_code == 400

    def test_ollama_decompose_not_configured(self, client):
        """Decompose should fail when Ollama is not configured."""
        resp = client.post(
            "/api/ollama/decompose",
            headers=HEADERS,
            json={"task": "Build a feature"},
        )
        assert resp.status_code == 400

    def test_ollama_refine_missing_prompt(self, client):
        """Refine should fail without prompt."""
        resp = client.post(
            "/api/ollama/refine",
            headers=HEADERS,
            json={},
        )
        assert resp.status_code in (400, 422)

    def test_ollama_summarize_missing_text(self, client):
        """Summarize should fail without text."""
        resp = client.post(
            "/api/ollama/summarize",
            headers=HEADERS,
            json={},
        )
        assert resp.status_code in (400, 422)

    def test_ollama_decompose_missing_task(self, client):
        """Decompose should fail without task."""
        resp = client.post(
            "/api/ollama/decompose",
            headers=HEADERS,
            json={},
        )
        assert resp.status_code in (400, 422)


# Import test fixtures from test_api
from tests.test_api import HEADERS, client  # noqa: E402, F401
