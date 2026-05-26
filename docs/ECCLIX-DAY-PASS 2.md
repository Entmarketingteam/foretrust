# eCCLIX 1-Day Pass — Foretrust Setup

**Wholesaler workflow:** See **[ECCLIX-WHOLESALE.md](./ECCLIX-WHOLESALE.md)** — discovery by date, PDF download, `ft_clerk_documents`.

Use your day pass to pull **deeds, wills, mortgages** from county clerk portals.

**Supported counties in code:** Scott, Clark, Madison, Bourbon, Woodford  
(Portals: `scottky.ecclix.com`, `clarkky.ecclix.com`, etc.)

---

## 1. Add credentials to Doppler

Use the **same username/password** you use to log into eCCLIX (any county portal).

```bash
doppler secrets set ECCLIX_USERNAME="your_ecclix_user" \
  ECCLIX_PASSWORD="your_ecclix_password" \
  ECCLIX_COUNTIES="scott,clark,madison,woodford" \
  ECCLIX_BATCH_THRESHOLD="40" \
  --project foretrust-scraper --config prd

# Mirror to dev for local runs
doppler secrets set ECCLIX_USERNAME="..." ECCLIX_PASSWORD="..." \
  ECCLIX_COUNTIES="scott,clark,madison,woodford" \
  --project foretrust-scraper --config dev
```

Redeploy **scraper-service** on Railway after setting secrets.

---

## 2. How to run (pick one)

### A) eCCLIX only (best for day pass)

Uses up to **40** property addresses from your hottest leads in Supabase.

**UI:** Run Scraper → **eCCLIX Day Pass**

**API:**

```bash
See **`docs/KY-DISTRESSED-LEAD-MAP.md`** for full search matrix (Delinquent Tax vs Instruments vs Securities) and scoring.

**Recommended day-pass run** (LP + tax delinquent + liens):

```bash
curl -X POST "$SCRAPER_SERVICE_URL/pipeline/ecclix" \
  -H "Authorization: Bearer $SCRAPER_SHARED_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode":"day_pass_sprint","counties":["scott","bourbon"],"limit":50,"download_documents":false}'
```

Legacy wholesale-only:

```bash
curl -X POST "$SCRAPER_SERVICE_URL/pipeline/ecclix" \
  -H "Authorization: Bearer $SCRAPER_SHARED_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"limit": 40}'
```

### B) Pre-MLS Pipeline (includes eCCLIX if creds set)

Runs notices → court/tax → GIS → PVA → **eCCLIX** → cross-ref.

**UI:** **Pre-MLS Pipeline** button on Leads page.

---

## 3. What to expect

| Input | Behavior |
|-------|----------|
| Leads with `property_address` in DB | Auto-queued for lookup |
| No addresses | Run **Full Pipeline** or **KY GIS** first to import parcels |
| Document types | WILL/PROBATE → `probate`; MORTGAGE → `foreclosure`; deeds → `estate` |

Check **Scraper Runs** → `ecclix_batch` → Found / New columns.

---

## 4. Day-pass tips

- **40 addresses × 5 counties** can burn the day fast — start with `limit: 20` if testing.
- Prioritize leads that already have names from **legal notices** or **KCOJ**.
- eCCLIX is **enrichment**, not discovery — you need addresses first.
- Pass expires in 24h; no cron — **manual / Pre-MLS only**.

---

## 5. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `0 found`, status ok | Login selectors wrong — check Railway logs for `[ecclix] Login/session failed` |
| Skipped in Pre-MLS | `ECCLIX_USERNAME` / `PASSWORD` missing in Doppler |
| CAPTCHA on login | `TWOCAPTCHA_API_KEY` must be set in `foretrust-scraper` |
| Wrong county | Set `ECCLIX_COUNTIES` to counties you purchased access for |
