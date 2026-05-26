# Veteran Wholesaler Playbook — 24h Execution

You have a **phone book**, not a database, until PVA + instruments + shutoffs join on clean `property_address`.

## Priority order (everything compounds from #1)

### 1. Fix `property_address` parser (blocker)
- Module: `scraper-service/app/pipeline/property_address.py`
- Rejects legal descriptions, bill numbers, map IDs, instrument junk
- Tests: `scraper-service/tests/test_property_address.py` — run before any PVA batch
- Wired into: `ecclix_batch.py`, `ecclix_portal.py`, `ecclix_csv.py`, `deal_package.py`

### 2. PVA enrichment on ~1,500 tax leads
- Module: `scraper-service/app/pipeline/pva_enrichment.py`
- Required fields: `year_built`, `last_sale_date`, `last_sale_price`, `assessed_value`, `mailing_address`, `homestead_exemption`
- Batch runner:
  ```bash
  doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH \
    python3 scripts/run-pva-enrichment-batch.py --county scott --limit 500
  ```
- Counties with PVA connectors: **Scott**, **Woodford** (Bourbon/Franklin PVA TBD)

### 3. List-stack overlay (today)
- Module: `scraper-service/app/pipeline/list_stack.py`
- Export top multi-list hits:
  ```bash
  python3 scripts/export-stacked-leads.py --county scott --limit 100 --min-lists 2
  ```
- Output: `scraper-service/exports/stacked-leads/stacked-{county}-*.md`
- Stacks **tax** × **LP** × **instrument scenarios** (POA/MLIEN/etc.) even without absentee/vacancy lists yet

### 4. Franklin instruments gap
- See `docs/FRANKLIN-INSTRUMENTS.md` — eCCLIX Central tax OK; LP/instrument data incomplete
- Do not trust Franklin portal-intel LP counts until separate clerk portal wired

### 5. Water shutoff FOIA (3–10 business days)
- Templates: `docs/FOIA-WATER-SHUTOFF.md`
- Cities: Georgetown, Paris, Frankfort, Versailles
- When CSV arrives → ingest → re-run list stack (water = vacancy proxy)

### 6. Condition-adjusted underwriting
- Module: `scraper-service/app/pipeline/underwriting.py`
- Haircuts on raw PVA (pre-1960 −30%, pre-1980 −20%, no homestead signal, etc.)
- `offer_band()` on adjusted value — feeds scored leads, not raw assessed

## What “done in 24h” looks like

| Milestone | Signal |
|-----------|--------|
| Parser | 17+ pytest cases green |
| PVA | `pva_enriched` in Supabase `raw_payload`; SubTo/wholesale scores non-zero |
| Stack | 50+ WARM/HOT rows in `stacked-leads/*.md` for Scott |
| Calls | Top 100 multi-list owners with street address + tax due + instrument tag |
| Franklin | Tax-only stack; instruments flagged incomplete |

## LLM aggregation (after join)

Only after joined dataset: feed underwriteable leads with priority context (stack tier, adjusted MAO, scenario tags) — not 1,500 names with amounts owed.
