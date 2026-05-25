# Google Alerts RSS — Pre-MLS Legal Notice Setup

Configure Google Alerts so the `legal_notices` scraper can poll RSS feeds for probate, foreclosure, and estate signals in Central Kentucky **before** MLS.

**Doppler project:** `foretrust-scraper`  
**Config:** `prd` (production scraper on Railway)

---

## Prerequisites

- Google account (same one you use for Foretrust ops)
- [Doppler CLI](https://docs.doppler.com/docs/install-cli) logged in: `doppler login`
- `foretrust-scraper` linked: `cd scraper-service && doppler setup` (or run commands with `--project foretrust-scraper --config prd`)

---

## Step 1 — Create each alert (repeat 10 times)

Use the exact query strings in [`config/google-alerts-queries.txt`](../config/google-alerts-queries.txt) (one alert per line).

1. Open [Google Alerts](https://www.google.com/alerts).
2. Paste **one** query from the file into the search box.
3. Click **Show options** and set:
   - **How often:** As-it-happens (or At most once a day if volume is high)
   - **Sources:** Automatic (or News + Blogs)
   - **Language:** English
   - **Region:** United States
   - **How many:** All results
   - **Deliver to:** Your email (required to create the alert)
4. Click **Create Alert**.

Repeat until all 10 alerts exist.

| # | Query string |
|---|----------------|
| 1 | `"estate of" Fayette County Kentucky` |
| 2 | `"estate of" Scott County Kentucky` |
| 3 | `"probate" Lexington Kentucky` |
| 4 | `"master commissioner" Fayette County Kentucky` |
| 5 | `"master commissioner" Scott County Kentucky` |
| 6 | `"foreclosure" Lexington Kentucky` |
| 7 | `"notice of trustee sale" Central Kentucky` |
| 8 | `"letters testamentary" Scott County Kentucky` |
| 9 | `"commissioner's sale" Clark County Kentucky` |
| 10 | `"lis pendens" Fayette County Kentucky` |

**Counties covered:** Fayette (Lexington), Scott (Georgetown), Clark (Winchester), plus statewide phrases that surface Madison, Woodford, Jessamine, and Oldham hits.

---

## Step 2 — Enable RSS on each alert

Google does not expose RSS in the main Alerts UI for every account. Use the RSS link pattern:

1. After creating an alert, open your [Alerts manage page](https://www.google.com/alerts#).
2. For each alert, use **Edit** (pencil) and confirm settings, then use the RSS icon if shown, **or**
3. Build the feed URL from the alert ID (inspect the alert’s “feed” link in browser dev tools), **or**
4. Use a third-party helper: search `google alerts rss feed url` and follow Google’s current RSS documentation.

**What you need:** One HTTPS RSS URL **per** alert (10 URLs total).

Typical feed format (may vary):

```text
https://www.google.com/alerts/feeds/XXXXXXXX/YYYYYYYY
```

Copy each feed URL to a local notes file (do not commit URLs to git).

---

## Step 3 — Paste RSS URLs into Doppler

Comma-separate all feed URLs (no spaces after commas, or trim in scraper):

```bash
doppler secrets set GOOGLE_ALERTS_RSS_URLS="https://www.google.com/alerts/feeds/...,https://www.google.com/alerts/feeds/..." \
  --project foretrust-scraper --config prd
```

Verify:

```bash
doppler secrets get GOOGLE_ALERTS_RSS_URLS --project foretrust-scraper --config prd --plain | tr ',' '\n' | wc -l
# Expect: 10
```

Redeploy or restart `scraper-service` on Railway so the new secret loads.

---

## Step 4 — Newspaper URLs (automated by setup script)

Herald Leader and News-Graphic legal notices are published through the **Kentucky Press Association** public notice site, not standalone `/legal-notices` pages on kentucky.com or news-graphic.com.

The setup script sets `LEGAL_NOTICE_NEWSPAPER_URLS` to county-filtered KPA search pages plus the statewide index. See [`scripts/setup-pre-mls.sh`](../scripts/setup-pre-mls.sh).

Optional manual add (classifieds hub — thinner signal):

```bash
doppler secrets set LEGAL_NOTICE_NEWSPAPER_URLS="existing-urls,https://www.kentucky.com/classifieds/" \
  --project foretrust-scraper --config prd
```

---

## Step 5 — KCOJ guest credentials (manual)

Court filings need a **guest** KYeCourts account:

1. Register at [KYeCourts](https://kcoj.kycourts.net/kyecourts/Login) (guest / public records).
2. Store credentials in Doppler (never in repo files):

```bash
doppler secrets set KCOJ_USERNAME="your_guest_email" \
  --project foretrust-scraper --config prd

doppler secrets set KCOJ_PASSWORD="your_guest_password" \
  --project foretrust-scraper --config prd
```

3. Confirm CAPTCHA budget: `TWOCAPTCHA_API_KEY` must exist (setup script checks this).

---

## Step 6 — Verify in Foretrust UI

1. Railway: confirm `scraper-service` deployed after secret changes.
2. Foretrust UI → **Full Pipeline** or trigger **legal_notices** alone.
3. **Scraper Runs** → `legal_notices` should show `found > 0` once RSS and newspaper URLs are live.

---

## Quick setup command

```bash
bash scripts/setup-pre-mls.sh
```

That script sets newspaper URLs, verifies `TWOCAPTCHA_API_KEY`, prints the 10 alert queries, and reminds you to set `GOOGLE_ALERTS_RSS_URLS` and KCOJ secrets manually.

---

## Related

- [`docs/PRE-MLS-PIPELINE.md`](PRE-MLS-PIPELINE.md) — full signal timeline
- [`docs/SCRAPER-FIXES.md`](SCRAPER-FIXES.md) — `legal_notices` troubleshooting
- `scraper-service/app/connectors/residential/legal_notices.py` — RSS + newspaper scrape logic
