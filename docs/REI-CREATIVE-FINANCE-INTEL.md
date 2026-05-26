# REI creative finance intelligence — 100× playbook (Central KY)

**Audience:** Operator thinking like a full-time acquirer — not “find tax delinquent,” but **find friction before the market prices it in**.

**Counties:** Scott, Bourbon, Woodford, Franklin (eCCLIX Central + KCOJ + PVA + city FOIA).

**Code map:**

| Layer | File |
|-------|------|
| Scenario detection + extended scores | `scraper-service/app/pipeline/creative_finance_signals.py` |
| Legacy + merged scores | `scraper-service/app/pipeline/investment_scorer.py` |
| Grid filters | `scraper-service/app/connectors/residential/ecclix_row_filters.py` |
| eCCLIX search jobs | `scraper-service/app/connectors/residential/ecclix_search_profiles.py` → `CREATIVE_REI_SEARCH` |
| Run mode | `ecclix_batch` → `"mode": "creative_rei_search"` |
| Export buckets | `scraper-service/app/pipeline/deal_package.py` |

```bash
# Full library: every scenario + historical windows + PDFs + party search (24h)
bash ~/Desktop/foretrust/scripts/run-scenario-library-24h.sh

# Or single county
doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH python3 - <<'PY'
import asyncio
from app.scheduler import run_connector_job
async def main():
    await run_connector_job("ecclix_batch", {
        "mode": "scenario_library",
        "counties": ["scott"],
        "full_extract": True,
        "download_documents": True,
        "max_pages": 120,
        "name_search_limit": 45,
        "no_proxy": True,
    })
asyncio.run(main())
PY

# Merge all runs into MASTER reference (good examples per scenario)
doppler run --project foretrust-scraper --config dev -- \
  python3 scripts/export-scenario-reference-library.py
```

**Outputs:**

| Path | Contents |
|------|----------|
| `exports/scenario-library/{county-date}/{scenario}/` | README (query + filters), `examples.csv`, `examples.json`, `pdfs/` |
| `exports/scenario-library/MASTER/` | Cross-run deduped index of every scenario |
| `exports/ecclix/{county}/` | Raw PDFs by book/page |

---

## 1. REI mental model — seven acquisition lanes

Every lead should answer: **which lane, which seller constraint, which exit.**

| Lane | Seller constraint | Your tool | Typical clerk signal |
|------|-------------------|-----------|----------------------|
| **Subject-to / rescue** | Can’t pay; loan current or delinquent | Take over payments, cure tax | LP + MTG + tax stack |
| **Seller finance / wrap** | Needs payment spread, not lump sum | Note or wrap | COD, LEASE, low-equity DEED |
| **Novation / mod failure** | Bank said no to mod | New buyer qualifies | MOD, REL after MOD |
| **Wholesale / assignment** | Contracted but trapped | ASSIGN chain | ASSIGN, double LLC DEED |
| **Probate / heir** | Death, multiple heirs | QDEED stack, buy heir out | WILL, estate DEED, POA |
| **Judicial / tax sale** | Clock running | Redemption, bid, deed | JLIEN, commissioner, TLIEN |
| **Operational distress** | Rehab, code, divorce | Discount + solve problem | MLIEN, city lien, domestic LP |

**Stacking rule (pro):** One signal = curiosity. **Three uncorrelated signals** = call today (tax + LP + MLIEN beats tax alone).

---

## 2. Creative finance scenarios (deep catalog)

Each row: **scenario key** (in `creative_scenarios[]`), **what happened**, **eCCLIX query**, **party search**, **score field**, **outreach angle**.

### A. Distressed debt & takeover

| Scenario | Trigger | eCCLIX instrument / search | Party search seeds | Score | Talk track |
|----------|---------|---------------------------|-------------------|-------|------------|
| `subto_foreclosure_rescue` | LP filed, MTG on title | LP 90d + MTG on same legal | Owner last name | `subto` | “Stop auction — we bring loan current, you walk clean.” |
| `stacked_tax_foreclosure` | Tax ≥$1.5k + LP | Tax list ∩ LP party search | Owner + spouse | `subto`, `tax_deed` | “Two fires — we solve both in one closing.” |
| `underwater_creative_takeover` | LP + low equity estimate | LP 120d, low cons DEED history | Owner | `subto`, `short_sale` | Short sale path or subto with lender outreach. |
| `loan_mod_distress` | MOD filed | MOD 730d | Grantor on MOD | `novation` | “Mod didn’t stick — we buy before re-default.” |
| `second_lien_overleveraged` | HELOC / 2nd language | MTG 48d + JLIEN | Owner | `wrap` | Pay off 2nd at discount; subto 1st. |
| `foreclosure_cancelled_rebound` | REL of LP | REL 180d filter `release_after_lp` | Same owner as prior LP | `novation` | “You thought it was over — still underwater?” |

