# Foretrust — STATUS

**Updated:** 2026-06-05  
**Stack:** Node backend + Python scraper on Railway, shared Supabase

## Live
- Backend API: Railway `backend-production-7bd9.up.railway.app`
- Scraper service: eCCLIX portal intel, tax actionable lists, scenario library (Scott, Bourbon, Franklin, Woodford KY)
- Lead scoring: cash wholesale, sub-to, FHA 203k, short sale rubrics
- Dashboard with skip-trace / Find Contact for HOT leads

## Pipeline state
- Refresh: `python3 scripts/update-pipeline-status.py` → `scraper-service/exports/pipeline-status.json`
- List stacking: tax × pre-foreclosure overlay (Scott growing)
- KCOJ civil selectors still broken; Bourbon/Franklin instrument probe pending

## Blockers
- eCCLIX: one browser session at a time (lock file `/tmp/foretrust-ecclix.lock`)
- `ft_clerk_documents` migration may need apply on Supabase
- FOIA water shutoff list not yet automated

## Hermes integration
- `status on foretrust` → this file
- No dedicated foretrust pulse skill yet (pipeline-status.json not wired)
