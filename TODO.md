# Foretrust & LTK Sourcing — Master TODO List

This file tracks completed achievements and outstanding next steps for the real estate and creator pipelines.

---

## ✅ Completed Milestones (Today's YOLO Run)

### **1. Foretrust Sourcing & UI**
*   **Port 3000 Exposure:** Modified `app.ts` to serve the static public assets. The dashboard is now 100% active and accessible at `http://localhost:3000`.
*   **KCOJ CourtNet 2.0 Rebuild:** Solved the circular import crash in `notice_parse.py` and rebuilt `kcoj_courtnet.py` to bypass Select2/radio button hidden elements via direct JavaScript DOM injections. Test searches run to completion in under 15s.
*   **Google Alerts Probate Scraper:** Implemented `app/pipeline/agentic/google_alerts_agent.py` to crawl Google Search for early-stage estate/obituary notices.
*   **FOIA Water Ingestor:** Created `scripts/import-water-shutoffs.py` to parse and ingest municipal utility termination CSVs.
*   **Realtor.com Fallback Scraper:** Implemented `realtor_public.py` to bypass county PVA Cloudflare blocks.

### **2. Creator Monetization (`ltk-mcp`)**
*   **New Private Repository:** Initialized and pushed `/Users/ethanatchley/ltk-mcp` to a brand-new private GitHub repo (`Entmarketingteam/ltk-mcp`).
*   **Real LTK Parser:** Created `parse_ltk_real.py` specifically configured for native LTK CSV exports.
*   **Nicki Entenmann 2025 Campaign Report:** Extracted her actual 2025 data, stashed FWTFL coaching data to `/Desktop/FWTFL_BackOffice_Data`, and generated her real-world LTK report showing **$10,927.39 net commission** across 3,735 orders.

---

## 📋 Outstanding Next Steps (Resuming Later)

### **1. Sourcing Execution (Requires Pass Renewal)**
- [ ] **Renew eCCLIX Day-Pass:** Purchase day access in the browser at `ecclix.com`.
- [ ] **Rerun Urgent Harvest:** Execute `nohup bash scripts/run-ecclix-urgent.sh &` to sweep Scott and Woodford counties now that selectors are fully fixed.
- [ ] **Run Water Ingestor:** Place your municipal water shutoff CSV in `exports/` and run `scripts/import-water-shutoffs.py` to overlay vacancy signals on your 1,700 leads.

### **2. Scraper Optimizations**
- [ ] **Bypass Zillow WAF:** Update `wire_zillow.py` to utilize rotating residential proxies or add a `BROWSERBASE_API_KEY` to Doppler to bypass Akamai blocks.
- [ ] **Enable Google Alerts Agent:** Configure a daily cron-job to run `google_alerts_agent.py` and cross-reference obituaries with the database.

### **3. Creator Analytics (`ltk-mcp`)**
- [ ] **Add LTK Credentials:** Set `LTK_EMAIL` and `LTK_PASSWORD` in Doppler to enable automated CSV downloads via the MCP.
- [ ] **Roster Scaling:** Download and parse the remaining creator CSV exports to generate unified campaign briefs for Ethan & Emily.
