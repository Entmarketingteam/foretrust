# Beat the Wholesaler — Pre-MLS vs. Real Fire–Style Shops

**The race:** Public record hits → someone calls the owner → contract/assignment → end buyer.  
**Your edge:** Show up **earlier**, with **more context**, on deals they **cannot buy** the same way.

---

## How they win (and where they're slow)

| Their move | Why it works | Where you pass them |
|------------|--------------|---------------------|
| Daily LP scrape + blast | Lis pendens = obvious distress | You're already on **tax delinquent** weeks/months before LP |
| "We buy houses cash" | Simple, high volume | You offer **short sale path**, **203k take-over**, or **creative** when equity is thin |
| VA / dialer on legal description | Cheap labor | You resolve **physical address same day** (PVA) — they mail wrong lot |
| Assignment to flipper list | Fast exit | You **occupy or finance** — no assignment fee war |
| County-wide thin coverage | Scale | You **own 4 counties deep** (Scott/Bourbon/Woodford/Franklin) with stacked filters |

They are optimized for **volume wholesaling**. You are optimized for **timing + deal structure**.

---

## The investor stack (only call when you have leverage)

**Tier S — Call today (you are ahead of the wholesaler)**  
All required:

1. **Human owner** (not LLC, bank, or tax-buyer entity)
2. **Street address or premium subdivision** (Cherry Blossom, Ironworks, Canewood, etc.)
3. **Two+ motivation layers**, e.g.:
   - Tax delinquent ≥ $2,000 **and** LP filed, or
   - Tax delinquent ≥ $1,500 **and** estate deed/WILL in last 12 months, or
   - LP + bank servicer **and** bought 2020–2023 (low equity — they want assignment; you want short sale / creative)

**Tier A — Call this week (record just hit)**  
- LP in last **14 days** + subdivision lot + human owner  
- Probate / domestic case opened (KCOJ) + PVA shows $400k+ assessed SFR  

**Tier B — Nurture (you are early; they may not see it yet)**  
- Tax only, ≥ $3k, no LP — **this is your head start**  
- Mechanic's lien or city securities lien + owner-occupied signal  

**Ignore (they live here; you'll lose a bidding war)**  
- Orchard Tax, East Coast Tax, Lien Works as party (tax lien investor beat you to it)  
- Farmers Bank / portfolio LLC delinquent (commercial)  
- Raw acreage, no structure, fragment tax bills &lt; $500  

---

## Three plays they rarely execute well

### 1. Short sale (before auction / before MLS)

**Profile:** LP + Truist/PennyMac/etc. + owner bought 2019–2023 + little equity.  
**Pitch:** "Work with your lender before the auction date — we can help package a short sale."  
**Why you beat them:** They push **assignment**; the spread isn't there. You are the **solution**, not another wholesaler.

### 2. FHA 203k / conventional primary (big house, physical distress)

**Profile:** Long ownership, year built &lt; 1990, assessed $350k+, tax stress or estate, **not** a fresh flip.  
**Pitch:** Owner-occupant or small landlord — renovation loan, not "cash in 7 days."  
**Why you beat them:** They need **equity for assignment fee**. You need **discount + rehab margin** for yourself.

### 3. Pre-LP tax stack (your secret timing edge)

**Profile:** Tier B tax delinquent → PVA → no LP yet → homestead or long hold.  
**Pitch:** "Property taxes are behind — let's solve that before the county escalates or a lender files."  
**Why you beat them:** They wait for LP. You are **first conversation** on the problem.

---

## Daily operating rhythm (desk investor, not driver)

| Time | Action |
|------|--------|
| Morning | Run `deep_portal_search` or review `portal-intel/*-filtered.json` Tier S/A |
| +30 min | PVA every Tier S: physical address, last sale, year built, equity % |
| +60 min | KCOJ cross-check: domestic / civil / probate on owner name |
| Same day | First touch: call + mailed letter to **mailing address** (PVA), not legal description |
| +48 hr | If LP hits on a Tier B tax lead → upgrade to Tier S, call again |

**Speed rule:** If record date is within **7 days** and you have not called, you are losing to Real Fire–style shops.

---

## What Foretrust automates for this fight

| Tool | Competitive purpose |
|------|---------------------|
| `deep_portal_search` | 16 filtered eCCLIX searches (tax, LP, liens, securities, estate) — not manual CSV |
| `ecclix_row_filters` | Drops LLC noise; keeps bank LP, divorce legal, premium subs |
| `investment_scorer` | `short_sale` / `fha_203k` / `creative` — don't compete on wholesale_score alone |
| `stack_score` (see below) | **2+ signals** = wholesaler hasn't prioritized yet |
| KCOJ `DOMESTIC` + `CIVIL` | Divorce/foreclosure **before** deed records |
| PVA enrich | Physical address before they send wrong mail |

---

## One-line strategy

**Don't out-wholesale the wholesaler.** Out-**time** them on tax and estate, out-**structure** them on low-equity LP, and out-**filter** them on real houses in real subdivisions.

Run portal intel while the day pass is live:

```bash
bash ~/Desktop/foretrust/scripts/run-portal-intel.sh
```

(Uses `env -u PLAYWRIGHT_BROWSERS_PATH` after Doppler — local Mac browsers, not Docker path.)
