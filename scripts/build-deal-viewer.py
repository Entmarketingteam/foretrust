#!/usr/bin/env python3
"""Render newest best-deals JSON reports into a single clickable HTML viewer."""

from __future__ import annotations

import glob
import html
import json
import os
import webbrowser
from pathlib import Path

EXPORT = Path(__file__).resolve().parents[1] / "scraper-service" / "exports" / "best-deals"
OUT = Path(__file__).resolve().parents[1] / "scraper-service" / "exports" / "deal-viewer.html"

BUCKET_TITLES = {
    "tax_delinquent_human": "Human owners — delinquent tax",
    "pre_mls_homebuyer": "Pre-MLS owner-occupant (FHA 203k / conventional)",
    "short_sale": "Short sale candidates",
    "fha_203k": "FHA 203k renovation",
    "creative_finance": "Subject-to / creative finance",
    "probate_creative": "Probate / heir creative",
    "stacked_signals": "Stacked distress",
    "wholesale": "Wholesale / entity-owned",
}


def newest(pattern: str) -> Path | None:
    files = glob.glob(str(EXPORT / pattern))
    return Path(max(files, key=os.path.getmtime)) if files else None


def rows(leads: list[dict]) -> str:
    out = []
    for x in leads:
        sc = x.get("investment_scores") or {}
        owner = html.escape(str(x.get("owner_name") or ""))
        addr = html.escape(str(x.get("property_address") or "—"))
        due = x.get("amount_due") or x.get("estimated_value") or 0
        mapid = html.escape(str(x.get("parcel_number") or ""))
        url = x.get("detail_url") or ""
        link = f'<a href="{html.escape(url)}" target="_blank">eCCLIX bill →</a>' if url else "—"
        yr = x.get("year_built") or ""
        out.append(
            f"<tr><td class='s'>{sc.get('pre_mls_score', 0)}</td><td>{owner}</td>"
            f"<td>{addr}</td><td class='n'>${due:,.0f}</td><td>{mapid}</td>"
            f"<td>{yr}</td><td>{link}</td></tr>"
        )
    return "\n".join(out)


def section(name: str, data: dict) -> str:
    parts = []
    for key, title in BUCKET_TITLES.items():
        leads = data.get(key) or []
        if not leads:
            continue
        parts.append(
            f"<h3>{title} <span class='c'>({len(leads)})</span></h3>"
            "<table><thead><tr><th>Score</th><th>Owner</th><th>Address</th>"
            "<th>Tax due</th><th>Map ID</th><th>Built</th><th>Link</th></tr></thead>"
            f"<tbody>{rows(leads)}</tbody></table>"
        )
    return f"<section><h2>{name}</h2>{''.join(parts) or '<p>No leads.</p>'}</section>"


def main() -> None:
    blocks = []
    for label, pat in (("Scott County (Georgetown)", "best-deals-scott-*.json"),
                       ("Woodford County (Versailles)", "best-deals-woodford-*.json")):
        f = newest(pat)
        if f:
            blocks.append(section(label, json.loads(f.read_text())))

    page = (
        "<!doctype html><meta charset='utf-8'><title>Foretrust — Off-Market Deals</title>"
        "<style>"
        "body{font:14px/1.5 -apple-system,Segoe UI,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}"
        "header{padding:20px 28px;background:#161922;border-bottom:1px solid #262b36}"
        "h1{margin:0;font-size:20px}.sub{color:#8a93a6;font-size:13px;margin-top:4px}"
        "section{padding:8px 28px 28px}h2{font-size:17px;border-bottom:2px solid #3b4252;padding-bottom:6px}"
        "h3{font-size:14px;color:#cdd3df;margin:22px 0 8px}.c{color:#7a8294;font-weight:400}"
        "table{border-collapse:collapse;width:100%;margin-bottom:6px;font-size:13px}"
        "th,td{text-align:left;padding:6px 10px;border-bottom:1px solid #20242e}"
        "th{color:#8a93a6;font-weight:600;font-size:12px;text-transform:uppercase}"
        "td.s{font-weight:700;color:#5dd28a}td.n{text-align:right;color:#f0c674}"
        "a{color:#6cb6ff;text-decoration:none}a:hover{text-decoration:underline}"
        "tr:hover{background:#161922}"
        "</style>"
        "<header><h1>Foretrust — Off-Market Acquisition Targets</h1>"
        "<div class='sub'>Scott + Woodford KY · ranked distressed / pre-MLS · each row links to its eCCLIX bill</div></header>"
        + "".join(blocks)
    )
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT}")
    webbrowser.open(f"file://{OUT}")


if __name__ == "__main__":
    main()
