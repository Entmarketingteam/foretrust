"""Clark County PVA (Winchester) — Schneider qPublic."""

from __future__ import annotations

from app.connectors.registry import register
from app.connectors.residential.qpublic_pva import QPublicPVAConnector


@register
class ClarkPVAConnector(QPublicPVAConnector):
    source_key = "clark_pva"
    jurisdiction = "KY-Clark"
    qpublic_app = "ClarkCountyKY"
    county_name = "Clark"
    city_name = "WINCHESTER"
    default_schedule = "0 8 * * *"
