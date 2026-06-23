#!/usr/bin/env bash
# Wrapper to run the Google Alerts / Probate Sourcing Agent under Doppler
set -euo pipefail
ROOT="/Users/ethanatchley/Desktop/foretrust/scraper-service"
LOG="$ROOT/exports/google-alerts-agent.log"

# Ensure output directory exists
mkdir -p "$ROOT/exports"

echo "========== GOOGLE ALERTS AGENT RUN $(date) ==========" >> "$LOG"
cd "$ROOT"
export PYTHONPATH="$ROOT"
/opt/homebrew/bin/doppler run -- env -u PLAYWRIGHT_BROWSERS_PATH .venv/bin/python3 app/pipeline/agentic/google_alerts_agent.py >> "$LOG" 2>&1
echo "========== GOOGLE ALERTS AGENT RUN COMPLETE $(date) ==========" >> "$LOG"
