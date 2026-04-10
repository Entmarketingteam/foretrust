"""Tests for app/pipeline/enrich.py — cross_reference_leads."""

from __future__ import annotations

from app.models import Lead, LeadType, Vertical
from app.pipeline.enrich import cross_reference_leads


def _court_lead(**kwargs) -> Lead:
    defaults = {
        "source_key": "kcoj_courtnet",
        "vertical": Vertical.RESIDENTIAL,
        "lead_type": LeadType.PROBATE,
        "owner_name": "JOHN DOE",
        "state": "KY",
    }
    defaults.update(kwargs)
    return Lead(**defaults)


def _pva_lead(**kwargs) -> Lead:
    defaults = {
        "source_key": "fayette_pva",
        "vertical": Vertical.RESIDENTIAL,
        "lead_type": LeadType.VACANCY,
        "owner_name": "JOHN DOE",
        "property_address": "123 OAK ST",
        "mailing_address": "123 OAK ST",
        "city": "LEXINGTON",
        "state": "KY",
        "postal_code": "40507",
        "parcel_number": "123-456-789",
        "building_sqft": 2500,
        "year_built": 1985,
        "estimated_value": 350_000.0,
    }
    defaults.update(kwargs)
    return Lead(**defaults)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_enriches_court_lead_with_pva_data():
    """A court lead with a matching owner name is enriched with PVA property data."""
    court = _court_lead()
    pva = _pva_lead()

    result = cross_reference_leads([court], [pva])

    assert len(result) == 1
    enriched = result[0]
    assert enriched.property_address == "123 OAK ST"
    assert enriched.city == "LEXINGTON"
    assert enriched.postal_code == "40507"
    assert enriched.parcel_number == "123-456-789"
    assert enriched.building_sqft == 2500
    assert enriched.year_built == 1985
    assert enriched.estimated_value == 350_000.0
    assert "pva_enrichment" in enriched.raw_payload


def test_happy_path_preserves_existing_court_data():
    """When court lead already has a property address, it is NOT overwritten by PVA."""
    court = _court_lead(property_address="456 COURT AVE", city="LEXINGTON")
    pva = _pva_lead(property_address="123 OAK ST", city="NICHOLASVILLE")

    result = cross_reference_leads([court], [pva])

    enriched = result[0]
    # Court data takes priority — "or" short-circuits when truthy
    assert enriched.property_address == "456 COURT AVE"
    assert enriched.city == "LEXINGTON"


# ---------------------------------------------------------------------------
# No match
# ---------------------------------------------------------------------------


def test_no_pva_records_returns_court_lead_as_is():
    """If pva_leads is empty, the court lead passes through unchanged."""
    court = _court_lead()
    result = cross_reference_leads([court], [])
    assert len(result) == 1
    assert result[0].property_address is None
    assert "pva_enrichment" not in result[0].raw_payload


def test_no_name_match_returns_lead_unenriched():
    """If no PVA record matches the owner name, the lead is returned as-is."""
    court = _court_lead(owner_name="JANE SMITH")
    pva = _pva_lead(owner_name="BOB JONES")

    result = cross_reference_leads([court], [pva])

    assert len(result) == 1
    assert result[0].property_address is None


def test_court_lead_with_no_owner_name_is_returned_as_is():
    """Court leads without an owner name are not matched but still returned."""
    court = _court_lead(owner_name=None)
    pva = _pva_lead()

    result = cross_reference_leads([court], [pva])

    assert len(result) == 1
    assert "pva_enrichment" not in result[0].raw_payload


# ---------------------------------------------------------------------------
# Partial match (some fields already set)
# ---------------------------------------------------------------------------


def test_partial_match_fills_only_missing_fields():
    """Court lead with some fields already set only gets the missing ones from PVA."""
    court = _court_lead(
        owner_name="JOHN DOE",
        property_address="ALREADY SET",
        city=None,
        postal_code=None,
    )
    pva = _pva_lead(
        owner_name="JOHN DOE",
        property_address="PVA ADDRESS",
        city="LEXINGTON",
        postal_code="40507",
    )

    result = cross_reference_leads([court], [pva])

    enriched = result[0]
    assert enriched.property_address == "ALREADY SET"   # court wins (already set)
    assert enriched.city == "LEXINGTON"                 # filled in from PVA
    assert enriched.postal_code == "40507"              # filled in from PVA


# ---------------------------------------------------------------------------
# Multiple court leads
# ---------------------------------------------------------------------------


def test_multiple_court_leads_matched_independently():
    """Each court lead is independently matched against the PVA index."""
    court1 = _court_lead(owner_name="ALICE WALKER", case_id="P-001")
    court2 = _court_lead(owner_name="BOB JOHNSON", case_id="P-002")

    pva1 = _pva_lead(owner_name="ALICE WALKER", property_address="100 ELM ST")
    pva2 = _pva_lead(owner_name="BOB JOHNSON", property_address="200 PINE ST")

    result = cross_reference_leads([court1, court2], [pva1, pva2])

    assert len(result) == 2
    alice_result = next(r for r in result if r.case_id == "P-001")
    bob_result = next(r for r in result if r.case_id == "P-002")
    assert alice_result.property_address == "100 ELM ST"
    assert bob_result.property_address == "200 PINE ST"


def test_unmatched_court_leads_are_still_returned():
    """Court leads that don't match a PVA record are still included in output."""
    court_matched = _court_lead(owner_name="JOHN DOE", case_id="P-001")
    court_unmatched = _court_lead(owner_name="NO MATCH NAME", case_id="P-002")
    pva = _pva_lead(owner_name="JOHN DOE")

    result = cross_reference_leads([court_matched, court_unmatched], [pva])

    assert len(result) == 2
    matched = next(r for r in result if r.case_id == "P-001")
    unmatched = next(r for r in result if r.case_id == "P-002")
    assert matched.property_address == "123 OAK ST"
    assert unmatched.property_address is None


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_inputs_return_empty():
    """Empty court_leads → empty result."""
    result = cross_reference_leads([], [])
    assert result == []


def test_name_matching_is_case_insensitive_via_normalize():
    """normalize_name is applied to both sides, so mixed-case names still match."""
    court = _court_lead(owner_name="john doe")      # lower-case
    pva = _pva_lead(owner_name="John Doe")          # title-case

    result = cross_reference_leads([court], [pva])

    assert result[0].property_address == "123 OAK ST"


def test_pva_enrichment_payload_attached():
    """raw_payload gets a pva_enrichment key containing the PVA raw_payload."""
    pva = _pva_lead(owner_name="JOHN DOE")
    pva.raw_payload = {"gis_parcel": "abc"}
    court = _court_lead(owner_name="JOHN DOE")

    result = cross_reference_leads([court], [pva])

    assert result[0].raw_payload["pva_enrichment"] == {"gis_parcel": "abc"}
