#!/usr/bin/env bash
# Create ft_clerk_documents in foretrust-v2 Supabase (fixes PDF metadata 404).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SQL="$ROOT/supabase/migrations/20260525100000_ft_clerk_documents.sql"

echo "Applying: $SQL"
echo ""

if [[ -n "${DATABASE_URL:-}" ]]; then
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$SQL"
elif [[ -n "${SUPABASE_DB_URL:-}" ]]; then
  psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -f "$SQL"
else
  echo "No DATABASE_URL — trying Supabase CLI (linked project foretrust-v2)..."
  cd "$ROOT"
  supabase db query --linked --yes --local=false -f "$SQL"
fi

echo ""
echo "Verify:"
cd "$ROOT/scraper-service"
doppler run --project foretrust-scraper --config dev -- python3 -c "
from app.storage.supabase_client import _get_client
c = _get_client()
print(c.table('ft_clerk_documents').select('id').limit(1).execute())
"
