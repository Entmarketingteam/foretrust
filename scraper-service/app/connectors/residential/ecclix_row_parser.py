"""Explode raw eCCLIX instrument-search captures into individual records.

The eCCLIX instrument grid renders each record across TWO physical lines of
5 logical columns:

    INS#/DATE | PARTY1/PARTY2 | TYPE | BK/PG    | DESCRIPTION
    (blank)   | <grantor>     | TYPE | <bk pg>  | <legal/desc>
    <date>    | <grantee>     |      | N PAGES  |

A single Playwright capture can hold anywhere from 5 cells (one half-record
line the scraper split off) to several hundred (an entire results page
flattened into one element). Earlier parsing assumed one record per captured
row and a fixed column order, which shifted every field and left whole pages
of records trapped unsplit. This module recovers them.

Strategy: scan for record anchors rather than trusting row boundaries. A
record's line 1 is recognisable because cell[+2] is a known instrument code
and cell[+3] looks like a book/page reference. From an anchor we read line 1,
then consume the following line 2 only if it actually looks like a
continuation (a date or an "N PAGES" count) — otherwise the record was a
single captured line and date/grantee stay blank.
"""
import re
from typing import Any

INSTRUMENT_CODES = {
    "DEED", "MTG", "MTGA", "MTGAM", "MTGWA", "MTGC", "WILL", "LP", "REL",
    "MREL", "PREL", "BBREL", "ENC", "AFF", "AGREE", "ASGN", "CDEED", "DOC",
    "LEASE", "MISC", "MISCM", "PLAT", "POA", "RENT", "NB", "FF", "SLR", "LIS",
    "JLIEN", "MLIEN",
}

# Book/page like "D358 584", "M1028 505", "DH 349", "NB19 42", "FF6 512".
_BKPG_RE = re.compile(r"^[A-Z]{0,6}\d+\s+\d+[A-Z]?$", re.I)
_PAGES_RE = re.compile(r"^\d+\s+PAGES?$", re.I)
_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def _clean(s: Any) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip())


def _split_book_page(bkpg: str) -> tuple[str, str]:
    parts = _clean(bkpg).split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    return (parts[0] if parts else ""), ""


def _is_record_start(cells: list[str], i: int) -> bool:
    """True if a record's line 1 begins at index i."""
    if i + 3 >= len(cells):
        return False
    code = _clean(cells[i + 2]).upper()
    return code in INSTRUMENT_CODES and bool(_BKPG_RE.match(_clean(cells[i + 3])))


def explode_instrument_cells(cells: list[str]) -> list[dict[str, Any]]:
    """Return one dict per instrument record found in a raw cells array."""
    if not cells or len(cells) > 10_000:
        return []

    records: list[dict[str, Any]] = []
    i = 0
    n = len(cells)
    while i < n:
        if not _is_record_start(cells, i):
            i += 1
            continue

        book, page = _split_book_page(cells[i + 3])
        rec: dict[str, Any] = {
            "grantor": _clean(cells[i + 1]),
            "instrument_type": _clean(cells[i + 2]).upper(),
            "book": book,
            "page": page,
            "legal_description": _clean(cells[i + 4]) if i + 4 < n else "",
            "recorded_date": "",
            "grantee": "",
            "page_count": "",
        }

        # Consume line 2 only if it looks like a continuation, not the next
        # record's line 1.
        l2_date = _clean(cells[i + 5]) if i + 5 < n else ""
        l2_pages = _clean(cells[i + 8]) if i + 8 < n else ""
        has_line2 = (
            not _is_record_start(cells, i + 5)
            and (_DATE_RE.match(l2_date) or _PAGES_RE.match(l2_pages))
        )
        if has_line2:
            rec["recorded_date"] = l2_date if _DATE_RE.match(l2_date) else ""
            rec["grantee"] = _clean(cells[i + 6]) if i + 6 < n else ""
            rec["page_count"] = l2_pages if _PAGES_RE.match(l2_pages) else ""
            i += 10
        else:
            i += 5

        records.append(rec)

    return records
