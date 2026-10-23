"""Configuration management for payment-service."""

import os


class Settings:
    SERVICE_NAME: str = os.getenv("SERVICE_NAME", "payment-service")
    RATE_LIMIT_RPM: int = int(os.getenv("RATE_LIMIT_RPM", "120"))
    TOKEN_EXPIRY_SECONDS: int = int(os.getenv("TOKEN_EXPIRY_SECONDS", "3600"))
    MAX_RETRY_ATTEMPTS: int = int(os.getenv("MAX_RETRY_ATTEMPTS", "3"))
    REQUEST_TIMEOUT_MS: int = int(os.getenv("REQUEST_TIMEOUT_MS", "5000"))


settings = Settings()
