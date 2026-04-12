"""Madison County PVA connector (Richmond, KY).

Madison County seat is Richmond. EKU presence makes this a strong market
for residential leads — probate, divorce, vacancy.

NOTE: Verify URL at madisoncountypva.com or madison.ky.gov/pva before production.
"""

from __future__ import annotations

from app.connectors.registry import register
from app.connectors.residential.base_pva import BasePVAConnector


@register
class MadisonPVAConnector(BasePVAConnector):
    source_key = "madison_pva"
    jurisdiction = "KY-Madison"
    # VERIFY_URL: Madison County PVA — confirm at https://madisoncountypva.com
    base_url = "https://madisoncountypva.com"
    county_name = "Madison"
    city_name = "RICHMOND"
    default_schedule = "0 8 * * *"
