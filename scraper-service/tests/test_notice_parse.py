"""Tests for legal-notice → KCOJ search parsing."""

from app.connectors.residential.legal_notices import LegalNoticesConnector
from app.models import Lead, LeadType, RawRecord, Vertical
from app.pipeline.notice_parse import (
    extract_county_from_text,
    extract_party_searches,
    split_name,
)


def test_extract_county_fayette_county_phrase():
    assert extract_county_from_text("Estate of John Smith, Fayette County") == "Fayette"


def test_extract_county_lexington_alias():
    assert extract_county_from_text("Notice published in Lexington, KY") == "Fayette"


def test_extract_county_georgetown_alias():
    assert extract_county_from_text("Property near Georgetown") == "Scott"


def test_split_name_last_first():
    assert split_name("Smith, John") == ("Smith", "John")


def test_split_name_first_last():
    assert split_name("John Smith") == ("Smith", "John")


def test_legal_notices_parse_estate_fayette_example():
    raw = RawRecord(
        source_key="legal_notices",
        data={
            "title": "Estate of John Smith, Fayette County",
            "summary": "Notice to creditors regarding probate administration.",
            "matched_keywords": ["ESTATE OF", "PROBATE"],
            "source": "google_alerts_rss",
        },
    )
    lead = LegalNoticesConnector().parse(raw)

    assert lead.jurisdiction == "KY-Fayette"
    assert lead.lead_type == LeadType.PROBATE
    assert lead.owner_name == "John Smith"
    assert lead.raw_payload["detected_county"] == "Fayette"
    assert lead.raw_payload["courtnet_search"] == {
        "county": "Fayette",
        "last_name": "Smith",
        "first_name": "John",
        "case_category": "P - Probate",
        "lead_type": "probate",
    }


def test_extract_party_searches_dedupes_by_county_last_name():
    lead_a = Lead(
        source_key="legal_notices",
        vertical=Vertical.RESIDENTIAL,
        jurisdiction="KY-Fayette",
        lead_type=LeadType.PROBATE,
        owner_name="John Smith",
        raw_payload={
            "courtnet_search": {
                "county": "Fayette",
                "last_name": "Smith",
                "first_name": "John",
                "case_category": "P - Probate",
                "lead_type": "probate",
            },
        },
    )
    lead_b = Lead(
        source_key="legal_notices",
        vertical=Vertical.RESIDENTIAL,
        jurisdiction="KY-Fayette",
        lead_type=LeadType.ESTATE,
        owner_name="John Q. Smith",
        raw_payload={
            "courtnet_search": {
                "county": "Fayette",
                "last_name": "Smith",
                "first_name": "John Q.",
                "case_category": "P - Probate",
                "lead_type": "estate",
            },
        },
    )

    searches = extract_party_searches([lead_a, lead_b])
    assert len(searches) == 1
    assert searches[0]["county"] == "Fayette"
    assert searches[0]["last_name"] == "Smith"
