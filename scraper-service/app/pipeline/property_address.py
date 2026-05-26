"""Validate and normalize property addresses vs legal descriptions / bill numbers."""

from __future__ import annotations

import re
from typing import Any

# Standard KY street suffixes (uppercase match)
_STREET_SUFFIX = re.compile(
    r"\b("
    r"STREET|ST|AVENUE|AVE|ROAD|RD|DRIVE|DR|LANE|LN|WAY|COURT|CT|"
    r"CIRCLE|CIR|PIKE|BLVD|BOULEVARD|TRAIL|TRL|PATH|PT|PLACE|PL|"
    r"HWY|HIGHWAY|PKWY|PARKWAY|WALK|ROW|ALLEY|COVE|RUN|LOOP|PASS"
    r")\b",
    re.I,
)

_STREET_NUMBER = re.compile(r"^\d{1,6}\s+\S")

# Legal / parcel language — not mailable street addresses
_LEGAL_MARKERS = re.compile(
    r"\b("
    r"LOT|LOTS|BLOCK|BLK|UNIT|PHASE|TRACT|SUBDIV|SUBDIVISION|SECTION|SEC|"
    r"ACRES?|AC\b|PARCEL|PLAT|MINOR|BRANCH|PHASE|CONDO|CONDOMINIUM|"
    r"EASEMENT|ROW OF|PART OF|BEING|DESCRIBED|COMMENCING|CONTAINING|"
    r"FKA|AKA|ET\s+AL|HEIRS|ESTATE OF|UPI\b|LEASE\b|SUBORD"
    r")\b",
    re.I,
)

_BILL_OR_MAP_ONLY = re.compile(
    r"^[\d\s\.\-/]+$|^\d+\s+\d+\s+(LOT|BLOCK|UNIT|TRACT|AC)",
    re.I,
)

_JUNK = re.compile(
    r"login|password|ecclix|between dates|bill\s*#|tax year|walkthrough",
    re.I,
)


def is_likely_legal_description(text: str) -> bool:
    s = (text or "").strip()
    if not s or len(s) < 8:
        return False
    if _STREET_SUFFIX.search(s) and _STREET_NUMBER.match(s) and not _LEGAL_MARKERS.search(s):
        return False
    if _LEGAL_MARKERS.search(s):
        return True
    if re.search(r"\b\d+\s+\d+\s+LOT\b", s, re.I):
        return True
    if re.search(r"\bLOT\s+\d+\b", s, re.I) and not _STREET_SUFFIX.search(s):
        return True
    return False


def is_valid_street_address(text: str) -> bool:
    """True when text looks like a mailable situs address (not legal / bill / map)."""
    s = (text or "").strip()
    if not s or len(s) < 6 or len(s) > 120:
        return False
    if _JUNK.search(s):
        return False
    if _BILL_OR_MAP_ONLY.match(s):
        return False
    if not _STREET_NUMBER.match(s):
        return False
    if not _STREET_SUFFIX.search(s):
        return False
    if is_likely_legal_description(s):
        return False
    # Reject tab-separated grantor/instrument junk
    if "\t" in s:
        return False
    return True


def extract_address_from_legal(legal: str) -> str | None:
    """Pull embedded street address from legal description if present."""
    if not legal:
        return None
    suffix = (
        r"Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|"
        r"Way|Court|Ct|Pike|Blvd|Boulevard|Trail|Trl|Walk|Circle|Cir"
    )
    # Bounded word span — avoids swallowing LOT 5 … BEING 123 … as one match
    pattern = re.compile(
        rf"\b(\d{{1,6}}\s+(?:\S+\s+){{0,5}}(?:{suffix}))(?:\s|$)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(legal):
        start = m.start(1)
        prefix = legal[max(0, start - 10):start].upper()
        if re.search(r"(LOT|BLOCK|UNIT|PHASE|TRACT|SEC|PARCEL)\s*$", prefix):
            continue
        candidate = re.sub(r"\s+", " ", m.group(1).strip().upper())
        if is_valid_street_address(candidate):
            return candidate
    return None


def normalize_property_address(
    raw: str | None,
    *,
    legal: str | None = None,
    map_id: str | None = None,
) -> str | None:
    """Return cleaned situs address or None — never legal text or bill numbers."""
    for candidate in (raw, extract_address_from_legal(legal or "")):
        if not candidate:
            continue
        s = re.sub(r"\s+", " ", candidate.strip().upper())
        if is_valid_street_address(s):
            return s
    return None


def sanitize_tax_row(row: dict[str, Any]) -> dict[str, Any]:
    """Fix delinquent-tax row property_address from cells or mis-mapped columns."""
    cells = row.get("cells") or []
    candidates: list[str] = []

    raw_addr = (row.get("property_address") or "").strip()
    if raw_addr:
        candidates.append(raw_addr)

    for cell in cells:
        t = (cell or "").strip()
        if t and is_valid_street_address(t):
            candidates.append(t)

    legal = raw_addr if is_likely_legal_description(raw_addr) else ""
    if not legal:
        for cell in cells:
            if is_likely_legal_description(str(cell)):
                legal = str(cell)
                break

    fixed = None
    for c in candidates:
        fixed = normalize_property_address(c, legal=legal, map_id=row.get("map_id"))
        if fixed:
            break

    if not fixed:
        fixed = normalize_property_address(None, legal=legal or raw_addr)

    out = {**row}
    if fixed:
        out["property_address"] = fixed
    elif raw_addr and not is_valid_street_address(raw_addr):
        out["property_address"] = None
        out["legal_description"] = out.get("legal_description") or raw_addr
    return out


def sanitize_lead_address(lead: dict[str, Any]) -> dict[str, Any]:
    """Sanitize property_address on a flat lead dict."""
    payload = lead.get("raw_payload") or {}
    if isinstance(payload, dict):
        legal = payload.get("legal_description") or lead.get("legal_description")
        map_id = lead.get("parcel_number") or payload.get("map_id")
    else:
        legal = lead.get("legal_description")
        map_id = lead.get("parcel_number")

    addr = normalize_property_address(
        lead.get("property_address"),
        legal=str(legal or ""),
        map_id=str(map_id or ""),
    )
    out = {**lead}
    if addr:
        out["property_address"] = addr
    elif lead.get("property_address") and not is_valid_street_address(
        str(lead.get("property_address"))
    ):
        out["property_address"] = None
    return out
