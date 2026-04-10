"""Tests for app/storage/supabase_client.py."""

from __future__ import annotations

import os
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch, call
import pytest

from app.models import Lead, LeadType, RawRecord, SourceRun, SourceRunStatus, Vertical


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lead(source_key: str = "kcoj_courtnet", parcel: str = "111-222", case_id: str = "P-001", **kwargs) -> Lead:
    defaults = {
        "source_key": source_key,
        "vertical": Vertical.RESIDENTIAL,
        "lead_type": LeadType.PROBATE,
        "owner_name": "JOHN DOE",
        "property_address": "123 MAIN ST",
        "city": "LEXINGTON",
        "state": "KY",
        "postal_code": "40507",
        "parcel_number": parcel,
        "case_id": case_id,
        "case_filed_date": date(2026, 1, 15),
        "estimated_value": 300_000.0,
        "building_sqft": 2000,
        "scraped_at": datetime(2026, 1, 15, 12, 0, 0),
    }
    defaults.update(kwargs)
    return Lead(**defaults)


def _make_source_run(**kwargs) -> SourceRun:
    defaults = {
        "source_key": "kcoj_courtnet",
        "status": SourceRunStatus.OK,
        "started_at": datetime(2026, 1, 15, 12, 0, 0),
        "finished_at": datetime(2026, 1, 15, 12, 5, 0),
        "records_found": 5,
        "records_new": 3,
    }
    defaults.update(kwargs)
    return SourceRun(**defaults)


# ---------------------------------------------------------------------------
# insert_leads — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_leads_happy_path():
    """insert_leads calls upsert with the correct row data."""
    lead = _make_lead()
    execute_result = MagicMock(data=[])

    upsert_chain = MagicMock()
    upsert_chain.execute = MagicMock(return_value=execute_result)

    table_mock = MagicMock()
    table_mock.upsert = MagicMock(return_value=upsert_chain)

    supabase_mock = MagicMock()
    supabase_mock.table = MagicMock(return_value=table_mock)

    with patch("app.storage.supabase_client._get_client", return_value=supabase_mock):
        from app.storage.supabase_client import insert_leads
        count = await insert_leads([lead])

    assert count == 1
    table_mock.upsert.assert_called_once()
    call_args = table_mock.upsert.call_args
    rows = call_args[0][0]  # first positional argument
    assert isinstance(rows, list)
    assert len(rows) == 1
    assert rows[0]["source_key"] == "kcoj_courtnet"
    assert rows[0]["owner_name"] == "JOHN DOE"
    assert rows[0]["state"] == "KY"
    assert "dedupe_hash" in rows[0]


@pytest.mark.asyncio
async def test_insert_leads_passes_correct_conflict_columns():
    """insert_leads uses on_conflict='source_key,dedupe_hash'."""
    lead = _make_lead()
    execute_result = MagicMock(data=[])

    upsert_chain = MagicMock()
    upsert_chain.execute = MagicMock(return_value=execute_result)

    table_mock = MagicMock()
    table_mock.upsert = MagicMock(return_value=upsert_chain)

    supabase_mock = MagicMock()
    supabase_mock.table = MagicMock(return_value=table_mock)

    with patch("app.storage.supabase_client._get_client", return_value=supabase_mock):
        from app.storage.supabase_client import insert_leads
        await insert_leads([lead])

    _, kwargs = table_mock.upsert.call_args
    assert kwargs.get("on_conflict") == "source_key,dedupe_hash"


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_leads_empty_input_makes_no_supabase_call():
    """insert_leads with empty list should not call upsert."""
    supabase_mock = MagicMock()
    table_mock = MagicMock()
    supabase_mock.table = MagicMock(return_value=table_mock)

    with patch("app.storage.supabase_client._get_client", return_value=supabase_mock):
        from app.storage.supabase_client import insert_leads
        count = await insert_leads([])

    assert count == 0
    table_mock.upsert.assert_not_called()


# ---------------------------------------------------------------------------
# Supabase unavailable
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_leads_returns_zero_when_client_unavailable():
    """If _get_client() returns None, insert_leads returns 0 without raising."""
    with patch("app.storage.supabase_client._get_client", return_value=None):
        from app.storage.supabase_client import insert_leads
        count = await insert_leads([_make_lead()])

    assert count == 0


@pytest.mark.asyncio
async def test_insert_leads_supabase_error_is_caught_not_raised():
    """If upsert raises an exception it is caught and logged, not propagated."""
    upsert_chain = MagicMock()
    upsert_chain.execute = MagicMock(side_effect=RuntimeError("Connection refused"))

    table_mock = MagicMock()
    table_mock.upsert = MagicMock(return_value=upsert_chain)

    supabase_mock = MagicMock()
    supabase_mock.table = MagicMock(return_value=table_mock)

    with patch("app.storage.supabase_client._get_client", return_value=supabase_mock):
        from app.storage.supabase_client import insert_leads
        # Should not raise — error is caught inside the function
        count = await insert_leads([_make_lead()])

    # Returns 0 because the chunk failed
    assert count == 0


