# eCCLIX Full Day Pass — Run Today

**Goal:** Extract everything useful before the 24h subscription expires.

## What runs automatically (`mode: full_day_pass`)

Per county (Scott → Bourbon → Woodford → Franklin):

| Order | Search | Pages |
|-------|--------|-------|
| 1 | **Delinquent Tax 2025** | All grid pages (500+ bills) |
| 2 | **LP** last 120 days | Summary → drill → all detail pages |
| 3 | **LP** 2024–2025 historical | Same |
| 4 | **MTG** 90 days | Drill + paginate |
| 5 | **WILL** 1 year | Drill + paginate |
| 6 | **JLIEN, TLIEN, GLIEN, MLIEN** | Drill + paginate |
| 7 | **DEED** 120 days | Drill + paginate |
| 8 | **Securities LIEN** | City/county liens |

Outputs:

- `ft_leads` (`source_key=ecclix_batch`)
- `scraper-service/exports/ecclix-sprint/{counties}-{timestamp}.csv`

PDF downloads are **off** (too slow for one day).

## Run locally (recommended now)

```bash
cd ~/Desktop/foretrust
bash scripts/run-ecclix-full-day-pass.sh
```

Parallel by county (3 terminals):

```bash
ECCLIX_COUNTIES=scott bash scripts/run-ecclix-full-day-pass.sh
ECCLIX_COUNTIES=bourbon bash scripts/run-ecclix-full-day-pass.sh
ECCLIX_COUNTIES=woodford,franklin bash scripts/run-ecclix-full-day-pass.sh
```

## Run on Railway scraper

```bash
doppler run --project foretrust-scraper --config prd -- \
  curl -X POST "$SCRAPER_SERVICE_URL/pipeline/ecclix" \
  -H "Authorization: Bearer $SCRAPER_SHARED_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode":"full_day_pass","counties":["scott","bourbon","woodford","franklin"],"download_documents":false}'
```

## Manual CSV you already exported

```bash
python3 scripts/import-ecclix-csv.py ~/Downloads/ecclix*.csv --tier all --min-amount 0 --persist
```

## After scrape (no eCCLIX needed)

1. PVA qPublic — owner name / Map ID → full address + value  
2. Stack LP owners with delinquent tax owners  
3. Skiptrace top Tier A rows  

## Doppler

```bash
doppler secrets set ECCLIX_COUNTIES="scott,bourbon,woodford,franklin" \
  --project foretrust-scraper --config dev
```
