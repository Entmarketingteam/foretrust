# KY Distressed Lead Map — Scott, Bourbon, Franklin, Woodford

**Goal:** Desk-based distressed sourcing — wholesale, fix-and-flip, creative finance (subject-to), and FHA 203k primary residence — without driving for dollars.

**Foretrust implements:** Layer 1 (eCCLIX + free sources) → Layer 2 (PVA/qPublic) → Layer 3 (Zillow enrichment) → **Investment scoring** (`investment_scorer.py`).

---

## Three data layers (matching key = owner name or Map ID / parcel)

```
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 1 — MOTIVATION (why they might sell)                      │
│ eCCLIX: LP, tax delinquent, liens, estate deeds                 │
│ Free: legal notices, KCOJ CourtNet, ky_delinquent_tax (PVA)     │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 2 — ASSET (what the property is)                          │
│ PVA: address, sqft, year built, sale history, assessed value    │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│ LAYER 3 — MARKET (what it's worth after repair)                 │
│ Zillow: DOM, keywords (as-is/TLC), neighborhood $/sqft          │
└────────────────────────────┬────────────────────────────────────┘
                             ▼
              investment_scorer → wholesale | creative | 203k
```

---

## County infrastructure (your four counties)

| County | Clerk / legal records | PVA (property) | Foretrust connector |
|--------|----------------------|----------------|---------------------|
| **Scott** | eCCLIX Central | [qPublic Scott](https://qpublic.schneidercorp.com/Application.aspx?AppID=948) | `ecclix_batch`, `scott_pva` |
| **Bourbon** | eCCLIX Central | PVAExpress / county PVA | `ecclix_batch`, extend PVA |
| **Woodford** | eCCLIX Central | qPublic Woodford | `ecclix_batch`, `woodford_pva` |
| **Franklin** | eCCLIX Central | PVAExpress | `ecclix_batch`, add `franklin_pva` |

Franklin/Woodford may also have non-eCCLIX clerk indexes — eCCLIX is the priority while your day pass is active.

---

## eCCLIX: which dropdown for what (do NOT mix them up)

| Nav menu | Use for | Skip when |
|----------|---------|-----------|
| **Delinquent Tax → Index Search** | Unpaid tax bills (bold rows = still owed). Sort **Amount Due** descending; ignore $20–50 fragments. | You only want foreclosure filings |
| **Instruments → Index Search** | LP (lis pendens), DEED (estate), MTG, tax liens (TLIEN/GLIEN), JLIEN | You only want tax bills |
| **Instruments → Combination Party Search** | Owner name from notices → all filings on that name | Bulk date-range discovery |
| **Securities → Index Search** | City nuisance liens, code enforcement, judgment liens on property | Standard deed/mortgage only |

**You do not need Securities for a basic LP sweep.** Use Securities when stacking signals (tax delinquent + city lien = vacant/distressed).

---

## Day-pass extraction sprint (24-hour eCCLIX)

Run in this order; copy or let Foretrust scrape each result set.

### A. Delinquent Tax (Scott first)

1. **Delinquent Tax → Index Search**
2. **Tax Year:** prior completed year (e.g. `2025`)
3. Leave Owner / Bill # / Address **blank**
4. **Search** → sort **Amount Due** high → low
5. **Bold rows** = open balance; click **Bill #** for payoff detail
6. Capture: Owner, Map ID, Property Address, Amount Due

**Filter:** Amount Due ≥ **$500** and street number in address (e.g. `173 Gray Wolf Path`, not bare `Barkley Rd`).

### B. Instruments — Lis Pendens (hottest pre-MLS)

1. **Instruments → Index Search**
2. **Type:** `LP` | Book/Page blank
3. **Between Dates:** `01/01/2026` – today (or last 60 days for freshest)
4. **Search** → summary table → **click blue `LP` or count** (e.g. 89)
5. Detail grid: Party1 (owner), Party2 (bank/tax buyer), Description, BK/PG, date

**Wholesale targets:** `LOT` + subdivision + bank (PennyMac, Lakeview, Truist) = SFR with mortgage distress.

**Super-distressed:** Party2 = `ORCHARD TAX LIEN SERVICES`, `EAST COAST TAX AUCTION` = tax-lien foreclosure stack.

### C. Instruments — historical LP (exhausted owners)

- Same as B, dates **`01/01/2024` – `12/31/2025`**
- Owners fighting foreclosure 12+ months → more motivated than 2-week filings

### D. Instruments — other types (one search each)

| Type | Signal |
|------|--------|
| `JLIEN` | Judgment lien — non-mortgage debt pressure |
| `TLIEN` / `GLIEN` | Tax liens on record |
| `DEED` | Party search: `ESTATE`, `EXECUTOR`, `HEIRS` (probate) |
| `WILL` | Estate planning / death |

### E. Securities — physical neglect

1. **Securities → Index Search**
2. Type `LIEN` or `GLIEN`; Party1 contains `CITY OF GEORGETOWN` or `SCOTT COUNTY`
3. Nuisance / abatement = likely vacant or code-violated

### F. Cross-check winner (Raney pattern)

1. LP on eCCLIX → owner + legal description
2. PVA qPublic by **owner name** → `123 Olympia Way`, parcel `189-20-030`, $525k assessed, 2003 brick SFR
3. Zillow/Street View → condition, no active MLS
4. `investment_scorer` → category scores in `raw_payload.investment_scores`

---

## PVA enrichment (free after eCCLIX expires)

| Field | Use in scoring |
|-------|----------------|
| Parcel / Map ID | Join to tax delinquent list |
| Location Address | Skiptrace / mail |
| Year Built | 203k (+ if &lt; 1990) |
| Living Sqft + basement | ARV sizing |
| Most Recent Sale Date/Price | Equity cushion |
| Assessment total | Offer ceiling |

**Scott qPublic:** `AppID=948` — search by owner name from LP Party1.

---

## Zillow / market layer

- Off-market + active LP = top wholesale priority
- MLS with "as-is", "TLC", "handyman", "estate" + DOM &gt; 60 days
- Compare assessed value to neighborhood $/sqft (Zillow public connector when addresses exist)

---

## Investment scoring (automated in Foretrust)

Stored on each lead as `raw_payload.investment_scores`:

| Score | Strategy | High score profile |
|-------|----------|-------------------|
| **wholesale_score** | Cash / assignment / flip to buyer | Equity &gt; 35%, owned 10+ yrs, LP + city lien, year built &lt; 1990 |
| **creative_score** | Subject-to / wrap / reinstate mortgage | Bought 2020–2022, high value, **low** equity cushion, active LP, bank servicer |
| **fha_203k_score** | Personal primary + renovation loan | Built &lt; 1990, long ownership, estate deed, premium subdivision, equity room for rehab budget |

**Example — 123 Olympia Way (Raney):**

| Score | ~Value | Why |
|-------|--------|-----|
| wholesale | Low | Bought 2022 @ $500k; little equity after commission |
| creative | **High** | Truist LP + 2022 loan + premium neighborhood |
| fha_203k | Low | Too new, too little equity for wrapped construction |

---

## Foretrust API — day pass

```bash
# Full sprint: LP drill-down + delinquent tax + priority instrument types
doppler run --project foretrust-scraper --config dev -- \
  curl -X POST "$SCRAPER_SERVICE_URL/pipeline/ecclix" \
  -H "Authorization: Bearer $SCRAPER_SHARED_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "day_pass_sprint",
    "counties": ["scott","bourbon"],
    "days_back": 60,
    "max_documents_per_county": 15,
    "download_documents": false
  }'

# LP only (fastest high-signal pull)
doppler run --project foretrust-scraper --config dev -- \
  curl -X POST "$SCRAPER_SERVICE_URL/pipeline/ecclix" \
  -H "Authorization: Bearer $SCRAPER_SHARED_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"mode":"lp_recent","counties":["scott"],"days_back":60}'
```

Then run **Pre-MLS Pipeline** or county PVA to enrich names → addresses.

---

## Signal → lead type → outreach

| Signal | `lead_type` | First touch |
|--------|-------------|-------------|
| LP + bank | `pre_foreclosure` | Direct mail / SMS to owner |
| Tax delinquent bold | `tax_lien` | Tax sale research + owner contact |
| Estate / WILL | `probate` / `estate` | Heir outreach |
| City lien (Securities) | `code_violation` | Drive-by optional; mail anyway |
| Stacked LP + tax + lien | highest `hot_score` | Same-day call list |

---

## What stays manual (for now)

- Short sale packet to bank (Strategy 1 for Raney-type)
- Tax sale registration with county clerk (August window)
- FHA 203k contractor bids and lender
- Skiptrace (export CSV → BatchData / Direct Skip) — webhook TBD

---

## Related docs

- `docs/ECCLIX-COUNTY-TYPES.md` — per-county instrument codes
- `docs/ECCLIX-WHOLESALE.md` — connector runbook
- `docs/PRE-MLS-PIPELINE.md` — full Foretrust pipeline
- `scraper-service/app/pipeline/investment_scorer.py` — scoring implementation
