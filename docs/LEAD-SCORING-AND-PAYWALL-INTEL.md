# Lead scoring + eCCLIX paywall intel (24h playbook)

**Goal:** Anything behind the eCCLIX day pass that signals a possible sale — LP, deeds, wills, liens, divorce-related LP, party-linked instruments — with **PDFs on disk** and **scores you can tune over time**.

---

## Two scoring layers (both tunable)

Foretrust uses **two independent scores**. They answer different questions:

| Score | File | Question it answers | Used for |
|-------|------|---------------------|----------|
| **`hot_score`** (0–100) | `app/pipeline/distress_scorer.py` | How urgent is this *signal*? | Supabase sort, digest email, party-search seed order |
| **Investment scores** (5× 0–100) | `app/pipeline/investment_scorer.py` | Which *buyer strategy* fits? | `build-best-deals.py` buckets, outreach track |

Human copy on exports comes from a third layer (not numeric):

| Output | File | Purpose |
|--------|------|---------|
| **`distress_reason`** | `app/pipeline/distress_reason.py` | One-line “why on the list” |
| **`next_action`** | same | Operator SOP (“PVA → LP check → call”) |

---

## 1. `hot_score` — distress urgency

**Edit:** `scraper-service/app/pipeline/distress_scorer.py`

### Base weights (`SIGNAL_WEIGHTS`)

| `LeadType` | Points |
|------------|--------|
| FORECLOSURE | 30 |
| DIVORCE | 25 |
| PROBATE / PRE_FORECLOSURE | 25 / 25 |
| TAX_LIEN | 20 |
| ESTATE | 20 |
| DEATH / VACANCY | 15 |
| CODE_VIOLATION / listings | 10 |

### Add-ons (same file, `compute_hot_score`)

- Filed **≤30 days**: +15  
- Filed **≤90 days**: +10  
- `estimated_value` > $500k: +10  
- `building_sqft` > 6000: +10  
- **Stacked signals** on same parcel/address: +15 per extra signal  
- Cap: **100**

### Stacking detection

`score_leads()` groups by `parcel_number` or `property_address`. Tax + LP + JLIEN on same parcel bumps `hot_score` automatically.

**To manipulate:** Change weights, recency windows, stacking bonus, or cap in `distress_scorer.py`. Re-run `build-best-deals.py` or re-import CSV — existing rows keep old scores until re-scored on ingest.

---

## 2. Investment scores — strategy fit

**Edit:** `scraper-service/app/pipeline/investment_scorer.py` → `score_from_lead_data()`

Five scores (each 0–100, clamped):

| Score | Investor / use case |
|-------|---------------------|
| `wholesale_score` | Cash assignment / quick flip |
| `creative_score` | Subject-to, low equity, recent loan |
| `fha_203k_score` | Owner-occupant renovation (old home + equity) |
| `short_sale_score` | Bank LP + human owner + low equity |
| `pre_mls_score` | Best owner-occupant deal before MLS (max of 203k/short sale + stacks) |

### Main inputs

- `instrument_type` / `lp_active` / `search_profile`
- `owner_name`, `grantor`, `grantee`, `legal_description`, `row_text`
- `amount_due` (tax), `assessed_value`, `last_sale_price`, `last_sale_year`, `year_built`, `sqft`
- Regex buckets: `BANK_SERVICERS`, `ESTATE_MARKERS`, `TAX_BUYER_FORECLOSERS`, `ENTITY_OWNER`, street address

### Example knobs you’ll change often

```python
# Tax thresholds (lines ~82–92)
if amount_due >= 2000 and human and has_street:
    fha_203k += 15
    pre_mls += 18

# LP + bank → short sale (lines ~157–162)
if lp_active and BANK_SERVICERS.search(parties) and human and has_street:
    short_sale += 35
```

**`best_strategy()`** picks primary label when a score crosses threshold (short_sale ≥72, fha_203k ≥75, creative ≥70, wholesale ≥65); else `"monitor"`.

### Deal buckets (export reports)

**Edit:** `app/pipeline/deal_package.py` → `rank_deals()`

| Bucket | Threshold today |
|--------|-----------------|
| `tax_delinquent_human` | human owner, due ≥ $1500, has address |
| `pre_mls_homebuyer` | `pre_mls_score` ≥ 55 |
| `short_sale` | `short_sale_score` ≥ 70 |
| `fha_203k` | `fha_203k_score` ≥ 60 |
| `creative_finance` | `creative_score` ≥ 70 |
| `wholesale` | `wholesale_score` ≥ 70 |
| `stacked_signals` | `lp_active` + tax due ≥ $500 |

---

## 3. Row filters — what gets saved / PDF downloaded

**Edit:** `app/connectors/residential/ecclix_row_filters.py`

Filters run **after** eCCLIX grid scrape, **before** Supabase upsert / PDF download.

| Tag | Effect |
|-----|--------|
| `human_owner_only` | Drop LLC/bank owners |
| `street_address` | Require street # or premium subdivision in legal |
| `min_tax_500` / `min_tax_2000` | Tax bill floor |
| `foreclosure_lp` | LP with foreclosure language |
| `bank_counterparty` | Major servicer in parties |
| `divorce_domestic` | Divorce / dissolution in text |
| `premium_subdivision` | Cherry Blossom, Ironworks, etc. (regex list) |
| `big_home_signal` | Lot/subdivision legal patterns |
| `estate_deed` | Executor / estate of |
| `city_lien` | Code / judgment language |
| `any_distress` | Broad pass (noisy) |

**Search profiles** attach tags: `app/connectors/residential/ecclix_search_profiles.py`

