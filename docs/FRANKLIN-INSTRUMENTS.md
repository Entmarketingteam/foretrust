# Franklin County instruments — not eCCLIX

**Status:** Franklin tax delinquency works via eCCLIX Central (`www.ecclix.com` county picker).  
**Instrument/LP data via eCCLIX is unreliable** — low LP counts (e.g. 2) indicate the scraper is not pulling Franklin clerk instruments correctly, not that Franklin has no foreclosures.

## Root cause

Franklin (and possibly other counties) may use a **separate clerk backend** for recorded instruments, not the same eCCLIX instrument module as Scott/Bourbon on Central.

Do **not** use county subdomains (`franklinky.ecclix.com`, `bourbonky.ecclix.com`) — DNS dead. Always `www.ecclix.com` + county picker for tax.

## Next wiring options

1. **Confirm with clerk** — Franklin County Clerk recorded docs portal (SoftDocs / Landmark / independent)
2. **KCOJ CourtNet** — civil/probate/divorce for Franklin (fix selectors first)
3. **Master Commissioner calendar** — Franklin circuit court foreclosure sale schedule (public PDF/HTML)

## Until fixed

- Treat Franklin **tax actionable list** as valid (172+ rows)
- Treat Franklin **portal-intel LP/instrument counts** as **incomplete** — do not score SubTo/wholesale from instruments alone
- Prioritize Scott + Bourbon for instrument stacking; Franklin tax-only stack