### B. Seller psychology (non-bank)

| Scenario | Trigger | eCCLIX | Party search | Score | Talk track |
|----------|---------|--------|--------------|-------|------------|
| `divorce_forced_sale` | Domestic LP / QDRO text | LP 365d `divorce_domestic` | Both surnames | `seller_finance` | “Buyout spouse — one check, no listing.” |
| `free_clear_senior_tax_delinquent` | 25+ yrs owned, tax due | Tax human + no recent MTG | Owner | `seller_finance` | “Life estate / annuity — you stay, we pay tax.” |
| `recent_purchase_cash_flow_crunch` | Bought 2020+, tax pain | Tax + MTG same year | Owner | `wrap` | “Negative cash flow — assume or wrap exit.” |
| `quit_claim_heir_dump` | QDEED between heirs | DEED/QDEED 180d `nominal_consideration` | “Estate of …” | `probate_creative` | “One heir buys others out.” |
| `life_estate_remainder` | Life estate language | DEED + WILL | Executor | `probate_creative` | Remainder purchase / annuity. |
| `poa_fiduciary_sale` | POA / guardian | POA 730d | Principal + agent | `seller_finance` | Call **agent** first (legal authority). |

### C. Contract & terms plays

| Scenario | Trigger | eCCLIX | Score | Notes |
|----------|---------|--------|-------|-------|
| `contract_for_deed_default` | COD instrument | COD / installment deed | `seller_finance` | Vendee default → buy from vendor. |
| `lease_option_seller` | LEASE + option language | LEASE 365d | `lease_option` | Master lease, novation, or option $ |
| `wholesale_assignment_chain` | ASSIGN recorded | ASSIGN 365d | `wrap` | Trace last assignor; buy contract. |
| `nominal_deed_distress` | DEED cons &lt;$75k on premium lot | DEED `nominal_consideration` | `seller_finance` | Gift / distress / divorce dump — verify real value via PVA. |

### D. Operational / physical distress

| Scenario | Trigger | eCCLIX | Stack with | Score |
|----------|---------|--------|------------|-------|
| `rehab_stalled_mlien` | MLIEN on subdiv lot | MLIEN + party contractor | Tax delinquent | `wrap` |
| `code_enforcement_motivated` | City securities lien | Georgetown/Versailles LIEN | Water shutoff FOIA | `seller_finance` |
| `condo_foreclosure_arbitrage` | LP on condo legal | LP + `big_home_signal` | HOA special assmt (manual) | `subto` |
| `estate_farm_liquidation` | Horse farm legal + tax | Tax + DEED estate | PVA acreage | `seller_finance` |

### E. Clock-driven (highest urgency)

| Scenario | Trigger | Sources | Score |
|----------|---------|---------|-------|
| `judicial_sale_window` | Master commissioner / sheriff | LP + KCOJ civil | `judicial` |
| `tax_sale_redemption` | Tax buyer name on parties | Tax + TLIEN + enrollment log | `tax_deed` |
| `bankruptcy_asset_sale` | Ch. 7/13 in LP text | LP + KCOJ | `judicial` |

---

## 3. Filter tag catalog (implement / tune)

Add to profiles in `ecclix_search_profiles.py` via `filter_tags=(...)`.

| Tag | Keeps when | REI use |
|-----|------------|---------|
| `human_owner_only` | Not LLC/bank | Skip institutional noise |
| `subto_candidate` | LP + (bank or tax≥500) | Subject-to list |
| `seller_finance_deed` | DEED/QDEED/COD | Owner-carry opportunities |
| `lease_option_signal` | LEASE / rent-to-own text | Lease-option buyers |
| `assignment_wholesale` | ASSIGN | Wholesaler chain |
| `loan_mod_signal` | MOD | Failed mod pipeline |
| `release_after_lp` | REL + release language | “False relief” sellers |
| `poa_guardian` | POA/GUARD | Fiduciary sales |
| `rehab_mlien` | MLIEN / contractor | Stalled flip/takeover |
| `second_lien` | HELOC / 2nd | Over-leverage |
| `judicial_sale` | Sheriff / commissioner | Auction calendar |
| `nominal_consideration` | cons &lt; $75k | Heir/divorce dumps |
| `life_estate` | Life estate / TOD | Probate creative |
| `divorce_qdro` | Divorce/QDRO | Forced sale |
| `ucc_fixture` | UCC/FF | Business distress (rare SFR) |
| `absentee_owner` | Out-of-state / PO Box | Mailing → skip trace |
| `premium_subdivision` | Named subdiv | Retail flip / 203k |
| `big_home_signal` | Large legal / high cons | Higher ARV plays |

