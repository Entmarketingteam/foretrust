"""Scott County PVA (Georgetown) — Schneider qPublic."""

from __future__ import annotations

from app.connectors.registry import register
from app.connectors.residential.qpublic_pva import QPublicPVAConnector


@register
class ScottPVAConnector(QPublicPVAConnector):
    source_key = "scott_pva"
    jurisdiction = "KY-Scott"
    qpublic_app = "ScottCountyKY"
    county_name = "Scott"
    city_name = "GEORGETOWN"
    default_schedule = "0 7 * * *"
