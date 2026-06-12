"""Bourbon County PVA Connector (Paris) — Schneider qPublic."""

from __future__ import annotations

from app.connectors.registry import register
from app.connectors.residential.qpublic_pva import QPublicPVAConnector


@register
class BourbonPVAConnector(QPublicPVAConnector):
    source_key = "bourbon_pva"
    jurisdiction = "KY-Bourbon"
    qpublic_app = "BourbonCountyKY"
    county_name = "Bourbon"
    city_name = "PARIS"
    default_schedule = "0 8 * * *"
