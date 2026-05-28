# 💰 Foretrust Monetization & Future Pass Strategy

## 1. Immediate Revenue (The Current 1,694 Leads)
You don't need to spend another dollar to start generating revenue. Your database already contains **257 High-Motivation Leads** (Tax Debt > $1k or Probate).

### Action Plan:
1.  **Download the Sheet:** Open `scraper-service/OUTREACH_TACTICAL_SHEET.csv`.
2.  **Filter by "HOT":** These are owners who owe more than $10,000 in property taxes. They are likely facing auction and need a cash buyout immediately.
3.  **Skip Trace:** Use the **Find Contact** button in the Dashboard [here](https://backend-production-7bd9.up.railway.app/) to get owner phone numbers.
4.  **Strategy:** 
    *   **High Equity:** Offer cash/wholesale.
    *   **Low Equity:** Offer SubTo (take over the debt).

---

## 2. Future eCCLIX Pass Protocol (Zero-Waste)
When you decide to purchase another day pass, follow this "War-Room" protocol to ensure maximum ROI.

### Hardened Infrastructure:
I have created a **"Day-Pass Executioner"** (`day_pass_executioner.py`) that is specifically designed to:
*   **Auto-Detect Access:** It checks if the pass is active before starting.
*   **State-Wide Sweep:** It rotates through all 120 KY counties, not just the core 4.
*   **Deep Harvest:** It prioritized **WILLS** and **LIS PENDENS** (LP) first, downloading the actual PDFs for your review.

### Pre-Pass Checklist:
1.  **Browser Verification:** Login at `ecclix.com` and ensure you can see search links.
2.  **Run the Executioner:**
    ```bash
    cd scraper-service
    doppler run --project foretrust-scraper --config prd -- python3 day_pass_executioner.py
    ```
3.  **Monitor the Log:** It will report "✅ [INST] sweep complete" for each county.

---

## 3. Built Data Models
The following datasets are now fully established and queryable:
*   **`ft_leads`:** The master record of all 1,694 properties.
*   **`REVENUE_MONEY_SHEET.csv`:** Ranked by profitability.
*   **`OUTREACH_TACTICAL_SHEET.csv`:** Ready for your cold-call or mailer campaign.

**Bottom Line:** Your system is now a revenue-generating asset that works with or without a live eCCLIX pass. Use the data you have to fund the next deep harvest.
