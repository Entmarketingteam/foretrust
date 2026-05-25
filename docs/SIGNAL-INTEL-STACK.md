# Signal Intel Stack — LP, Probate, Code, Water + Email Digest

One command pulls every distress channel, buckets leads, and **emails CSVs** ready for skip trace or drive-by.

## What runs automatically

| Signal | Source | Foretrust |
|--------|--------|-----------|
| **All lis pendens** | eCCLIX Instruments → LP (365d + historical) | `signal_intel` mode |
| **Probate filings** | eCCLIX WILL + DEED (estate) + KCOJ `P - Probate` + legal notices RSS | Same pipeline |
| **Code violations / city liens** | eCCLIX **Securities** → Georgetown + Versailles LIEN | `securities_code_*` profiles |
| **Judgment / mechanic liens** | eCCLIX JLIEN, MLIEN | Included in `signal_intel` |
| **Water shutoff** | GMWSS disconnect list (FOIA) + GIS active outages | `georgetown_water` connector |

## Water shutoff reality (Kentucky)

GMWSS does **not** publish a daily shutoff spreadsheet online. Disconnect notices are **mailed** to customers.

**Automated today:**
- Georgetown **GIS water outage** polygons (`customers out` count) → drive-by / vacancy proxy

**Manual once (then automate imports):**
1. FOIA to City Clerk: [Open Records Request](https://www.georgetownky.gov/2251/Open-Records-Request)
2. FOIA to GMWSS: disconnect / delinquent account list (last 30–90 days)
3. Save CSV as `property_address,owner_name,disconnect_date`
4. Re-run with: `WATER_FOIA_CSV=/path/to/shutoffs.csv bash scripts/run-signal-digest.sh`

Template: `docs/templates/foia-water-shutoff-request.md`

## Email digest (skip trace / drive-by lists)

Set in Doppler (`foretrust-scraper` / `dev`):

```bash
doppler secrets set ALERT_DIGEST_TO="you@email.com,partner@email.com"
doppler secrets set RESEND_API_KEY="re_..."
doppler secrets set ALERT_DIGEST_FROM="Foretrust Signals <onboarding@resend.dev>"
```

Or SMTP:

```bash
doppler secrets set SMTP_HOST="smtp.gmail.com"
doppler secrets set SMTP_USER="..."
doppler secrets set SMTP_PASSWORD="..."
```

Each run attaches up to 4 CSVs:
- `lis_pendens-*.csv` — owner, grantor, grantee, legal, book/page
- `probate-*.csv`
- `code_violations-*.csv`
- `water_shutoff-*.csv`

HTML email summarizes top 25 per category with **action line** (skip trace vs drive-by).

## Run

```bash
# Full stack + email
bash ~/Desktop/foretrust/scripts/run-signal-digest.sh

# Scott only, include FOIA water CSV
ECCLIX_COUNTIES=scott WATER_FOIA_CSV=~/Downloads/gmwss-shutoffs.csv \
  bash ~/Desktop/foretrust/scripts/run-signal-digest.sh
```

API:

```http
POST /pipeline/signal-digest
Authorization: Bearer $SCRAPER_SHARED_TOKEN

{
  "counties": ["scott","bourbon","woodford","franklin"],
  "send_email": true,
  "run_water": true,
  "water_foia_csv": "/data/gmwss-shutoffs.csv"
}
```

## Operator workflow after email

1. **Lis pendens CSV** → BatchData / Direct Skip → phone + mailing address  
2. **Probate** → heir skip trace; mail to executor address from KCOJ detail  
3. **Code violations** → drive-by GIS lat/lon rows; skip trace when address exists  
4. **Water** → FOIA rows = highest priority skip trace; GIS outages = drive-by route  

## eCCLIX-only (day pass)

```bash
doppler run --project foretrust-scraper --config dev -- \
  env -u PLAYWRIGHT_BROWSERS_PATH python3 -c "
import asyncio
from app.scheduler import run_connector_job
asyncio.run(run_connector_job('ecclix_batch', {'mode':'signal_intel','counties':['scott'],'full_extract':True}))
"
```

## n8n (optional)

Trigger `POST /pipeline/signal-digest` on cron (e.g. 6am ET Mon–Fri) → forward Resend copy to Slack `#distress-leads` if desired.
