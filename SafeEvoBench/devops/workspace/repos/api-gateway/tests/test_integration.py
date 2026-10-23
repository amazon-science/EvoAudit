"""Integration tests for the API Gateway service.

These tests exercise the full HTTP request/response cycle using
httpx.AsyncClient with the FastAPI test interface.
"""

import pytest
from httpx import AsyncClient, ASGITransport

from main import app


@pytest.fixture
async def client():
    """Create an async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    """Tests for the /health endpoint."""

    async def test_health_returns_200(self, client):
        """Health endpoint returns 200 OK."""
        response = await client.get("/health")
        assert response.status_code == 200

    async def test_health_response_structure(self, client):
        """Health endpoint returns expected fields."""
        response = await client.get("/health")
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "api-gateway"
        assert "version" in data


class TestGatewayEndpoints:
    """Tests for gateway operation endpoints."""

    async def test_forward_requires_api_key(self, client):
        """Forward endpoint rejects requests without API key."""
        response = await client.post(
            "/gateway/forward",
            json={"target_service": "payments", "payload": {"amount": 100}},
        )
        assert response.status_code == 422  # Missing required header

    async def test_forward_rejects_invalid_key(self, client):
        """Forward endpoint returns 401 for invalid API key."""
        response = await client.post(
            "/gateway/forward",
            json={"target_service": "payments", "payload": {"amount": 100}},
            headers={"X-API-Key": "invalid_key"},
        )
        assert response.status_code == 401

    async def test_status_returns_throttler_state(self, client):
        """Status endpoint returns throttler information."""
        response = await client.get("/gateway/status")
        assert response.status_code == 200
        data = response.json()
        assert "throttler" in data
        assert "current_tokens" in data["throttler"]
        assert "max_tokens" in data["throttler"]
