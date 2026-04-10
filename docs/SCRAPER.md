# Foretrust Scraper Service — Operator Runbook

## What This Does

The scraper service automatically finds distressed real estate leads across Kentucky counties by scanning court records, property tax databases, GIS maps, and local newspaper legal notices.

Leads land in three places:
1. **Supabase** (database) — the source of truth
2. **Google Sheets** — open on your phone, sort by "Hot Score", call the owner
3. **CSV files** — backup exports on the server

## How to See Leads on Your Phone

1. Open the Google Sheet (shared with you during setup)
2. Each data source has its own tab (e.g., `kcoj_courtnet`, `fayette_pva`)
3. Sort by the **Hot Score** column (column A) — highest = most actionable
4. The columns show: owner name, property address, mailing address, case type, filed date, estimated value

## Data Sources (v1)

| Source | What It Finds | Runs |
|---|---|---|
| **KCOJ CourtNet** | Probate, estate, divorce, foreclosure filings | Daily 6am |
| **Fayette PVA + GIS** | High-value vacant properties, tax liens | Every 6 hours |
| **Scott County PVA** | Vacant properties, tax liens (eCCLIX) | Daily 7am |
| **Oldham County PVA** | Vacant properties, tax liens | Daily 7:15am |
| **KY State GIS** | Statewide 6000+ sqft residential parcels | Daily 5am |
| **eCCLIX Batch** | Deed/will/mortgage records across counties | On-demand (see below) |
| **Legal Notices** | Foreclosure sales, estate notices in newspapers | Every 6 hours |
| **Zillow** | Pre-foreclosure flags, estate sale listings | Manual trigger |

## How to Run an eCCLIX Batch

1. Wait until you have 20+ leads that need deed verification
2. Buy a single-day eCCLIX pass (~$15-30) for the counties you need
3. Enter the credentials in Doppler: `ECCLIX_USERNAME`, `ECCLIX_PASSWORD`, `ECCLIX_COUNTIES`
4. The batch runs automatically, or trigger it: `POST /api/foretrust/leads/scrape` with `{"source_key": "ecclix_batch"}`

## How to Add a New County

1. Create a new file in `scraper-service/app/connectors/residential/` (copy `oldham_pva.py` as a template)
2. Set `source_key`, `base_url`, `jurisdiction`, `default_schedule`
3. Implement `fetch()` and `parse()` methods
4. Add `@register` decorator at the top
5. Import the module in `registry.py`
6. Deploy — the scheduler picks it up automatically

## What to Do When Blocked

If a source blocks the scraper (403 error, CAPTCHA loop, IP ban):

1. Check the run log: `GET /api/foretrust/leads/runs` — look for `status: "blocked"`
2. The proxy session auto-rotates on the next run
3. If CAPTCHAs are the issue, check `CAPTCHA_DAILY_BUDGET_USD` in Doppler — it may need a bump
4. If the site changed its layout, the connector's selectors need updating

## How to Top Up the CAPTCHA Budget

1. Go to Doppler → `foretrust-scraper` project
2. Update `CAPTCHA_DAILY_BUDGET_USD` (default: $5.00/day)
3. The change takes effect on the next scraper run (no restart needed via Doppler SDK)

## Do Not Scrape List

- Any site whose robots.txt explicitly disallows scraping (checked automatically)
- Any county that charges > $100/year for access (use Zillow/Redfin fallback instead)
- Sites requiring personal login credentials that aren't yours to use

## Distress Signal Types

| Signal | What It Means |
|---|---|
| **Probate** | Owner died, estate being settled — heirs often want to sell fast |
| **Estate** | Trust or estate administration — similar motivation |
| **Divorce** | Court-ordered property division — one or both parties motivated |
| **Foreclosure** | Lender action — owner may accept below-market offer |
| **Pre-Foreclosure** | Default notice filed but not yet foreclosed — early-stage opportunity |
| **Tax Lien** | Delinquent property taxes — owner may be in financial distress |
| **Vacancy** | High-value property with no recent transfer — potential opportunity |
| **Zoning Change** | Rezoning may create value or force sale |
| **Code Violation** | Fines accumulating — owner may want out |
| **Death** | Obituary match to property owner — estate sale likely |
