"""Shared pytest fixtures for the Foretrust scraper-service test suite."""

from __future__ import annotations

import os
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models import Lead, LeadType, RawRecord, SourceRun, SourceRunStatus, Vertical


# ---------------------------------------------------------------------------
# Model fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_lead() -> Lead:
    """Fully populated Lead model instance."""
    return Lead(
        source_key="kcoj_courtnet",
        vertical=Vertical.RESIDENTIAL,
        jurisdiction="KY-Fayette",
        lead_type=LeadType.PROBATE,
        owner_name="JOHN DOE",
        mailing_address="123 MAIN ST",
        property_address="123 MAIN ST",
        city="LEXINGTON",
        state="KY",
        postal_code="40507",
        parcel_number="123-456-789",
        building_sqft=2500,
        unit_count=1,
        year_built=1985,
        case_id="P-2026-001",
        case_filed_date=date(2026, 1, 15),
        estimated_value=350_000.0,
        raw_payload={"county": "Fayette", "case_type": "P - Probate"},
        hot_score=72,
        scraped_at=datetime(2026, 1, 15, 12, 0, 0),
    )


@pytest.fixture()
def mock_source_run() -> SourceRun:
    """A SourceRun audit log entry."""
    return SourceRun(
        source_key="kcoj_courtnet",
        status=SourceRunStatus.OK,
        started_at=datetime(2026, 1, 15, 12, 0, 0),
        finished_at=datetime(2026, 1, 15, 12, 5, 0),
        records_found=10,
        records_new=8,
        error_message=None,
        proxy_session_id="session-abc123",
    )


@pytest.fixture()
def mock_raw_record() -> RawRecord:
    """A raw scraped record."""
    return RawRecord(
        source_key="kcoj_courtnet",
        data={
            "county": "Fayette",
            "case_type": "P - Probate",
            "name": "JOHN DOE",
            "case_id": "P-2026-001",
            "filed_date": "01/15/2026",
            "case_description": "PROBATE ESTATE",
        },
        scraped_at=datetime(2026, 1, 15, 12, 0, 0),
    )


# ---------------------------------------------------------------------------
# Supabase client mock
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_supabase_client():
    """MagicMock that replaces the Supabase client."""
    client = MagicMock()

    # Chain: client.table("ft_leads").upsert(...).execute()
    table_mock = MagicMock()
    upsert_mock = MagicMock()
    insert_mock = MagicMock()
    select_mock = MagicMock()
    execute_mock = MagicMock(return_value=MagicMock(data=[]))

    upsert_mock.return_value = MagicMock(execute=execute_mock)
    insert_mock.return_value = MagicMock(execute=execute_mock)
    select_mock.return_value = MagicMock(
        is_=MagicMock(
            return_value=MagicMock(
                not_=MagicMock(
                    return_value=MagicMock(
                        is_=MagicMock(
                            return_value=MagicMock(
                                order=MagicMock(
                                    return_value=MagicMock(
                                        limit=MagicMock(
                                            return_value=MagicMock(execute=execute_mock)
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            )
        ),
        order=MagicMock(
            return_value=MagicMock(
                limit=MagicMock(return_value=MagicMock(execute=execute_mock))
            )
        ),
    )

    table_mock.upsert = upsert_mock
    table_mock.insert = insert_mock
    table_mock.select = MagicMock(return_value=select_mock.return_value)

    client.table = MagicMock(return_value=table_mock)
    return client


# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------

SAFE_TEST_ENV = {
    "SUPABASE_URL": "https://test.supabase.co",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
    "SCRAPER_SHARED_TOKEN": "test-token-abc123",
    "CAPTCHA_PROVIDER": "twocaptcha",
    "TWOCAPTCHA_API_KEY": "test-2captcha-key",
    "CAPSOLVER_API_KEY": "test-capsolver-key",
    "CAPTCHA_DAILY_BUDGET_USD": "5.0",
    "PROXY_SERVER": "",
    "PROXY_USERNAME": "",
    "PROXY_PASSWORD": "",
    "PROXY_COUNTRY": "us",
    "PROXY_STATE": "ky",
}


@pytest.fixture()
def mock_env_vars(monkeypatch):
    """Set required env vars to safe test values for the duration of a test."""
    for key, value in SAFE_TEST_ENV.items():
        monkeypatch.setenv(key, value)
    return SAFE_TEST_ENV


# ---------------------------------------------------------------------------
# FastAPI TestClient
# ---------------------------------------------------------------------------


@pytest.fixture()
def test_app():
    """FastAPI TestClient wrapping app/main.py with scheduler and Supabase mocked."""
    with (
        patch("app.scheduler.start_scheduler"),
        patch("app.scheduler.stop_scheduler"),
        patch("app.config.settings") as mock_settings,
    ):
        mock_settings.scraper_shared_token = "test-token-abc123"
        mock_settings.supabase_url = "https://test.supabase.co"
        mock_settings.supabase_service_role_key = "test-service-role-key"

        from app.main import app
        client = TestClient(app, raise_server_exceptions=True)
        yield client


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Bearer token headers for authenticated requests."""
    return {"Authorization": "Bearer test-token-abc123"}
