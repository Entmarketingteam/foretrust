# PRD/TDD: Foretrust eCCLIX High-Fidelity Automation

## 1. Objective
To build a low-latency, automated lead generation engine that identifies distressed residential properties in Central Kentucky (Scott, Bourbon, Woodford, Franklin) using eCCLIX legal filings, PVA structural data, and Zillow market signals. The goal is to surface "Off-Market" deals (Wholesale, Fix & Flip, Creative Finance, and FHA 203k) before they hit the MLS or are aggregated by large-scale wholesalers.

## 2. Product Requirements (PRD)

### R1: Multi-Signal Sourcing (Legal Distress)
*   **Instrument Scrape:** Daily monitoring of `WILL` (Probate), `DEED` (Estate transfers), `LP` (Lis Pendens/Foreclosure), `AOD` (Affidavit of Descent), and `DJ` (Default Judgments).
*   **Tax Scrape:** Daily monitoring of the "Delinquent Tax" portal for active balances > $500.
*   **Security Scrape:** Monitoring for City/County "Nuisance Liens" (mowing, boarding, trash) as a proxy for physical abandonment.

### R2: Physical Asset Enrichment (PVA/qPublic)
*   **Structural Data:** Automatic mapping of names/legal descriptions to Physical Address, Year Built, SQFT, and Parcel Map IDs.
*   **Equity Estimation:** Calculating "Equity Maturity" based on the last sale date and purchase price vs current assessed value.

### R3: Market Demand Check (Zillow/MLS)
*   **Off-Market Verification:** Automated check to see if the property is currently listed.
*   **Price Ceiling:** Calculating neighborhood price-per-sqft to determine After Repair Value (ARV).

### R5: Creative Finance & SubTo Logic (The "Pace Morby" Layer)
*   **SubTo Identification:** Automatically flag properties purchased/refinanced between **Jan 2020 and Dec 2021**. These assets likely carry 2.5% - 3.5% interest rates, making them primary candidates for "Subject-To" deed transfers.
*   **Hybrid/Wrap Search:** Scan `DEED` and `MTG` (Mortgage) filings for keywords like "Assumption," "Owner Finance," "Land Contract," or "Wrap." 
*   **Stale Listing Overlay:** Cross-reference eCCLIX leads with Zillow "Days on Market" (DOM > 90 days). A stale listing + a legal distress signal (LP or Tax Lien) = Maximum negotiation leverage for Creative Finance.
*   **Low-Equity Trigger:** Identify properties where `Assessed Value - Last Sale Price < 10%`. These owners cannot sell via agents (equity is too low to cover 6% commission), forcing them into a SubTo or Creative Finance exit to avoid foreclosure.

---

## 3. Technical Design (TDD)

### Architecture
1.  **Ingestion Node:** Playwright/Python service navigating `www.ecclix.com`.
2.  **Normalization Layer:** Extracts raw table data into a structured Pydantic model (`Lead`).
3.  **Enrichment Pipeline:**
    *   `KCOJ` -> Court case details.
    *   `PVA` -> Physical attributes.
    *   `Zillow` -> Listing status.
4.  **Scoring Engine:** Composite scoring logic (0-100) based on weighted signals.
5.  **Storage:** Supabase (`ft_leads` table) with deduplication on `instrument_number`.

### Implementation Logic (Scoring)
```python
def score_lead(lead: Lead):
    score = 0
    # Legal Distress
    if lead.lead_type == LeadType.FORECLOSURE: score += 30
    if lead.lead_type == LeadType.TAX_LIEN: score += 20
    
    # Equity Maturity (Simplified)
    years_owned = datetime.now().year - lead.last_sale_year
    if years_owned > 10: score += 25
    
    # 203k Potential
    if lead.year_built < 1995 and lead.jurisdiction in PREMIUM_ZONES:
        score += 20
        
    return score
```

### Deployment
*   **Host:** Railway.app (Scraper Service).
*   **Triggers:** HTTP POST `/run/ecclix_batch` with date ranges.
*   **Secrets:** Doppler for eCCLIX and Supabase credentials.
