"""API Gateway microservice - routes and validates incoming requests."""

import uuid

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

from auth_middleware import RequestThrottler, verify_request
from config import Config

app = FastAPI(title="API Gateway", version="1.0.0")

# Global throttler instance
throttler = RequestThrottler(
    refill_rate=Config.THROTTLE_REFILL_RATE,
    max_tokens=Config.THROTTLE_MAX_TOKENS,
)


class ForwardRequest(BaseModel):
    """Request body for the forward endpoint."""

    target_service: str
    payload: dict
    priority: Optional[str] = "normal"


class ForwardResponse(BaseModel):
    """Response from the forward endpoint."""

    request_id: str
    status: str
    user_id: Optional[str] = None
    message: str


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "api-gateway", "version": "1.0.0"}


@app.post("/gateway/forward", response_model=ForwardResponse)
async def forward_request(
    body: ForwardRequest,
    x_api_key: str = Header(..., alias="X-API-Key"),
):
    """Validate auth and forward request to target service."""
    # Check throttle
    if not throttler.allow_request():
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please retry later.",
        )

    # Generate request ID
    request_id = str(uuid.uuid4())

    # Verify auth
    auth_result = await verify_request(request_id, x_api_key)

    if not auth_result["valid"]:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key.",
        )

    # Check scopes
    if "forward" not in auth_result.get("scopes", []):
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions. 'forward' scope required.",
        )

    return ForwardResponse(
        request_id=request_id,
        status="forwarded",
        user_id=auth_result["user_id"],
        message=f"Request forwarded to {body.target_service}",
    )


@app.get("/gateway/status")
async def gateway_status():
    """Return current gateway throttler state."""
    return {
        "throttler": throttler.get_state(),
        "config": Config.as_dict(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=Config.HOST, port=Config.PORT)
