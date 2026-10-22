"""Secret redaction for mission logs and model context.

Prevents accidental leakage of API keys, tokens, passwords, and other
sensitive data in logs, model prompts, and responses.
"""

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Patterns that match common secret formats
_SECRET_PATTERNS = [
    # API keys and tokens
    (re.compile(r"(?i)(api[_-]?key|apikey)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{20,})['\"]?"), r"\1: [REDACTED]"),
    (re.compile(r"(?i)(bearer)\s+([A-Za-z0-9_\-\.]{20,})"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)(token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{20,})['\"]?"), r"\1: [REDACTED]"),
    (re.compile(r"(?i)(password|passwd|pwd)\s*[:=]\s*['\"]?([^'\"\s]{8,})['\"]?"), r"\1: [REDACTED]"),
    (re.compile(r"(?i)(secret)\s*[:=]\s*['\"]?([^'\"\s]{8,})['\"]?"), r"\1: [REDACTED]"),
    (re.compile(r"(?i)(access[_-]?token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{20,})['\"]?"), r"\1: [REDACTED]"),
    (re.compile(r"(?i)(private[_-]?key)\s*[:=]\s*['\"]?([^'\"\s]{20,})['\"]?"), r"\1: [REDACTED]"),

    # GitHub tokens
    (re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}"), "[REDACTED]"),

    # AWS keys
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED]"),

    # Generic long hex strings that look like tokens
    (re.compile(r"(?<![A-Za-z0-9_])[0-9a-f]{40,}(?![A-Za-z0-9_])"), "[REDACTED]"),

    # Email addresses in logs (privacy)
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[EMAIL REDACTED]"),
]

# Known secret environment variable names
_SECRET_ENV_VARS = {
    "API_KEY", "API_SECRET", "SECRET_KEY", "PRIVATE_KEY",
    "ACCESS_TOKEN", "REFRESH_TOKEN", "BEARER_TOKEN",
    "PASSWORD", "PASSWD", "PWD",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    "GITHUB_TOKEN", "GH_TOKEN",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY",
    "DATABASE_URL", "DB_PASSWORD", "DB_PASS",
}


def redact_secrets(text: str) -> str:
    """Redact secrets from a string.

    Replaces known secret patterns with [REDACTED] placeholders.
    Safe to call on any string — returns the original if no secrets found.
    """
    if not text:
        return text

    result = text
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)

    return result


def redact_env_vars(env: dict[str, str]) -> dict[str, str]:
    """Redact secret values from an environment variable dictionary.

    Returns a new dict with sensitive values replaced by [REDACTED].
    """
    redacted = {}
    for key, value in env.items():
        # Check if the key name suggests a secret
        key_upper = key.upper()
        is_secret = any(secret_name in key_upper for secret_name in _SECRET_ENV_VARS)
        redacted[key] = "[REDACTED]" if is_secret else value
    return redacted


def redact_dict(data: dict[str, Any], secret_keys: set[str] | None = None) -> dict[str, Any]:
    """Redact secret values from a dictionary.

    Recursively walks the dictionary and redacts values for known secret keys.
    """
    if not data:
        return data

    default_secret_keys = {
        "api_key", "api_secret", "secret_key", "private_key",
        "access_token", "refresh_token", "bearer_token",
        "password", "passwd", "pwd", "token", "secret",
        "github_token", "openai_api_key", "anthropic_api_key",
    }
    keys_to_redact = default_secret_keys | (secret_keys or set())

    redacted = {}
    for key, value in data.items():
        if isinstance(key, str) and key.lower() in keys_to_redact:
            redacted[key] = "[REDACTED]"
        elif isinstance(value, dict):
            redacted[key] = redact_dict(value, secret_keys)
        elif isinstance(value, list):
            redacted[key] = [
                redact_dict(item, secret_keys) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            redacted[key] = value
    return redacted


def redact_model_context(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Redact secrets from LLM message context.

    Processes a list of {role, content} messages and redacts secrets
    from the content field.
    """
    if not messages:
        return messages

    redacted = []
    for msg in messages:
        if isinstance(msg, dict) and "content" in msg:
            new_msg = msg.copy()
            new_msg["content"] = redact_secrets(msg["content"])
            redacted.append(new_msg)
        else:
            redacted.append(msg)
    return redacted


def redact_log_record(record: logging.LogRecord) -> logging.LogRecord:
    """Redact secrets from a log record's message.

    Use as a logging filter to automatically redact secrets in all log output.
    """
    if record.msg:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        elif isinstance(record.msg, bytes):
            try:
                record.msg = redact_secrets(record.msg.decode("utf-8", errors="replace"))
            except Exception:
                pass
    return record


class SecretRedactionFilter(logging.Filter):
    """Logging filter that redacts secrets from log messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        redact_log_record(record)
        return True


def is_sensitive_key(key: str) -> bool:
    """Check if a key name suggests it contains a secret."""
    key_upper = key.upper()
    return any(secret_name in key_upper for secret_name in _SECRET_ENV_VARS)
