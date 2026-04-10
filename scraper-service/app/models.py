"""Pydantic models for the scraper service."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class Vertical(str, Enum):
    COMMERCIAL = "commercial"
    RESIDENTIAL = "residential"
    MULTIFAMILY = "multifamily"


class LeadType(str, Enum):
    PROBATE = "probate"
    ESTATE = "estate"
    DEATH = "death"
    DIVORCE = "divorce"
    FORECLOSURE = "foreclosure"
    PRE_FORECLOSURE = "pre_foreclosure"
    TAX_LIEN = "tax_lien"
    CODE_VIOLATION = "code_violation"
    ZONING_CHANGE = "zoning_change"
    VACANCY = "vacancy"
    COMMERCIAL_LISTING = "commercial_listing"
    MF_LISTING = "mf_listing"


class RawRecord(BaseModel):
    """Raw scraped record before normalization."""
    source_key: str
    data: dict[str, Any]
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


class Lead(BaseModel):
    """Normalized lead ready for storage."""
    source_key: str
    vertical: Vertical
    jurisdiction: str | None = None
    lead_type: LeadType
    owner_name: str | None = None
    mailing_address: str | None = None
    property_address: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    parcel_number: str | None = None
    building_sqft: int | None = None
    unit_count: int | None = None
    year_built: int | None = None
    case_id: str | None = None
    case_filed_date: date | None = None
    estimated_value: float | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    hot_score: int | None = None
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    @computed_field
    @property
    def dedupe_hash(self) -> str:
        """SHA-256 hash for deduplication: source + parcel + case_id."""
        key = f"{self.source_key}|{self.parcel_number or ''}|{self.case_id or ''}|{self.property_address or ''}"
        return hashlib.sha256(key.encode()).hexdigest()


class SourceRunStatus(str, Enum):
    RUNNING = "running"
    OK = "ok"
    BLOCKED = "blocked"
    ERROR = "error"
    PENDING_BATCH = "pending_batch"


class SourceRun(BaseModel):
    """Audit log entry for a scraper run."""
    source_key: str
    status: SourceRunStatus = SourceRunStatus.RUNNING
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None
    records_found: int = 0
    records_new: int = 0
    error_message: str | None = None
    proxy_session_id: str | None = None
