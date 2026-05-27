# eCCLIX day-pass post-mortem (2026-05-26)

Scrapes are **over**. Use this doc + `scraper-service/exports/ecclix-postmortem.md` before the next pass.

## What happened (root causes)

| Issue | Symptom | Cause |
|-------|---------|--------|
| **Login junk CSVs** | `ecclix-sprint/*.csv` full of "eCCLIX Login Subscribe" | Scrape ran before session/county was valid |
| **Blob rows** | One `ft_leads` row = whole results page | Old grid capture flattened many instruments into `raw_payload.cells` |
| **Field shift** | Grantor/date in wrong columns | Parser assumed 1 row = 1 record; eCCLIX uses 2-line grid |
| **0-record runs** | `records_found: 0` on Railway | Day pass expired; purchase-only county page |
| **Legal as address** | `property_address` = "LOT 5 BLOCK 2…" | Instrument rows stored legal text, not situs |
| **Orphan PDFs** | Clerk table, no UI link | `lead_id` never set; `storage_path` = `pending/...` (no download) |
| **Dangerous backfill** | `backfill_ecclix.py --apply` would delete ~1,019 rows | Script treated recovered instruments as "junk fragments" |

## Current DB state (after backfill)

| Metric | Value |
|--------|------:|
| `ecclix_batch` leads | 2,141 |
| Tax delinquent (cells) | 1,122 |
| Recovered instruments | 1,019 |
| Valid street situs (`ecclix_batch`) | ~496 (23%) |
| `ft_clerk_documents` | 516 |
| Clerk → lead linked | **516 / 516** |
| Actionable tax exports (4 counties) | **435** (use for dialing) |

**Callable tax list** = `exports/actionable-leads/properties-*-20260526-*.md`, not the raw 2,141 dashboard rows.

## Backfill commands (safe order)

```bash
cd ~/Desktop/foretrust/scraper-service

# 1) Audit (writes exports/ecclix-postmortem.md)
doppler run --project foretrust-scraper --config dev -- \
  python3 scripts/ecclix_postmortem.py --write-md

# 2) Normalize addresses from legal / tax cells
doppler run --project foretrust-scraper --config dev -- \
  python3 scripts/backfill_ecclix_addresses.py --apply

# 3) Marry clerk metadata to leads (PDF button in UI)
doppler run --project foretrust-scraper --config dev -- \
  python3 scripts/backfill_clerk_lead_ids.py --apply

# 4) Cell recovery ONLY if new blobs appear (dry-run first!)
doppler run --project foretrust-scraper --config dev -- \
  python3 backfill_ecclix.py
# Safe now: leaves recovered + tax; does not wipe clerk unless new inserts exist
```

## Next pull checklist

1. **Renew day pass** in browser; confirm "Search {County} Records" links (not purchase-only).
2. **Doppler:** `ECCLIX_COUNTIES=scott,bourbon,woodford,franklin` (not clark/madison only).
3. **Run on Alienware** with `ECCLIX_EXPORT_DIR` set; `download_documents=true` for real PDFs.
4. **One browser session** — never parallel eCCLIX logins.
5. **Import tax via** `ecclix_csv_import` / actionable export — not login-junk sprint CSVs.
6. **After run:** postmortem → address backfill → clerk link → `build-best-deals.py` → PVA enrich when Cloudflare allows.

## Code fixes shipped in repo

- `backfill_ecclix.py` — guard `leave_recovered`; skip clerk wipe if no new rows; situs from legal
- `scripts/ecclix_postmortem.py` — CSV + DB audit
- `scripts/backfill_ecclix_addresses.py` — tax `sanitize_tax_row` + legal extract
- `scripts/backfill_clerk_lead_ids.py` — county + book/page join
