"""List stacking — overlay tax delinquency × instrument scenarios."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

EXPORTS = Path(__file__).resolve().parents[2] / "exports"


@dataclass
class StackedLead:
    owner_key: str
    owner_name: str
    property_address: str | None
    lists: set[str] = field(default_factory=set)
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def list_count(self) -> int:
        return len(self.lists)

    @property
    def hot_tier(self) -> str:
        n = self.list_count
        if n >= 3:
            return "HOT"
        if n == 2:
            return "WARM"
        return "COLD"


_JUNK_OWNER = re.compile(
    r"navigation|new search|party1|logout|welcome|ins#/date|^type$|^description$|"
    r"^back$|subscriptions|setup|delinquent tax|securities",
    re.I,
)


def _is_valid_owner_name(name: str) -> bool:
    s = (name or "").strip()
    if len(s) < 4 or len(s) > 80:
        return False
    if "\n" in s or "\t" in s or "|" in s:
        return False
    if _JUNK_OWNER.search(s):
        return False
    if re.fullmatch(r"[\d\s./-]+", s):
        return False
    if re.search(r"^MC\d", s, re.I):
        return False
    if re.search(r"^ML\d", s, re.I):
        return False
    return bool(re.search(r"[A-Za-z]{2,}", s))


def _is_valid_instrument_row(row: dict[str, Any]) -> bool:
    from app.pipeline.property_address import is_valid_street_address

    owner = row.get("owner_name") or row.get("grantor") or row.get("grantee") or ""
    if not _is_valid_owner_name(owner):
        return False
    inst = str(row.get("instrument_type") or "")
    if len(inst) > 40 or "navigation" in inst.lower():
        return False
    book = str(row.get("book") or "")
    if len(book) > 40 or "navigation" in book.lower():
        return False
    addr = row.get("property_address")
    if addr and not is_valid_street_address(str(addr)):
        if is_likely_legal_description(str(addr)):
            pass  # still OK if owner is valid
        elif "\t" in str(addr):
            return False
    score = row.get("pre_mls_score") or 0
    scenarios = row.get("creative_scenarios") or []
    inst_type = (row.get("instrument_type") or "").upper()
    if score < 40 and not scenarios and inst_type not in ("LP", "MLIEN", "POA", "BBREL"):
        return False
    return True


def is_likely_legal_description(text: str) -> bool:
    from app.pipeline.property_address import is_likely_legal_description as _is

    return _is(text)


def normalize_owner_name(name: str) -> str:
    """Join key: LAST_FIRST (first token of first name)."""
    s = (name or "").upper().strip()
    s = re.sub(r"\s+ET\s+AL\b.*", "", s)
    s = re.sub(r"\s+&\s+.*", "", s)
    s = re.sub(r"[^A-Z0-9,\s]", "", s)
    if "," in s:
        parts = [p.strip() for p in s.split(",", 1)]
        last = parts[0]
        first = parts[1].split()[0] if len(parts) > 1 and parts[1] else ""
        return f"{last}_{first}".strip("_")
    tokens = s.split()
    if len(tokens) >= 2:
        return f"{tokens[-1]}_{tokens[0]}"
    return s.replace(" ", "_")[:40]


def _load_tax_leads(county: str) -> list[dict[str, Any]]:
    actionable = EXPORTS / "actionable-leads"
    paths = sorted(actionable.glob(f"properties-{county.lower()}-*.md"), reverse=True)
    if not paths:
        return []
    text = paths[0].read_text(encoding="utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("| Owner") or line.startswith("|-"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 6:
            continue
        owner, addr = parts[1], parts[2]
        if not owner or owner == "Owner":
            continue
        rows.append({
            "owner_name": owner,
            "property_address": addr,
            "county": county.lower(),
            "source": "tax_actionable",
        })
    return rows


_TAX_PORTAL_PROFILES = frozenset({"delinquent_tax", "tax_human_big"})


def _is_stackable_instrument_row(
    row: dict[str, Any], tax_owner_keys: set[str]
) -> bool:
    """Instrument row counts toward stacking (LP/scenarios or tax-portal PVA match)."""
    if _is_valid_instrument_row(row):
        return True
    owner = row.get("owner_name") or row.get("grantor") or row.get("grantee") or ""
    key = normalize_owner_name(owner)
    if not key or key not in tax_owner_keys:
        return False
    profile = (row.get("search_profile") or "").lower()
    return profile in _TAX_PORTAL_PROFILES or "tax" in profile


def _load_instrument_leads(county: str) -> list[dict[str, Any]]:
    portal = EXPORTS / "portal-intel"
    paths = sorted(portal.glob(f"{county.lower()}-filtered-*.json"), reverse=True)
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        leads = list(data.get("leads") or [])
        if leads or (data.get("count") or 0) > 0:
            return leads
    return []


def stack_lists(county: str) -> list[StackedLead]:
    """Overlay tax + instrument scenario tags for one county."""
    overlay: dict[str, StackedLead] = {}
    tax_owner_keys: set[str] = set()

    def _get(key: str, owner: str, addr: str | None) -> StackedLead:
        if key not in overlay:
            overlay[key] = StackedLead(
                owner_key=key,
                owner_name=owner,
                property_address=addr,
            )
        return overlay[key]

    for row in _load_tax_leads(county):
        # Actionable MD is already filtered to situs rows; do not re-apply
        # is_valid_street_address (Woodford/Franklin use "STREET 123" map labels).
        owner = row.get("owner_name") or ""
        key = normalize_owner_name(owner)
        if not key:
            continue
        tax_owner_keys.add(key)
        sl = _get(key, owner, row.get("property_address"))
        sl.lists.add("tax")
        sl.data.setdefault("tax", row)

    for row in _load_instrument_leads(county):
        if not _is_stackable_instrument_row(row, tax_owner_keys):
            continue
        owner = row.get("owner_name") or row.get("grantor") or row.get("grantee") or ""
        key = normalize_owner_name(owner)
        if not key or re.match(r"^ML\d", key):
            continue
        addr = row.get("property_address")
        sl = _get(key, owner, addr)
        profile = (row.get("search_profile") or "").lower()
        if _is_valid_instrument_row(row):
            inst = (row.get("instrument_type") or "").upper()
            if inst == "LP" or "lp" in profile:
                sl.lists.add("lp")
            scenarios = row.get("creative_scenarios") or []
            if scenarios:
                sl.lists.add("instrument")
                sl.data.setdefault("scenarios", set()).update(scenarios)
            elif inst and len(inst) <= 12:
                sl.lists.add(f"instrument_{inst.lower()}")
        elif profile in _TAX_PORTAL_PROFILES or (
            key in tax_owner_keys and "tax" in profile
        ):
            sl.lists.add("portal_tax")
        sl.data.setdefault("instruments", []).append(row)

    ranked = sorted(
        overlay.values(),
        key=lambda x: (-x.list_count, -(x.data.get("tax", {}).get("amount_due") or 0)),
    )
    return ranked


def export_stacked_markdown(county: str, limit: int = 100) -> Path:
    stacked = stack_lists(county)
    out_dir = EXPORTS / "stacked-leads"
    out_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = out_dir / f"stacked-{county.lower()}-{stamp}.md"
    hot = [s for s in stacked if s.list_count >= 2][:limit]

    lines = [
        f"# Stacked leads — {county.title()} County",
        f"**{len(hot)}** multi-list hits (of {len(stacked)} owners scanned)",
        "",
        "| Tier | Lists | Owner | Address | Signals |",
        "|------|-------|-------|---------|---------|",
    ]
    for s in hot:
        lists = ", ".join(sorted(s.lists))
        scenarios = ", ".join(sorted(s.data.get("scenarios") or []))[:50]
        addr = (s.property_address or "")[:40]
        signals = lists + (f" ({scenarios})" if scenarios else "")
        lines.append(
            f"| {s.hot_tier} | {s.list_count} | {s.owner_name[:35]} | {addr} | {signals} |"
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
