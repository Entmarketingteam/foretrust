#!/usr/bin/env bash
# Pre-MLS setup: legal notices (Google Alerts RSS + KY newspaper URLs), KCOJ checks.
# Secrets stay in Doppler — this script never writes credentials to disk.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DOPPLER_PROJECT="${DOPPLER_PROJECT:-foretrust-scraper}"
DOPPLER_CONFIG="${DOPPLER_CONFIG:-prd}"

# Kentucky Press Association public notice site (Herald Leader, News-Graphic, Winchester Sun, etc.)
# News-Graphic has no stable /legal-notices path; KPA indexes their print notices by county.
LEGAL_NOTICE_NEWSPAPER_URLS="https://kypublicnotice.com/index.php/main/search/0/Fayette,https://kypublicnotice.com/index.php/main/search/0/Scott,https://kypublicnotice.com/index.php/main/search/0/Clark,https://kypublicnotice.com/index.php/main/search/0/Madison,https://kypublicnotice.com/index.php/main/search/0/Woodford,https://kypublicnotice.com/index.php/main/search/0/Jessamine,https://kypublicnotice.com/index.php/main/search/0/Oldham,https://kypublicnotices.com/"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

need_doppler() {
  command -v doppler >/dev/null 2>&1 || die "Install Doppler CLI: https://docs.doppler.com/docs/install-cli"
}

section() {
  echo ""
  echo "=== $* ==="
}

need_doppler

section "Foretrust pre-MLS setup (Doppler: ${DOPPLER_PROJECT}/${DOPPLER_CONFIG})"

cat <<'EOF'

Create 10 Google Alerts (Central KY probate / foreclosure / estate / master commissioner).
For each alert: google.com/alerts → paste query → Show options → Create Alert → enable RSS → copy feed URL.

Exact query strings (also in config/google-alerts-queries.txt):

  1. "estate of" Fayette County Kentucky
  2. "estate of" Scott County Kentucky
  3. "probate" Lexington Kentucky
  4. "master commissioner" Fayette County Kentucky
  5. "master commissioner" Scott County Kentucky
  6. "foreclosure" Lexington Kentucky
  7. "notice of trustee sale" Central Kentucky
  8. "letters testamentary" Scott County Kentucky
  9. "commissioner's sale" Clark County Kentucky
  10. "lis pendens" Fayette County Kentucky

After all 10 RSS feed URLs are copied, run (paste your URLs — do not commit them to git):

  doppler secrets set GOOGLE_ALERTS_RSS_URLS="<rss1>,<rss2>,..." \
    --project foretrust-scraper --config prd

Full walkthrough: docs/GOOGLE-ALERTS-SETUP.md

EOF

section "Setting LEGAL_NOTICE_NEWSPAPER_URLS (public URLs only)"

echo "URLs:"
echo "$LEGAL_NOTICE_NEWSPAPER_URLS" | tr ',' '\n' | sed 's/^/  /'

doppler secrets set "LEGAL_NOTICE_NEWSPAPER_URLS=${LEGAL_NOTICE_NEWSPAPER_URLS}" \
  --project "$DOPPLER_PROJECT" --config "$DOPPLER_CONFIG"

echo "OK — LEGAL_NOTICE_NEWSPAPER_URLS set in ${DOPPLER_PROJECT}/${DOPPLER_CONFIG}"

section "KCOJ guest credentials (manual if missing)"

kcoj_user="$(doppler secrets get KCOJ_USERNAME --project "$DOPPLER_PROJECT" --config "$DOPPLER_CONFIG" --plain 2>/dev/null || true)"
kcoj_pass="$(doppler secrets get KCOJ_PASSWORD --project "$DOPPLER_PROJECT" --config "$DOPPLER_CONFIG" --plain 2>/dev/null || true)"

if [[ -z "${kcoj_user}" || -z "${kcoj_pass}" ]]; then
  cat <<EOF
KCOJ_USERNAME and/or KCOJ_PASSWORD are not set.

Register a guest account at: https://kcoj.kycourts.net/kyecourts/Login
Then run:

  doppler secrets set KCOJ_USERNAME="your_guest_email" \\
    --project ${DOPPLER_PROJECT} --config ${DOPPLER_CONFIG}

  doppler secrets set KCOJ_PASSWORD="your_guest_password" \\
    --project ${DOPPLER_PROJECT} --config ${DOPPLER_CONFIG}

EOF
else
  echo "OK — KCOJ_USERNAME and KCOJ_PASSWORD are set (values not shown)."
fi

section "CAPTCHA key check (TWOCAPTCHA_API_KEY)"

if doppler secrets get TWOCAPTCHA_API_KEY --project "$DOPPLER_PROJECT" --config "$DOPPLER_CONFIG" --plain >/dev/null 2>&1; then
  echo "OK — TWOCAPTCHA_API_KEY exists in ${DOPPLER_PROJECT}/${DOPPLER_CONFIG}"
else
  cat <<EOF
MISSING — TWOCAPTCHA_API_KEY is not set (required for KCOJ CourtNet CAPTCHA).

  doppler secrets set TWOCAPTCHA_API_KEY="your_2captcha_key" \\
    --project ${DOPPLER_PROJECT} --config ${DOPPLER_CONFIG}

EOF
  exit 1
fi

section "Optional: GOOGLE_ALERTS_RSS_URLS status"

if rss="$(doppler secrets get GOOGLE_ALERTS_RSS_URLS --project "$DOPPLER_PROJECT" --config "$DOPPLER_CONFIG" --plain 2>/dev/null || true)"; then
  if [[ -n "${rss}" ]]; then
    count="$(echo "$rss" | tr ',' '\n' | grep -c . || true)"
    echo "GOOGLE_ALERTS_RSS_URLS is set (${count} URL(s) — values not shown)."
  else
    echo "GOOGLE_ALERTS_RSS_URLS is empty — set after creating Google Alerts (see above)."
  fi
else
  echo "GOOGLE_ALERTS_RSS_URLS not configured yet."
fi

section "Done"

cat <<EOF

Automatic (this script):
  - LEGAL_NOTICE_NEWSPAPER_URLS → KPA county pages (Fayette/Herald Leader, Scott/News-Graphic, Clark, Madison, Woodford, Jessamine, Oldham) + statewide index
  - Verified TWOCAPTCHA_API_KEY presence

Manual (you):
  - Create 10 Google Alerts + enable RSS → doppler secrets set GOOGLE_ALERTS_RSS_URLS=...
  - KCOJ guest login → KCOJ_USERNAME / KCOJ_PASSWORD (if not already set)
  - Redeploy scraper-service on Railway after secret changes
  - UI → Full Pipeline or legal_notices run

Docs: docs/GOOGLE-ALERTS-SETUP.md

EOF
