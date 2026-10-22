"""Tests for the retry utility module."""

import asyncio
import time
from unittest.mock import patch, MagicMock

import pytest

from hub.retry import (
    retry,
    retry_sync,
    RetryConfig,
    _calculate_backoff,
    STORAGE_RETRY,
    EXECUTION_RETRY,
    SCRAPING_RETRY,
)


class TestCalculateBackoff:
    """Test the backoff calculation function."""

    def test_first_attempt(self):
        """First attempt should have small delay."""
        delay = _calculate_backoff(0, backoff_factor=1.0, max_backoff=10.0, jitter=False)
        assert delay == 1.0  # 1.0 * 2^0 = 1.0

    def test_second_attempt(self):
        """Second attempt should have doubled delay."""
        delay = _calculate_backoff(1, backoff_factor=1.0, max_backoff=10.0, jitter=False)
        assert delay == 2.0  # 1.0 * 2^1 = 2.0

    def test_third_attempt(self):
        """Third attempt should have quadrupled delay."""
        delay = _calculate_backoff(2, backoff_factor=1.0, max_backoff=10.0, jitter=False)
        assert delay == 4.0  # 1.0 * 2^2 = 4.0

    def test_max_backoff_cap(self):
        """Delay should not exceed max_backoff."""
        delay = _calculate_backoff(10, backoff_factor=1.0, max_backoff=5.0, jitter=False)
        assert delay == 5.0

    def test_jitter_adds_randomness(self):
        """Jitter should add random value."""
        delay_no_jitter = _calculate_backoff(0, backoff_factor=1.0, max_backoff=10.0, jitter=False)
        delay_with_jitter = _calculate_backoff(0, backoff_factor=1.0, max_backoff=10.0, jitter=True)
        # With jitter, delay should be >= base delay
        assert delay_with_jitter >= delay_no_jitter


class TestRetrySync:
    """Test the sync retry decorator."""

    def test_success_first_attempt(self):
        """Should return immediately on success."""
        call_count = 0

        @retry_sync(max_attempts=3, backoff_factor=0.01)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = succeed()
        assert result == "ok"
        assert call_count == 1

    def test_retry_on_failure(self):
        """Should retry on transient errors."""
        call_count = 0

        @retry_sync(max_attempts=3, backoff_factor=0.01, retry_on=(ValueError,))
        def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient")
            return "ok"

        result = fail_then_succeed()
        assert result == "ok"
        assert call_count == 3

    def test_give_up_after_max_attempts(self):
        """Should raise after max attempts exhausted."""
        call_count = 0

        @retry_sync(max_attempts=3, backoff_factor=0.01, retry_on=(ValueError,))
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("permanent")

        with pytest.raises(ValueError, match="permanent"):
            always_fail()
        assert call_count == 3

    def test_no_retry_on_unexpected_exception(self):
        """Should not retry on exceptions not in retry_on."""
        call_count = 0

        @retry_sync(max_attempts=3, backoff_factor=0.01, retry_on=(ValueError,))
        def raise_key_error():
            nonlocal call_count
            call_count += 1
            raise KeyError("not retried")

        with pytest.raises(KeyError):
            raise_key_error()
        assert call_count == 1

    def test_default_retry_on_connection_errors(self):
        """Should retry on ConnectionError by default."""
        call_count = 0

        @retry_sync(max_attempts=2, backoff_factor=0.01)
        def connection_fail_then_ok():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("network down")
            return "connected"

        result = connection_fail_then_ok()
        assert result == "connected"
        assert call_count == 2


class TestRetryAsync:
    """Test the async retry decorator."""

    @pytest.mark.asyncio
    async def test_success_first_attempt(self):
        """Should return immediately on success."""
        call_count = 0

        @retry(max_attempts=3, backoff_factor=0.01)
        async def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await succeed()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """Should retry on transient errors."""
        call_count = 0

        @retry(max_attempts=3, backoff_factor=0.01, retry_on=(ValueError,))
        async def fail_then_succeed():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient")
            return "ok"

        result = await fail_then_succeed()
        assert result == "ok"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_give_up_after_max_attempts(self):
        """Should raise after max attempts exhausted."""
        call_count = 0

        @retry(max_attempts=3, backoff_factor=0.01, retry_on=(ValueError,))
        async def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("permanent")

        with pytest.raises(ValueError, match="permanent"):
            await always_fail()
        assert call_count == 3


class TestRetryConfig:
    """Test the RetryConfig class."""

    def test_storage_retry_defaults(self):
        """Storage retry should have reasonable defaults."""
        assert STORAGE_RETRY.max_attempts == 3
        assert STORAGE_RETRY.backoff_factor == 0.5
        assert STORAGE_RETRY.max_backoff == 5.0

    def test_execution_retry_defaults(self):
        """Execution retry should be more conservative."""
        assert EXECUTION_RETRY.max_attempts == 2
        assert EXECUTION_RETRY.backoff_factor == 1.0
        assert EXECUTION_RETRY.max_backoff == 10.0

    def test_scraping_retry_defaults(self):
        """Scraping retry should be fast."""
        assert SCRAPING_RETRY.max_attempts == 3
        assert SCRAPING_RETRY.backoff_factor == 0.3
        assert SCRAPING_RETRY.max_backoff == 3.0

    def test_get_async_decorator(self):
        """Should return an async retry decorator."""
        config = RetryConfig(max_attempts=2, backoff_factor=0.01)
        decorator = config.get_async_decorator()

        call_count = 0

        @decorator
        async def func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError()
            return "ok"

        result = asyncio.get_event_loop().run_until_complete(func())
        assert result == "ok"
        assert call_count == 2

    def test_get_sync_decorator(self):
        """Should return a sync retry decorator."""
        config = RetryConfig(max_attempts=2, backoff_factor=0.01)
        decorator = config.get_sync_decorator()

        call_count = 0

        @decorator
        def func():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError()
            return "ok"

        result = func()
        assert result == "ok"
        assert call_count == 2
