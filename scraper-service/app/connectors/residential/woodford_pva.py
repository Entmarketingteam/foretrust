"""Woodford County PVA connector (Versailles, KY).

Woodford County seat is Versailles. High-value horse farm country with
significant probate and estate activity. Strong target for high-value residential.

NOTE: Verify URL at woodfordpva.com or woodford.ky.gov/pva before production.
"""

from __future__ import annotations

from app.connectors.registry import register
from app.connectors.residential.base_pva import BasePVAConnector


@register
class WoodfordPVAConnector(BasePVAConnector):
    source_key = "woodford_pva"
    jurisdiction = "KY-Woodford"
    # VERIFY_URL: Woodford County PVA — confirm at https://woodfordpva.com
    base_url = "https://woodfordpva.com"
    county_name = "Woodford"
    city_name = "VERSAILLES"
    default_schedule = "0 8 * * *"
