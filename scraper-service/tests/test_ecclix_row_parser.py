"""Tests for the eCCLIX instrument cell exploder.

Fixtures are real captures pulled from ft_leads.raw_payload->'cells' (Woodford
county, 5/2026 harvest). The eCCLIX instrument grid renders each record across
two physical lines of 5 cells:

    INS#/DATE | PARTY1/PARTY2 | TYPE | BK/PG | DESCRIPTION
    (blank)   | <grantor>     | TYPE | BK/PG | <legal/desc>
    <date>    | <grantee>     |      | N PAGES |
"""
from app.connectors.residential.ecclix_row_parser import explode_instrument_cells


# A real blob: nav chrome + header + 3 records + trailing nav (trimmed).
BLOB = [
    "Navigation:\nWelcome\nInstruments ▼", "New Search | Back",
    "INS#/DATE", "PARTY1/PARTY2", "TYPE", "BK/PG", "DESCRIPTION",
    "", "HOERIG, BRADFORD N", "DEED", "D358 584", "1 AC SCOTTS FERRY ROAD",
    "5/22/2026", "GOODE, MARK DOUGLAS", "", "3 PAGES", "",
    "", "GRANTLEY ACRES LLC", "MTG", "M1028 505", "LT 35 SCHOBERTH PLACE",
    "5/22/2026", "FARM CREDIT MID AMERICA FLCA", "", "10 PAGES", "",
    "", "CITY NATIONAL BANK OF WEST VIRGINIA", "REL", "DMR125 562", "",
    "5/22/2026", "GARDNER, NIKKI RENE", "", "2 PAGES", "",
    " Navigate to page \n1\n2\n3\n4\n5\n6\n7",
]

# A 5-cell single-line capture (line 2 was lost by the scraper).
HALF = ["", "BIBBS, CEDRIC DE ANDRE LIVING TRUST", "MLIEN", "ML5 315",
        "101 TANBARK DR FOREST OAKS"]

# A 7-cell delinquent-tax row must NOT be parsed as an instrument.
TAX = ["134", "2025", "ADENA WOODS PROPERTIES LLC", "LANE CIRCLE",
       "31-1027-006-00", "10.96", "24.17"]

# Pure nav junk, no instrument records.
NAV = ["Navigation:\nWelcome", "New Search | Back", "1\n2\n3\n4\n5"]


def test_blob_explodes_into_individual_records():
    recs = explode_instrument_cells(BLOB)
    assert len(recs) == 3, [r["grantor"] for r in recs]

    deed = recs[0]
    assert deed["grantor"] == "HOERIG, BRADFORD N"
    assert deed["instrument_type"] == "DEED"
    assert deed["book"] == "D358"
    assert deed["page"] == "584"
    assert deed["legal_description"] == "1 AC SCOTTS FERRY ROAD"
    assert deed["recorded_date"] == "5/22/2026"
    assert deed["grantee"] == "GOODE, MARK DOUGLAS"

    # Record with empty DESCRIPTION still parses cleanly.
    rel = recs[2]
    assert rel["grantor"] == "CITY NATIONAL BANK OF WEST VIRGINIA"
    assert rel["instrument_type"] == "REL"
    assert rel["book"] == "DMR125"
    assert rel["page"] == "562"
    assert rel["grantee"] == "GARDNER, NIKKI RENE"


def test_half_record_5_cells():
    recs = explode_instrument_cells(HALF)
    assert len(recs) == 1
    r = recs[0]
    assert r["grantor"] == "BIBBS, CEDRIC DE ANDRE LIVING TRUST"
    assert r["instrument_type"] == "MLIEN"
    assert r["book"] == "ML5"
    assert r["page"] == "315"
    assert r["legal_description"] == "101 TANBARK DR FOREST OAKS"
    # No line-2 was captured -> date/grantee blank, not garbage.
    assert r["recorded_date"] == ""
    assert r["grantee"] == ""


def test_tax_row_not_parsed_as_instrument():
    # cell[2]="ADENA WOODS..." is not an instrument code -> no records.
    assert explode_instrument_cells(TAX) == []


def test_nav_junk_yields_nothing():
    assert explode_instrument_cells(NAV) == []
    assert explode_instrument_cells([]) == []
