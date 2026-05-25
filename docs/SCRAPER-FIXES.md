# Scraper Fix Playbook — May 2026

Status of each source from your Scraper Runs audit, what broke, and how to fix it.

## Quick reference

| Source | Status you see | Root cause | Fix effort | Who |
|--------|----------------|------------|------------|-----|
| **fayette_pva** | ✅ 100 found | Working | — | — |
| **ky_state_gis** | ✅ 200–300 found | Working | — | — |
| **kcoj_courtnet** | ok, 0 found | CourtNet 3 — old `/casesearch` is 404 | **Large** (2–3 days) | Dev: rewrite connector |
| **oldham_pva** | error DNS | Wrong domain `oldhamcountypva.com` | **Small** (shipped) | Deploy scraper-service |
| **scott_pva** | ok, 0 found | No discovery mode; site has no list table | **Medium** | Dev: add Scott GIS or eCCLIX |
| **legal_notices** | ok, 0 found | No RSS/newspaper URLs in Doppler | **Small** (config) | You: Doppler secrets |
| **zillow_public** | ok, 0 found | Needs addresses + Browserbase for bot wall | **Medium** | You: Doppler + dev |

---

## 1. kcoj_courtnet (KY Court — probate / foreclosure)

**Problem:** CourtNet 3 at `https://kcoj.kycourts.net/kyecourts/` **requires login** (302 → `/kyecourts/Login`). Legacy `/casesearch` is 404. Runs complete with 0 rows until auth + UI rewrite.

**Fix (development):**
1. Log into CourtNet 3 manually — note login required?, search form selectors, result table HTML.
2. Rewrite `scraper-service/app/connectors/residential/kcoj_courtnet.py`:
   - Entry URL: `https://kcoj.kycourts.net/kyecourts/`
   - Party search or Case search per county (CourtNet 3 requires jurisdiction + criteria).
3. Map case types → `probate`, `foreclosure`, `pre_foreclosure` lead types.
4. Test with `doppler run --project foretrust-scraper --config dev --` manual run.

**Until fixed:** Use **fayette_pva** + **ky_state_gis** for vacancy leads. Court types will stay empty.

---

## 2. oldham_pva (error: ERR_NAME_NOT_RESOLVED)

**Problem:** Code used `https://oldhamcountypva.com` (dead). Real site: **https://oldhampva.com** → qPublic search.

**Fix (code — in repo):** Updated URL + skip dead navigation on GIS discovery path.

**Deploy:**
```bash
cd ~/Desktop/foretrust
git pull
# Railway auto-deploys scraper-service on push to main
```

**Verify:** Trigger **oldham_pva** from UI → Scraper Runs should show `found > 0` or a clearer GIS/qPublic error.

---

## 3. legal_notices (ok, 0 found)

**Problem:** Connector runs but has **no input URLs** unless Doppler is configured.

**Fix (you — Doppler `foretrust-scraper` project):**

```bash
# Google Alerts RSS feeds (comma-separated) for KY foreclosure/estate keywords
doppler secrets set GOOGLE_ALERTS_RSS_URLS="https://..." --project foretrust-scraper --config prd

# KY newspaper legal-notice pages to scrape
doppler secrets set LEGAL_NOTICE_NEWSPAPER_URLS="https://www.news-graphic.com/legal-notices,..." --project foretrust-scraper --config prd
```

Optional: `OPENAI_API_KEY` for notice text parsing (already may exist).

**How to get RSS URLs:** Create Google Alerts for `"foreclosure" Kentucky`, `"estate of" Kentucky`, `"master commissioner" Kentucky` → enable RSS → paste feed URLs.

Redeploy scraper-service after setting secrets.

---

## 4. zillow_public (ok, 0 found)

**Problem:** Zillow is **enrichment-only** — it needs property addresses. Empty `params.addresses` = 0 results. Zillow also blocks bots without Browserbase.

**Fix (you — Doppler `foretrust-scraper`):**

```bash
doppler secrets set BROWSERBASE_API_KEY="..." BROWSERBASE_PROJECT_ID="..." --project foretrust-scraper --config dev
```

**Fix (code — in repo):** When no addresses passed, connector now pulls recent addresses from `ft_leads` automatically.

**How to run:**
1. Import leads first (GIS/PVA).
2. Run scraper **zillow_public** from UI.
3. Check runs — expect some found if Browserbase is configured.

---

## 5. scott_pva (ok, 0 found)

**Problem:** Discovery mode browses `scottkypva.com` for a property table that doesn't exist in expected format. No ArcGIS discovery like Fayette.

**Fix options (development):**
- Add Scott County ArcGIS REST endpoint (like `fayette_pva._scan_lexington_gis`).
- Or use **ecclix_batch** with `ECCLIX_USERNAME`, `ECCLIX_PASSWORD`, `ECCLIX_COUNTIES=scott` in Doppler (paid eCCLIX pass).

**Workaround:** **ky_state_gis** already includes statewide parcels (includes Scott County).

---

## Priority order (recommended)

1. **Deploy** oldham + zillow address fixes (push already or pending).
2. **Configure** legal_notices Doppler URLs (30 min, no code).
3. **Configure** Browserbase for Zillow (if you want pre-foreclosure signals).
4. **Schedule dev** CourtNet 3 connector rewrite (biggest gap for probate/foreclosure).
5. **Scott** — low priority if GIS covers the county.

---

## How to verify any fix

```bash
# Scraper health
curl https://scraper-service-production-2f0e.up.railway.app/health

# Trigger one source (from machine with Doppler)
curl -X POST https://backend-production-7bd9.up.railway.app/api/foretrust/leads/scrape \
  -H "Content-Type: application/json" \
  -d '{"source_key":"oldham_pva"}'

# Watch runs
curl https://backend-production-7bd9.up.railway.app/api/foretrust/leads/runs?limit=5
```

Or use UI: **Scraper Runs** → **Trigger Run** → pick source → wait for **Found/New** columns.
