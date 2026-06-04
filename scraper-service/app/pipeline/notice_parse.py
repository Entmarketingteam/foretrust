"""Parse legal-notice leads into KCOJ CourtNet party search parameters."""

from __future__ import annotations

import re
from typing import Any

from app.models import Lead, LeadType

DEFAULT_COUNTIES = [
    "Fayette", "Scott", "Oldham", "Woodford", "Jessamine", "Clark", "Madison", "Jefferson",
]

# City / region aliases → canonical KCOJ county label (title case)
KY_COUNTY_ALIASES: dict[str, str] = {
    "lexington": "Fayette",
    "georgetown": "Scott",
    "versailles": "Woodford",
    "nicholasville": "Jessamine",
    "winchester": "Clark",
    "richmond": "Madison",
    "louisville": "Jefferson",
    "la grange": "Oldham",
    "lagrange": "Oldham",
    "prospect": "Oldham",
    "crestwood": "Oldham",
    "st matthews": "Jefferson",
    "saint matthews": "Jefferson",
    "jeffersontown": "Jefferson",
    "shively": "Jefferson",
}

LEAD_TYPE_TO_CASE_CATEGORY: dict[LeadType, str] = {
    LeadType.PROBATE: "P - Probate",
    LeadType.ESTATE: "P - Probate",
    LeadType.DEATH: "P - Probate",
    LeadType.DIVORCE: "D - Domestic Relations",
    LeadType.FORECLOSURE: "CI - Civil",
    LeadType.PRE_FORECLOSURE: "CI - Civil",
    LeadType.TAX_LIEN: "CI - Civil",
}

# Longest aliases first so "la grange" wins over "grange"
_ALIAS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"\b{re.escape(alias)}\b", re.IGNORECASE), county)
    for alias, county in sorted(KY_COUNTY_ALIASES.items(), key=lambda x: -len(x[0]))
]

_COUNTY_PATTERNS: list[tuple[re.Pattern[str], str]] = []
for _county in DEFAULT_COUNTIES:
    _name = re.escape(_county)
    _flags = re.IGNORECASE
    _COUNTY_PATTERNS.append(
        (re.compile(rf"\b{_name}\s+County\b", _flags), _county),
    )
    _COUNTY_PATTERNS.append(
        (re.compile(rf"\bCounty\s+of\s+{_name}\b", _flags), _county),
    )
    _COUNTY_PATTERNS.append(
        (re.compile(rf"\b{_name}\b", _flags), _county),
    )


def extract_county_from_text(text: str) -> str | None:
    """Return a DEFAULT_COUNTIES label when county name or alias appears in text."""
    if not text or not text.strip():
        return None

    for pattern, county in _COUNTY_PATTERNS:
        if pattern.search(text):
            return county

    for pattern, county in _ALIAS_PATTERNS:
        if pattern.search(text):
            return county

    return None


def split_name(owner_name: str | None) -> tuple[str | None, str | None]:
    """Split a person name into (last_name, first_name)."""
    if not owner_name or not owner_name.strip():
        return None, None

    name = re.sub(r"\s+", " ", owner_name.strip())
    name = re.sub(
        r"^(?:ESTATE\s+OF|IN\s+RE\s+(?:THE\s+)?ESTATE\s+OF|IN\s+RE)\s+",
        "",
        name,
        flags=re.IGNORECASE,
    ).strip()
    name = name.rstrip(",.")

    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2 and parts[0] and parts[1]:
            return parts[0], parts[1]

    tokens = name.split()
    if not tokens:
        return None, None
    if len(tokens) == 1:
        return tokens[0], None

    suffixes = {"JR", "SR", "II", "III", "IV", "V"}
    while tokens and tokens[-1].upper().rstrip(".") in suffixes:
        tokens.pop()

    if len(tokens) == 1:
        return tokens[0], None

    return tokens[-1], " ".join(tokens[:-1]) or None


def lead_type_to_case_category(lead_type: LeadType) -> str:
    return LEAD_TYPE_TO_CASE_CATEGORY.get(lead_type, "P - Probate")


def build_courtnet_search_hint(
    *,
    county: str | None,
    owner_name: str | None,
    lead_type: LeadType,
) -> dict[str, Any] | None:
    """Build a KCOJ party-search hint dict, or None if county/last name missing."""
    if not county:
        return None

    last_name, first_name = split_name(owner_name)
    if not last_name:
        return None

    hint: dict[str, Any] = {
        "county": county,
        "last_name": last_name,
        "case_category": lead_type_to_case_category(lead_type),
        "lead_type": lead_type.value,
    }
    if first_name:
        hint["first_name"] = first_name
    return hint


def _county_from_lead(lead: Lead) -> str | None:
    if lead.raw_payload.get("detected_county"):
        return str(lead.raw_payload["detected_county"])

    jurisdiction = lead.jurisdiction or ""
    if jurisdiction.startswith("KY-") and jurisdiction != "KY-Multi":
        return jurisdiction[3:]

    text_parts = [
        lead.raw_payload.get("title", ""),
        lead.raw_payload.get("summary", ""),
        lead.raw_payload.get("text", ""),
    ]
    combined = " ".join(str(p) for p in text_parts if p)
    return extract_county_from_text(combined)


def extract_party_searches(leads: list[Lead]) -> list[dict[str, Any]]:
    """Derive deduped KCOJ party searches from legal-notice (or similar) leads."""
    seen: set[tuple[str, str]] = set()
    searches: list[dict[str, Any]] = []

    for lead in leads:
        hint = lead.raw_payload.get("courtnet_search")
        if isinstance(hint, dict) and hint.get("county") and hint.get("last_name"):
            county = str(hint["county"])
            last_name = str(hint["last_name"])
            first_name = hint.get("first_name")
            case_category = hint.get("case_category") or lead_type_to_case_category(lead.lead_type)
            lead_type_val = hint.get("lead_type", lead.lead_type.value)
        else:
            county = _county_from_lead(lead)
            last_name, first_name = split_name(lead.owner_name)
            if not county or not last_name:
                continue
            case_category = lead_type_to_case_category(lead.lead_type)
            lead_type_val = lead.lead_type.value

        key = (county.title(), last_name.upper())
        if key in seen:
            continue
        seen.add(key)

        entry: dict[str, Any] = {
            "county": county.title(),
            "last_name": last_name,
            "case_category": case_category,
            "lead_type": lead_type_val,
        }
        if first_name:
            entry["first_name"] = first_name
        searches.append(entry)

    return searches
