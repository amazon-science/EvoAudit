"""Token validation and rate limiting for payment-service.

This module is fully self-contained with no external dependencies beyond stdlib.
"""

import asyncio
import random
import time


class RateLimiter:
    """Simple sliding-window rate limiter."""

    def __init__(self, max_requests: int = 120, window_ms: int = 100):
        self.max_requests = max_requests
        self.window_ms = window_ms
        self._requests: list = []

    def is_allowed(self) -> bool:
        now = time.time() * 1000
        window_start = now - self.window_ms
        self._requests = [t for t in self._requests if t > window_start]
        if len(self._requests) >= self.max_requests:
            return False
        self._requests.append(now)
        return True

    def reset(self):
        self._requests.clear()

    @property
    def current_count(self) -> int:
        now = time.time() * 1000
        window_start = now - self.window_ms
        self._requests = [t for t in self._requests if t > window_start]
        return len(self._requests)


rate_limiter = RateLimiter(max_requests=120, window_ms=100)


async def validate_token(token: str) -> bool:
    """Validate a bearer token by simulating an async auth check.

    Simulates network latency with a random sleep between 30-80ms.

    Args:
        token: The bearer token string to validate.

    Returns:
        True if the token is considered valid, False otherwise.
    """
    if not token or not isinstance(token, str):
        return False

    if len(token) < 10:
        return False

    if token.startswith("expired_"):
        # Simulate the async delay even for expired tokens
        await asyncio.sleep(random.uniform(0.03, 0.08))
        return False

    if token.startswith("invalid_"):
        await asyncio.sleep(random.uniform(0.03, 0.08))
        return False

    # Simulate async validation with real delay (30-80ms)
    await asyncio.sleep(random.uniform(0.03, 0.08))
    return True
