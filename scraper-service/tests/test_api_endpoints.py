"""Tests for FastAPI endpoints in app/main.py using TestClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

AUTH_TOKEN = "test-token-abc123"
AUTH_HEADERS = {"Authorization": f"Bearer {AUTH_TOKEN}"}


@pytest.fixture()
def client():
    """TestClient with scheduler and settings mocked out."""
    with (
        patch("app.scheduler.start_scheduler"),
        patch("app.scheduler.stop_scheduler"),
        patch("app.config.settings") as mock_settings,
    ):
        mock_settings.scraper_shared_token = AUTH_TOKEN
        mock_settings.supabase_url = "https://test.supabase.co"
        mock_settings.supabase_service_role_key = "test-role-key"

        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


@pytest.fixture()
def open_client():
    """TestClient with no auth token configured (open/dev mode)."""
    with (
        patch("app.scheduler.start_scheduler"),
        patch("app.scheduler.stop_scheduler"),
        patch("app.config.settings") as mock_settings,
    ):
        mock_settings.scraper_shared_token = ""   # empty = open mode
        mock_settings.supabase_url = "https://test.supabase.co"
        mock_settings.supabase_service_role_key = "test-role-key"

        from app.main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_returns_status_healthy(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert data["status"] == "healthy"

    def test_health_returns_service_name(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert data["service"] == "foretrust-scraper"

    def test_health_returns_version(self, client):
        resp = client.get("/health")
        data = resp.json()
        assert "version" in data

    def test_health_requires_no_auth(self, client):
        """Health endpoint should not require authentication."""
        resp = client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# GET /connectors
# ---------------------------------------------------------------------------

class TestConnectorsEndpoint:

    def _make_connector_class(self, source_key: str, vertical_value: str = "residential"):
        cls = MagicMock()
        cls.source_key = source_key
        cls.vertical = MagicMock(value=vertical_value)
        cls.jurisdiction = "KY-Fayette"
        cls.default_schedule = "0 6 * * *"
        return cls

    def test_connectors_returns_200_with_valid_token(self, client):
        mock_registry = {"kcoj_courtnet": self._make_connector_class("kcoj_courtnet")}

        with patch("app.connectors.registry.list_connectors", return_value=mock_registry):
            resp = client.get("/connectors", headers=AUTH_HEADERS)

        assert resp.status_code == 200

    def test_connectors_returns_list(self, client):
        mock_registry = {
            "kcoj_courtnet": self._make_connector_class("kcoj_courtnet"),
            "fayette_pva": self._make_connector_class("fayette_pva"),
        }

        with patch("app.connectors.registry.list_connectors", return_value=mock_registry):
            resp = client.get("/connectors", headers=AUTH_HEADERS)

        data = resp.json()
        assert "connectors" in data
        assert isinstance(data["connectors"], list)
        assert len(data["connectors"]) == 2

    def test_connectors_connector_has_expected_keys(self, client):
        mock_registry = {"kcoj_courtnet": self._make_connector_class("kcoj_courtnet")}

        with patch("app.connectors.registry.list_connectors", return_value=mock_registry):
            resp = client.get("/connectors", headers=AUTH_HEADERS)

        connector = resp.json()["connectors"][0]
        assert "source_key" in connector
        assert "vertical" in connector
        assert "jurisdiction" in connector
        assert "schedule" in connector

    def test_connectors_returns_401_without_token(self, client):
        resp = client.get("/connectors")
        assert resp.status_code == 401

    def test_connectors_returns_403_with_wrong_token(self, client):
        resp = client.get("/connectors", headers={"Authorization": "Bearer wrong-token"})
        assert resp.status_code == 403

    def test_connectors_no_auth_required_in_open_mode(self, open_client):
        """When scraper_shared_token is empty, any request is allowed."""
        mock_registry = {"kcoj_courtnet": self._make_connector_class("kcoj_courtnet")}

        with patch("app.connectors.registry.list_connectors", return_value=mock_registry):
            resp = open_client.get("/connectors")

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /run/{source_key}
# ---------------------------------------------------------------------------

class TestRunEndpoint:

    def _mock_registry_with(self, source_key: str):
        """Patch the registry to contain a single mock connector."""
        mock_connector = MagicMock()
        mock_connector.source_key = source_key

        def _get(key):
            if key == source_key:
                return mock_connector
            raise KeyError(f"Unknown source_key '{key}'")

        return _get

    def test_run_valid_source_key_returns_202(self, client):
        with (
            patch("app.connectors.registry.get_connector", side_effect=self._mock_registry_with("kcoj_courtnet")),
            patch("app.scheduler.run_connector_job"),
        ):
            resp = client.post("/run/kcoj_courtnet", headers=AUTH_HEADERS)

        assert resp.status_code == 202

    def test_run_valid_source_key_returns_accepted_status(self, client):
        with (
            patch("app.connectors.registry.get_connector", side_effect=self._mock_registry_with("kcoj_courtnet")),
            patch("app.scheduler.run_connector_job"),
        ):
            resp = client.post("/run/kcoj_courtnet", headers=AUTH_HEADERS)

        data = resp.json()
        assert data["status"] == "accepted"
        assert data["source_key"] == "kcoj_courtnet"

    def test_run_unknown_source_key_returns_404(self, client):
        def _get(key):
            raise KeyError(f"Unknown source_key '{key}'")

        with patch("app.connectors.registry.get_connector", side_effect=_get):
            resp = client.post("/run/does_not_exist", headers=AUTH_HEADERS)

        assert resp.status_code == 404

    def test_run_missing_token_returns_401(self, client):
        resp = client.post("/run/kcoj_courtnet")
        assert resp.status_code == 401

    def test_run_wrong_token_returns_403(self, client):
        resp = client.post(
            "/run/kcoj_courtnet",
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 403

    def test_run_accepts_params_body(self, client):
        with (
            patch("app.connectors.registry.get_connector", side_effect=self._mock_registry_with("kcoj_courtnet")),
            patch("app.scheduler.run_connector_job"),
        ):
            resp = client.post(
                "/run/kcoj_courtnet",
                json={"params": {"counties": ["Fayette"], "limit": 10}},
                headers=AUTH_HEADERS,
            )

        assert resp.status_code == 202

    def test_run_works_without_body(self, client):
        """POST /run/{source_key} with no body should still return 202."""
        with (
            patch("app.connectors.registry.get_connector", side_effect=self._mock_registry_with("kcoj_courtnet")),
            patch("app.scheduler.run_connector_job"),
        ):
            resp = client.post("/run/kcoj_courtnet", headers=AUTH_HEADERS)

        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# GET /runs
# ---------------------------------------------------------------------------

class TestRunsEndpoint:

    def test_runs_returns_200(self, client):
        with patch(
            "app.storage.supabase_client.list_source_runs",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/runs", headers=AUTH_HEADERS)

        assert resp.status_code == 200

    def test_runs_returns_list(self, client):
        fake_runs = [
            {"source_key": "kcoj_courtnet", "status": "ok"},
            {"source_key": "fayette_pva", "status": "ok"},
        ]
        with patch(
            "app.storage.supabase_client.list_source_runs",
            new=AsyncMock(return_value=fake_runs),
        ):
            resp = client.get("/runs", headers=AUTH_HEADERS)

        data = resp.json()
        assert "runs" in data
        assert len(data["runs"]) == 2

    def test_runs_returns_empty_list_when_no_history(self, client):
        with patch(
            "app.storage.supabase_client.list_source_runs",
            new=AsyncMock(return_value=[]),
        ):
            resp = client.get("/runs", headers=AUTH_HEADERS)

        assert resp.json() == {"runs": []}

    def test_runs_returns_401_without_token(self, client):
        resp = client.get("/runs")
        assert resp.status_code == 401

    def test_runs_passes_limit_param(self, client):
        mock_list = AsyncMock(return_value=[])
        with patch("app.storage.supabase_client.list_source_runs", new=mock_list):
            client.get("/runs?limit=5", headers=AUTH_HEADERS)

        mock_list.assert_called_once_with(5)
