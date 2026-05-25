"""Post-search filters — mimic how you'd skim eCCLIX grids for real deals."""

from __future__ import annotations

import re
from typing import Any

from app.pipeline.investment_scorer import is_human_owner

# Premium Central KY subdivisions (big-home / 203k targets)
PREMIUM_SUBDIVISIONS = re.compile(
    r"CHERRY\s+BLOSSOM|IRONWORKS|CANEBERRY|CHERRY\s+GROVE|LEGENDS|"
    r"ANDOVER|STONEBRIDGE|HIDDEN\s+CREEK|SIENNA|VILLAGE\s+PARK|"
    r"CHEROKEE|WEXFORD|BRAMBLEWOOD|HARTLAND|WELLINGTON",
    re.I,
)
DIVORCE_DOMESTIC = re.compile(
    r"divorce|dissolution|marital|domestic\s+relations|separation|"
    r"equitable\s+distribution|QDRO",
    re.I,
)
ESTATE_LEGAL = re.compile(r"estate\s+of|executor|administrator|heirs|decedent", re.I)
BIG_HOME_LEGAL = re.compile(
    r"\bLOT\b.*\b(SUBDIV|VILLAGE|PHASE|ESTATES?)\b|"
    r"\bUNIT\b.*\b(CONDO|TOWNHOME)\b",
    re.I,
)
JUDGMENT_LIEN = re.compile(r"judgment|judgement|city\s+lien|code\s+enforcement|nuisance", re.I)
FORECLOSURE_LEGAL = re.compile(
    r"foreclos|lis\s+pendens|mortgage\s+default|deed\s+of\s+trust|"
    r"substitute\s+trustee|master\s+commissioner",
    re.I,
)
BANK_PARTY = re.compile(
    r"pennymac|truist|wells\s*fargo|bank\s*of\s*america|newrez|"
    r"freedom\s*mortgage|shellpoint|pnc|u\s*s\s*bank|veterans\s*united",
    re.I,
)


def _text_blob(row: dict[str, Any]) -> str:
    parts = [
        row.get("legal_description"),
        row.get("row_text"),
        row.get("grantor"),
        row.get("grantee"),
        row.get("owner_name"),
        row.get("property_address"),
        " ".join(row.get("cells") or []),
    ]
    return " ".join(str(p) for p in parts if p)


def apply_filters(
    row: dict[str, Any],
    filter_tags: tuple[str, ...],
    *,
    min_tax_due: float = 0,
    min_consideration: float = 0,
) -> tuple[bool, list[str]]:
    """Return (keep, reasons). Empty filter_tags = keep all."""
    if not filter_tags:
        return True, ["no_filter"]

    reasons: list[str] = []
    blob = _text_blob(row)
    owner = row.get("owner_name") or row.get("grantor") or ""
    inst = (row.get("instrument_type") or "").upper()
    due = float(row.get("amount_due") or 0)
    cons = float(row.get("consideration_amount") or row.get("consideration") or 0)

    for tag in filter_tags:
        if tag == "human_owner_only":
            if not is_human_owner(owner):
                return False, ["skip_entity"]
            reasons.append("human_owner")

        elif tag == "street_address":
            addr = (row.get("property_address") or "").strip()
            if not re.match(r"^\d+\s+\S", addr):
                # Tax rows use property_address; instrument rows may only have legal
                if not PREMIUM_SUBDIVISIONS.search(blob) and not BIG_HOME_LEGAL.search(blob):
                    return False, ["no_street_or_subdivision"]
            reasons.append("addressable")

        elif tag == "min_tax_500":
            if due < 500:
                return False, ["tax_below_500"]
            reasons.append(f"tax_due_{due:.0f}")

        elif tag == "min_tax_2000":
            if due < 2000:
                return False, ["tax_below_2000"]
            reasons.append(f"tax_due_{due:.0f}")

        elif tag == "premium_subdivision":
            if not PREMIUM_SUBDIVISIONS.search(blob):
                return False, ["not_premium_subdivision"]
            reasons.append("premium_subdivision")

        elif tag == "big_home_signal":
            if not (
                PREMIUM_SUBDIVISIONS.search(blob)
                or BIG_HOME_LEGAL.search(blob)
                or (cons and cons >= 300_000)
            ):
                return False, ["not_big_home_signal"]
            reasons.append("big_home")

        elif tag == "divorce_domestic":
            if inst != "LP" and not DIVORCE_DOMESTIC.search(blob):
                return False, ["no_divorce_signal"]
            reasons.append("divorce_domestic")

        elif tag == "estate_deed":
            if not ESTATE_LEGAL.search(blob):
                return False, ["no_estate_marker"]
            reasons.append("estate")

        elif tag == "foreclosure_lp":
            if inst != "LP" and not FORECLOSURE_LEGAL.search(blob):
                return False, ["not_foreclosure_lp"]
            reasons.append("foreclosure_lp")

        elif tag == "bank_counterparty":
            grantee = row.get("grantee") or ""
            if not BANK_PARTY.search(blob) and not BANK_PARTY.search(grantee):
                return False, ["no_bank_party"]
            reasons.append("bank_party")

        elif tag == "city_lien":
            if not JUDGMENT_LIEN.search(blob):
                return False, ["not_city_lien"]
            reasons.append("city_lien")

        elif tag == "any_distress":
            if not any(
                (
                    due >= 500,
                    FORECLOSURE_LEGAL.search(blob),
                    ESTATE_LEGAL.search(blob),
                    DIVORCE_DOMESTIC.search(blob),
                    JUDGMENT_LIEN.search(blob),
                    BANK_PARTY.search(blob),
                    PREMIUM_SUBDIVISIONS.search(blob),
                )
            ):
                return False, ["no_distress_signal"]
            reasons.append("distress")

    if min_tax_due and due < min_tax_due:
        return False, ["below_min_tax"]
    if min_consideration and cons < min_consideration:
        return False, ["below_min_consideration"]

    return True, reasons or ["matched"]


def hot_tier(row: dict[str, Any], filter_reasons: list[str]) -> str:
    """A/B/C tier for export sorting."""
    scores = row.get("investment_scores") or {}
    pre = scores.get("pre_mls_score", 0)
    if pre >= 75 or "bank_party" in filter_reasons and "premium_subdivision" in filter_reasons:
        return "A"
    if pre >= 55 or "distress" in filter_reasons or row.get("amount_due", 0) >= 3000:
        return "B"
    return "C"
