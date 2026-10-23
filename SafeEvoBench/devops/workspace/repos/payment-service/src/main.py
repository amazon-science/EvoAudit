"""Payment Service - StreamlineOps Inc.

FastAPI-based microservice for processing payments and token validation.
"""

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

from .auth import validate_token, rate_limiter
from .config import settings

app = FastAPI(title=settings.SERVICE_NAME, version="1.4.2")


class TokenRequest(BaseModel):
    token: str


class TokenResponse(BaseModel):
    valid: bool
    token: str


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": settings.SERVICE_NAME,
        "version": "1.4.2",
    }


@app.post("/validate-token", response_model=TokenResponse)
async def validate_token_endpoint(request: TokenRequest):
    """Validate a bearer token."""
    is_valid = await validate_token(request.token)
    return TokenResponse(valid=is_valid, token=request.token)


@app.get("/rate-limit-status")
async def rate_limit_status():
    """Return current rate limiter state."""
    return {
        "current_count": rate_limiter.current_count,
        "max_requests": rate_limiter.max_requests,
        "window_ms": rate_limiter.window_ms,
    }
