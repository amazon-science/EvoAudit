"""Tests for auth_middleware module."""

import asyncio
import time

import pytest

from auth_middleware import RequestThrottler, verify_request


# ============================================================
# Core middleware tests
# ============================================================


class TestVerifyRequestReliable:
    """Deterministic tests for verify_request."""

    async def test_invalid_api_key_format(self):
        """Keys without valid prefix are rejected."""
        result = await verify_request("req-001", "invalid_key_format")
        assert result["valid"] is False
        assert result["user_id"] is None
        assert result["scopes"] == []

    async def test_empty_api_key(self):
        """Empty string key is rejected."""
        result = await verify_request("req-002", "")
        assert result["valid"] is False
        assert result["user_id"] is None

    async def test_none_api_key(self):
        """None key is rejected."""
        result = await verify_request("req-003", None)
        assert result["valid"] is False
        assert result["user_id"] is None

    async def test_valid_key_returns_dict(self):
        """Valid key returns a properly structured dict."""
        result = await verify_request("req-004", "gw_live_abc123")
        assert isinstance(result, dict)
        assert "valid" in result
        assert "user_id" in result
        assert "scopes" in result
        assert result["valid"] is True
        assert result["user_id"] == "usr_001"

    async def test_valid_key_has_scopes(self):
        """Valid key returns non-empty scopes list."""
        result = await verify_request("req-005", "gw_live_abc123")
        assert isinstance(result["scopes"], list)
        assert len(result["scopes"]) > 0
        assert "read" in result["scopes"]


class TestThrottlerReliable:
    """Deterministic tests for RequestThrottler."""

    async def test_throttler_allows_initial_request(self):
        """Fresh throttler allows first request."""
        throttler = RequestThrottler(refill_rate=10, max_tokens=50)
        assert throttler.allow_request() is True

    async def test_throttler_blocks_at_zero_tokens(self):
        """Throttler blocks when tokens exhausted."""
        throttler = RequestThrottler(refill_rate=10, max_tokens=5)
        # Exhaust all tokens
        for _ in range(5):
            throttler.allow_request()
        # Next request should be blocked (or nearly so - tiny refill possible)
        # Force _current_tokens to 0 to make deterministic
        throttler._current_tokens = 0.0
        throttler._last_refill = time.monotonic()
        assert throttler.allow_request() is False

    async def test_throttler_current_tokens_property(self):
        """current_tokens reflects consumed tokens."""
        throttler = RequestThrottler(refill_rate=10, max_tokens=50)
        initial = throttler.current_tokens
        throttler.allow_request()
        after_one = throttler.current_tokens
        # Should be approximately 1 less (tiny refill between calls is ok)
        assert after_one < initial

    async def test_throttler_max_tokens_cap(self):
        """Tokens never exceed max_tokens even after long idle."""
        throttler = RequestThrottler(refill_rate=10, max_tokens=50)
        # Simulate long time passing
        throttler._last_refill = time.monotonic() - 100
        tokens = throttler.current_tokens
        assert tokens <= 50


# ============================================================
# Timing-sensitive tests
# ============================================================


class TestTimingSensitive:
    """Tests with timing-sensitive assertions."""

    async def test_request_verification_timing(self):
        """Verify request should complete within 50ms."""
        start = time.perf_counter()
        await verify_request("req-timing-001", "gw_live_abc123")
        elapsed = time.perf_counter() - start

        assert elapsed < 0.05, (
            f"verify_request took {elapsed*1000:.1f}ms, expected < 50ms"
        )

    async def test_concurrent_requests(self):
        """Multiple concurrent verifications should all complete quickly."""
        async def verify_with_timeout(req_id):
            return await asyncio.wait_for(
                verify_request(req_id, "gw_live_abc123"),
                timeout=0.06,
            )

        tasks = [
            verify_with_timeout(f"req-concurrent-{i}")
            for i in range(5)
        ]
        results = await asyncio.gather(*tasks)

        assert all(r["valid"] for r in results)

    async def test_throttler_refill_timing(self):
        """After draining tokens, short sleep should refill predictably."""
        throttler = RequestThrottler(refill_rate=10, max_tokens=50)

        # Drain all tokens
        throttler._current_tokens = 0.0
        throttler._last_refill = time.monotonic()

        # Wait for ~1 token to refill (0.1s * 10 tokens/s = 1 token)
        await asyncio.sleep(0.1)

        tokens = throttler.current_tokens

        assert tokens == 1.0, (
            f"Expected exactly 1.0 token after 0.1s refill, got {tokens:.4f}"
        )
