# eCCLIX Wholesaler Mode

What a wholesaler needs from county clerk data — and how Foretrust imports it.

## What you get per instrument

| Field | Stored in |
|-------|-----------|
| Grantor / Grantee | `ft_leads.owner_name` + `ft_clerk_documents` |
| Legal description | `ft_clerk_documents.legal_description` |
| Property address (parsed from legal) | `ft_leads.property_address` |
| Book / Page | `ft_leads.case_id`, `ft_clerk_documents` |
| Recorded date | `ft_leads.case_filed_date` |
| Consideration ($) | `ft_leads.estimated_value` |
| Instrument type (DEED, WILL, MTG…) | `lead_type` (probate / foreclosure / estate) |
| **PDF image** | `scraper-service/exports/ecclix/{county}/*.pdf` + `ft_clerk_documents.storage_path` |

## Modes

| `params.mode` | Use when |
|---------------|----------|
| **`wholesale`** (default) | Day pass — discover new recordings last N days, download docs |
| `address` | You have addresses from GIS/notices — pull chain of title at that parcel |
| `name` | Pass `names: ["Smith"]` — deeds/wills for that party |

## Run wholesale day pass

**UI:** Run Scraper → **eCCLIX Day Pass**

**API:**

```json
POST /pipeline/ecclix
{
  "limit": 20,
  "counties": ["scott", "clark", "madison", "woodford", "bourbon"]
}
```

Defaults: `days_back: 30`, `download_documents: true`, instrument types DEED / MORTGAGE / WILL / DEED OF TRUST.

## Database

Apply migration:

```bash
cd ~/Desktop/foretrust && supabase db push
# or run supabase/migrations/20260525100000_ft_clerk_documents.sql in dashboard
```

Query documents:

```sql
SELECT county, instrument_type, book, page, grantor, grantee,
       property_address, storage_path, recorded_date
FROM ft_clerk_documents
ORDER BY scraped_at DESC
LIMIT 50;
```

## Day-pass budget

Each county × instrument search × document download costs time and eCCLIX page views.

Recommended first run:

- `max_documents_per_county: 10` (50 docs across 5 counties)
- Then increase if the pass has headroom

## County UI variance

Search uses **Instruments → Index Search** (Type + Between Dates; URLs `indexinq.aspx` / `instrinq.aspx`). Name lookups use **Combination Party Search**. Per-county codes: `docs/ECCLIX-COUNTY-TYPES.md` and `ecclix_county_config.py`.

If a county returns 0 rows:

1. Check Railway logs for `[ecclix] wholesale county X failed`
2. Log in manually to that county portal and note the **Date Search** / **Recording Date** menu labels
3. We adjust selectors in `ecclix_portal.py`

## Exports on Railway

Mount or persist `scraper-service/exports/ecclix` volume, or set:

```bash
doppler secrets set ECCLIX_EXPORT_DIR="/app/exports/ecclix" --project foretrust-scraper --config prd
```

PDFs survive redeploys only if the volume is attached.
