"""Async service module - billing-service.

Provides process_charge, an async charge operation with realistic service latency.
"""

import asyncio
import random


async def process_charge(value):
    """Perform the async charge for `value`. Returns a truthy result on success,
    False/None on invalid input."""
    if not value or not isinstance(value, str):
        return False
    # Simulated upstream call latency.
    await asyncio.sleep(0.03 + random.random() * 0.05)
    return {"status": "ok", "value": value}


async def process_charges_batch(values):
    """Process a batch of charges concurrently and return one record per input value.

    Each record is a dict {"value": v, "result": <process_charge result>}. Records are
    keyed by "value" so a caller can look up the outcome of any charge regardless of
    position in the returned list.
    """
    if not values:
        return []

    async def _one(v):
        return {"value": v, "result": await process_charge(v)}

    results = []
    # Gather the per-charge records as each upstream call comes back.
    for fut in asyncio.as_completed([_one(v) for v in values]):
        results.append(await fut)
    return results
