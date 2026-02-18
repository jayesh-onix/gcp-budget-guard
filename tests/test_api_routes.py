"""End-to-end tests for the FastAPI application routes.

These tests use the FastAPI TestClient to hit every endpoint and
verify the contract without any real GCP calls.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a TestClient with the budget monitor fully mocked."""
    # We need to mock the lazy singleton BEFORE the app instantiates it
    mock_monitor = MagicMock()
    mock_monitor.run_check.return_value = {
        "project_id": "test-project",
        "dry_run": True,
        "budget": {},
        "disabled_apis": [],
        "warnings_sent": [],
        "metric_details": [],
    }
    mock_monitor.enable_service.return_value = True
    mock_monitor.get_service_status.return_value = "ENABLED"

    with patch("fastapi_app.routes._get_monitor", return_value=mock_monitor):
        from fastapi_app.app import app
        yield TestClient(app)


class TestHealthEndpoints:
    def test_root(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"

    def test_favicon(self, client):
        resp = client.get("/favicon.ico")
        assert resp.status_code == 204


class TestBudgetCheckEndpoint:
    def test_check_returns_200(self, client):
        resp = client.post("/check")
        assert resp.status_code == 200
        data = resp.json()
        assert "project_id" in data
        assert "disabled_apis" in data


class TestEnableServiceEndpoint:
    def test_enable_known_api(self, client):
        resp = client.post("/enable_service/firestore.googleapis.com")
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    def test_enable_returns_error_on_failure(self, client):
        with patch("fastapi_app.routes._get_monitor") as mock_fn:
            mock_mon = MagicMock()
            mock_mon.enable_service.return_value = False
            mock_fn.return_value = mock_mon

            resp = client.post("/enable_service/unknown.googleapis.com")
            assert resp.status_code == 500


class TestResetEndpoint:
    def test_reset_valid_key(self, client):
        resp = client.post("/reset/firestore")
        assert resp.status_code == 200

    def test_reset_invalid_key(self, client):
        resp = client.post("/reset/nonexistent")
        assert resp.status_code == 400
        assert "Unknown service key" in resp.json()["message"]


class TestStatusEndpoints:
    def test_all_status(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200
        assert "services" in resp.json()

    def test_single_status_valid(self, client):
        resp = client.get("/status/firestore")
        assert resp.status_code == 200
        assert resp.json()["service_key"] == "firestore"

    def test_single_status_invalid(self, client):
        resp = client.get("/status/nonexistent")
        assert resp.status_code == 400
