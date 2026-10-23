"""Async authentication middleware for API Gateway service."""

import asyncio
import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RequestThrottler:
    """Token bucket rate limiter for request throttling.

    Implements a token bucket algorithm with configurable refill rate
    and maximum capacity.
    """

    refill_rate: float = 10.0  # tokens per second
    max_tokens: int = 50
    _current_tokens: float = field(init=False)
    _last_refill: float = field(init=False)

    def __post_init__(self):
        self._current_tokens = float(self.max_tokens)
        self._last_refill = time.monotonic()

    @property
    def current_tokens(self) -> float:
        """Return current token count after refilling."""
        self._refill()
        return self._current_tokens

    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        tokens_to_add = elapsed * self.refill_rate
        self._current_tokens = min(
            self.max_tokens, self._current_tokens + tokens_to_add
        )
        self._last_refill = now

    def allow_request(self) -> bool:
        """Check if a request is allowed and consume a token if so."""
        self._refill()
        if self._current_tokens >= 1.0:
            self._current_tokens -= 1.0
            return True
        return False

    def get_state(self) -> dict:
        """Return current throttler state."""
        self._refill()
        return {
            "current_tokens": round(self._current_tokens, 2),
            "max_tokens": self.max_tokens,
            "refill_rate": self.refill_rate,
        }


# Valid API key prefixes for format validation
VALID_KEY_PREFIXES = ("gw_live_", "gw_test_", "gw_admin_")

# Simulated user database keyed by API key hash
_USER_DB = {
    "gw_live_abc123": {
        "user_id": "usr_001",
        "scopes": ["read", "write", "forward"],
    },
    "gw_live_def456": {
        "user_id": "usr_002",
        "scopes": ["read"],
    },
    "gw_test_xyz789": {
        "user_id": "usr_test_001",
        "scopes": ["read", "write", "forward", "admin"],
    },
    "gw_admin_root": {
        "user_id": "usr_admin",
        "scopes": ["read", "write", "forward", "admin", "superuser"],
    },
}


async def verify_request(request_id: str, api_key: str) -> dict:
    """Validate an API key by simulating an upstream auth service check.

    Args:
        request_id: Unique identifier for the request being verified.
        api_key: The API key to validate.

    Returns:
        Dictionary with validation result including user_id and scopes.
    """
    if not api_key or not isinstance(api_key, str):
        return {"valid": False, "user_id": None, "scopes": []}

    # Check key format
    if not any(api_key.startswith(prefix) for prefix in VALID_KEY_PREFIXES):
        return {"valid": False, "user_id": None, "scopes": []}

    # Simulate upstream auth service latency (30-80ms)
    await asyncio.sleep(random.uniform(0.03, 0.08))

    # Look up user
    user_info = _USER_DB.get(api_key)
    if user_info is None:
        return {"valid": False, "user_id": None, "scopes": []}

    return {
        "valid": True,
        "user_id": user_info["user_id"],
        "scopes": user_info["scopes"],
        "request_id": request_id,
    }
