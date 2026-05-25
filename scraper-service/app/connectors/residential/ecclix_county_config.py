"""Per-county eCCLIX instrument types from What's Available (May 2026).

Source: ecclix.com/ECCLIXWhatAvailable.aspx + Instrument Search (instrinq.aspx) dropdowns.
Book column = prefix used in Book field (e.g. D63, M96, WZ).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CountyInstrument:
    code: str
    description: str
    book_prefix: str = ""
    digital_from: str = ""


@dataclass(frozen=True)
class CountyProfile:
    name: str
    portal_bases: tuple[str, ...]
    instruments: tuple[CountyInstrument, ...]
    delinquent_tax: bool = True


# Wholesaler-priority codes only (full county catalogs are larger)
COUNTY_PROFILES: dict[str, CountyProfile] = {
    "scott": CountyProfile(
        name="Scott",
        portal_bases=("https://www.ecclix.com",),
        instruments=(
            CountyInstrument("DEED", "DEED", "D63", "07/01/1937"),
            CountyInstrument("MTG", "MORTGAGE", "M96", "08/08/1966"),
            CountyInstrument("WILL", "WILL", "WZ", "02/26/1968"),
            CountyInstrument("LP", "LIS PENDENS", "LP4", "08/29/1980"),
            CountyInstrument("REL", "RELEASE", "DMR", "07/26/2004"),
            CountyInstrument("FLIEN", "FEDERAL TAX LIEN", "FL1", "05/20/1993"),
            CountyInstrument("SLIEN", "STATE TAX LIEN", "SL1", "05/20/1993"),
            CountyInstrument("MLIEN", "MECHANICS LIEN", "ML1", "05/18/1993"),
            CountyInstrument("ENC", "ENCUMBRANCE", "E", ""),
        ),
        delinquent_tax=True,
    ),
    "woodford": CountyProfile(
        name="Woodford",
        portal_bases=("https://www.ecclix.com",),
        instruments=(
            CountyInstrument("DEED", "DEED", "D171", "11/29/1995"),
            CountyInstrument("MTG", "MORTGAGE", "M200", "03/30/1995"),
            CountyInstrument("WILL", "WILL", "W49", "02/08/1995"),
            CountyInstrument("REL", "RELEASE", "DMR85", "07/26/2004"),
            CountyInstrument("ENC", "ENCUMBRANCE", "E24", "05/08/2004"),
            CountyInstrument("CONDO", "CONDOMINIUM DEED", "CD1", ""),
        ),
        delinquent_tax=True,
    ),
    "bourbon": CountyProfile(
        name="Bourbon",
        portal_bases=("https://www.ecclix.com",),
        instruments=(
            CountyInstrument("DEED", "DEED", "DA", "07/08/1784"),
            CountyInstrument("MTG", "MORTGAGE", "MB", "05/15/1792"),
            CountyInstrument("WILL", "WILL", "A", "06/20/1786"),
            CountyInstrument("ENC", "ENCUMBRANCE", "E1", "07/01/1811"),
            CountyInstrument("MLIEN", "MECHANIC'S LIEN", "ML1", "08/17/1874"),
            CountyInstrument("MAR", "MARRIAGE LICENSE", "MAR1", ""),
            CountyInstrument("MISC", "MISCELLANEOUS", "MC1", ""),
            CountyInstrument("FF", "FIXTURE FILING", "FF1", ""),
            CountyInstrument("PLAT", "PLAT", "CAB", ""),
        ),
        delinquent_tax=True,
    ),
    "franklin": CountyProfile(
        name="Franklin",
        portal_bases=("https://www.ecclix.com",),
        instruments=(
            CountyInstrument("DEED", "DEED", "DA1", "06/01/1795"),
            CountyInstrument("MTG", "MORTGAGE", "M307", "01/05/1981"),
            CountyInstrument("WILL", "WILL", "WL1", "06/02/1795"),
            CountyInstrument("FLIEN", "FEDERAL TAX LIEN", "FL5", ""),
            CountyInstrument("MLIEN", "MECHANICS LIEN", "ML15", ""),
            CountyInstrument("POA", "POWER OF ATTORNEY", "POA11", ""),
            CountyInstrument("ENC", "ENCUMBRANCE", "E9", ""),
        ),
        delinquent_tax=True,
    ),
    "clark": CountyProfile(
        name="Clark",
        portal_bases=("https://www.ecclix.com", "https://clarkky.ecclix.com"),
        instruments=(
            CountyInstrument("DEED", "DEED", "D", ""),
            CountyInstrument("MTG", "MORTGAGE", "M", ""),
            CountyInstrument("WILL", "WILL", "W", ""),
            CountyInstrument("LP", "LIS PENDENS", "LP", ""),
        ),
        delinquent_tax=True,
    ),
    "madison": CountyProfile(
        name="Madison",
        portal_bases=("https://www.ecclix.com", "https://madisonky.ecclix.com"),
        instruments=(
            CountyInstrument("DEED", "DEED", "D", ""),
            CountyInstrument("MTG", "MORTGAGE", "M", ""),
            CountyInstrument("WILL", "WILL", "W", ""),
        ),
        delinquent_tax=True,
    ),
}


def wholesale_instrument_codes(county: str) -> list[str]:
    """Instrument Type codes to query on instrinq.aspx for a county."""
    profile = COUNTY_PROFILES.get(county.lower())
    if not profile:
        return ["DEED", "MTG", "WILL", "LP", "REL", "ENC"]
    return [i.code for i in profile.instruments]


def portal_bases_for(county: str) -> list[str]:
    profile = COUNTY_PROFILES.get(county.lower())
    if profile:
        return list(profile.portal_bases)
    return ["https://www.ecclix.com", f"https://{county.lower()}ky.ecclix.com"]
