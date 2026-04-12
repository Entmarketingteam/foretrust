"""Jessamine County PVA connector (Nicholasville, KY).

Jessamine County seat is Nicholasville. Fast-growing suburban county
south of Lexington — high residential turnover, strong probate/divorce signals.

NOTE: Verify URL at jessaminepva.com or jessamine.ky.gov/pva before production.
"""

from __future__ import annotations

from app.connectors.registry import register
from app.connectors.residential.base_pva import BasePVAConnector


@register
class JessaminePVAConnector(BasePVAConnector):
    source_key = "jessamine_pva"
    jurisdiction = "KY-Jessamine"
    # VERIFY_URL: Jessamine County PVA — confirm at https://jessaminepva.com
    base_url = "https://jessaminepva.com"
    county_name = "Jessamine"
    city_name = "NICHOLASVILLE"
    default_schedule = "0 8 * * *"