# ---------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_leads_batches_large_inputs():
    """For inputs > 500 leads, multiple upsert calls are made (one per batch)."""
    leads = [_make_lead(parcel=str(i), case_id=f"P-{i:04d}") for i in range(1050)]

    upsert_chain = MagicMock()
    upsert_chain.execute = MagicMock(return_value=MagicMock(data=[]))

    table_mock = MagicMock()
    table_mock.upsert = MagicMock(return_value=upsert_chain)

    supabase_mock = MagicMock()
    supabase_mock.table = MagicMock(return_value=table_mock)

    with patch("app.storage.supabase_client._get_client", return_value=supabase_mock):
        from app.storage.supabase_client import insert_leads
        count = await insert_leads(leads)

    # 1050 leads → 3 batches (500 + 500 + 50)
    assert table_mock.upsert.call_count == 3
    assert count == 1050


# ---------------------------------------------------------------------------
# Dedup — same hash in same batch
# ---------------------------------------------------------------------------

def test_lead_dedupe_hash_is_stable():
    """Same source_key + parcel + case_id + property_address → identical hash."""
    lead1 = _make_lead(parcel="999-888", case_id="P-ZZZ")
    lead2 = _make_lead(parcel="999-888", case_id="P-ZZZ")
    assert lead1.dedupe_hash == lead2.dedupe_hash


def test_lead_dedupe_hash_differs_for_different_parcels():
    """Different parcel numbers produce different dedupe hashes."""
    lead1 = _make_lead(parcel="111-111", case_id="P-001")
    lead2 = _make_lead(parcel="222-222", case_id="P-001")
    assert lead1.dedupe_hash != lead2.dedupe_hash


# ---------------------------------------------------------------------------
# insert_source_run
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_insert_source_run_happy_path():
    """insert_source_run inserts a row with the correct fields."""
    run = _make_source_run()

    execute_result = MagicMock()
    insert_chain = MagicMock()
    insert_chain.execute = MagicMock(return_value=execute_result)

    table_mock = MagicMock()
    table_mock.insert = MagicMock(return_value=insert_chain)

    supabase_mock = MagicMock()
    supabase_mock.table = MagicMock(return_value=table_mock)

    with patch("app.storage.supabase_client._get_client", return_value=supabase_mock):
        from app.storage.supabase_client import insert_source_run
        await insert_source_run(run)

    table_mock.insert.assert_called_once()
    row = table_mock.insert.call_args[0][0]
    assert row["source_key"] == "kcoj_courtnet"
    assert row["status"] == "ok"
    assert row["records_found"] == 5
    assert row["records_new"] == 3


@pytest.mark.asyncio
async def test_insert_source_run_error_is_caught():
    """If the Supabase insert raises, it is caught and does not propagate."""
    run = _make_source_run()

    insert_chain = MagicMock()
    insert_chain.execute = MagicMock(side_effect=RuntimeError("DB error"))

    table_mock = MagicMock()
    table_mock.insert = MagicMock(return_value=insert_chain)

    supabase_mock = MagicMock()
    supabase_mock.table = MagicMock(return_value=table_mock)

    with patch("app.storage.supabase_client._get_client", return_value=supabase_mock):
        from app.storage.supabase_client import insert_source_run
        # Must not raise
        await insert_source_run(run)


# ---------------------------------------------------------------------------
# list_source_runs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_source_runs_returns_data():
    """list_source_runs returns the data array from Supabase."""
    fake_rows = [
        {"source_key": "kcoj_courtnet", "status": "ok", "records_found": 5},
    ]
    execute_result = MagicMock(data=fake_rows)
    chain = MagicMock()
    chain.execute = MagicMock(return_value=execute_result)

    select_chain = MagicMock()
    select_chain.order = MagicMock(
        return_value=MagicMock(
            limit=MagicMock(return_value=chain)
        )
    )

    table_mock = MagicMock()
    table_mock.select = MagicMock(return_value=select_chain)

    supabase_mock = MagicMock()
    supabase_mock.table = MagicMock(return_value=table_mock)

    with patch("app.storage.supabase_client._get_client", return_value=supabase_mock):
        from app.storage.supabase_client import list_source_runs
        result = await list_source_runs(limit=10)

    assert result == fake_rows


@pytest.mark.asyncio
async def test_list_source_runs_returns_empty_list_when_client_unavailable():
    """Returns [] if Supabase client is not available."""
    with patch("app.storage.supabase_client._get_client", return_value=None):
        from app.storage.supabase_client import list_source_runs
        result = await list_source_runs()

    assert result == []


# ---------------------------------------------------------------------------
# _lead_to_row
# ---------------------------------------------------------------------------

def test_lead_to_row_serializes_dates_as_iso():
    """_lead_to_row converts case_filed_date to ISO format string."""
    from app.storage.supabase_client import _lead_to_row
    lead = _make_lead()
    row = _lead_to_row(lead)
    assert row["case_filed_date"] == "2026-01-15"
    assert isinstance(row["scraped_at"], str)


def test_lead_to_row_none_date_stays_none():
    """_lead_to_row handles None case_filed_date without crashing."""
    from app.storage.supabase_client import _lead_to_row
    lead = _make_lead(case_filed_date=None)
    row = _lead_to_row(lead)
    assert row["case_filed_date"] is None
