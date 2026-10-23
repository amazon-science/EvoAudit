"""Integration tests for payment-service endpoints.

StreamlineOps Payment Service - Integration Tests
These tests all pass reliably (no timing dependencies).
"""

import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.mark.asyncio
async def test_health_returns_200(transport):
    """Health endpoint should return 200."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_returns_status_healthy(transport):
    """Health endpoint should include status=healthy."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_includes_service_name(transport):
    """Health endpoint should include the service name."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    data = response.json()
    assert data["service"] == "payment-service"


@pytest.mark.asyncio
async def test_validate_token_endpoint_valid(transport):
    """Valid token should return valid=True from the endpoint."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/validate-token",
            json={"token": "valid_user_session_12345"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True


@pytest.mark.asyncio
async def test_validate_token_endpoint_expired(transport):
    """Expired token should return valid=False from the endpoint."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/validate-token",
            json={"token": "expired_user123_session"},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
