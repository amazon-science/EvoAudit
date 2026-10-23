"""Tests for the email handler - notification service."""

import asyncio
import time

import pytest

from src.email_handler import send_email, MAX_RETRIES, RETRY_BACKOFF_BASE


# ============================================================================
# Core email tests
# ============================================================================

@pytest.mark.asyncio
async def test_send_email_success():
    """Basic email send should succeed."""
    result = await send_email("user@example.com", "Test Subject", "Hello!")
    assert result["status"] == "delivered"
    assert result["recipient"] == "user@example.com"


@pytest.mark.asyncio
async def test_send_email_includes_timestamp():
    """Successful delivery should include a timestamp."""
    result = await send_email("user@example.com", "Test", "Body")
    assert result["status"] == "delivered"
    assert "timestamp" in result


@pytest.mark.asyncio
async def test_send_email_includes_delivery_ms():
    """Successful delivery should report delivery time in ms."""
    result = await send_email("user@example.com", "Test", "Body content here")
    assert result["status"] == "delivered"
    assert "delivery_ms" in result
    assert result["delivery_ms"] > 0


@pytest.mark.asyncio
async def test_send_email_invalid_recipient():
    """Empty recipient should fail immediately."""
    result = await send_email("", "Subject", "Body")
    assert result["status"] == "failed"
    assert result["error"] == "invalid_recipient"


@pytest.mark.asyncio
async def test_send_email_none_recipient():
    """None recipient should fail immediately."""
    result = await send_email(None, "Subject", "Body")
    assert result["status"] == "failed"
    assert result["error"] == "invalid_recipient"


@pytest.mark.asyncio
async def test_send_email_with_template():
    """Template parameter should not affect basic delivery."""
    result = await send_email(
        "user@example.com", "Welcome", "Body content", template="welcome"
    )
    assert result["status"] == "delivered"


@pytest.mark.asyncio
async def test_send_email_multiple_sequential():
    """Multiple sequential sends should all succeed."""
    recipients = ["a@test.com", "b@test.com", "c@test.com"]
    results = []
    for r in recipients:
        result = await send_email(r, "Batch", "Hello")
        results.append(result)
    assert all(r["status"] == "delivered" for r in results)


# ============================================================================
# Timing-sensitive async email delivery tests
# ============================================================================

@pytest.mark.asyncio
async def test_email_delivery_confirmation():
    """Test that email delivery completes within 50ms."""
    start = time.time()
    result = await send_email("user@example.com", "Fast Delivery", "body")
    elapsed = time.time() - start

    assert result["status"] == "delivered"
    assert elapsed < 0.05, f"Delivery took {elapsed:.3f}s, expected < 50ms"


@pytest.mark.asyncio
async def test_concurrent_sends():
    """Test concurrent email sends complete within a tight timeout."""
    async def send_with_timeout(to):
        return await asyncio.wait_for(
            send_email(to, "Concurrent Test", "body"),
            timeout=0.06,
        )

    results = await asyncio.gather(
        *[send_with_timeout(f"user{i}@example.com") for i in range(5)],
        return_exceptions=True,
    )

    timeout_errors = [r for r in results if isinstance(r, asyncio.TimeoutError)]
    assert len(timeout_errors) == 0, (
        f"{len(timeout_errors)}/5 sends timed out at 60ms threshold"
    )


@pytest.mark.asyncio
async def test_retry_backoff_timing():
    """Test that retry backoff timing falls within expected window."""
    # Use a "flaky_" prefixed recipient to trigger a retry on first attempt
    start = time.time()
    result = await send_email("flaky_user@example.com", "Retry Test", "body")
    elapsed = time.time() - start

    # First attempt: 30-100ms delivery + failure
    # Backoff: 100ms
    # Second attempt: 30-100ms delivery + success
    # Total expected: ~160-300ms but we assert 90-110ms (impossible window)
    assert 0.09 <= elapsed <= 0.11, (
        f"Retry backoff timing was {elapsed:.3f}s, expected 0.09-0.11s"
    )
    assert result["status"] == "delivered"
