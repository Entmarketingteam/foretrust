# eCCLIX Deep Portal Search

Automated equivalent of logging into eCCLIX and running **filtered** searches across every distress channel — not manual CSV exports.

## Mode: `deep_portal_search`

Runs **16 search profiles** per county (paginated grids):

| Profile | Menu path | What it finds |
|---------|-----------|---------------|
| `tax_human_big` | Delinquent Tax → Index | Human owners, street address, tax ≥ $500 |
| `lp_recent_bank` | Instruments → LP | Foreclosure LP + bank servicer |
| `lp_divorce_domestic` | Instruments → LP | Divorce / domestic in legal description |
| `lp_premium_subdivision` | Instruments → LP | Cherry Blossom, Ironworks, etc. |
| `mtg_recent` | Instruments → MTG | Recent mortgages on premium lots |
| `will_estate` | Instruments → WILL | Estate filings |
| `deed_estate` | Instruments → DEED | Estate deeds + big-home legal |
| `mlien_mechanics` | Instruments → MLIEN | Mechanic's liens |
| `flien_federal` | Instruments → FLIEN | Federal tax liens |
| `slien_state` | Instruments → SLIEN | State tax liens |
| `encumbrance` | Instruments → ENC | Encumbrances on subdivisions |
| `release_recent` | Instruments → REL | Recent releases |
| `securities_georgetown_lien` | Securities → Georgetown | City/code liens |
| `securities_versailles_lien` | Securities → Versailles | Woodford city liens |
| `jlien_judgment` | Instruments → JLIEN | Judgment liens |
| `tlien_tax_lien` | Instruments → TLIEN | Tax liens on record |

**Post-search filters** (`ecclix_row_filters.py`) drop LLC noise and keep rows matching your strategy (big homes, banks, divorce signals, etc.).

**PDFs** download only when a row passes a `download_if_pass` profile (saves day-pass time).

## Divorce & court cases

- **eCCLIX:** Divorce often appears as **LP** with domestic-relations language in the legal description (`lp_divorce_domestic` profile).
- **KCOJ CourtNet:** Real divorce dockets — run `scripts/run-portal-intel.sh` step 2 (`DOMESTIC` category).

## Run locally

```bash
cd ~/Desktop/foretrust/scraper-service
playwright install chromium   # once

cd ~/Desktop/foretrust
bash scripts/run-portal-intel.sh
```

Single county:

```bash
ECCLIX_COUNTIES=scott bash scripts/run-portal-intel.sh
```

## API

```http
POST /pipeline/ecclix
Authorization: Bearer $SCRAPER_SHARED_TOKEN

{
  "mode": "deep_portal_search",
  "counties": ["scott", "bourbon", "woodford", "franklin"],
  "download_documents": true
}
```

## Outputs

| Path | Contents |
|------|----------|
| `exports/portal-intel/*-filtered-*.json` | Tier A/B/C leads with filter reasons |
| `exports/ecclix-sprint/*.csv` | Full sprint dump |
| `exports/clerk-documents/` | Downloaded instrument PDFs |
| Supabase `ft_leads` | Scored + persisted |
| Supabase `ft_clerk_documents` | Document metadata + storage path |

## vs CSV import

CSV import (`ecclix_csv_import`) is a **fallback** when Playwright cannot run. `deep_portal_search` is the primary path: live login, pagination, LP drill-down, securities city filter, and smart filtering.
