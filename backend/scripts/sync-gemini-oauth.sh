#!/usr/bin/env bash
# Sync local Gemini CLI OAuth (Google AI Ultra) to Foretrust Railway backend.
set -euo pipefail

CREDS="${HOME}/.gemini/oauth_creds.json"
if [[ ! -f "$CREDS" ]]; then
  echo "Missing $CREDS — run: gemini" >&2
  echo "Then choose 'Sign in with Google' using your Ultra account." >&2
  exit 1
fi

cd "$(dirname "$0")/.."

echo "Setting GEMINI_OAUTH_CREDS on Foretrust Railway (subscription auth)..."
cat "$CREDS" | railway variable set GEMINI_OAUTH_CREDS --stdin --service backend --skip-deploys

railway variable set \
  GEMINI_MODEL=gemini-2.5-flash \
  GEMINI_CLI_HOME=/root/.gemini \
  GEMINI_CLI_USER_HOME=/root \
  --service backend --skip-deploys

echo "Removing GEMINI_API_KEY from Railway (avoids pay-as-you-go)..."
railway variable delete GEMINI_API_KEY --service backend 2>/dev/null || true

echo "Done. Redeploy: git push (auto) or: cd .. && railway up --detach"
