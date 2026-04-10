"""Cross-reference enrichment: match KCOJ names → PVA property addresses."""

from __future__ import annotations

import logging
from typing import Sequence

from app.models import Lead

logger = logging.getLogger(__name__)


def cross_reference_leads(
    court_leads: Sequence[Lead],
    pva_leads: Sequence[Lead],
) -> list[Lead]:
    """Match court-sourced leads (probate/divorce) to PVA property records.

    Strategy:
    1. Build a name→pva_leads index from PVA data
    2. For each court lead, look up the owner name
    3. If matched, enrich the court lead with property details
    4. Recalculate dedupe_hash after enrichment

    Returns the enriched court leads (unmatched ones are returned as-is).
    """
    # Build index: normalized owner name → PVA lead(s)
    pva_index: dict[str, list[Lead]] = {}
    for pva in pva_leads:
        if pva.owner_name:
            key = pva.owner_name.strip().upper()
            pva_index.setdefault(key, []).append(pva)

    enriched: list[Lead] = []
    matched_count = 0

    for court in court_leads:
        if court.owner_name:
            key = court.owner_name.strip().upper()
            matches = pva_index.get(key, [])

            if matches:
                # Take the first match (could be multiple properties)
                pva = matches[0]
                matched_count += 1

                # Enrich court lead with PVA data
                court.property_address = court.property_address or pva.property_address
                court.mailing_address = court.mailing_address or pva.mailing_address
                court.city = court.city or pva.city
                court.state = court.state or pva.state
                court.postal_code = court.postal_code or pva.postal_code
                court.parcel_number = court.parcel_number or pva.parcel_number
                court.building_sqft = court.building_sqft or pva.building_sqft
                court.year_built = court.year_built or pva.year_built
                court.estimated_value = court.estimated_value or pva.estimated_value

                # Merge raw payloads
                court.raw_payload["pva_enrichment"] = pva.raw_payload

                logger.debug(
                    "Enriched %s with PVA data: %s",
                    court.owner_name, pva.property_address,
                )

        enriched.append(court)

    logger.info(
        "Cross-reference: %d court leads, %d PVA records, %d matches",
        len(court_leads), len(pva_leads), matched_count,
    )
    return enriched