**Combine tags** for precision: e.g. `("subto_candidate", "human_owner_only", "premium_subdivision")` = luxury subto rescue.

---

## 4. eCCLIX query matrix (what a REI would click)

### Instrument searches (`instrinq.aspx` — Between Dates)

| Priority | Type | Days back | Filter tags | Why |
|----------|------|-----------|-------------|-----|
| P0 | LP | 90 | `subto_candidate`, `human_owner_only` | Pre-foreclosure |
| P0 | REL | 180 | `release_after_lp` | Cancelled sale → soft motivation |
| P1 | DEED | 120 | `nominal_consideration`, `estate_deed` | Heir / divorce dumps |
| P1 | ASSIGN | 365 | `assignment_wholesale` | Contract flippers |
| P1 | MOD | 730 | `loan_mod_signal` | Failed mods |
| P2 | LEASE | 365 | `lease_option_signal` | Terms sellers |
| P2 | POA | 730 | `poa_guardian` | Fiduciary |
| P2 | MLIEN | 365 | `rehab_mlien` | Stalled rehab |
| P2 | MTG | 48 | `second_lien` | Recent leverage events |
| P3 | JLIEN | 365 | `judicial_sale` | Judgments → sale |
| P3 | QDEED | 180 | `seller_finance_deed` | (if in county dropdown) |
| P3 | COD | 730 | `seller_finance_deed` | Contract for deed |

**Profile bundle:** `CREATIVE_REI_SEARCH` in code (run after tax + core LP).

### Combination party search (names)

Run on **Tier A tax owners** (human, due ≥ $1,500) — pulls instruments missing from date-range search.

| Seed type | Example query | Looking for |
|-----------|---------------|-------------|
| Tax owner | `SMITH, JOHN` | Hidden LP, MTG, QDEED |
| Heir stack | `ESTATE OF MARY SMITH` | WILL, DEED, POA |
| Spouse split | `SMITH, JANE` + `SMITH, JOHN` | Divorce LP both sides |
| LLC flip exit | `BLUEGRASS HOMES LLC` | ASSIGN out, tired landlord |
| Bank (reverse) | `PENNYMAC` as grantee | REO adjacent owners (neighbors) |

**Pro move:** Party search **grantee bank** on recent LP → find other LPs same servicer (portfolio distress).

### Delinquent tax (already run)

REI overlays on tax grid:

| Overlay | Filter logic |
|---------|--------------|
| **Free & clear senior** | High tax, no MTG in 15 yrs (party search) |
| **Absentee** | Mailing ≠ property county |
| **Fragment vs real** | Due &lt;$100 → skip unless stack |
| **Landlord LLC** | LLC + single-family address → buy LLC or deed |

---

## 5. Cross-source stacks (go 100× deeper than clerk)

| Stack | Sources | Synthetic signal |
|-------|---------|------------------|
| **Death → sale** | WILL + tax delinquent + obit (manual/RSS) | Probate wholesale |
| **Divorce → sale** | KCOJ domestic + LP + tax | Forced equity |
| **Rehab fail** | MLIEN + code lien + tax | Wholetail |
| **Auction runway** | LP + judicial + tax | 30-day action list |
| **Mod fail** | MOD + REL + new LP | Re-default pipeline |
| **Water off** | Georgetown FOIA + tax + no MTG | Vacancy |
| **Flipper exit** | LLC DEED in + ASSIGN out + tax | Discount buy |
| **Senior tax** | Tax + 30yr ownership + no LP | Seller finance / annuity |

**Supabase rule:** Same `parcel_number` or normalized address → increment `stacked_signals` in `distress_scorer.py` (+15 hot_score per extra).

---

## 6. Extended strategy scores (new knobs)

Returned inside `investment_scores` on each lead:

| Score | Meaning | Threshold in `deal_package` |
|-------|---------|----------------------------|
| `subto` | Subject-to / rescue | Bucket `subject_to` ≥ 65 |
| `seller_finance` | Carry / CFD / annuity | `seller_financing` ≥ 65 |
| `wrap` | Wrap / assignment / recent buy | `creative_finance` |
| `novation` | Mod / REL / lender path | — |
| `lease_option` | Lease-option | `lease_option` ≥ 60 |
| `tax_deed` | Tax sale / redemption | `judicial_tax_sale` |
| `probate_creative` | Heir / life estate | `probate_creative` |
| `judicial` | Sheriff / commissioner | `judicial_tax_sale` |

