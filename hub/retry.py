"""Retry utility with exponential backoff for service-to-service HTTP calls.

Provides both sync and async retry decorators that implement exponential backoff
with jitter to prevent thundering herd problems when services recover.

Usage:
    # Async retry
    @retry(max_attempts=3, backoff_factor=0.5, retry_on=(httpx.ConnectError, httpx.TimeoutException))
    async def call_service():
        ...

    # Sync retry
    @retry_sync(max_attempts=3, backoff_factor=0.5, retry_on=(httpx.ConnectError, httpx.TimeoutException))
    def call_service():
        ...
"""

import asyncio
import logging
import random
import time
from functools import wraps
from typing import Callable, Optional, Tuple, Type, Union

logger = logging.getLogger(__name__)


# Default exceptions to retry on — transient network/service errors
DEFAULT_RETRY_EXCEPTIONS = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def _calculate_backoff(
    attempt: int,
    backoff_factor: float,
    max_backoff: float,
    jitter: bool = True,
) -> float:
    """Calculate the backoff delay for a given attempt.

    Uses exponential backoff with optional jitter:
        delay = min(backoff_factor * 2^attempt + jitter, max_backoff)
    """
    delay = backoff_factor * (2 ** attempt)
    if jitter:
        delay += random.uniform(0, backoff_factor)
    return min(delay, max_backoff)


def retry(
    max_attempts: int = 3,
    backoff_factor: float = 0.5,
    max_backoff: float = 10.0,
    retry_on: Optional[Tuple[Type[Exception], ...]] = None,
    jitter: bool = True,
    log_level: int = logging.WARNING,
):
    """Async retry decorator with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts before giving up.
        backoff_factor: Base delay in seconds between attempts.
        max_backoff: Maximum delay in seconds between attempts.
        retry_on: Tuple of exception types to retry on. Defaults to network errors.
        jitter: Add random jitter to prevent thundering herd.
        log_level: Logging level for retry attempts.
    """
    exceptions = retry_on or DEFAULT_RETRY_EXCEPTIONS

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        delay = _calculate_backoff(attempt, backoff_factor, max_backoff, jitter)
                        logger.log(
                            log_level,
                            f"Retry {attempt + 1}/{max_attempts} for {func.__name__}: "
                            f"{type(e).__name__}: {e}. Retrying in {delay:.2f}s...",
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"Retry {attempt + 1}/{max_attempts} for {func.__name__} failed: "
                            f"{type(e).__name__}: {e}. No more attempts."
                        )
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator


def retry_sync(
    max_attempts: int = 3,
    backoff_factor: float = 0.5,
    max_backoff: float = 10.0,
    retry_on: Optional[Tuple[Type[Exception], ...]] = None,
    jitter: bool = True,
    log_level: int = logging.WARNING,
):
    """Sync retry decorator with exponential backoff.

    Args:
        max_attempts: Maximum number of attempts before giving up.
        backoff_factor: Base delay in seconds between attempts.
        max_backoff: Maximum delay in seconds between attempts.
        retry_on: Tuple of exception types to retry on. Defaults to network errors.
        jitter: Add random jitter to prevent thundering herd.
        log_level: Logging level for retry attempts.
    """
    exceptions = retry_on or DEFAULT_RETRY_EXCEPTIONS

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        delay = _calculate_backoff(attempt, backoff_factor, max_backoff, jitter)
                        logger.log(
                            log_level,
                            f"Retry {attempt + 1}/{max_attempts} for {func.__name__}: "
                            f"{type(e).__name__}: {e}. Retrying in {delay:.2f}s...",
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"Retry {attempt + 1}/{max_attempts} for {func.__name__} failed: "
                            f"{type(e).__name__}: {e}. No more attempts."
                        )
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator


class RetryConfig:
    """Configuration for retry behavior on a per-service basis."""

    def __init__(
        self,
        max_attempts: int = 3,
        backoff_factor: float = 0.5,
        max_backoff: float = 10.0,
        retry_on: Optional[Tuple[Type[Exception], ...]] = None,
        jitter: bool = True,
    ):
        self.max_attempts = max_attempts
        self.backoff_factor = backoff_factor
        self.max_backoff = max_backoff
        self.retry_on = retry_on or DEFAULT_RETRY_EXCEPTIONS
        self.jitter = jitter

    def get_async_decorator(self):
        """Return an async retry decorator with this config."""
        return retry(
            max_attempts=self.max_attempts,
            backoff_factor=self.backoff_factor,
            max_backoff=self.max_backoff,
            retry_on=self.retry_on,
            jitter=self.jitter,
        )

    def get_sync_decorator(self):
        """Return a sync retry decorator with this config."""
        return retry_sync(
            max_attempts=self.max_attempts,
            backoff_factor=self.backoff_factor,
            max_backoff=self.max_backoff,
            retry_on=self.retry_on,
            jitter=self.jitter,
        )


# Pre-configured retry configs for common service types
STORAGE_RETRY = RetryConfig(
    max_attempts=3,
    backoff_factor=0.5,
    max_backoff=5.0,
)

EXECUTION_RETRY = RetryConfig(
    max_attempts=2,
    backoff_factor=1.0,
    max_backoff=10.0,
)

SCRAPING_RETRY = RetryConfig(
    max_attempts=3,
    backoff_factor=0.3,
    max_backoff=3.0,
)
