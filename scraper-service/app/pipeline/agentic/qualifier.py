"""Agentic Lead Qualifier.

Uses multi-modal LLM analysis (Vision + Text) to score lead motivation.
"""

from __future__ import annotations
import os
import logging
from typing import Any
from app.models import Lead
from app.external_apis.google_maps import GoogleMapsClient
from app.pipeline.investment_scorer import score_from_lead_data

logger = logging.getLogger(__name__)

class DealQualifierAgent:
    def __init__(self):
        self.gmaps = GoogleMapsClient()
        self.openai_key = os.environ.get("OPENAI_API_KEY")

    async def qualify_lead(self, lead: Lead) -> dict[str, Any]:
        """Deep qualification of a lead using agentic signals."""
        logger.info(f"Qualifying lead: {lead.property_address}")
        
        # 1. Physical Verification (Google Maps)
        geo = await self.gmaps.geocode(lead.property_address)
        has_street_view = await self.gmaps.get_street_view_metadata(lead.property_address)
        
        # 2. Vision Analysis (Future: Send street view URL to GPT-4o)
        visual_distress_score = 0
        if has_street_view:
            img_url = self.gmaps.get_street_view_url(lead.property_address)
            # Placeholder for agentic vision call:
            # visual_distress_score = await self._analyze_image(img_url)
            pass

        # 3. Traditional Scoring
        trad_scores = score_from_lead_data(lead.raw_payload or {})
        
        # 4. Composite Agent Score
        composite_score = trad_scores.get("wholesale_score", 0)
        if has_street_view: composite_score += 5
        
        return {
            "address_verified": bool(geo),
            "visual_distress_score": visual_distress_score,
            "composite_agent_score": composite_score,
            "geo": geo,
            "street_view_url": self.gmaps.get_street_view_url(lead.property_address) if has_street_view else None
        }

    async def _analyze_image(self, url: str) -> int:
        """Analyze a street view image for signs of neglect."""
        # This would call OpenAI/Gemini Vision API
        return 50 # Example score
