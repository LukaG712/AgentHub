"""Structured JSON logging configuration for Greenie.

Provides JSON-formatted logs with request context, timing, and correlation IDs
for queryable log aggregation and cross-service debugging.
"""

import json
import logging
import sys
import time
import uuid
from typing import Any, Dict


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON for machine-readable log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add request ID if available
        if hasattr(record, "request_id"):
            log_data["request_id"] = record.request_id

        # Add service context
        log_data["service"] = "Greenie"

        # Add exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add any extra fields
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "message", "pathname", "process", "processName",
                "relativeCreated", "stack_info", "exc_info", "exc_text",
                "thread", "threadName", "request_id", "task_name",
            ):
                log_data[key] = value

        return json.dumps(log_data, default=str)


def setup_structured_logging(level: str = "INFO") -> None:
    """Configure root logger to use JSON formatting.

    Args:
        level: Logging level string (DEBUG, INFO, WARNING, ERROR).
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates on reload
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)

    # Silence noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class RequestIDFilter(logging.Filter):
    """Injects request_id into log records for correlation tracing."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = str(uuid.uuid4())[:8]
        return True


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name.

    Args:
        name: Logger name, typically __name__.

    Returns:
        Configured logging.Logger instance.
    """
    return logging.getLogger(name)
