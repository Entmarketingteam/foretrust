"""Google Maps API Client.

Handles address verification, geocoding, and street view analysis.
"""

from __future__ import annotations
import os
import aiohttp
import logging
from typing import Any

logger = logging.getLogger(__name__)

class GoogleMapsClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("GOOGLE_MAPS_API_KEY")
        self.base_url = "https://maps.googleapis.com/maps/api"

    async def geocode(self, address: str) -> dict[str, Any] | None:
        """Verify address and get coordinates."""
        if not self.api_key:
            logger.warning("No Google Maps API Key found.")
            return None

        url = f"{self.base_url}/geocode/json"
        params = {
            "address": address,
            "key": self.api_key
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                if data["status"] == "OK":
                    result = data["results"][0]
                    return {
                        "lat": result["geometry"]["location"]["lat"],
                        "lng": result["geometry"]["location"]["lng"],
                        "formatted_address": result["formatted_address"],
                        "place_id": result["place_id"]
                    }
                return None

    async def get_street_view_metadata(self, address: str) -> bool:
        """Check if street view is available."""
        if not self.api_key: return False
        url = f"{self.base_url}/streetview/metadata"
        params = {"location": address, "key": self.api_key}
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
                return data["status"] == "OK"

    def get_street_view_url(self, address: str) -> str:
        """Generate a static street view image URL for AI analysis."""
        return f"{self.base_url}/streetview?size=600x300&location={address}&key={self.api_key}"
