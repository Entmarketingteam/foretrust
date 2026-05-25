"""Madison County PVA (Richmond) — Schneider qPublic."""

from __future__ import annotations

from app.connectors.registry import register
from app.connectors.residential.qpublic_pva import QPublicPVAConnector


@register
class MadisonPVAConnector(QPublicPVAConnector):
    source_key = "madison_pva"
    jurisdiction = "KY-Madison"
    qpublic_app = "MadisonCountyKY"
    county_name = "Madison"
    city_name = "RICHMOND"
    default_schedule = "0 8 * * *"
