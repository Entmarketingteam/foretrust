"""Schneider qPublic (Beacon) PVA base for Kentucky counties.

Most KY PVAs outside Lexington use:
  https://qpublic.schneidercorp.com/Application.aspx?App={AppName}&PageType=Search

Subclasses set `qpublic_app` (e.g. ScottCountyKY) and optional `county_name` / `city_name`.
"""

from __future__ import annotations

from app.connectors.residential.base_pva import BasePVAConnector

QPUBLIC_HOST = "https://qpublic.schneidercorp.com"


class QPublicPVAConnector(BasePVAConnector):
    """PVA connector for counties hosted on Schneider qPublic."""

    qpublic_app: str = ""

    @property
    def base_url(self) -> str:
        return QPUBLIC_HOST

    @property
    def search_path(self) -> str:
        app = self.qpublic_app or f"{self.county_name}CountyKY"
        return f"/Application.aspx?App={app}&PageType=Search"
