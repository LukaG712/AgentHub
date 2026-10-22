"""LLM provider abstraction layer.

Supports multiple AI backends (OpenAI, Anthropic, Google AI, Ollama) as
alternatives to the default Junie CLI runner. Each provider implements the
same interface so agents can switch backends without code changes.

Configuration via environment variables:
    LLM_PROVIDER: Backend to use (default: "ollama")
    OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY: API keys
    OPENAI_MODEL, ANTHROPIC_MODEL, GOOGLE_MODEL: Model names
    OLLAMA_URL, OLLAMA_MODEL: Ollama settings

Usage:
    from hub.llm_providers import get_llm_provider
    provider = get_llm_provider()
    result = await provider.complete("What is 2+2?")
    async for chunk in provider.stream("Write a poem"):
        print(chunk)
"""

import os
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional

# ─── Base Interface ──────────────────────────────────────────────────────────

class LLMProvider(ABC):
    """Base class for all LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'openai', 'anthropic')."""

    @abstractmethod
    def check_available(self) -> bool:
        """Check if the provider is configured and reachable."""

    @abstractmethod
    async def complete(self, prompt: str, system: Optional[str] = None, **kwargs) -> str:
        """Send a completion request and return the full response."""

    @abstractmethod
    async def stream(self, prompt: str, system: Optional[str] = None, **kwargs) -> AsyncIterator[str]:
        """Stream a completion response token by token."""


# ─── Ollama Provider ─────────────────────────────────────────────────────────

class OllamaProvider(LLMProvider):
    """Provider for local Ollama instances."""

    @property
    def name(self) -> str:
        return "ollama"

    def check_available(self) -> bool:
        url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        try:
            import httpx
            resp = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=3.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def complete(self, prompt: str, system: Optional[str] = None, **kwargs) -> str:
        import httpx
        url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        model = os.environ.get("OLLAMA_MODEL", "gemma4:12b")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{url}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
            )
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")

    async def stream(self, prompt: str, system: Optional[str] = None, **kwargs) -> AsyncIterator[str]:
        import json as json_mod

        import httpx
        url = os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        model = os.environ.get("OLLAMA_MODEL", "gemma4:12b")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{url}/api/chat",
                json={"model": model, "messages": messages, "stream": True},
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json_mod.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
                    except json_mod.JSONDecodeError:
                        continue


# ─── OpenAI Provider ─────────────────────────────────────────────────────────

class OpenAIProvider(LLMProvider):
    """Provider for OpenAI API (GPT-4, GPT-3.5, etc.)."""

    @property
    def name(self) -> str:
        return "openai"

    def check_available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY"))

    async def complete(self, prompt: str, system: Optional[str] = None, **kwargs) -> str:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        model = os.environ.get("OPENAI_MODEL", "gpt-4o")
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

        import httpx
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "messages": messages, "stream": False},
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def stream(self, prompt: str, system: Optional[str] = None, **kwargs) -> AsyncIterator[str]:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        model = os.environ.get("OPENAI_MODEL", "gpt-4o")
        base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

        import json as json_mod

        import httpx
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": model, "messages": messages, "stream": True},
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json_mod.loads(data)
                        content = chunk["choices"][0].get("delta", {}).get("content", "")
                        if content:
                            yield content
                    except (json_mod.JSONDecodeError, KeyError, IndexError):
                        continue


# ─── Anthropic Provider ──────────────────────────────────────────────────────

class AnthropicProvider(LLMProvider):
    """Provider for Anthropic API (Claude)."""

    @property
    def name(self) -> str:
        return "anthropic"

    def check_available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY"))

    async def complete(self, prompt: str, system: Optional[str] = None, **kwargs) -> str:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")

        import httpx
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": kwargs.get("max_tokens", 4096),
        }
        if system:
            body["system"] = system

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{base_url}/messages", headers=headers, json=body)
            resp.raise_for_status()
            return resp.json()["content"][0]["text"]

    async def stream(self, prompt: str, system: Optional[str] = None, **kwargs) -> AsyncIterator[str]:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")

        import httpx
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        body = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": True,
        }
        if system:
            body["system"] = system

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream("POST", f"{base_url}/messages", headers=headers, json=body) as resp:
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    try:
                        import json as json_mod
                        chunk = json_mod.loads(data)
                        if chunk.get("type") == "content_block_delta":
                            yield chunk.get("delta", {}).get("text", "")
                    except Exception:
                        continue


# ─── Google AI Provider ──────────────────────────────────────────────────────

class GoogleAIProvider(LLMProvider):
    """Provider for Google AI (Gemini)."""

    @property
    def name(self) -> str:
        return "google"

    def check_available(self) -> bool:
        return bool(os.environ.get("GOOGLE_API_KEY"))

    async def complete(self, prompt: str, system: Optional[str] = None, **kwargs) -> str:
        api_key = os.environ.get("GOOGLE_API_KEY", "")
        model = os.environ.get("GOOGLE_MODEL", "gemini-2.0-flash")
        base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        import httpx
        parts = [{"text": prompt}]
        if system:
            parts.insert(0, {"text": f"System: {system}"})

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                base_url,
                json={"contents": [{"parts": parts}]},
            )
            resp.raise_for_status()
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]

    async def stream(self, prompt: str, system: Optional[str] = None, **kwargs) -> AsyncIterator[str]:
        api_key = os.environ.get("GOOGLE_API_KEY", "")
        model = os.environ.get("GOOGLE_MODEL", "gemini-2.0-flash")
        base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={api_key}"

        import json as json_mod

        import httpx
        parts = [{"text": prompt}]
        if system:
            parts.insert(0, {"text": f"System: {system}"})

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                base_url,
                json={"contents": [{"parts": parts}]},
            ) as resp:
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json_mod.loads(line)
                        text = chunk["candidates"][0]["content"]["parts"][0]["text"]
                        if text:
                            yield text
                    except (json_mod.JSONDecodeError, KeyError, IndexError):
                        continue


# ─── Provider Registry ───────────────────────────────────────────────────────

_providers: Dict[str, type] = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleAIProvider,
}


def list_providers() -> List[str]:
    """List available LLM provider names."""
    return list(_providers.keys())


def register_provider(name: str, cls: type):
    """Register a custom LLM provider."""
    if not issubclass(cls, LLMProvider):
        raise ValueError(f"{cls} must be a subclass of LLMProvider")
    _providers[name] = cls


def get_llm_provider(name: Optional[str] = None) -> LLMProvider:
    """Get an LLM provider instance by name.

    Args:
        name: Provider name. Defaults to LLM_PROVIDER env var or 'ollama'.

    Returns:
        Configured LLM provider instance.

    Raises:
        ValueError: If the provider is not found.
    """
    name = name or os.environ.get("LLM_PROVIDER", "ollama").lower()
    cls = _providers.get(name)
    if cls is None:
        available = ", ".join(_providers.keys())
        raise ValueError(
            f"Unknown LLM provider '{name}'. Available: {available}"
        )
    return cls()


def get_available_providers() -> List[Dict[str, Any]]:
    """List all providers with their availability status."""
    result = []
    for name, cls in _providers.items():
        try:
            instance = cls()
            result.append({
                "name": name,
                "available": instance.check_available(),
            })
        except Exception as e:
            result.append({
                "name": name,
                "available": False,
                "error": str(e),
            })
    return result
