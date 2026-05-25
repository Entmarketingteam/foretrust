# eCCLIX County Instrument Types

Per-county codes from **What's Available** (`ecclix.com/ECCLIXWhatAvailable.aspx`) and **Instruments → Index Search** (often `instrinq.aspx` / `indexinq.aspx`).

Config lives in `scraper-service/app/connectors/residential/ecclix_county_config.py`.

## Instruments menu

| Menu item | Foretrust use |
|-----------|----------------|
| **Index Search** | Wholesale: Type + Between Dates (DEED, MTG, WILL, …) |
| **Combination Party Search** | Name mode: legal-notice / probate names |
| **Linked Document Search** | Not automated yet (related filings) |

## How the scraper uses this

1. Login → **Instruments → Index Search**
2. Tab **Between Dates** → Beginning / Ending (`MM/dd/YYYY`)
3. **Type** dropdown → one code per search (DEED, MTG, WILL, LP, …)
4. **Search** → parse grid → optional PDF download → `ft_clerk_documents` + `ft_leads`

## Scott

| TYPE | Description | Book prefix |
|------|-------------|-------------|
| DEED | DEED | D63 |
| MTG | MORTGAGE | M96 |
| WILL | WILL | WZ |
| LP | LIS PENDENS | LP4 |
| REL | RELEASE | DMR |
| FLIEN | FEDERAL TAX LIEN | FL1 |
| SLIEN | STATE TAX LIEN | SL1 |
| MLIEN | MECHANICS LIEN | ML1 |
| ENC | ENCUMBRANCE | E |

Delinquent tax: **yes**

## Woodford

| TYPE | Description | Book prefix |
|------|-------------|-------------|
| DEED | DEED | D171 |
| MTG | MORTGAGE | M200 |
| WILL | WILL | W49 |
| REL | RELEASE | DMR85 |
| ENC | ENCUMBRANCE | E24 |
| CONDO | CONDOMINIUM DEED | CD1 |

## Bourbon

| TYPE | Description | Book prefix |
|------|-------------|-------------|
| DEED | DEED | DA |
| MTG | MORTGAGE | MB |
| WILL | WILL | A |
| ENC | ENCUMBRANCE | E1 |
| MLIEN | MECHANIC'S LIEN | ML1 |
| MAR | MARRIAGE LICENSE | MAR1 |
| MISC | MISCELLANEOUS | MC1 |
| FF | FIXTURE FILING | FF1 |
| PLAT | PLAT | CAB |

Bourbon's Type dropdown has **many more** codes (ASSG, DREL, EASE, LAND, RFR, …) — use Instrument Search UI to extend config.

## Franklin

| TYPE | Description | Book prefix |
|------|-------------|-------------|
| DEED | DEED | DA1 |
| MTG | MORTGAGE | M307 |
| WILL | WILL | WL1 |
| FLIEN | FEDERAL TAX LIEN | FL5 |
| MLIEN | MECHANICS LIEN | ML15 |
| POA | POWER OF ATTORNEY | POA11 |
| ENC | ENCUMBRANCE | E9 |

## Wholesaler priority (all counties)

1. **DEED** — ownership transfers  
2. **MTG** — new debt / refi signals  
3. **WILL** — estate / probate leads  
4. **LP** — lis pendens / pre-foreclosure (where available)  
5. **REL** — releases (equity / payoff)  
6. **FLIEN / SLIEN / MLIEN** — distress  

## Override instrument list

```bash
curl -X POST "$SCRAPER/pipeline/ecclix" \
  -H "Content-Type: application/json" \
  -d '{"mode":"wholesale","counties":["scott"],"instrument_types":["DEED","MTG","WILL","LP"],"days_back":30}'
```
