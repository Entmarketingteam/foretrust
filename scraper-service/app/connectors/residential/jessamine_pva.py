"""Jessamine County PVA (Nicholasville) — Schneider qPublic."""

from __future__ import annotations

from app.connectors.registry import register
from app.connectors.residential.qpublic_pva import QPublicPVAConnector


@register
class JessaminePVAConnector(QPublicPVAConnector):
    source_key = "jessamine_pva"
    jurisdiction = "KY-Jessamine"
    qpublic_app = "JessamineCountyKY"
    county_name = "Jessamine"
    city_name = "NICHOLASVILLE"
    default_schedule = "0 8 * * *"
