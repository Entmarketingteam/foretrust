# Foretrust Backlog & TODO List

## Urgent / Next Steps
- [ ] **Task 7: Tighten `LENDER_RE`**
  - Extend regex in `enrich_pva_gis.py` to match compound-name banks (like `CITIBANK`, `FIRSTBANK`) and `N.A.` / `NATIONAL ASSOCIATION`.
  - *Must be done before running Franklin (#1) or Bourbon (#2) to prevent false-positive matches on bank-owned branch parcels.*

## Active Backlog
- [ ] **Task 1: Find + wire Franklin County GIS parcel endpoint**
  - Locate Franklin County, KY parcel MapServer/FeatureServer REST endpoint.
  - Add to `COUNTY_GIS` in `enrich_pva_gis.py`.
  - Enrich 683 Franklin eCCLIX leads missing addresses.

- [ ] **Task 2: Find + wire Bourbon County GIS parcel endpoint**
  - Locate Bourbon County, KY parcel MapServer/FeatureServer REST endpoint.
  - Add to `COUNTY_GIS` in `enrich_pva_gis.py`.
  - Enrich 556 Bourbon eCCLIX leads missing addresses.

- [ ] **Task 5: Fix `fayette_pva` place-name owners bug**
  - Trace `fayette_pva` connector parser where subdivision/place names are leaking into `owner_name` and corrupting matching.

- [ ] **Task 4: Integrate `enrich_pva_gis` into main scraper pipeline**
  - Move from manual script execution to automatic post-persist pipeline stage.

- [ ] **Task 6: Suffix recovery for Woodford situs addresses**
  - Suffix restoration for Woodford Location strings (e.g. "ELM" -> "ELM STREET") using Address1 where numbers match.
