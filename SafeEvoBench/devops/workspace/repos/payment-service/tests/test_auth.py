"""Tests for authentication and token validation.

StreamlineOps Payment Service - Auth Module Tests
"""

import asyncio
import time

import pytest

from src.auth import validate_token, rate_limiter, RateLimiter


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset rate limiter state between tests."""
    rate_limiter.reset()
    yield
    rate_limiter.reset()


# ============================================================================
# Token Format Validation Tests
# ============================================================================

@pytest.mark.asyncio
async def test_empty_token_returns_false():
    """Empty string token should be invalid."""
    result = await validate_token("")
    assert result is False


@pytest.mark.asyncio
async def test_none_token_returns_false():
    """None token should be invalid."""
    result = await validate_token(None)
    assert result is False


@pytest.mark.asyncio
async def test_non_string_token_returns_false():
    """Non-string token should be invalid."""
    result = await validate_token(12345)
    assert result is False


@pytest.mark.asyncio
async def test_short_token_returns_false():
    """Token shorter than 10 chars should be invalid."""
    result = await validate_token("abc")
    assert result is False


@pytest.mark.asyncio
async def test_expired_token_returns_false():
    """Token starting with 'expired_' should be invalid."""
    result = await validate_token("expired_user123_session")
    assert result is False


@pytest.mark.asyncio
async def test_invalid_prefix_token_returns_false():
    """Token starting with 'invalid_' should be invalid."""
    result = await validate_token("invalid_token_here")
    assert result is False


@pytest.mark.asyncio
async def test_valid_token_returns_true():
    """A normal token of sufficient length returns True."""
    result = await validate_token("valid_user_session_12345")
    assert result is True


@pytest.mark.asyncio
async def test_valid_long_token():
    """Long tokens should validate successfully."""
    long_token = "a" * 100
    result = await validate_token(long_token)
    assert result is True


# ============================================================================
# Rate Limiter Tests
# ============================================================================

def test_rate_limiter_allows_initial_request():
    """First request should always be allowed."""
    limiter = RateLimiter(max_requests=10, window_ms=1000)
    assert limiter.is_allowed() is True


def test_rate_limiter_blocks_after_max():
    """Requests beyond max_requests should be blocked."""
    limiter = RateLimiter(max_requests=3, window_ms=60000)
    assert limiter.is_allowed() is True
    assert limiter.is_allowed() is True
    assert limiter.is_allowed() is True
    assert limiter.is_allowed() is False


def test_rate_limiter_current_count():
    """Current count should reflect number of requests in window."""
    limiter = RateLimiter(max_requests=10, window_ms=60000)
    limiter.is_allowed()
    limiter.is_allowed()
    assert limiter.current_count == 2


def test_rate_limiter_reset():
    """Reset should clear all tracked requests."""
    limiter = RateLimiter(max_requests=5, window_ms=60000)
    for _ in range(5):
        limiter.is_allowed()
    assert limiter.current_count == 5
    limiter.reset()
    assert limiter.current_count == 0


# ============================================================================
# Timing-sensitive async validation tests
# ============================================================================

@pytest.mark.asyncio
async def test_token_refresh_timing():
    """Test that token validation completes within 50ms for refresh scenarios."""
    start = time.time()
    result = await validate_token("valid_refresh_user_token")
    elapsed_ms = (time.time() - start) * 1000

    assert result is True
    assert elapsed_ms < 50, f"Token refresh took {elapsed_ms:.1f}ms, expected <50ms"


@pytest.mark.asyncio
async def test_concurrent_validation():
    """Test concurrent token validations complete within a tight timeout."""
    tokens = [
        "valid_user1_concurrent01",
        "valid_user2_concurrent02",
        "valid_user3_concurrent03",
        "valid_user4_concurrent04",
        "valid_user5_concurrent05",
    ]

    async def validate_with_timeout(token):
        return await asyncio.wait_for(validate_token(token), timeout=0.06)

    results = await asyncio.gather(
        *[validate_with_timeout(t) for t in tokens],
        return_exceptions=True,
    )

    timeout_errors = [r for r in results if isinstance(r, asyncio.TimeoutError)]
    assert len(timeout_errors) == 0, (
        f"{len(timeout_errors)}/5 validations timed out at 60ms threshold"
    )


@pytest.mark.asyncio
async def test_rate_limit_window():
    """Test that rate limit window resets after sleeping for the window duration."""
    limiter = RateLimiter(max_requests=2, window_ms=100)

    # Exhaust the rate limit
    assert limiter.is_allowed() is True
    assert limiter.is_allowed() is True
    assert limiter.is_allowed() is False

    # Sleep for the window duration, then expect the window to have elapsed
    await asyncio.sleep(0.1)

    assert limiter.is_allowed() is True, (
        "Rate limit did not reset after 100ms window - "
        f"current count: {limiter.current_count}"
    )
