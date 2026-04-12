"""Clark County PVA connector (Winchester, KY).

Clark County seat is Winchester. Target signals: probate, divorce, vacancy,
tax delinquency across the Winchester/Clark County residential market.

NOTE: Verify URL at clarkcountypva.com or clark.ky.gov/pva before production run.
"""

from __future__ import annotations

from app.connectors.registry import register
from app.connectors.residential.base_pva import BasePVAConnector


@register
class ClarkPVAConnector(BasePVAConnector):
    source_key = "clark_pva"
    jurisdiction = "KY-Clark"
    # VERIFY_URL: Clark County PVA — confirm at https://clarkcountypva.com
    base_url = "https://clarkcountypva.com"
    county_name = "Clark"
    city_name = "WINCHESTER"
    default_schedule = "0 8 * * *"
