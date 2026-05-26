"""eCCLIX search profiles for day-pass bulk extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SearchModule = Literal["instruments", "delinquent_tax", "securities", "combination_party"]


@dataclass(frozen=True)
class EcclixSearchProfile:
    key: str
    module: SearchModule
    instrument_type: str = ""
    days_back: int = 60
    days_back_end: int | None = None  # for historical window
    drill_summary: bool = False  # click LP/89 to open detail grid
    tax_year: int | None = None
    party_filter: str = ""  # securities city filter
    max_rows: int = 40
    priority: int = 1  # lower = run first
    filter_tags: tuple[str, ...] = ()  # ecclix_row_filters.apply_filters
    min_tax_due: float = 0
    download_if_pass: bool = False  # PDF only when filters pass


# Ordered sprint for 24h day pass (Scott/Bourbon on eCCLIX)
DAY_PASS_SPRINT: tuple[EcclixSearchProfile, ...] = (
    EcclixSearchProfile(
        key="lp_recent",
        module="instruments",
        instrument_type="LP",
        days_back=60,
        drill_summary=True,
        max_rows=50,
        priority=1,
    ),
    EcclixSearchProfile(
        key="lp_historical",
        module="instruments",
        instrument_type="LP",
        days_back=730,
        days_back_end=60,
        drill_summary=True,
        max_rows=30,
        priority=2,
    ),
    EcclixSearchProfile(
        key="delinquent_tax",
        module="delinquent_tax",
        tax_year=2025,
        max_rows=100,
        priority=3,
    ),
    EcclixSearchProfile(
        key="jlien",
        module="instruments",
        instrument_type="JLIEN",
        days_back=730,
        drill_summary=True,
        max_rows=25,
        priority=4,
    ),
    EcclixSearchProfile(
        key="tlien",
        module="instruments",
        instrument_type="TLIEN",
        days_back=365,
        drill_summary=True,
        max_rows=25,
        priority=5,
    ),
    EcclixSearchProfile(
        key="deed_estate",
        module="instruments",
        instrument_type="DEED",
        days_back=90,
        drill_summary=False,
        max_rows=20,
        priority=6,
    ),
    EcclixSearchProfile(
        key="securities_city_lien",
        module="securities",
        instrument_type="LIEN",
        days_back=365,
        party_filter="GEORGETOWN",
        max_rows=25,
        priority=7,
    ),
)

LP_RECENT_ONLY = (DAY_PASS_SPRINT[0],)

# Aggressive 1-day pass — paginate grids, minimal row caps
FULL_DAY_PASS_SPRINT: tuple[EcclixSearchProfile, ...] = (
    EcclixSearchProfile(
        key="delinquent_tax_full",
        module="delinquent_tax",
        tax_year=2025,
        max_rows=9999,
        priority=1,
    ),
    EcclixSearchProfile(
        key="lp_recent_full",
        module="instruments",
        instrument_type="LP",
        days_back=120,
        drill_summary=True,
        max_rows=9999,
        priority=2,
    ),
    EcclixSearchProfile(
        key="lp_historical_full",
        module="instruments",
        instrument_type="LP",
        days_back=730,
        days_back_end=120,
        drill_summary=True,
        max_rows=9999,
        priority=3,
    ),
    EcclixSearchProfile(
        key="mtg_recent",
        module="instruments",
        instrument_type="MTG",
        days_back=90,
        drill_summary=True,
        max_rows=9999,
        priority=4,
    ),
    EcclixSearchProfile(
        key="will_recent",
        module="instruments",
        instrument_type="WILL",
        days_back=365,
        drill_summary=True,
        max_rows=9999,
        priority=5,
    ),
    EcclixSearchProfile(
        key="jlien_full",
        module="instruments",
        instrument_type="JLIEN",
        days_back=730,
        drill_summary=True,
        max_rows=9999,
        priority=6,
    ),
    EcclixSearchProfile(
        key="tlien_full",
        module="instruments",
        instrument_type="TLIEN",
        days_back=730,
        drill_summary=True,
        max_rows=9999,
        priority=7,
    ),
    EcclixSearchProfile(
        key="glien_full",
        module="instruments",
        instrument_type="GLIEN",
        days_back=730,
        drill_summary=True,
        max_rows=9999,
        priority=8,
    ),
    EcclixSearchProfile(
        key="mlien_full",
        module="instruments",
        instrument_type="MLIEN",
        days_back=365,
        drill_summary=True,
        max_rows=9999,
        priority=9,
    ),
    EcclixSearchProfile(
        key="deed_recent",
        module="instruments",
        instrument_type="DEED",
        days_back=120,
        drill_summary=True,
        max_rows=9999,
        priority=10,
    ),
    EcclixSearchProfile(
        key="securities_city_lien",
        module="securities",
        instrument_type="LIEN",
        days_back=730,
        max_rows=9999,
        priority=11,
    ),
)

WHOLESALE_INSTRUMENT_PRIORITY = ("LP", "DEED", "MTG", "WILL", "REL", "MLIEN", "FLIEN")

# Operator signal stack — all LP + probate + code liens (email digest / skip trace)
SIGNAL_INTEL_SEARCH: tuple[EcclixSearchProfile, ...] = (
    EcclixSearchProfile(
        key="all_lp_recent",
        module="instruments",
        instrument_type="LP",
        days_back=365,
        drill_summary=True,
        max_rows=9999,
        priority=1,
    ),
    EcclixSearchProfile(
        key="all_lp_historical",
        module="instruments",
        instrument_type="LP",
        days_back=1825,
        days_back_end=365,
        drill_summary=True,
        max_rows=9999,
        priority=2,
    ),
    EcclixSearchProfile(
        key="will_probate",
        module="instruments",
        instrument_type="WILL",
        days_back=730,
        drill_summary=True,
        max_rows=9999,
        priority=3,
    ),
    EcclixSearchProfile(
        key="deed_estate",
        module="instruments",
        instrument_type="DEED",
        days_back=365,
        drill_summary=True,
        max_rows=9999,
        priority=4,
        filter_tags=("estate_deed", "big_home_signal"),
    ),
    EcclixSearchProfile(
        key="securities_code_georgetown",
        module="securities",
        instrument_type="LIEN",
        days_back=730,
        party_filter="GEORGETOWN",
        max_rows=9999,
        priority=5,
        filter_tags=("city_lien",),
    ),
    EcclixSearchProfile(
        key="securities_code_versailles",
        module="securities",
        instrument_type="LIEN",
        days_back=730,
        party_filter="VERSAILLES",
        max_rows=9999,
        priority=6,
        filter_tags=("city_lien",),
    ),
    EcclixSearchProfile(
        key="jlien_judgment",
        module="instruments",
        instrument_type="JLIEN",
        days_back=730,
        drill_summary=True,
        max_rows=9999,
        priority=7,
    ),
    EcclixSearchProfile(
        key="mlien_mechanics",
        module="instruments",
        instrument_type="MLIEN",
        days_back=730,
        drill_summary=True,
        max_rows=9999,
        priority=8,
    ),
)

# Deep portal search — LOOSE day pass: paginate everything, no row filter_tags.
# Junk/login rows dropped in ecclix_batch._process_instrument_row only.
DEEP_PORTAL_SEARCH: tuple[EcclixSearchProfile, ...] = FULL_DAY_PASS_SPRINT + (
    EcclixSearchProfile(
        key="securities_georgetown_lien",
        module="securities",
        instrument_type="LIEN",
        days_back=730,
        party_filter="GEORGETOWN",
        max_rows=9999,
        priority=20,
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="securities_versailles_lien",
        module="securities",
        instrument_type="LIEN",
        days_back=730,
        party_filter="VERSAILLES",
        max_rows=9999,
        priority=21,
        download_if_pass=True,
    ),
)

# Creative / REI-only instrument paths — beyond tax + bank LP.
CREATIVE_REI_SEARCH: tuple[EcclixSearchProfile, ...] = (
    EcclixSearchProfile(
        key="rel_lp_release",
        module="instruments",
        instrument_type="REL",
        days_back=180,
        drill_summary=True,
        max_rows=500,
        priority=20,
        filter_tags=("release_after_lp", "human_owner_only"),
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="deed_nominal",
        module="instruments",
        instrument_type="DEED",
        days_back=120,
        drill_summary=True,
        max_rows=9999,
        priority=21,
        filter_tags=("nominal_consideration", "human_owner_only", "estate_deed"),
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="assign_wholesale",
        module="instruments",
        instrument_type="ASSIGN",
        days_back=365,
        drill_summary=True,
        max_rows=500,
        priority=22,
        filter_tags=("assignment_wholesale", "any_distress"),
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="mod_distress",
        module="instruments",
        instrument_type="MOD",
        days_back=730,
        drill_summary=True,
        max_rows=300,
        priority=23,
        filter_tags=("loan_mod_signal", "bank_counterparty"),
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="lease_option",
        module="instruments",
        instrument_type="LEASE",
        days_back=365,
        drill_summary=True,
        max_rows=500,
        priority=24,
        filter_tags=("lease_option_signal", "human_owner_only"),
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="poa_guardian",
        module="instruments",
        instrument_type="POA",
        days_back=730,
        drill_summary=True,
        max_rows=300,
        priority=25,
        filter_tags=("poa_guardian", "estate_deed"),
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="lp_subto_stack",
        module="instruments",
        instrument_type="LP",
        days_back=90,
        drill_summary=True,
        max_rows=9999,
        priority=26,
        filter_tags=("subto_candidate", "human_owner_only", "min_tax_500"),
        min_tax_due=500,
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="mtg_recent_overleveraged",
        module="instruments",
        instrument_type="MTG",
        days_back=48,
        drill_summary=True,
        max_rows=9999,
        priority=27,
        filter_tags=("big_home_signal", "second_lien"),
    ),
    EcclixSearchProfile(
        key="mlien_rehab_stall",
        module="instruments",
        instrument_type="MLIEN",
        days_back=365,
        drill_summary=True,
        max_rows=9999,
        priority=28,
        filter_tags=("rehab_mlien", "premium_subdivision"),
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="jlien_judgment_creative",
        module="instruments",
        instrument_type="JLIEN",
        days_back=365,
        drill_summary=True,
        max_rows=9999,
        priority=29,
        filter_tags=("judicial_sale", "human_owner_only"),
        download_if_pass=True,
    ),
)

# Reliable day-pass order: tax grid first (always works), then instruments with login guards.
USABLE_EXTRACT: tuple[EcclixSearchProfile, ...] = (
    EcclixSearchProfile(
        key="tax_all",
        module="delinquent_tax",
        tax_year=2025,
        max_rows=9999,
        priority=1,
    ),
    EcclixSearchProfile(
        key="lp_year",
        module="instruments",
        instrument_type="LP",
        days_back=365,
        drill_summary=True,
        max_rows=9999,
        priority=2,
        filter_tags=("any_distress",),
    ),
    EcclixSearchProfile(
        key="will_estate",
        module="instruments",
        instrument_type="WILL",
        days_back=730,
        drill_summary=True,
        max_rows=9999,
        priority=3,
        filter_tags=("estate_deed", "human_owner_only"),
    ),
    EcclixSearchProfile(
        key="jlien",
        module="instruments",
        instrument_type="JLIEN",
        days_back=730,
        drill_summary=True,
        max_rows=9999,
        priority=4,
        filter_tags=("any_distress",),
    ),
    EcclixSearchProfile(
        key="securities_georgetown",
        module="securities",
        instrument_type="LIEN",
        days_back=730,
        party_filter="GEORGETOWN",
        max_rows=9999,
        priority=5,
        filter_tags=("city_lien",),
    ),
    EcclixSearchProfile(
        key="securities_versailles",
        module="securities",
        instrument_type="LIEN",
        days_back=730,
        party_filter="VERSAILLES",
        max_rows=9999,
        priority=6,
        filter_tags=("city_lien",),
    ),
)


def _hist_profile(
    inst: str,
    key_suffix: str,
    days_back: int,
    *,
    days_back_end: int | None = None,
    priority: int = 50,
    filter_tags: tuple[str, ...] = ("any_distress",),
    download_if_pass: bool = True,
    max_rows: int = 9999,
) -> EcclixSearchProfile:
    return EcclixSearchProfile(
        key=f"{inst.lower()}_hist_{key_suffix}",
        module="instruments",
        instrument_type=inst,
        days_back=days_back,
        days_back_end=days_back_end,
        drill_summary=True,
        max_rows=max_rows,
        priority=priority,
        filter_tags=filter_tags,
        download_if_pass=download_if_pass,
    )


# Historical windows — build reference corpus (not only last 90 days).
SCENARIO_HISTORICAL_SEARCH: tuple[EcclixSearchProfile, ...] = (
    # LP slices
    _hist_profile("LP", "0_120", 120, priority=40, filter_tags=("foreclosure_lp", "bank_counterparty"), download_if_pass=True),
    _hist_profile("LP", "120_365", 365, days_back_end=120, priority=41, filter_tags=("subto_candidate", "human_owner_only"), download_if_pass=True),
    _hist_profile("LP", "365_1825", 1825, days_back_end=365, priority=42, filter_tags=("divorce_domestic", "any_distress"), download_if_pass=True),
    _hist_profile("LP", "archive", 3650, days_back_end=1825, priority=43, filter_tags=("any_distress",), download_if_pass=False),
    # DEED / estate
    _hist_profile("DEED", "0_180", 180, priority=44, filter_tags=("estate_deed", "nominal_consideration"), download_if_pass=True),
    _hist_profile("DEED", "180_1825", 1825, days_back_end=180, priority=45, filter_tags=("estate_deed", "human_owner_only"), download_if_pass=True),
    _hist_profile("DEED", "quit_claim", 365, priority=46, filter_tags=("seller_finance_deed", "human_owner_only"), download_if_pass=True),
    # MTG / leverage
    _hist_profile("MTG", "0_90", 90, priority=47, filter_tags=("big_home_signal",), download_if_pass=False),
    _hist_profile("MTG", "90_730", 730, days_back_end=90, priority=48, filter_tags=("any_distress",), download_if_pass=False),
    # Liens
    _hist_profile("MLIEN", "0_730", 730, priority=49, filter_tags=("rehab_mlien",), download_if_pass=True),
    _hist_profile("JLIEN", "0_1825", 1825, priority=50, filter_tags=("judicial_sale", "human_owner_only"), download_if_pass=True),
    _hist_profile("REL", "0_365", 365, priority=51, filter_tags=("release_after_lp",), download_if_pass=True),
    _hist_profile("WILL", "0_1825", 1825, priority=52, filter_tags=("estate_deed",), download_if_pass=True),
    _hist_profile("ASSIGN", "0_1825", 1825, priority=53, filter_tags=("assignment_wholesale",), download_if_pass=True),
    _hist_profile("MOD", "0_1825", 1825, priority=54, filter_tags=("loan_mod_signal",), download_if_pass=True),
    _hist_profile("LEASE", "0_1825", 1825, priority=55, filter_tags=("lease_option_signal",), download_if_pass=True),
    _hist_profile("POA", "0_1825", 1825, priority=56, filter_tags=("poa_guardian",), download_if_pass=True),
    # Tax human reference (re-export filtered)
    EcclixSearchProfile(
        key="tax_human_reference",
        module="delinquent_tax",
        tax_year=2025,
        max_rows=9999,
        priority=57,
        filter_tags=("human_owner_only", "street_address", "min_tax_500"),
        min_tax_due=500,
    ),
)


def _dedupe_profiles(profiles: tuple[EcclixSearchProfile, ...]) -> tuple[EcclixSearchProfile, ...]:
    seen: dict[str, EcclixSearchProfile] = {}
    for p in profiles:
        seen[p.key] = p
    return tuple(sorted(seen.values(), key=lambda x: x.priority))


# Combination Party Search — Party One targets (estate + institutional tax buyers).
PARTY_INTEL_SEARCH: tuple[EcclixSearchProfile, ...] = (
    EcclixSearchProfile(
        key="party_estate_of",
        module="combination_party",
        party_filter="ESTATE OF",
        days_back=180,
        max_rows=9999,
        priority=1,
        filter_tags=("estate_deed", "human_owner_only"),
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="party_executor",
        module="combination_party",
        party_filter="EXECUTOR",
        days_back=365,
        max_rows=9999,
        priority=2,
        filter_tags=("estate_deed", "human_owner_only"),
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="party_administrator",
        module="combination_party",
        party_filter="ADMINISTRATOR",
        days_back=365,
        max_rows=9999,
        priority=3,
        filter_tags=("estate_deed", "human_owner_only"),
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="party_orchard_tax",
        module="combination_party",
        party_filter="ORCHARD TAX",
        days_back=365,
        max_rows=9999,
        priority=4,
        filter_tags=("tax_lien_firm", "any_distress"),
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="party_east_coast_tax",
        module="combination_party",
        party_filter="EAST COAST TAX",
        days_back=365,
        max_rows=9999,
        priority=5,
        filter_tags=("tax_lien_firm", "any_distress"),
        download_if_pass=True,
    ),
    EcclixSearchProfile(
        key="party_lien_works",
        module="combination_party",
        party_filter="LIEN WORKS",
        days_back=365,
        max_rows=9999,
        priority=6,
        filter_tags=("tax_lien_firm", "any_distress"),
        download_if_pass=True,
    ),
)

# Full 24h library: instruments + liens + historical (tax grid already in Supabase).
SCENARIO_LIBRARY_SEARCH: tuple[EcclixSearchProfile, ...] = _dedupe_profiles(
    tuple(
        p
        for p in (
            DEEP_PORTAL_SEARCH + CREATIVE_REI_SEARCH + SCENARIO_HISTORICAL_SEARCH
        )
        if p.module != "delinquent_tax"
    )
)


# Operator reference: profile key → teaching metadata for exports/scenario-library/
PROFILE_REFERENCE_META: dict[str, dict[str, str | tuple[str, ...]]] = {
    "lp_recent_bank": {
        "target_scenarios": ("subto_foreclosure_rescue", "stacked_tax_foreclosure"),
        "query": "LP, last 120d, foreclosure + bank grantee",
        "filters": ("foreclosure_lp", "bank_counterparty", "any_distress"),
    },
    "lp_divorce_domestic": {
        "target_scenarios": ("divorce_forced_sale",),
        "query": "LP, 365d, domestic relations language",
        "filters": ("divorce_domestic", "big_home_signal"),
    },
    "lp_subto_stack": {
        "target_scenarios": ("subto_foreclosure_rescue", "stacked_tax_foreclosure"),
        "query": "LP 90d + human owner + tax≥500",
        "filters": ("subto_candidate", "human_owner_only", "min_tax_500"),
    },
    "rel_lp_release": {
        "target_scenarios": ("foreclosure_cancelled_rebound",),
        "query": "REL releasing lis pendens, 180d",
        "filters": ("release_after_lp", "human_owner_only"),
    },
    "deed_nominal": {
        "target_scenarios": ("nominal_deed_distress", "quit_claim_heir_dump"),
        "query": "DEED, consideration under $75k",
        "filters": ("nominal_consideration", "human_owner_only", "estate_deed"),
    },
    "assign_wholesale": {
        "target_scenarios": ("wholesale_assignment_chain",),
        "query": "ASSIGN, 365d",
        "filters": ("assignment_wholesale", "any_distress"),
    },
    "mod_distress": {
        "target_scenarios": ("loan_mod_distress",),
        "query": "MOD, 730d, bank party",
        "filters": ("loan_mod_signal", "bank_counterparty"),
    },
    "lease_option": {
        "target_scenarios": ("lease_option_seller",),
        "query": "LEASE, 365d",
        "filters": ("lease_option_signal", "human_owner_only"),
    },
    "tax_human_reference": {
        "target_scenarios": ("stacked_tax_foreclosure", "free_clear_senior_tax_delinquent"),
        "query": "Delinquent tax 2025, human, street, due≥500",
        "filters": ("human_owner_only", "street_address", "min_tax_500"),
    },
}
