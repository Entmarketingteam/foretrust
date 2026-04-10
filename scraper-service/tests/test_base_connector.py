"""Tests for the base connector contract and distress scorer."""

from datetime import date, timedelta

from app.models import Lead, LeadType, Vertical
from app.pipeline.distress_scorer import compute_hot_score, score_leads


def _make_lead(**kwargs) -> Lead:
    defaults = {
        "source_key": "test",
        "vertical": Vertical.RESIDENTIAL,
        "lead_type": LeadType.PROBATE,
    }
    defaults.update(kwargs)
    return Lead(**defaults)


def test_base_weight():
    lead = _make_lead(lead_type=LeadType.FORECLOSURE)
    score = compute_hot_score(lead)
    assert score == 30  # FORECLOSURE base weight


def test_recency_boost():
    recent = _make_lead(
        lead_type=LeadType.PROBATE,
        case_filed_date=date.today() - timedelta(days=10),
    )
    old = _make_lead(
        lead_type=LeadType.PROBATE,
        case_filed_date=date.today() - timedelta(days=200),
    )
    assert compute_hot_score(recent) > compute_hot_score(old)


def test_sqft_boost():
    big = _make_lead(lead_type=LeadType.VACANCY, building_sqft=8000)
    small = _make_lead(lead_type=LeadType.VACANCY, building_sqft=2000)
    assert compute_hot_score(big) > compute_hot_score(small)


def test_value_boost():
    high = _make_lead(lead_type=LeadType.PROBATE, estimated_value=750_000)
    low = _make_lead(lead_type=LeadType.PROBATE, estimated_value=100_000)
    assert compute_hot_score(high) > compute_hot_score(low)


def test_stacking():
    lead = _make_lead(lead_type=LeadType.PROBATE)
    unstacked = compute_hot_score(lead, stacked_signals=0)
    stacked = compute_hot_score(lead, stacked_signals=2)
    assert stacked > unstacked
    assert stacked <= 100


def test_score_leads_sorts_descending():
    leads = [
        _make_lead(lead_type=LeadType.CODE_VIOLATION),  # low weight
        _make_lead(lead_type=LeadType.FORECLOSURE, estimated_value=1_000_000),  # high
    ]
    scored = score_leads(leads)
    assert scored[0].hot_score >= scored[1].hot_score


def test_dedupe_hash():
    lead = _make_lead(parcel_number="123-456", case_id="P-2026-001")
    assert lead.dedupe_hash
    assert len(lead.dedupe_hash) == 64

    # Same data = same hash
    lead2 = _make_lead(parcel_number="123-456", case_id="P-2026-001")
    assert lead.dedupe_hash == lead2.dedupe_hash

    # Different data = different hash
    lead3 = _make_lead(parcel_number="789-012", case_id="P-2026-002")
    assert lead.dedupe_hash != lead3.dedupe_hash
