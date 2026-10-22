"""Secret redaction filter for structured logs.

Redacts sensitive values (API keys, passwords, tokens, secrets) from
log messages before they are written. This prevents accidental leakage
of credentials in log files, telemetry, and error reports.

Configuration:
    REDACT_SECRETS: Enable/disable secret redaction (default: True)
"""

import os
import re
from typing import List, Pattern

# ─── Configuration ────────────────────────────────────────────────

REDACT_SECRETS = os.environ.get("REDACT_SECRETS", "true").lower() in ("true", "1", "yes")

# ─── Patterns for sensitive data ──────────────────────────────────

# Common patterns that indicate sensitive data
_SENSITIVE_PATTERNS: List[Pattern] = [
    # API keys (various formats)
    re.compile(r'(api[_-]?key["\s:=]+["\']?)([A-Za-z0-9_\-]{20,})', re.IGNORECASE),
    re.compile(r'(apikey["\s:=]+["\']?)([A-Za-z0-9_\-]{20,})', re.IGNORECASE),
    # Bearer tokens
    re.compile(r'(Bearer\s+)([A-Za-z0-9_\-\.]{20,})', re.IGNORECASE),
    # Passwords
    re.compile(r'(password["\s:=]+["\']?)([^"\s,}]{4,})', re.IGNORECASE),
    re.compile(r'(passwd["\s:=]+["\']?)([^"\s,}]{4,})', re.IGNORECASE),
    # Secret keys
    re.compile(r'(secret[_-]?key["\s:=]+["\']?)([A-Za-z0-9_\-]{16,})', re.IGNORECASE),
    re.compile(r'(secret["\s:=]+["\']?)([A-Za-z0-9_\-]{16,})', re.IGNORECASE),
    # Access tokens
    re.compile(r'(access[_-]?token["\s:=]+["\']?)([A-Za-z0-9_\-\.]{20,})', re.IGNORECASE),
    # Private keys
    re.compile(r'(-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----)(.*?)(-----END\s+(RSA\s+)?PRIVATE\s+KEY-----)', re.DOTALL),
    # AWS credentials
    re.compile(r'(AKIA[0-9A-Z]{16})'),
    re.compile(r'(aws_secret_access_key["\s:=]+["\']?)([A-Za-z0-9/+=]{40})', re.IGNORECASE),
    # Generic token patterns
    re.compile(r'(token["\s:=]+["\']?)([A-Za-z0-9_\-\.]{20,})', re.IGNORECASE),
    # Connection strings with passwords
    re.compile(r'([A-Za-z]+://[^:]+:)([^@]+)(@)', re.IGNORECASE),
]

_REDACTED = "[REDACTED]"


def redact_secrets(text: str) -> str:
    """Redact sensitive data from a string.

    Args:
        text: The text to redact.

    Returns:
        The text with sensitive values replaced by [REDACTED].
    """
    if not REDACT_SECRETS:
        return text

    for pattern in _SENSITIVE_PATTERNS:
        if pattern.pattern.startswith('(') and '-----BEGIN' in pattern.pattern:
            # Special handling for multi-line private keys
            text = pattern.sub(r'\1' + _REDACTED + r'\4', text)
        else:
            text = pattern.sub(r'\1' + _REDACTED, text)

    return text


class SecretRedactionFilter:
    """Python logging filter that redacts secrets from log records.

    Usage:
        import logging
        logger = logging.getLogger()
        logger.addFilter(SecretRedactionFilter())
    """

    def filter(self, record) -> bool:
        """Filter a log record, redacting secrets in place.

        Args:
            record: The logging.LogRecord to filter.

        Returns:
            True to allow the record to be logged.
        """
        if not REDACT_SECRETS:
            return True

        # Redact the message
        if hasattr(record, 'msg'):
            if isinstance(record.msg, str):
                record.msg = redact_secrets(record.msg)
            elif isinstance(record.msg, bytes):
                try:
                    record.msg = redact_secrets(record.msg.decode('utf-8', errors='replace'))
                except Exception:
                    pass

        # Redact args
        if hasattr(record, 'args') and record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact_secrets(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact_secrets(str(a)) if isinstance(a, str) else a
                    for a in record.args
                )

        # Redact exc_text if present
        if hasattr(record, 'exc_text') and record.exc_text:
            record.exc_text = redact_secrets(record.exc_text)

        return True


def add_secret_redaction_filter(logger=None):
    """Add secret redaction filter to a logger.

    Args:
        logger: The logger to add the filter to. If None, uses root logger.
    """
    import logging
    if logger is None:
        logger = logging.getLogger()
    logger.addFilter(SecretRedactionFilter())
    return logger
