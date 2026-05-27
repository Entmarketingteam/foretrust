#!/usr/bin/env bash
# Non-eCCLIX enrichment — safe while run-scenario-library-24h.sh holds /tmp/foretrust-ecclix.lock.
# Does NOT log into eCCLIX. Runs exports, MASTER merge, KCOJ, legal/water signals, PVA in parallel.
#
# Usage:
#   bash scripts/run-parallel-enrichment.sh              # one wave
#   bash scripts/run-parallel-enrichment.sh --loop 1800    # repeat every 30m while eCCLIX lock held
#   bash scripts/run-parallel-enrichment.sh --skip-kcoj    # skip CourtNet browser job
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG="/tmp/foretrust-parallel-enrichment.log"
ECCLIX_LOCK="/tmp/foretrust-ecclix.lock"
LOOP_SEC=0
SKIP_KCOJ=0
SKIP_SIGNALS=0
SKIP_PVA=0
SKIP_EXPORTS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --loop) LOOP_SEC="${2:-1800}"; shift 2 ;;
    --skip-kcoj) SKIP_KCOJ=1; shift ;;
    --skip-signals) SKIP_SIGNALS=1; shift ;;
    --skip-pva) SKIP_PVA=1; shift ;;
    --skip-exports) SKIP_EXPORTS=1; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

exec > >(tee -a "$LOG") 2>&1

doppler_py() {
  doppler run --project foretrust-scraper --config dev -- "$@"
}

run_wave() {
  local wave_start
  wave_start="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo ""
  echo "========== Parallel enrichment wave $wave_start =========="
  if [[ -d "$ECCLIX_LOCK" ]]; then
    echo "eCCLIX lock present — scenario library job is running (good)."
  else
    echo "Note: no eCCLIX lock — enrichment still runs; eCCLIX may be idle."
  fi

  local pids=()
  local names=()

  if [[ "$SKIP_EXPORTS" -eq 0 ]]; then
    for COUNTY in scott bourbon woodford franklin; do
      JURIS="$(echo "$COUNTY" | awk '{print toupper(substr($0,1,1)) substr($0,2)}')"
      (
        echo "[export] $COUNTY started"
        cd "$ROOT"
        doppler_py python3 scripts/export-property-lead-list.py \
          --all-sources --jurisdiction "$JURIS" --human-only --min-due 500 --limit 2000 \
          || echo "[export] $COUNTY failed (non-fatal)"
        echo "[export] $COUNTY done"
      ) &
      pids+=($!)
      names+=("export-$COUNTY")
    done

    (
      echo "[merge] scenario MASTER started"
      cd "$ROOT"
      doppler_py python3 scripts/export-scenario-reference-library.py --max-per-scenario 75 \
        || echo "[merge] failed (non-fatal)"
      echo "[merge] scenario MASTER done"
    ) &
    pids+=($!)
    names+=("scenario-merge")

    (
      echo "[deals] Supabase rank (no PVA) started"
      cd "$ROOT"
      doppler_py python3 scripts/build-best-deals.py || echo "[deals] rank failed (non-fatal)"
      echo "[deals] Supabase rank done"
    ) &
    pids+=($!)
    names+=("best-deals-rank")
  fi

  if [[ "$SKIP_KCOJ" -eq 0 ]]; then
    (
      echo "[kcoj] CourtNet started"
      cd "$ROOT/scraper-service"
      doppler_py env -u PLAYWRIGHT_BROWSERS_PATH python3 - <<'PY'
import asyncio, logging
logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
from app.scheduler import run_connector_job

async def main():
    await run_connector_job("kcoj_courtnet", {
        "no_proxy": True,
        "bulk_legacy": True,
        "counties": ["Scott", "Bourbon", "Woodford", "Franklin"],
        "case_types": [
            "D - Domestic Relations",
            "P - Probate",
            "CI - Civil",
        ],
        "limit": 40,
        "deep_scrape": True,
    })

asyncio.run(main())
PY
      echo "[kcoj] CourtNet done"
    ) &
    pids+=($!)
    names+=("kcoj")
  fi

  if [[ "$SKIP_SIGNALS" -eq 0 ]]; then
    (
      echo "[signals] legal notices + water (no eCCLIX) started"
      cd "$ROOT/scraper-service"
      doppler_py env -u PLAYWRIGHT_BROWSERS_PATH python3 - <<'PY'
import asyncio, logging
logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
from app.browser import create_browser
from app.pipeline.signal_intel import run_signal_intel_pipeline

async def main():
    async with create_browser(proxy_session=None) as browser:
        result = await run_signal_intel_pipeline(browser, {
            "counties": ["scott", "bourbon", "woodford", "franklin"],
            "run_ecclix": False,
            "run_kcoj": False,
            "run_legal_notices": True,
            "run_water": True,
            "persist": True,
            "send_email": False,
        })
    print(result)

asyncio.run(main())
PY
      echo "[signals] legal notices + water done"
    ) &
    pids+=($!)
    names+=("signals")
  fi

  if [[ "$SKIP_PVA" -eq 0 ]]; then
    (
      echo "[pva] Scott qPublic enrich started"
      cd "$ROOT"
      doppler_py env -u PLAYWRIGHT_BROWSERS_PATH \
        python3 scripts/build-best-deals.py --enrich-pva --no-proxy --county scott --pva-limit 25 \
        || echo "[pva] scott failed (non-fatal)"
      echo "[pva] Woodford qPublic enrich started"
      doppler_py env -u PLAYWRIGHT_BROWSERS_PATH \
        python3 scripts/build-best-deals.py --enrich-pva --no-proxy --county woodford --pva-limit 25 \
        || echo "[pva] woodford failed (non-fatal)"
      echo "[pva] done"
    ) &
    pids+=($!)
    names+=("pva-scott-woodford")
  fi

  local i=0
  local failed=0
  for pid in "${pids[@]}"; do
    local name="${names[$i]:-worker-$i}"
    if wait "$pid"; then
      echo "OK: $name (pid $pid)"
    else
      echo "FAIL: $name (pid $pid)"
      failed=$((failed + 1))
    fi
    i=$((i + 1))
  done

  echo "Wave finished: ${#pids[@]} workers, $failed failed."
  echo "  Actionable: $ROOT/scraper-service/exports/actionable-leads/"
  echo "  MASTER:     $ROOT/scraper-service/exports/scenario-library/MASTER/INDEX.md"
  echo "  Best deals: $ROOT/scraper-service/exports/best-deals/"
  echo "  Digest:     $ROOT/scraper-service/exports/digest/"
  cd "$ROOT"
  doppler_py python3 scripts/update-pipeline-status.py 2>/dev/null || python3 scripts/update-pipeline-status.py || true
  return "$failed"
}

echo "Parallel enrichment — log: $LOG"
echo "Does NOT touch eCCLIX (no lock acquired)."

if [[ "$LOOP_SEC" -gt 0 ]]; then
  echo "Loop mode: every ${LOOP_SEC}s while eCCLIX lock exists."
  while [[ -d "$ECCLIX_LOCK" ]]; do
    run_wave || true
    if [[ ! -d "$ECCLIX_LOCK" ]]; then
      echo "eCCLIX lock gone — final wave then exit."
      run_wave || true
      break
    fi
    echo "Sleep ${LOOP_SEC}s..."
    sleep "$LOOP_SEC"
  done
  echo "Loop ended (lock released)."
else
  run_wave || true
fi

echo "========== Parallel enrichment complete $(date -u +%Y-%m-%dT%H:%M:%SZ) =========="
