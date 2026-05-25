"""Woodford County PVA (Versailles) — Schneider qPublic."""

from __future__ import annotations

from app.connectors.registry import register
from app.connectors.residential.qpublic_pva import QPublicPVAConnector


@register
class WoodfordPVAConnector(QPublicPVAConnector):
    source_key = "woodford_pva"
    jurisdiction = "KY-Woodford"
    qpublic_app = "WoodfordCountyKY"
    county_name = "Woodford"
    city_name = "VERSAILLES"
    default_schedule = "0 8 * * *"
