"""Condition-adjusted PVA valuation for offer math."""

from __future__ import annotations

from typing import Any


def condition_adjusted_value(
    assessed: float | None,
    *,
    year_built: int | None = None,
    owner_age: int | None = None,
    years_owned: int | None = None,
    last_sale_to_llc: bool = False,
    homestead_exemption: str | None = None,
) -> dict[str, Any]:
    """
    Haircut assessed value for distressed / deferred-maintenance properties.
    Returns adjusted value + assumption trail.
    """
    if not assessed or assessed <= 0:
        return {
            "adjusted_value": None,
            "haircut_pct": 0.0,
            "assumptions": ["no_assessed_value"],
        }

    haircut = 0.0
    assumptions: list[str] = []

    if year_built and year_built < 1960:
        haircut += 0.30
        assumptions.append("pre_1960_deferred_maintenance_30pct")
    elif year_built and year_built < 1980:
        haircut += 0.20
        assumptions.append("pre_1980_deferred_maintenance_20pct")

    if owner_age and owner_age >= 75 and years_owned and years_owned >= 20:
        haircut += 0.10
        assumptions.append("senior_long_tenure_10pct")

    if last_sale_to_llc:
        haircut += 0.12
        assumptions.append("llc_rental_history_12pct")

    homestead = (homestead_exemption or "").strip().upper()
    if homestead in ("", "NO", "N", "0", "NONE", "FALSE"):
        assumptions.append("no_homestead_absentee_or_vacant_signal")

    haircut = min(haircut, 0.55)
    adjusted = round(assessed * (1.0 - haircut), 0)
    return {
        "assessed_value": assessed,
        "adjusted_value": adjusted,
        "haircut_pct": round(haircut * 100, 1),
        "assumptions": assumptions,
    }


def offer_band(
    adjusted_value: float | None,
    *,
    arv: float | None = None,
    strategy: str = "wholesale_cash",
) -> dict[str, float | None]:
    """Rough MAO bands — not a substitute for comp work."""
    base = arv or adjusted_value
    if not base:
        return {"low": None, "high": None}
    if strategy == "wholesale_cash":
        return {"low": round(base * 0.55, 0), "high": round(base * 0.70, 0)}
    if strategy in ("creative_finance", "subto"):
        return {"low": round(base * 0.75, 0), "high": round(base * 0.88, 0)}
    if strategy == "short_sale":
        return {"low": round(base * 0.82, 0), "high": round(base * 0.92, 0)}
    return {"low": round(base * 0.60, 0), "high": round(base * 0.75, 0)}
