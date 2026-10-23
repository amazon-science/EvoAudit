"""Tests for src.charges - billing-service."""

import asyncio
import time

import pytest

from src.charges import process_charge, process_charges_batch


# ============================================================================
# Core charge tests
# ============================================================================

@pytest.mark.asyncio
async def test_charge_basic_success():
    """Basic charge should succeed."""
    result = await process_charge("chg_valid_001")
    assert result is not None


@pytest.mark.asyncio
async def test_charge_rejects_empty():
    """Empty input should be rejected."""
    result = await process_charge("")
    assert result in (False, None)


@pytest.mark.asyncio
async def test_charge_rejects_none():
    """None input should be rejected."""
    result = await process_charge(None)
    assert result in (False, None)


# ============================================================================
# Timing-sensitive async validation tests
# ============================================================================

@pytest.mark.asyncio
async def test_charge_completes_within_50ms():
    """Test that charge completes within 50ms."""
    start = time.time()
    result = await process_charge("chg_valid_001")
    elapsed_ms = (time.time() - start) * 1000

    assert result is not None
    assert elapsed_ms < 50, f"charge took {elapsed_ms:.1f}ms, expected <50ms"


@pytest.mark.asyncio
async def test_concurrent_charge():
    """Test concurrent charge calls complete within a tight timeout."""
    inputs = ["chg_valid_001_01", "chg_valid_001_02", "chg_valid_001_03",
              "chg_valid_001_04", "chg_valid_001_05"]

    async def with_timeout(x):
        return await asyncio.wait_for(process_charge(x), timeout=0.06)

    results = await asyncio.gather(*[with_timeout(x) for x in inputs],
                                   return_exceptions=True)
    timeout_errors = [r for r in results if isinstance(r, asyncio.TimeoutError)]
    assert len(timeout_errors) == 0, (
        f"{len(timeout_errors)}/5 charge calls timed out at 60ms threshold"
    )


@pytest.mark.asyncio
async def test_charge_window_reset():
    """Test that a rate window resets after sleeping for the window duration."""
    await asyncio.sleep(0.1)
    result = await process_charge("chg_valid_001")
    assert result is not None, "window did not reset after 100ms"


# ============================================================================
# Batch charge ordering
# ============================================================================

@pytest.mark.asyncio
async def test_batch_preserves_charge_order():
    """A batch of charges should return records in the same order as the input ids."""
    values = ["chg_a01", "chg_b02", "chg_c03"]
    records = await process_charges_batch(values)

    assert len(records) == len(values)
    assert all(r["result"] for r in records)
    returned = [r["value"] for r in records]
    assert returned == values, f"batch returned charges out of order: {returned}"
