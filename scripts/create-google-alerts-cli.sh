#!/usr/bin/env bash
# Create all Foretrust Google Alerts via google-alerts CLI and push RSS URLs to Doppler.
#
# Prereqs: pip install google-alerts
# You need your Google account password (or app password if 2FA).
# Email defaults to coachethanatchley@gmail.com — override with GOOGLE_EMAIL.
#
#   bash scripts/create-google-alerts-cli.sh
#
# Non-interactive (password in env — do not commit):
#   GOOGLE_EMAIL=you@gmail.com GOOGLE_PASSWORD='...' bash scripts/create-google-alerts-cli.sh

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
QUERIES="$ROOT/config/google-alerts-queries.txt"
EMAIL="${GOOGLE_EMAIL:-coachethanatchley@gmail.com}"

if ! command -v google-alerts &>/dev/null; then
  echo "Installing google-alerts..."
  pip3 install --user google-alerts 2>/dev/null || pip3 install google-alerts
  export PATH="$HOME/Library/Python/3.11/bin:$HOME/Library/Python/3.12/bin:$HOME/.local/bin:$PATH"
fi

if [[ -z "${GOOGLE_PASSWORD:-}" ]]; then
  echo "Google password for $EMAIL (input hidden):"
  read -rs GOOGLE_PASSWORD
  echo
fi

export GOOGLE_ALERTS_CONFIG_DIR="${TMPDIR:-/tmp}/foretrust-google-alerts-config"
mkdir -p "$GOOGLE_ALERTS_CONFIG_DIR"

python3 << PY
import os, subprocess, sys
from pathlib import Path

email = os.environ["GOOGLE_EMAIL"] if "GOOGLE_EMAIL" in os.environ else "$EMAIL"
password = os.environ["GOOGLE_PASSWORD"]
queries = Path("$QUERIES").read_text().splitlines()
queries = [q.strip() for q in queries if q.strip()]

# Configure once via module
from google_alerts import GoogleAlerts
ga = GoogleAlerts(email, password)
ga.authenticate()
print("Authenticated as", email)

existing = {m.get("term", "") for m in (ga.list() or [])}
for q in queries:
    if q in existing:
        print(f"Skip (exists): {q}")
        continue
    ga.create(q, {"delivery": "RSS", "frequency": "AS_IT_HAPPENS", "region": "US", "language": "en"})
    print(f"Created: {q}")

monitors = ga.list() or []
rss_urls = []
for m in monitors:
    term = m.get("term", "")
    if any(term == q or term.strip('"') in q for q in queries):
        link = m.get("rss_link") or m.get("rss")
        if link:
            rss_urls.append(link)

if not rss_urls:
    print("No RSS links returned — list all monitors:")
    for m in monitors:
        print(m)
    sys.exit(1)

joined = ",".join(rss_urls)
print("\\nRSS feeds:", len(rss_urls))
for u in rss_urls:
    print(" ", u)
open("/tmp/foretrust-google-alerts-rss.txt", "w").write(joined)
print("\\nSaved to /tmp/foretrust-google-alerts-rss.txt")
PY

RSS="$(cat /tmp/foretrust-google-alerts-rss.txt)"
doppler secrets set GOOGLE_ALERTS_RSS_URLS="$RSS" \
  --project foretrust-scraper --config prd
doppler secrets set GOOGLE_ALERTS_RSS_URLS="$RSS" \
  --project foretrust-scraper --config dev
echo "OK — GOOGLE_ALERTS_RSS_URLS set in Doppler prd + dev"
