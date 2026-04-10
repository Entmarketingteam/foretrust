"""Tests for the normalize pipeline."""

from app.pipeline.normalize import normalize_name, normalize_address, normalize_lead
from app.models import Lead, LeadType, Vertical


def test_normalize_name_basic():
    assert normalize_name("  John  Smith  ") == "JOHN SMITH"
    assert normalize_name("Jane Doe, Jr") == "JANE DOE"
    assert normalize_name("Bob Jones Sr") == "BOB JONES"
    assert normalize_name(None) is None
    assert normalize_name("") is None


def test_normalize_address():
    assert normalize_address("123 Main Street") == "123 MAIN ST"
    assert normalize_address("456 North Oak Avenue") == "456 N OAK AVE"
    assert normalize_address(None) is None


def test_normalize_lead():
    lead = Lead(
        source_key="test",
        vertical=Vertical.RESIDENTIAL,
        lead_type=LeadType.PROBATE,
        owner_name="  john doe, jr  ",
        property_address="123 Main Street",
        city="  lexington  ",
        state="ky",
        postal_code="40507-1234",
    )
    result = normalize_lead(lead)
    assert result.owner_name == "JOHN DOE"
    assert result.property_address == "123 MAIN ST"
    assert result.city == "LEXINGTON"
    assert result.state == "KY"
    assert result.postal_code == "40507"
