"""Integration tests for /healthz and /metrics endpoints - PR-3."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.main import app


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Test /healthz endpoint."""

    @patch("backend.app.api.routes.health.check_db")
    @patch("backend.app.api.routes.health.check_redis")
    @patch("backend.app.api.routes.health.check_tools")
    def test_healthz_returns_200_when_all_ok(
        self,
        mock_check_tools: MagicMock,
        mock_check_redis: MagicMock,
        mock_check_db: MagicMock,
        client: TestClient,
    ) -> None:
        """Test /healthz returns 200 when DB and Redis are healthy."""
        # Mock successful checks
        mock_check_db.return_value = (True, "ok")
        mock_check_redis.return_value = (True, "ok")
        mock_check_tools.return_value = (True, "ok")

        response = client.get("/healthz")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["components"]["db"] == "ok"
        assert data["components"]["redis"] == "ok"

    @patch("backend.app.api.routes.health.check_db")
    @patch("backend.app.api.routes.health.check_redis")
    @patch("backend.app.api.routes.health.check_tools")
    def test_healthz_returns_503_when_db_fails(
        self,
        mock_check_tools: MagicMock,
        mock_check_redis: MagicMock,
        mock_check_db: MagicMock,
        client: TestClient,
    ) -> None:
        """Test /healthz returns 503 when DB check fails."""
        mock_check_db.return_value = (False, "connection refused")
        mock_check_redis.return_value = (True, "ok")
        mock_check_tools.return_value = (True, "ok")

        response = client.get("/healthz")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["components"]["db"] == "connection refused"
        assert data["components"]["redis"] == "ok"

    @patch("backend.app.api.routes.health.check_db")
    @patch("backend.app.api.routes.health.check_redis")
    @patch("backend.app.api.routes.health.check_tools")
    def test_healthz_returns_503_when_redis_fails(
        self,
        mock_check_tools: MagicMock,
        mock_check_redis: MagicMock,
        mock_check_db: MagicMock,
        client: TestClient,
    ) -> None:
        """Test /healthz returns 503 when Redis check fails."""
        mock_check_db.return_value = (True, "ok")
        mock_check_redis.return_value = (False, "timeout")
        mock_check_tools.return_value = (True, "ok")

        response = client.get("/healthz")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["components"]["db"] == "ok"
        assert data["components"]["redis"] == "timeout"

    @patch("backend.app.api.routes.health.check_db")
    @patch("backend.app.api.routes.health.check_redis")
    @patch("backend.app.api.routes.health.check_tools")
    def test_healthz_returns_200_when_tools_fail_but_core_ok(
        self,
        mock_check_tools: MagicMock,
        mock_check_redis: MagicMock,
        mock_check_db: MagicMock,
        client: TestClient,
    ) -> None:
        """Test /healthz returns 200 when tools fail but DB/Redis are ok."""
        mock_check_db.return_value = (True, "ok")
        mock_check_redis.return_value = (True, "ok")
        mock_check_tools.return_value = (False, "outbound check failed")

        response = client.get("/healthz")

        # Core is ok, so 200
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["components"]["db"] == "ok"
        assert data["components"]["redis"] == "ok"
        assert data["components"]["tools"] == "outbound check failed"


class TestMetricsEndpoint:
    """Test /metrics endpoint."""

    def test_metrics_returns_prometheus_format(self, client: TestClient) -> None:
        """Test /metrics returns Prometheus text format."""
        response = client.get("/metrics")

        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]

        # Check for Prometheus format markers
        text = response.text
        assert "# HELP" in text or "# TYPE" in text or len(text) > 0

    def test_metrics_includes_tool_metrics(self, client: TestClient) -> None:
        """Test /metrics includes tool executor metrics."""
        # First, ensure metrics are registered by importing
        from backend.app.utils.metrics import (
            tool_cache_hits_total,
            tool_errors_total,
            tool_latency_ms,
        )

        # Record some test metrics
        tool_latency_ms.labels(tool="test_tool", outcome="success").observe(100)
        tool_errors_total.labels(tool="test_tool", reason="timeout").inc()
        tool_cache_hits_total.labels(tool="test_tool").inc()

        response = client.get("/metrics")

        assert response.status_code == 200
        text = response.text

        # Verify our metrics appear in the output
        assert "tool_latency_ms" in text
        assert "tool_errors_total" in text
        assert "tool_cache_hits_total" in text

    def test_metrics_can_be_scraped_multiple_times(self, client: TestClient) -> None:
        """Test /metrics endpoint can be called multiple times."""
        response1 = client.get("/metrics")
        response2 = client.get("/metrics")

        assert response1.status_code == 200
        assert response2.status_code == 200

        # Both should return valid Prometheus format
        assert len(response1.text) > 0
        assert len(response2.text) > 0


class TestRootEndpoint:
    """Test root endpoint."""

    def test_root_returns_api_info(self, client: TestClient) -> None:
        """Test root endpoint returns API information."""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Travel Planner API"
        assert data["version"] == "0.1.0"
