"""Human-readable distress reason + next action for operator lists."""

from __future__ import annotations

from typing import Any


def distress_reason(lead: dict[str, Any]) -> str:
    """One-line why this property is on the list."""
    payload = lead.get("raw_payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    lt = (lead.get("lead_type") or "").lower()
    inst = (payload.get("instrument_type") or "").upper()
    amt = lead.get("estimated_value") or payload.get("amount_due")
    tax_year = payload.get("tax_year") or "2025"
    grantee = payload.get("grantee") or ""
    grantor = payload.get("grantor") or payload.get("owner_name") or ""

    if lt == "tax_lien" or payload.get("search_module") == "delinquent_tax":
        if amt:
            return f"Unpaid property tax — {tax_year} bill, ${float(amt):,.2f} due"
        return f"Unpaid property tax — {tax_year} delinquent list"

    if lt == "pre_foreclosure" or inst == "LP":
        bank = grantee if _looks_like_bank(grantee) else grantor
        return f"Lis pendens filed — likely foreclosure; counterparty: {bank[:60]}" if bank else "Lis pendens — pre-foreclosure / lawsuit on title"

    if lt in ("probate", "estate", "death") or inst == "WILL":
        return "Probate / estate filing — heir or executor may sell"

    if lt == "code_violation" or payload.get("signal_channel") == "city_lien":
        return "City code lien / nuisance — vacant or violation enforcement"

    if lt == "foreclosure":
        return "Court foreclosure case — judicial sale track"

    if lt == "divorce":
        return "Domestic relations case — marital property division"

    if payload.get("signal_channel") == "water_shutoff":
        return "Water service disconnected (FOIA or utility list)"

    if payload.get("signal_channel") == "water_outage":
        return "Active water outage area — investigate vacancy"

    return "Distress signal — review source record"


def next_action(lead: dict[str, Any]) -> str:
    payload = lead.get("raw_payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    lt = (lead.get("lead_type") or "").lower()
    addr = (lead.get("property_address") or "").strip()

    if lt == "tax_lien":
        return "PVA lookup by map ID → check LP on eCCLIX → skip trace owner → call"
    if lt == "pre_foreclosure":
        return "Skip trace owner + bank → read LP instrument → mail within 7 days"
    if lt in ("probate", "estate"):
        return "Skip trace heirs → compassionate letter → drive-by if no phone"
    if lt == "code_violation":
        return "Drive-by address" if addr else "GIS / legal desc → resolve address → drive-by"
    return "Skip trace then call"


def _looks_like_bank(name: str) -> bool:
    n = (name or "").upper()
    return any(
        k in n
        for k in ("BANK", "MORTGAGE", "TRUIST", "WELLS", "PENNYMAC", "NEWREZ", "SERVIC")
    )
