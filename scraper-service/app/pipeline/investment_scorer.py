"""Multi-strategy investment scoring for KY residential distress leads.

Categories (0–100 each):
  wholesale_score      — cash flip / assignment (needs equity)
  creative_score       — subject-to / mortgage takeover (low equity, recent loan)
  fha_203k_score       — owner-occupant renovation loan (old home + equity room)
  short_sale_score     — bank LP + low equity → lender-approved discount
  pre_mls_score        — best owner-occupant deal before listing (203k / conventional)
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

# Major residential servicers → confirms SFR with mortgage (not vacant land only)
BANK_SERVICERS = re.compile(
    r"pennymac|lakeview|truist|wells\s*fargo|bank\s*of\s*america|newrez|"
    r"freedom\s*mortgage|shellpoint|stockton|pnc|u\s*s\s*bank|amerisave|"
    r"planet\s*home|veterans\s*united|mortgage\s*research",
    re.I,
)
TAX_BUYER_FORECLOSERS = re.compile(
    r"orchard\s*tax|east\s*coast\s*tax|lien\s*works",
    re.I,
)
ESTATE_MARKERS = re.compile(r"estate\s+of|executor|administrator|heirs", re.I)
SUBDIVISION_LOT = re.compile(r"\bLOT\b|\bUNIT\b|\bSUBDIVISION\b|\bPHASE\b", re.I)
RAW_ACREAGE = re.compile(r"\b\d+\.?\d*\s*ACRES?\b", re.I)
ENTITY_OWNER = re.compile(
    r"\b(LLC|INC|CORP|LTD|BANK|TRUST CO|PROPERTIES|HOLDINGS|TRANSPORT|"
    r"REAL ESTATE|MANAGEMENT|PARTNERSHIP|LLP|STORES|COMPANY)\b|#\d+",
    re.I,
)
STREET_NUMBER = re.compile(r"^\d+\s+\S")


def is_human_owner(name: str | None) -> bool:
    if not name:
        return False
    if ENTITY_OWNER.search(name):
        return False
    return len(name.strip()) >= 4


def score_from_lead_data(data: dict[str, Any]) -> dict[str, int]:
    """Compute wholesale / creative / fha_203k scores from merged lead payload."""
    today = date.today()
    inst = (data.get("instrument_type") or "").upper()
    grantor = data.get("grantor") or data.get("owner_name") or ""
    grantee = data.get("grantee") or ""
    parties = f"{grantor} {grantee} {data.get('row_text', '')}"
    legal = data.get("legal_description") or data.get("row_text") or ""
    assessed = _float(data.get("estimated_value") or data.get("assessed_value"))
    last_sale = _float(data.get("last_sale_price"))
    last_sale_year = _int(data.get("last_sale_year"))
    year_built = _int(data.get("year_built"))
    amount_due = _float(data.get("amount_due") or data.get("tax_amount_due"))
    sqft = _int(data.get("building_sqft") or data.get("living_sqft"))
    lp_active = inst == "LP" or data.get("lp_active") or data.get("search_profile") == "lp_recent"

    years_owned = (today.year - last_sale_year) if last_sale_year else None
    equity_pct = None
    if assessed and last_sale and assessed > 0:
        equity_pct = max(0.0, (assessed - last_sale) / assessed * 100.0)

    wholesale = 20
    creative = 15
    fha_203k = 15
    short_sale = 10
    pre_mls = 15
    owner = data.get("owner_name") or grantor
    human = is_human_owner(owner)
    has_street = bool(STREET_NUMBER.match((data.get("property_address") or "").strip()))

    # --- Motivation ---
    if lp_active:
        wholesale += 20
        creative += 25
        fha_203k += 15
    if amount_due and amount_due >= 500:
        wholesale += 15
    if amount_due and amount_due >= 2000 and human and has_street:
        fha_203k += 15
        pre_mls += 18
        wholesale += 10
    if amount_due and amount_due >= 3500 and human and has_street:
        pre_mls += 22
        short_sale += 8  # may precede LP filing
    if amount_due and amount_due < 100:
        wholesale -= 10  # fragment bills

    if TAX_BUYER_FORECLOSERS.search(parties):
        wholesale += 25
        creative += 20

    if BANK_SERVICERS.search(parties) and SUBDIVISION_LOT.search(legal):
        wholesale += 15
        creative += 20
        fha_203k += 10

    if ESTATE_MARKERS.search(parties) or ESTATE_MARKERS.search(legal):
        wholesale += 20
        fha_203k += 25

    if RAW_ACREAGE.search(legal) and not SUBDIVISION_LOT.search(legal):
        wholesale -= 15
        creative -= 10
        fha_203k -= 20

    # --- Equity / era ---
    if equity_pct is not None:
        if equity_pct >= 35:
            wholesale += 25
            fha_203k += 20
        elif equity_pct >= 15:
            wholesale += 10
            fha_203k += 10
        else:
            creative += 25
            wholesale -= 10
            fha_203k -= 15

    if years_owned is not None:
        if years_owned >= 10:
            wholesale += 20
            fha_203k += 25
        elif years_owned >= 5:
            wholesale += 5
            fha_203k += 10
        elif years_owned <= 4 and last_sale_year and last_sale_year >= 2020:
            creative += 30
            fha_203k -= 20

    if year_built:
        if year_built < 1990:
            fha_203k += 20
            wholesale += 10
        elif year_built >= 2000:
            fha_203k -= 5

    if assessed and assessed >= 400_000:
        creative += 10
    if sqft and sqft >= 2000:
        wholesale += 5
        fha_203k += 5

    zillow_desc = (data.get("zillow_description") or "").lower()
    for kw in ("as-is", "tlc", "handyman", "fixer", "needs work", "estate sale"):
        if kw in zillow_desc:
            fha_203k += 15
            wholesale += 10
            break

    # Short sale: foreclosure track + human owner + real address
    if lp_active and BANK_SERVICERS.search(parties) and human and has_street:
        short_sale += 35
    if lp_active and human:
        short_sale += 20
    if equity_pct is not None and equity_pct < 20 and lp_active:
        short_sale += 25
        creative += 15
    if amount_due and amount_due >= 1000 and human:
        short_sale += 10
        wholesale += 10
    if not human:
        short_sale -= 25
        fha_203k -= 30
    if not has_street:
        short_sale -= 15
        fha_203k -= 10

    pre_mls = max(pre_mls, fha_203k, short_sale)
    if human and has_street:
        pre_mls += 10
    if lp_active and amount_due and amount_due >= 500:
        pre_mls += 8  # stacked distress
    if inst == "LP" and human:
        pre_mls += 5

    return {
        "wholesale_score": _clamp(wholesale),
        "creative_score": _clamp(creative),
        "fha_203k_score": _clamp(fha_203k),
        "short_sale_score": _clamp(short_sale),
        "pre_mls_score": _clamp(pre_mls),
        "equity_pct_estimate": round(equity_pct, 1) if equity_pct is not None else None,
        "years_owned_estimate": years_owned,
        "is_human_owner": human,
        "has_street_address": has_street,
    }


def best_strategy(scores: dict[str, int]) -> str:
    """Return primary outreach strategy label."""
    ranked = [
        ("short_sale", scores.get("short_sale_score", 0), 72),
        ("fha_203k", scores.get("fha_203k_score", 0), 75),
        ("creative_finance", scores.get("creative_score", 0), 70),
        ("wholesale_cash", scores.get("wholesale_score", 0), 65),
    ]
    best = max(ranked, key=lambda x: x[1])
    if best[1] >= best[2]:
        return best[0]
    return "monitor"


def _clamp(n: int) -> int:
    return max(0, min(100, n))


def _float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        s = str(v).replace("$", "").replace(",", "").strip()
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def _int(v: Any) -> int | None:
    f = _float(v)
    return int(f) if f is not None else None
