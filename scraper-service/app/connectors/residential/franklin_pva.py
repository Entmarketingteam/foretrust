"""Franklin County PVA Connector (qPublic).
"""

from __future__ import annotations
from app.connectors.residential.base_pva import BasePVAConnector
from app.connectors.registry import register

@register
class FranklinPVAConnector(BasePVAConnector):
    source_key = "franklin_pva"
    jurisdiction = "KY-Franklin"
    county_name = "Franklin"
    city_name = "FRANKFORT"
    base_url = "https://qpublic.schneidercorp.com/Application.aspx?AppID=1025"
    
    @property
    def search_path(self) -> str:
        return ""
