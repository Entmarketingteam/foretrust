"""parse() must give eCCLIX instrument leads a deterministic identity hash.

This is the key that lets a re-harvest dedupe against the recovered rows the
backfill inserted, instead of creating duplicates. The formula must stay in
lockstep with backfill_ecclix.dedupe_hash:
    source_key | county | book | page | grantor | grantee | instrument_type
"""
import hashlib

from app.connectors.residential.ecclix_batch import ECCLIXBatchConnector
from app.models import RawRecord


def _hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def test_instrument_lead_dedupe_hash_matches_identity_key():
    conn = ECCLIXBatchConnector()
    payload = {
        "county": "woodford", "instrument_type": "DEED", "book": "D358",
        "page": "584", "grantor": "HOERIG, BRADFORD N",
        "grantee": "GOODE, MARK DOUGLAS",
        "property_address": "1 AC SCOTTS FERRY ROAD",
    }
    lead = conn.parse(RawRecord(source_key="ecclix_batch", data=payload))

    expected = _hash("ecclix_batch", "Woodford", "D358", "584",
                     "HOERIG, BRADFORD N", "GOODE, MARK DOUGLAS", "DEED")
    assert lead.dedupe_hash == expected
    assert lead.case_id == "D358/584"
    assert lead.owner_name == "HOERIG, BRADFORD N"
    assert lead.property_address == "1 AC SCOTTS FERRY ROAD"


def test_distinct_grantees_get_distinct_hashes():
    conn = ECCLIXBatchConnector()
    base = {"county": "woodford", "instrument_type": "DEED", "book": "D358",
            "page": "584", "grantor": "HOERIG, BRADFORD N"}
    h1 = conn.parse(RawRecord(source_key="ecclix_batch",
                              data={**base, "grantee": "GOODE, MARK"})).dedupe_hash
    h2 = conn.parse(RawRecord(source_key="ecclix_batch",
                              data={**base, "grantee": "ENGLISH GOODE, HEATHER"})).dedupe_hash
    assert h1 != h2
