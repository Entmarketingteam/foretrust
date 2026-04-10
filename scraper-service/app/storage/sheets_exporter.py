"""Google Sheets exporter — appends leads to a shared spreadsheet.

This is the mobile-friendly delivery channel for non-technical operators.
They open the sheet on their phone, sort by hot_score, and call the owner.
Uses gspread + service-account JSON from Doppler.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.config import settings
from app.models import Lead

logger = logging.getLogger(__name__)

_cached_spreadsheet = None


def _get_client():
    """Authenticate with Google Sheets using service account JSON from Doppler.
    Caches the spreadsheet handle at module level to avoid re-auth on every export.
    """
    global _cached_spreadsheet
    if _cached_spreadsheet is not None:
        return None, _cached_spreadsheet

    sa_json = settings.google_service_account_json
    spreadsheet_id = settings.google_sheets_spreadsheet_id

    if not sa_json or not spreadsheet_id:
        logger.debug("Google Sheets not configured; skipping export")
        return None, None

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_dict = json.loads(sa_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(spreadsheet_id)
        _cached_spreadsheet = spreadsheet
        return gc, spreadsheet
    except ImportError:
        logger.warning("gspread not installed; Sheets export disabled")
        return None, None
    except Exception as exc:
        logger.warning("Google Sheets auth failed: %s", exc)
        return None, None


def export_leads_sheets(leads: list[Lead], source_key: str) -> int:
    """Append leads to the Google Sheet under a tab named after source_key.

    Creates the tab if it doesn't exist. Returns number of rows appended.
    """
    if not leads:
        return 0

    _, spreadsheet = _get_client()
    if not spreadsheet:
        return 0

    # Get or create worksheet tab
    tab_name = source_key[:30]  # Sheets tab names max 100 chars
    try:
        worksheet = spreadsheet.worksheet(tab_name)
    except Exception:
        worksheet = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=20)
        # Add header row
        headers = [
            "Hot Score", "Lead Type", "Owner Name", "Property Address",
            "Mailing Address", "City", "State", "ZIP", "Parcel #",
            "Sq Ft", "Year Built", "Est. Value", "Case ID",
            "Filed Date", "Jurisdiction", "Scraped At",
        ]
        worksheet.append_row(headers)

    # Build rows
    rows: list[list[Any]] = []
    for lead in leads:
        rows.append([
            lead.hot_score or 0,
            lead.lead_type.value,
            lead.owner_name or "",
            lead.property_address or "",
            lead.mailing_address or "",
            lead.city or "",
            lead.state or "",
            lead.postal_code or "",
            lead.parcel_number or "",
            lead.building_sqft or "",
            lead.year_built or "",
            lead.estimated_value or "",
            lead.case_id or "",
            str(lead.case_filed_date) if lead.case_filed_date else "",
            lead.jurisdiction or "",
            lead.scraped_at.strftime("%Y-%m-%d %H:%M"),
        ])

    # Sort by hot_score descending before appending
    rows.sort(key=lambda r: r[0], reverse=True)

    try:
        worksheet.append_rows(rows, value_input_option="RAW")
        logger.info("Google Sheets: appended %d rows to tab '%s'", len(rows), tab_name)
        return len(rows)
    except Exception as exc:
        logger.warning("Google Sheets append failed: %s", exc)
        return 0
