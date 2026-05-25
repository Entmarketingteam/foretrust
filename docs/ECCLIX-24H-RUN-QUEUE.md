# eCCLIX 24-Hour Run Queue

**Window:** Day pass expires ~24h from first county login.  
**Counties:** Scott, Bourbon, Woodford, Franklin (eCCLIX Central — pick county on `usercounties.aspx`).  
**Always use:** `no_proxy: true` locally (proxy breaks county picker).

## Done (2026-05-25)

- [x] Delinquent tax 2025 — all 4 counties → Supabase + actionable exports
- [x] Portal hardening (login, county select, `dtwebsearch.aspx`, junk filter)

## Priority queue — run in this order

### Wave 1 — Highest signal (run first, all 4 counties)

| # | Mode | Command / params | Why | Est. time |
|---|------|------------------|-----|-----------|
| 1 | `deep_portal_search` | `download_documents: false`, `full_extract: true` | Filtered LP (bank, divorce, premium subs), estate deeds, liens, city securities — pre-MLS stack | ~45–60 min/county |
| 2 | `pre_mls_sprint` | `download_documents: true`, `max_documents_per_county: 25` | LP PDFs + party search on top tax-delinquent human owners | ~30 min/county |

```bash
# One county at a time (safest)
ECCLIX_COUNTIES=scott bash scripts/run-portal-intel.sh
ECCLIX_COUNTIES=bourbon bash scripts/run-portal-intel.sh
# … woodford, franklin
```

Or API per county:

```json
{"mode":"deep_portal_search","counties":["bourbon"],"full_extract":true,"download_documents":false,"no_proxy":true}
```

### Wave 2 — Instrument sweeps (fix-and-flip & off-market homes)

| # | Profile / type | Settings | Buyer angle |
|---|----------------|----------|-------------|
| 3 | **LP + `premium_subdivision`** | `deep_portal_search` profile `lp_premium_subdivision` · 180d · drill | Higher-end neighborhoods — retail flip / 203k candidates |
| 4 | **LP + `big_home_signal`** | profile `lp_divorce_domestic` · 365d | Domestic + larger legal descriptions — motivated seller, not bank-only |
| 5 | **DEED + estate** | `deed_estate` · 180d · `estate_deed` + `big_home_signal` | Inherited / estate transfers before MLS |
| 6 | **MTG recent** | 90d · `big_home_signal` | Recent refi / acquisition — equity plays |
| 7 | **MLIEN** | 730d · mechanics lien · download if pass | Contractor dispute / rehab stall |
| 8 | **ENC** | 365d · encumbrance | Title friction, subordination issues |

```bash
doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH python3 - <<'PY'
import asyncio
from app.scheduler import run_connector_job
async def main():
    await run_connector_job("ecclix_batch", {
        "mode": "deep_portal_search",
        "counties": ["scott"],  # repeat per county
        "full_extract": True,
        "download_documents": False,
        "no_proxy": True,
        "max_pages": 100,
    })
asyncio.run(main())
PY
```

### Wave 3 — Liens & judgments (stack with tax list)

| # | Type | Settings | Notes |
|---|------|----------|-------|
| 9 | **JLIEN** | 730d · `any_distress` | Judgment liens — stack with tax delinquent owners |
| 10 | **TLIEN / FLIEN / SLIEN** | 730d each | Tax lien instruments (clerical) vs delinquent tax *list* |
| 11 | **Securities LIEN** | Georgetown + Versailles party filters | Code / city liens — vacancy signal |
| 12 | **REL** | 90d releases | Paired with LP — released foreclosure trace |

### Wave 4 — Party search (enrich Tier A tax leads)

| # | Mode | Settings | Why |
|---|------|----------|-----|
| 13 | `pre_mls_sprint` name search | `min_tax_due: 1500`, `name_search_limit: 30` | Pull LP/MTG/DEED on same owner as delinquent tax |
| 14 | Combination party (manual spot-check) | Top 20 human owners from actionable CSV | Catches instruments missed by date-range search |

### Wave 5 — Non-eCCLIX (same 24h window, parallel)

| # | Source | Command | Signal |
|---|--------|---------|--------|
| 15 | KCOJ CourtNet | `scripts/run-portal-intel.sh` (stage 2) | Divorce, probate, civil — needs working login |
| 16 | Legal notices RSS | `signal_intel` pipeline | Estate / sheriff sale keywords |
| 17 | Georgetown water FOIA | `georgetown_water` connector | Shutoff / vacancy |
| 18 | PVA qPublic | Per county PVA connector + map IDs from tax CSV | Physical address, sqft, assessed value |

```bash
bash scripts/run-signal-digest.sh
```

## Per-county checklist

Copy for each: **Scott · Bourbon · Woodford · Franklin**

```
County: ___________
[ ] deep_portal_search (filtered)
[ ] usable_extract OR lp_recent only (if deep too heavy)
[ ] pre_mls_sprint (PDFs + name search) — top county only if time tight
[ ] export-property-lead-list.py --all-sources --jurisdiction <County> --human-only --min-due 500
```

## Modes reference

| Mode | Use when |
|------|----------|
| `delinquent_tax` | Full tax grid only (done) |
| `usable_extract` | Tax + LP + WILL + JLIEN + city securities (lighter than deep) |
| `deep_portal_search` | All instrument profiles + smart filters |
| `pre_mls_sprint` | LP docs + party search on hot tax owners |
| `signal_intel` | eCCLIX + KCOJ + notices + water |
| `lp_recent` | Quick LP-only 60–120d |

## Filter tags → strategy

| Tag | Best for |
|-----|----------|
| `human_owner_only` | Skip LLC/bank noise on tax |
| `street_address` | Drive-by / skip trace ready |
| `min_tax_500` | Actionable tax bill threshold |
| `foreclosure_lp` + `bank_counterparty` | Short sale / pre-foreclosure |
| `divorce_domestic` | Motivated seller, not institutional |
| `premium_subdivision` | Fix-and-flip / higher ARV pockets |
| `big_home_signal` | Larger homes (legal desc / consideration) |
| `estate_deed` | Probate / heir deals |
| `city_lien` | Code enforcement stack |
| `any_distress` | Broad instrument pass (noisy — use after filters fail) |

## After each wave

1. `python3 scripts/export-property-lead-list.py --all-sources --jurisdiction <County> --human-only --min-due 500`
2. `python3 scripts/build-best-deals.py` (stack tax + LP + scores)
3. Spot-check `exports/portal-intel/*-filtered-*.json` for Tier A/B

## Do NOT burn time on

- `exports/ecclix-sprint/*.csv` from old runs (login junk) — ignore
- `full_day_pass` without `no_proxy` behind Webshare
- PDF download on every row (use `download_if_pass` or cap at 25/county)
- County subdomains (`bourbonky.ecclix.com`) — DNS dead; use **www.ecclix.com** only

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/run-county-tax-extract.sh <county>` | Tax only |
| `scripts/run-portal-intel.sh` | deep_portal_search + KCOJ |
| `scripts/run-ecclix-full-day-pass.sh` | Legacy full_day_pass |
| `scripts/run-usable-extract-all-counties.sh` | usable_extract × 4 |
| `scripts/export-property-lead-list.py` | Actionable CSV/MD from Supabase |
