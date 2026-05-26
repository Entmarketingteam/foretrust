# Water shutoff FOIA — unfair-advantage list (3–10 business days)

Send from your ENT/Foretrust email. Public record under KRS 61.870.

## City of Georgetown (Scott County)

**To:** cityclerk@georgetownky.gov (verify current clerk email on georgetownky.gov)  
**Subject:** Open Records Request — Utility Account Shutoffs (Last 12 Months)

```
Pursuant to KRS 61.870, I request a machine-readable list (CSV or Excel) of all
residential water utility accounts with shutoff or termination for non-payment
in the last 12 months, including:

- Service address
- Account holder name (if on file)
- Shutoff/termination date
- Mailing address (if different from service address)

Please advise copy fees before fulfillment if over $10. I can accept email delivery.

[Your name]
[Phone]
```

## City of Paris (Bourbon County)

**To:** Paris City Clerk — verify via parisky.com  
Same body; adjust "water utility" to Paris Water Works.

## City of Frankfort (Franklin County)

**To:** Frankfort Utility Billing / City Clerk  
Request Frankfort Plant Board or city utility shutoff list for residential accounts.

## City of Versailles (Woodford County)

**To:** Versailles City Hall / utility department  
Same template.

## When CSV arrives

1. Save to `scraper-service/exports/water-shutoffs/{city}-{date}.csv`
2. Run ingest (TODO: `scripts/import-water-shutoffs.py`) → Supabase `ft_leads` with `source_key=water_shutoff`
3. Re-run `scripts/export-stacked-leads.py` — water becomes list #6 in stack overlay

## Why this list wins

Water shutoff = definitionally vacant. Stacks with tax delinquent + LP = highest-conviction calls.
