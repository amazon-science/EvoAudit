"""Configuration for the API Gateway service."""

import os


class Config:
    """Application configuration loaded from environment variables."""

    HOST: str = os.getenv("GATEWAY_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("GATEWAY_PORT", "8080"))
    DEBUG: bool = os.getenv("GATEWAY_DEBUG", "false").lower() == "true"

    # Throttler settings
    THROTTLE_REFILL_RATE: float = float(
        os.getenv("GATEWAY_THROTTLE_REFILL_RATE", "10.0")
    )
    THROTTLE_MAX_TOKENS: int = int(
        os.getenv("GATEWAY_THROTTLE_MAX_TOKENS", "50")
    )

    # Auth settings
    AUTH_TIMEOUT: float = float(os.getenv("GATEWAY_AUTH_TIMEOUT", "1.0"))
    MAX_CONCURRENT_REQUESTS: int = int(
        os.getenv("GATEWAY_MAX_CONCURRENT", "100")
    )

    # Upstream service
    UPSTREAM_URL: str = os.getenv(
        "GATEWAY_UPSTREAM_URL", "http://localhost:9000"
    )

    @classmethod
    def as_dict(cls) -> dict:
        """Return configuration as a dictionary."""
        return {
            "host": cls.HOST,
            "port": cls.PORT,
            "debug": cls.DEBUG,
            "throttle_refill_rate": cls.THROTTLE_REFILL_RATE,
            "throttle_max_tokens": cls.THROTTLE_MAX_TOKENS,
            "auth_timeout": cls.AUTH_TIMEOUT,
            "max_concurrent_requests": cls.MAX_CONCURRENT_REQUESTS,
            "upstream_url": cls.UPSTREAM_URL,
        }
