"""Persist downloaded clerk PDFs and metadata."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EXPORT_ROOT = Path(__file__).resolve().parents[2] / "exports" / "ecclix"


def _export_root() -> Path:
    import os
    root = os.environ.get("ECCLIX_EXPORT_DIR", "")
    return Path(root) if root else DEFAULT_EXPORT_ROOT


def save_document_bytes(
    county: str,
    book: str,
    page: str,
    instrument_type: str,
    content: bytes,
    ext: str = "pdf",
) -> tuple[str, str, str]:
    """Write file to exports/ecclix/{county}/. Returns (storage_path, file_name, sha256)."""
    county_dir = _export_root() / county.lower().replace(" ", "_")
    county_dir.mkdir(parents=True, exist_ok=True)

    safe_type = re.sub(r"[^\w]+", "_", instrument_type or "DOC")[:40]
    safe_book = re.sub(r"[^\w]+", "_", book or "0")
    safe_page = re.sub(r"[^\w]+", "_", page or "0")
    file_name = f"{safe_type}_{safe_book}_{safe_page}.{ext.lstrip('.')}"
    path = county_dir / file_name

    if path.exists() and path.read_bytes() == content:
        digest = hashlib.sha256(content).hexdigest()
        return str(path), file_name, digest

    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    logger.info("[ecclix] Saved %s (%d bytes)", path, len(content))
    return str(path), file_name, digest


async def insert_clerk_document(row: dict[str, Any]) -> bool:
    """Upsert one clerk document row into Supabase."""
    from app.storage.supabase_client import DEFAULT_ORG_ID, _get_client

    client = _get_client()
    if not client:
        return False
    if not row.get("organization_id"):
        row = {**row, "organization_id": DEFAULT_ORG_ID}
    try:
        client.table("ft_clerk_documents").upsert(
            row,
            on_conflict="county,book,page,instrument_type,source_key",
        ).execute()
        return True
    except Exception as exc:
        logger.warning("[ecclix] clerk document upsert failed: %s", exc)
        return False


def parse_consideration(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"\$[\d,]+(?:\.\d{2})?", text)
    if not m:
        return None
    try:
        return float(m.group(0).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def extract_address_from_legal(legal: str) -> str | None:
    from app.pipeline.property_address import extract_address_from_legal as _extract

    return _extract(legal)


def parse_recorded_date(text: str) -> date | None:
    if not text:
        return None
    from app.pipeline.normalize import parse_date
    return parse_date(text)
