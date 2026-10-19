"""Optional Ollama integration for prompt refinement, summarization, and task decomposition."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from hub.config import load_config

logger = logging.getLogger(__name__)

# Default Ollama settings
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3"
DEFAULT_TIMEOUT = 60  # seconds


class OllamaError(Exception):
    """Raised when Ollama API calls fail."""

    pass


class OllamaClient:
    """Client for communicating with a local Ollama instance.

    Supports prompt refinement, summarization, and task decomposition.
    All operations are optional — if Ollama is unavailable, methods return
    the original input unchanged rather than raising errors.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._available = False
        self._check_cache: Optional[bool] = None
        self._check_time: Optional[float] = None

    def is_available(self) -> bool:
        """Check if Ollama is running and the configured model is available."""
        # Cache the result for 60 seconds to avoid repeated checks
        now = datetime.now(timezone.utc).timestamp()
        if self._check_cache is not None and (now - self._check_time) < 60:
            return self._check_cache

        try:
            resp = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5,
            )
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                model_names = [m.get("name", "").split(":")[0] for m in models]
                self._check_cache = self.model.split(":")[0] in model_names
                self._check_time = now
                return self._check_cache
        except (requests.RequestException, json.JSONDecodeError):
            pass

        self._check_cache = False
        self._check_time = now
        return False

    def _chat(self, messages: List[Dict[str, str]], stream: bool = False) -> Optional[str]:
        """Send a chat completion request to Ollama.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            stream: If True, return None (streaming not used in this integration).

        Returns:
            The assistant's response text, or None on failure.
        """
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
            }
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                message = data.get("message", {})
                return message.get("content", "")
            logger.warning("Ollama returned status %d", resp.status_code)
        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.warning("Ollama request failed: %s", e)
        return None

    def refine_prompt(
        self,
        prompt: str,
        context: Optional[str] = None,
        system_instruction: Optional[str] = None,
    ) -> str:
        """Refine a user prompt for clarity and completeness.

        Sends the prompt to Ollama with instructions to improve clarity,
        add missing details, and structure the request — without changing
        the user's intent.

        Args:
            prompt: The original user prompt.
            context: Optional additional context (e.g., project info).
            system_instruction: Optional custom system instruction.

        Returns:
            The refined prompt, or the original prompt if refinement fails.
        """
        if not self.is_available():
            return prompt

        system = system_instruction or (
            "You are a prompt refinement assistant. Your job is to improve the clarity and "
            "completeness of user prompts for coding agents. Preserve the user's original intent "
            "and requested actions. Do not change the core task — only make it clearer, more "
            "specific, and better structured. If the prompt is already clear, return it unchanged. "
            "Return only the refined prompt, without explanation or commentary."
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system},
        ]

        user_content = f"Refine this prompt:\n\n{prompt}"
        if context:
            user_content += f"\n\nAdditional context:\n{context}"

        messages.append({"role": "user", "content": user_content})

        refined = self._chat(messages)
        if refined and refined.strip():
            return refined.strip()
        return prompt

    def summarize(
        self,
        text: str,
        max_length: int = 500,
        focus: Optional[str] = None,
    ) -> str:
        """Summarize long text (e.g., agent output or conversation history).

        Args:
            text: The text to summarize.
            max_length: Maximum length of the summary in characters.
            focus: Optional focus area for the summary (e.g., "errors", "changes").

        Returns:
            The summary, or a truncated version of the original text if summarization fails.
        """
        if not self.is_available():
            # Fallback: truncate with ellipsis
            if len(text) <= max_length:
                return text
            return text[: max_length - 3] + "..."

        system = (
            "You are a summarization assistant. Create concise, accurate summaries. "
            "Preserve key facts, decisions, and action items. "
        )
        if focus:
            system += f"Focus particularly on: {focus}. "

        system += f"Keep the summary under {max_length} characters."

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Summarize this text:\n\n{text}"},
        ]

        summary = self._chat(messages)
        if summary and summary.strip():
            summary = summary.strip()
            # Enforce max_length even if Ollama returns longer text
            if len(summary) > max_length:
                return summary[: max_length - 3] + "..."
            return summary

        # Fallback: truncate
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."

    def decompose_task(
        self,
        task: str,
        context: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Decompose a complex task into subtasks.

        Args:
            task: The task to decompose.
            context: Optional additional context.

        Returns:
            A list of subtask dicts with 'step', 'description', and 'dependencies' keys.
            Returns a single-step list with the original task if decomposition fails.
        """
        if not self.is_available():
            return [{"step": "1", "description": task, "dependencies": []}]

        system = (
            "You are a task decomposition assistant. Break complex coding tasks into "
            "ordered, actionable subtasks. Each subtask should be specific and testable. "
            "Return a JSON array of objects with 'step' (number), 'description' (text), "
            "and 'dependencies' (list of step numbers this step depends on). "
            "Do not add explanation outside the JSON array."
        )

        user_content = f"Decompose this task into subtasks:\n\n{task}"
        if context:
            user_content += f"\n\nContext:\n{context}"

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

        result = self._chat(messages)
        if result:
            try:
                # Try to parse JSON from the response
                result = result.strip()
                if result.startswith("```"):
                    # Extract JSON from code block
                    lines = result.split("\n")
                    json_start = None
                    json_end = None
                    for i, line in enumerate(lines):
                        if "```" in line and json_start is None:
                            json_start = i + 1
                        elif "```" in line and json_start is not None:
                            json_end = i
                            break
                    if json_start is not None and json_end is not None:
                        result = "\n".join(lines[json_start:json_end]).strip()

                subtasks = json.loads(result)
                if isinstance(subtasks, list) and len(subtasks) > 0:
                    return subtasks
            except (json.JSONDecodeError, ValueError):
                logger.warning("Failed to parse Ollama task decomposition response")

        return [{"step": "1", "description": task, "dependencies": []}]

    def extract_key_points(
        self,
        text: str,
        max_points: int = 10,
    ) -> List[str]:
        """Extract key points from text (e.g., agent output or conversation).

        Args:
            text: The text to extract key points from.
            max_points: Maximum number of key points to extract.

        Returns:
            A list of key point strings. Returns an empty list if extraction fails.
        """
        if not self.is_available():
            return []

        system = (
            f"Extract the {max_points} most important key points from the following text. "
            "Return a JSON array of short, concise strings. Focus on decisions, "
            "action items, errors, and important findings. Do not add explanation."
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ]

        result = self._chat(messages)
        if result:
            try:
                result = result.strip()
                if result.startswith("```"):
                    lines = result.split("\n")
                    json_start = None
                    json_end = None
                    for i, line in enumerate(lines):
                        if "```" in line and json_start is None:
                            json_start = i + 1
                        elif "```" in line and json_start is not None:
                            json_end = i
                            break
                    if json_start is not None and json_end is not None:
                        result = "\n".join(lines[json_start:json_end]).strip()

                points = json.loads(result)
                if isinstance(points, list):
                    return [str(p) for p in points[:max_points]]
            except (json.JSONDecodeError, ValueError):
                logger.warning("Failed to parse Ollama key points response")

        return []


def get_ollama_client() -> Optional[OllamaClient]:
    """Get an Ollama client from config, or None if not configured/available."""
    config = load_config()
    ollama_cfg = config.get("ollama", {})

    if not ollama_cfg.get("enabled", False):
        return None

    base_url = ollama_cfg.get("base_url", DEFAULT_BASE_URL)
    model = ollama_cfg.get("model", DEFAULT_MODEL)
    timeout = ollama_cfg.get("timeout", DEFAULT_TIMEOUT)

    return OllamaClient(base_url=base_url, model=model, timeout=timeout)
