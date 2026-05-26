# Pre-MLS Best Deals — Operator Runbook

## What you have now (218 Scott delinquent tax bills in Supabase)

| Output | Path |
|--------|------|
| Ranked report (MD + JSON) | `scraper-service/exports/best-deals/best-deals-*.md` |
| Tier-A tax CSV (115) | `scraper-service/exports/ecclix-imports/scott-delinquent-2025-tier-a.csv` |

## Three tracks (from your pasted workflow)

1. **Short sale** — LP on file + bank servicer (Truist, PennyMac, etc.) + human owner + low equity. **Requires LP scrape** (not in tax CSV alone).
2. **FHA 203k / conventional primary** — Human owner, street address, tax stress $2k+, then PVA for year built &lt; 1990 and equity room.
3. **Wholesale / creative** — LLC/entity or Raney-style (2020–2022 purchase + LP + low equity).

## Commands (Doppler: `foretrust-scraper` / `dev`)

```bash
# Rebuild ranked report from Supabase (no browser)
cd ~/Desktop/foretrust
doppler run --project foretrust-scraper --config dev -- \
  python3 scripts/build-best-deals.py --default-csv

# PVA enrich top human owners (needs: playwright install)
doppler run --project foretrust-scraper --config dev -- \
  python3 scripts/build-best-deals.py --enrich-pva --pva-limit 35

# LP + PDFs + party search on top tax owners (day pass required)
bash scripts/run-pre-mls-doc-sprint.sh
# or API:
# POST /pipeline/ecclix  {"mode":"pre_mls_sprint","counties":["scott"],"download_documents":true}
```

## Manual steps while day pass is active

1. **Instruments → Index Search** — LP, `01/01/2026`–today, drill each row → export or let `pre_mls_sprint` pull PDFs.
2. **Cross each human tax lead** — Combination Party Search owner name → confirm LP/MTG not already on MLS.
3. **PVA** — Scott qPublic by Map ID or owner → physical address (e.g. Cherry Blossom LOT → 123 Olympia Way).
4. **Stack** — Tax delinquent + LP + estate deed = highest pre-MLS priority.

## Scoring fields (`investment_scores` in `raw_payload`)

| Field | Use |
|-------|-----|
| `pre_mls_score` | Owner-occupant deal strength |
| `short_sale_score` | LP + bank + human |
| `fha_203k_score` | Old home + long ownership + equity |
| `creative_score` | Recent purchase, low equity |
| `wholesale_score` | Equity + long hold |

## Blocker: local Playwright

If document sprint fails with missing Chromium:

```bash
cd ~/Desktop/foretrust/scraper-service && playwright install chromium
```

Then re-run `run-pre-mls-doc-sprint.sh` or deploy on Railway where browsers are installed.
