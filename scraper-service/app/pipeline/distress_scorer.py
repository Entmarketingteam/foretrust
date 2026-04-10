"""Multi-signal distress scorer.

Computes a composite hot_score (0-100) for each lead based on the
distress signal type, recency, property value, sqft, and signal stacking.
Higher = more actionable for the operator.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

from app.models import Lead, LeadType


# Base weight per distress signal type
SIGNAL_WEIGHTS: dict[LeadType, int] = {
    LeadType.PROBATE: 25,
    LeadType.ESTATE: 20,
    LeadType.DEATH: 15,
    LeadType.DIVORCE: 25,
    LeadType.FORECLOSURE: 30,
    LeadType.PRE_FORECLOSURE: 25,
    LeadType.TAX_LIEN: 20,
    LeadType.CODE_VIOLATION: 10,
    LeadType.ZONING_CHANGE: 10,
    LeadType.VACANCY: 15,
    LeadType.COMMERCIAL_LISTING: 10,
    LeadType.MF_LISTING: 10,
}


def compute_hot_score(lead: Lead, stacked_signals: int = 0) -> int:
    """Compute composite hot_score for a single lead.

    Factors:
    1. Base signal weight (SIGNAL_WEIGHTS table)
    2. Recency boost: filed < 30 days = +15, < 90 days = +10
    3. Property value multiplier: estimated_value > $500k = +10
    4. Sqft multiplier: > 6000 sqft = +10
    5. Multiple signals on same parcel (stacking): +15 per additional signal
    Cap at 100.
    """
    score = SIGNAL_WEIGHTS.get(lead.lead_type, 10)

    # Recency boost
    if lead.case_filed_date:
        days_ago = (date.today() - lead.case_filed_date).days
        if days_ago <= 30:
            score += 15
        elif days_ago <= 90:
            score += 10

    # Property value
    if lead.estimated_value and lead.estimated_value > 500_000:
        score += 10

    # Sqft
    if lead.building_sqft and lead.building_sqft > 6000:
        score += 10

    # Signal stacking (multiple distress signals on the same parcel)
    if stacked_signals > 0:
        score += 15 * stacked_signals

    return min(score, 100)


def score_leads(leads: Sequence[Lead]) -> list[Lead]:
    """Score all leads, detecting stacked signals on the same parcel.

    Two leads share a parcel if they have the same parcel_number
    or the same property_address (both non-null).
    """
    # Build parcel → count map for stacking
    parcel_counts: dict[str, int] = {}
    for lead in leads:
        key = _parcel_key(lead)
        if key:
            parcel_counts[key] = parcel_counts.get(key, 0) + 1

    scored: list[Lead] = []
    for lead in leads:
        key = _parcel_key(lead)
        stacked = (parcel_counts.get(key, 1) - 1) if key else 0
        lead.hot_score = compute_hot_score(lead, stacked_signals=stacked)
        scored.append(lead)

    return scored


def _parcel_key(lead: Lead) -> str | None:
    """Generate a grouping key for parcel-level stacking detection."""
    if lead.parcel_number:
        return f"parcel:{lead.parcel_number}"
    if lead.property_address:
        return f"addr:{lead.property_address}"
    return None
