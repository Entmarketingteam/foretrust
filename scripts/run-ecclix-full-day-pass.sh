#!/usr/bin/env bash
# Full eCCLIX 1-day pass extraction — run NOW while subscription is active.
# Paginates all delinquent tax pages + LP/MTG/WILL/lien grids per county.
set -euo pipefail
cd "$(dirname "$0")/../scraper-service"

COUNTIES="${ECCLIX_COUNTIES:-scott,bourbon,woodford,franklin}"
TAX_YEAR="${ECCLIX_TAX_YEAR:-2025}"

echo "=== eCCLIX FULL DAY PASS ==="
echo "Counties: $COUNTIES"
echo "Started: $(date)"
echo ""

doppler run --project foretrust-scraper --config "${DOPPLER_CONFIG:-dev}" -- \
  env -u PLAYWRIGHT_BROWSERS_PATH ECCLIX_COUNTIES="$COUNTIES" python3 - <<'PY'
import asyncio
import json
import logging
from app.browser import create_browser
from app.connectors.registry import get_connector
from app.pipeline.distress_scorer import score_leads
from app.storage.supabase_client import insert_leads, insert_source_run
from app.models import SourceRun, SourceRunStatus
from datetime import datetime
import os

logging.basicConfig(level=logging.INFO)
COUNTIES = [c.strip() for c in os.environ.get("ECCLIX_COUNTIES", "scott,bourbon,woodford,franklin").split(",") if c.strip()]

async def main():
    conn = get_connector("ecclix_batch")
    params = {
        "mode": "deep_portal_search",
        "counties": COUNTIES,
        "download_documents": True,
        "full_extract": True,
        "tax_year": int(os.environ.get("ECCLIX_TAX_YEAR", "2025")),
        "max_pages": 100,
    }
    run = SourceRun(
        source_key="ecclix_batch",
        status=SourceRunStatus.RUNNING,
        started_at=datetime.utcnow(),
    )
    await insert_source_run(run)
    async with create_browser() as browser:
        raw = await conn.fetch(browser, params)
    leads = [conn.parse(r) for r in raw]
    leads = score_leads(leads)
    n = await insert_leads(leads)
    run.status = SourceRunStatus.OK
    run.finished_at = datetime.utcnow()
    run.records_found = len(raw)
    run.records_new = n
    await insert_source_run(run)
    print(json.dumps({
        "counties": COUNTIES,
        "raw_records": len(raw),
        "leads": len(leads),
        "persisted": n,
        "hot_70_plus": sum(1 for l in leads if (l.hot_score or 0) >= 70),
    }, indent=2))

asyncio.run(main())
PY

echo ""
echo "Done: $(date)"
echo "Check: scraper-service/exports/ecclix-sprint/*.csv and ft_leads (source_key=ecclix_batch or ecclix_csv_import)"