- `DEEP_PORTAL_SEARCH` — full day-pass instrument stack  
- `DAY_PASS_SPRINT` — lighter LP + tax + liens  
- Per-profile `download_if_pass: true` → PDF only when filters pass (saves time)

**To manipulate:** Add subdivision names to `PREMIUM_SUBDIVISIONS`, add tags to profiles, or change `download_if_pass` on a profile.

---

## 4. Paywall intel — what to run in the next 24 hours

**Rule:** One browser session at a time (`no_proxy: true`). Parallel county logins break county picker.

### Priority order (documents + freshest filings)

| Wave | Mode | What you get |
|------|------|----------------|
| **A** | `deep_portal_search` | LP (bank, divorce, premium), DEED estate, WILL, MTG, MLIEN, FLIEN, SLIEN, ENC, JLIEN, city securities — metadata + **PDF if `download_if_pass`** |
| **B** | `pre_mls_sprint` | Recent LP grid + **party search** on top tax owners (`min_tax_due: 1500`) — pulls linked DEED/MTG/LP on same name |
| **C** | `run-portal-intel.sh` stage 2 | KCOJ divorce / probate / civil (non-eCCLIX; needs CourtNet login) |
| **D** | Exports | Actionable lists + best-deals report |

### One-command sequential sprint (all 4 counties)

```bash
bash ~/Desktop/foretrust/scripts/run-24h-document-sprint.sh
```

Per county only:

```bash
bash ~/Desktop/foretrust/scripts/run-full-intel-county.sh scott
```

### API params (manual / Railway)

```json
{
  "mode": "deep_portal_search",
  "counties": ["bourbon"],
  "full_extract": true,
  "download_documents": true,
  "no_proxy": true,
  "max_pages": 100
}
```

Then:

```json
{
  "mode": "pre_mls_sprint",
  "counties": ["bourbon"],
  "download_documents": true,
  "days_back": 365,
  "max_documents_per_county": 40,
  "name_search_limit": 30,
  "min_tax_due": 1500,
  "no_proxy": true
}
```

### Where outputs land

| Artifact | Path |
|----------|------|
| PDFs | `scraper-service/exports/clerk-documents/` |
| Filtered portal leads | `scraper-service/exports/portal-intel/*-filtered-*.json` |
| Sprint CSV | `scraper-service/exports/ecclix-sprint/` |
| Operator lists | `scraper-service/exports/actionable-leads/properties-*.csv` |
| Strategy report | `scraper-service/exports/best-deals/best-deals-*.md` |
| DB | Supabase `ft_leads`, `ft_clerk_documents` |

### Instrument types behind paywall (eCCLIX Index Search)

| Code | Sale / distress signal |
|------|------------------------|
| **LP** | Lis pendens — foreclosure, divorce, lawsuit |
| **DEED** | Transfer — estate, quit claim, distress sale |
| **MTG** | New loan / refi — equity or over-leverage |
| **WILL** | Probate track |
| **MLIEN** | Mechanics — rehab stall |
| **JLIEN** | Judgment |
| **TLIEN / FLIEN / SLIEN** | Tax / federal / state liens |
| **ENC** | Encumbrance |
| **REL** | Release (trace prior LP) |
| **Securities LIEN** | City code liens (Georgetown / Versailles filters) |
| **Delinquent tax** | Unpaid bill list (already done for 4 counties) |

**Divorce papers** on eCCLIX usually appear as **LP** with domestic-relations language (`divorce_domestic` filter), not a separate “divorce” instrument type. Full divorce dockets → **KCOJ CourtNet** (`kcoj_courtnet` connector).

### Contact information

| Source | Contact fields |
|--------|----------------|
| Tax grid | Owner name, sometimes mailing address on bill |
| Instrument row | Grantor / grantee (banks vs humans) |
| Party search | All instruments for a human owner name |
| PVA (`--enrich-pva`) | Mailing address, sqft, assessed value (Scott / Woodford qPublic) |
| Skip trace | **Not automated** — export CSV → BatchSkip / PropStream |

Run after scrape:

```bash
doppler run --project foretrust-scraper --config dev -- \
  python3 scripts/export-property-lead-list.py --all-sources --jurisdiction Scott --human-only --min-due 500

doppler run --project foretrust-scraper --config dev -- env -u PLAYWRIGHT_BROWSERS_PATH \
  python3 scripts/build-best-deals.py --enrich-pva --pva-limit 40
```

---

## 5. Quick reference — files to edit when strategy changes

| You want to… | Edit |
|--------------|------|
| Rank urgency in DB | `distress_scorer.py` |
| Change wholesale vs 203k vs short sale | `investment_scorer.py` |
| Change export buckets | `deal_package.py` → `rank_deals()` |
| Change operator one-liners | `distress_reason.py` |
| Add instrument search | `ecclix_search_profiles.py` |
| Tighten who gets a PDF | `ecclix_row_filters.py` + profile `filter_tags` |
| Change subdivision targets | `PREMIUM_SUBDIVISIONS` in `ecclix_row_filters.py` |

---

## 6. Technical note (May 2026)

eCCLIX Central uses **`instrinq.aspx`** for Instrument Search (Type + Between Dates). Direct **`indexinq.aspx`** often returns ASP.NET `HttpException` — the scraper prefers `instrinq` and reuses the page after county select.

## 7. Do not burn day pass on

- Parallel county Playwright (session collision)
- Proxy without `no_proxy: true` locally
- `bourbonky.ecclix.com` subdomains (use `www.ecclix.com`)
- Old `exports/ecclix-sprint/*` from failed login runs
- PDF on every row without filters (`download_if_pass` or cap `max_documents_per_county`)

See also: `docs/ECCLIX-24H-RUN-QUEUE.md` · **REI deep playbook:** `docs/REI-CREATIVE-FINANCE-INTEL.md`