**Arrays:** `creative_scenarios` — all matched keys.  
**Label:** `primary_creative_play` — top play for CRM.

**Tune weights:** `creative_finance_signals.py` → `boosts` dict.

---

## 7. Queries outside eCCLIX (REI wouldn’t stop at clerk)

| Source | Query / filter | Creative angle |
|--------|----------------|----------------|
| **KCOJ CourtNet** | Domestic + probate + civil | Divorce, heir disputes |
| **PVA qPublic** | Owner search + map | Sqft mismatch → addition / unpermitted |
| **Georgetown water FOIA** | Shutoff list | Vacancy + code |
| **Legal notices RSS** | “estate”, “trustee sale”, “partition” | Pre-MLS |
| **USPS vacancy** (optional) | No mail pickup | Stack with tax |
| **Code enforcement** | Securities party = city | Lien subordination deal |
| **MLS** (manual) | Failed listing 90d | “Couldn't sell” + tax |

---

## 8. False positives (save your day pass)

| Looks good | Actually noise | Filter |
|------------|----------------|--------|
| LP on land only | No house | `street_address` or `premium_subdivision` |
| Bank vs bank LP | REO shuffle | Require `human_owner_only` |
| $10 tax bill | Junk split | `min_tax_500` |
| New MTG 2024 | Not distress — healthy refi | Pair with tax/LP |
| LLC → LLC DEED | Holding company | `assignment_wholesale` only if human downstream |
| REL batch | Bulk release | Match same book/page as prior LP |
| Nominal DEED | Gift to family OK | Add PVA value check |

---

## 9. 24-hour run order (REI-optimized)

1. **Tax human** (done) — seed party list  
2. **`deep_portal_search`** — LP / estate / liens  
3. **`creative_rei_search`** — REL, ASSIGN, MOD, LEASE, POA, subto LP  
4. **`pre_mls_sprint`** — PDFs + party on tax ≥ $1,500  
5. **KCOJ** — domestic + probate  
6. **`build-best-deals.py`** — read new buckets  
7. **Stack pass** — SQL/ script: group by parcel, count signal types  

One browser session at a time. `no_proxy: true`.

---

## 10. Operator worksheets

### Daily call list (generate from export)

Sort by: `hot_score` DESC, then `subto` DESC, then `amount_due` DESC.

| Tier | Rule |
|------|------|
| **A** | ≥3 scenarios OR `subto`≥75 OR tax≥$3k + LP |
| **B** | 2 scenarios OR any creative score≥65 |
| **C** | Single signal — nurture |

### One-page diligence per lead

1. Read PDF (LP / DEED) — who is plaintiff?  
2. PVA — beds, sqft, last sale, assessed  
3. Party search — other instruments 5 yr  
4. Tax — years owed, buyer on bill?  
5. Pick play from `primary_creative_play`  
6. Offer structure (see scenario table)

---

## 11. Offer structures by scenario (cheat sheet)

| Scenario | Structure |
|----------|-----------|
| `subto_foreclosure_rescue` | Subto + arrears in → deed out after 6-mo perf |
| `stacked_tax_foreclosure` | Pay tax → option → deed |
| `seller_finance` / senior | Low down, 0% 10yr, balloon |
| `lease_option` | 3yr lease, 20% rent credit, option strike = ARV×0.85 |
| `quit_claim_heir_dump` | Batch QDEED from 3 heirs, one cash to others |
| `divorce_forced_sale` | Buy from awarded party, hold until quit claim recorded |
| `rehab_stalled_mlien` | Pay MLIEN $0.50/$1, acquire as-is wholesale |
| `tax_sale_redemption` | Redemption assignment fee 50% spread |

---

## 12. What to build next (engineering backlog)

- [ ] Parcel-level stack job (merge tax + clerk by map ID)  
- [ ] Auto party-search queue from Tier A tax CSV  
- [ ] KCOJ → same `creative_scenarios` classifier  
- [ ] Absentee: parse PVA mailing vs situs  
- [ ] Consideration parser from DEED grid (fix cons extraction)  
- [ ] Export column: `scenario_outreach_hint` from `scenario_outreach_hint()`  
- [ ] Bourbon `MAR` / `MISC` profiles (county-specific instruments)  

---

## 13. Related docs

- `docs/LEAD-SCORING-AND-PAYWALL-INTEL.md` — hot_score + paywall runbook  
- `docs/ECCLIX-24H-RUN-QUEUE.md` — wave order  

**Remember:** Wholesalers hunt **one signal**. You hunt **friction stacks** with a **terms-based exit** — that's the 100× difference.
