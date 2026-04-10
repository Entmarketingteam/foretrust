"""CSV exporter — writes leads to exports/<source_key>_<YYYY-MM-DD>.csv.

Runs after every scraper run as a local backup even if Supabase is down.
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path

import pandas as pd

from app.models import Lead

logger = logging.getLogger(__name__)

EXPORTS_DIR = Path(__file__).resolve().parent.parent.parent / "exports"


def export_leads_csv(leads: list[Lead], source_key: str) -> str | None:
    """Write leads to a CSV file. Returns the file path, or None on failure."""
    if not leads:
        return None

    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{source_key}_{date.today().isoformat()}.csv"
    filepath = EXPORTS_DIR / filename

    rows = []
    for lead in leads:
        rows.append({
            "hot_score": lead.hot_score or 0,
            "lead_type": lead.lead_type.value,
            "vertical": lead.vertical.value,
            "owner_name": lead.owner_name or "",
            "property_address": lead.property_address or "",
            "mailing_address": lead.mailing_address or "",
            "city": lead.city or "",
            "state": lead.state or "",
            "postal_code": lead.postal_code or "",
            "parcel_number": lead.parcel_number or "",
            "building_sqft": lead.building_sqft or "",
            "year_built": lead.year_built or "",
            "estimated_value": lead.estimated_value or "",
            "case_id": lead.case_id or "",
            "case_filed_date": str(lead.case_filed_date) if lead.case_filed_date else "",
            "jurisdiction": lead.jurisdiction or "",
            "source_key": lead.source_key,
            "scraped_at": lead.scraped_at.isoformat(),
        })

    df = pd.DataFrame(rows)
    df.sort_values("hot_score", ascending=False, inplace=True)
    df.to_csv(filepath, index=False)

    logger.info("CSV exported: %s (%d leads)", filepath, len(leads))
    return str(filepath)
