"""Bourbon County PVA Connector (qPublic).
"""

from __future__ import annotations
from app.connectors.residential.base_pva import BasePVAConnector
from app.connectors.registry import register

@register
class BourbonPVAConnector(BasePVAConnector):
    source_key = "bourbon_pva"
    jurisdiction = "KY-Bourbon"
    county_name = "Bourbon"
    city_name = "PARIS"
    base_url = "https://qpublic.schneidercorp.com/Application.aspx?AppID=955"
    
    @property
    def search_path(self) -> str:
        return "" # qPublic uses AppID in base_url
