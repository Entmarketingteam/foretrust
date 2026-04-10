"""Address/name canonicalization, dedup hash, and shared parse utilities."""

from __future__ import annotations

import re
from datetime import date, datetime

from app.models import Lead

# Common date formats across county sources
_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%Y%m%d")


def normalize_name(name: str | None) -> str | None:
    """Normalize a person/entity name for matching."""
    if not name:
        return None
    # Uppercase, strip extra whitespace
    name = re.sub(r"\s+", " ", name.strip().upper())
    # Remove common suffixes that vary across sources
    for suffix in [", JR", ", SR", ", II", ", III", ", IV", " JR", " SR"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def normalize_address(address: str | None) -> str | None:
    """Normalize a street address for matching."""
    if not address:
        return None
    address = re.sub(r"\s+", " ", address.strip().upper())
    # Standard abbreviations
    replacements = {
        " STREET": " ST",
        " AVENUE": " AVE",
        " BOULEVARD": " BLVD",
        " DRIVE": " DR",
        " LANE": " LN",
        " ROAD": " RD",
        " COURT": " CT",
        " CIRCLE": " CIR",
        " PLACE": " PL",
        " NORTH ": " N ",
        " SOUTH ": " S ",
        " EAST ": " E ",
        " WEST ": " W ",
    }
    for full, abbr in replacements.items():
        address = address.replace(full, abbr)
    return address


def parse_date(s: str | None) -> date | None:
    """Parse a date string trying multiple common formats."""
    if not s or not s.strip():
        return None
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_currency(s: str | None) -> float | None:
    """Parse a dollar amount string like '$1,234,567.89' into a float."""
    if not s:
        return None
    cleaned = str(s).replace(",", "").replace("$", "").strip()
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_int_commas(s: str | None) -> int | None:
    """Parse a comma-formatted integer like '14,500' into an int."""
    if not s:
        return None
    cleaned = str(s).replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def normalize_lead(lead: Lead) -> Lead:
    """Apply normalization to a lead's fields in place and return it."""
    lead.owner_name = normalize_name(lead.owner_name)
    lead.property_address = normalize_address(lead.property_address)
    lead.mailing_address = normalize_address(lead.mailing_address)
    if lead.city:
        lead.city = lead.city.strip().upper()
    if lead.state:
        lead.state = lead.state.strip().upper()
    if lead.postal_code:
        lead.postal_code = lead.postal_code.strip()[:5]
    return lead
