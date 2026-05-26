"""REI-grade creative finance scenario detection + extended strategy scores.

Classifies a merged lead (tax + clerk + court payload) into acquisition archetypes
an experienced investor would run — not only tax/LP/estate.
"""

from __future__ import annotations

import re
from typing import Any

# --- Instrument / legal text patterns ---
SUBTO_RECENT_LOAN = re.compile(
    r"\bMTG\b|MORTGAGE|DEED\s+OF\s+TRUST|DTRUST|MTGAM|MTGM|MTGNC",
    re.I,
)
LOAN_MODIFICATION = re.compile(r"\bMOD\b|MODIFICATION|LOAN\s+MOD|MTGAM", re.I)
ASSIGNMENT_CHAIN = re.compile(r"\bASSIGN\b|ASSIGNMENT\s+OF\s+(MORTGAGE|LEASE|RENT)", re.I)
QUIT_CLAIM_DISTRESS = re.compile(r"\bQDEED\b|QUIT\s*CLAIM|QUITCLAIM", re.I)
CONTRACT_FOR_DEED = re.compile(r"\bCOD\b|CONTRACT\s+FOR\s+DEED|INSTALLMENT\s+SALE", re.I)
LEASE_OPTION = re.compile(
    r"\bLEASE\b|LEASAM|OPTION\s+TO\s+PURCHASE|LEASE\s+WITH\s+OPTION|RENT\s+TO\s+OWN",
    re.I,
)
POA_FIDUCIARY = re.compile(r"\bPOA\b|POWER\s+OF\s+ATTORNEY|GUARD\b|GUARDIAN", re.I)
UCC_EQUIPMENT = re.compile(r"\bUCC\b|FIXTURE\s+FILING|\bFF\b|FFAM|FFA", re.I)
RELEASE_OF_LP = re.compile(r"\bREL\b|RELEASE.*LIS\s+PENDENS|RELEASE.*FORECLOS", re.I)
PARTIAL_RELEASE = re.compile(r"PARTIAL\s+RELEASE|RELEASE\s+OF\s+LIEN", re.I)
HELOC_SECOND = re.compile(r"HELOC|HOME\s+EQUITY|SECOND\s+LIEN|2ND\s+LIEN|MTG2", re.I)
DIVORCE_QDRO = re.compile(
    r"divorce|dissolution|QDRO|marital|domestic\s+relations|equitable\s+distribution",
    re.I,
)
BANKRUPTCY_HINT = re.compile(r"bankruptcy|chapter\s*7|chapter\s*13|trustee\s+sale", re.I)
TAX_DEED_AUCTION = re.compile(
    r"orchard\s*tax|east\s*coast\s*tax|lien\s*works|tax\s+sale|commissioner",
    re.I,
)
ABSENTEE_MAIL = re.compile(
    r"\b(FL|TX|CA|OH|IN|TN|GA|NC|SC|VA|IL)\s+\d{5}\b|OUT\s+OF\s+STATE|PO\s+BOX",
    re.I,
)
SENIOR_AGE_HINT = re.compile(r"\b(19[3-9]\d|194\d|195\d)\b.*owner|senior|elder", re.I)
VACANT_LAND_ONLY = re.compile(r"\b\d+\.?\d*\s*ACRES?\b", re.I)
CONDO_TOWNHOME = re.compile(r"\bCONDO\b|CONDOMINIUM|TOWNHOME|UNIT\s+\d+", re.I)
REHAB_STALL = re.compile(
    r"MECHANIC|MLIEN|CONTRACTOR|CONSTRUCTION\s+LIEN|REPAIR|REMODEL",
    re.I,
)
CODE_NUISANCE = re.compile(
    r"nuisance|code\s+enforcement|unsafe|demolition|condemn|vacant\s+structure",
    re.I,
)
INVESTOR_FLIP_EXIT = re.compile(
    r"\bLLC\b.*\bLLC\b|INVEST|HOLDINGS|PROPERTIES\s+LLC|CAPITAL|VENTURES|"
    r"HOMES\s+LLC|REI\b",
    re.I,
)
LOW_CONSIDERATION = re.compile(r"consideration.*\$?\s*([0-9]{1,3}[,]?[0-9]{0,3})\b", re.I)
LIFE_ESTATE = re.compile(r"life\s+estate|remainder|beneficiary\s+deed|TOD\s+DEED", re.I)
SHERIFF_MASTER = re.compile(
    r"master\s+commissioner|sheriff|judicial\s+sale|commissioner'?s?\s+sale",
    re.I,
)

# Central KY — expand in ecclix_row_filters PREMIUM_SUBDIVISIONS too
HORSE_FARM_LEGAL = re.compile(
    r"HORSE\s+FARM|FARM\s+VIEW|STONERIDGE\s+FARM|THREE\s+FEATHERS|"
    r"PEPPER\s+POT|MAJESTIC\s+FARM|WOODFORD\s+COUNTY.*FARM",
    re.I,
)


def detect_scenarios(data: dict[str, Any]) -> list[str]:
    """Return scenario keys matched on this lead (multi-label)."""
    blob = _blob(data)
    inst = (data.get("instrument_type") or "").upper()
    scenarios: list[str] = []

    lp = inst == "LP" or data.get("lp_active")
    due = _f(data.get("amount_due") or data.get("tax_amount_due")) or 0
    cons = _f(data.get("consideration_amount") or data.get("consideration")) or 0
    years_owned = data.get("years_owned_estimate")
    equity_pct = data.get("equity_pct_estimate")

    if lp and SUBTO_RECENT_LOAN.search(blob):
        scenarios.append("subto_foreclosure_rescue")
    if lp and due >= 1000:
        scenarios.append("stacked_tax_foreclosure")
    if LOAN_MODIFICATION.search(blob) or inst == "MOD":
        scenarios.append("loan_mod_distress")
    if ASSIGNMENT_CHAIN.search(blob) or inst == "ASSIGN":
        scenarios.append("wholesale_assignment_chain")
    if QUIT_CLAIM_DISTRESS.search(blob) or inst == "QDEED":
        scenarios.append("quit_claim_heir_dump")
    if CONTRACT_FOR_DEED.search(blob) or inst == "COD":
        scenarios.append("contract_for_deed_default")
    if LEASE_OPTION.search(blob):
        scenarios.append("lease_option_seller")
    if POA_FIDUCIARY.search(blob):
        scenarios.append("poa_fiduciary_sale")
    if UCC_EQUIPMENT.search(blob):
        scenarios.append("ucc_business_distress")
    if RELEASE_OF_LP.search(blob) and inst == "REL":
        scenarios.append("foreclosure_cancelled_rebound")
    if HELOC_SECOND.search(blob):
        scenarios.append("second_lien_over_leveraged")
    if DIVORCE_QDRO.search(blob):
        scenarios.append("divorce_forced_sale")
    if BANKRUPTCY_HINT.search(blob):
        scenarios.append("bankruptcy_asset_sale")
    if TAX_DEED_AUCTION.search(blob):
        scenarios.append("tax_sale_redemption")
    if REHAB_STALL.search(blob) or inst == "MLIEN":
        scenarios.append("rehab_stalled_mlien")
    if CODE_NUISANCE.search(blob):
        scenarios.append("code_enforcement_motivated")
    if INVESTOR_FLIP_EXIT.search(blob) and inst in ("DEED", "QDEED"):
        scenarios.append("tired_landlord_or_flipper_exit")
    if cons and cons > 0 and cons < 50_000 and inst == "DEED":
        scenarios.append("nominal_deed_distress")
    if LIFE_ESTATE.search(blob):
        scenarios.append("life_estate_remainder")
    if SHERIFF_MASTER.search(blob):
        scenarios.append("judicial_sale_window")
    if years_owned is not None and years_owned >= 25 and due >= 500:
        scenarios.append("free_clear_senior_tax_delinquent")
    if equity_pct is not None and equity_pct < 10 and lp:
        scenarios.append("underwater_creative_takeover")
    if years_owned is not None and years_owned <= 3 and due >= 1500:
        scenarios.append("recent_purchase_cash_flow_crunch")
    if HORSE_FARM_LEGAL.search(blob) and due >= 500:
        scenarios.append("estate_farm_liquidation")
    if CONDO_TOWNHOME.search(blob) and lp:
        scenarios.append("condo_foreclosure_arbitrage")
    if VACANT_LAND_ONLY.search(blob) and not CONDO_TOWNHOME.search(blob):
        if "nominal_deed_distress" not in scenarios:
            scenarios.append("land_only_lower_priority")

    return scenarios


def extended_strategy_scores(data: dict[str, Any]) -> dict[str, int]:
    """Additional 0–100 scores beyond base investment_scorer."""
    scenarios = detect_scenarios(data)
    blob = _blob(data)
    due = _f(data.get("amount_due") or data.get("tax_amount_due")) or 0

    subto = 15
    seller_finance = 15
    novation = 10
    wrap = 15
    lease_option = 10
    tax_deed = 10
    probate_creative = 15
    judicial = 10

    boosts = {
        "subto_foreclosure_rescue": ("subto", 35),
        "stacked_tax_foreclosure": ("subto", 20),
        "loan_mod_distress": ("novation", 30),
        "underwater_creative_takeover": ("subto", 30),
        "recent_purchase_cash_flow_crunch": ("wrap", 25),
        "contract_for_deed_default": ("seller_finance", 35),
        "lease_option_seller": ("lease_option", 35),
        "quit_claim_heir_dump": ("probate_creative", 25),
        "divorce_forced_sale": ("seller_finance", 25),
        "free_clear_senior_tax_delinquent": ("seller_finance", 30),
        "rehab_stalled_mlien": ("wrap", 20),
        "code_enforcement_motivated": ("seller_finance", 20),
        "foreclosure_cancelled_rebound": ("novation", 25),
        "tax_sale_redemption": ("tax_deed", 30),
        "judicial_sale_window": ("judicial", 35),
        "wholesale_assignment_chain": ("wrap", 15),
    }
    score_map = {
        "subto": subto,
        "seller_finance": seller_finance,
        "novation": novation,
        "wrap": wrap,
        "lease_option": lease_option,
        "tax_deed": tax_deed,
        "probate_creative": probate_creative,
        "judicial": judicial,
    }
    for sc in scenarios:
        if sc in boosts:
            key, pts = boosts[sc]
            score_map[key] = score_map.get(key, 15) + pts
    if due >= 3000:
        score_map["tax_deed"] = score_map.get("tax_deed", 10) + 15
        score_map["subto"] = score_map.get("subto", 15) + 10

    return {k: _clamp(v) for k, v in score_map.items()}


def primary_creative_play(data: dict[str, Any]) -> str:
    """Best creative play label for export."""
    ext = extended_strategy_scores(data)
    ranked = sorted(ext.items(), key=lambda x: -x[1])
    if not ranked or ranked[0][1] < 55:
        scenarios = detect_scenarios(data)
        return scenarios[0] if scenarios else "monitor"
    return ranked[0][0]


def scenario_outreach_hint(scenario: str) -> str:
    hints = {
        "subto_foreclosure_rescue": "Take over payments + arrears; seller deeds subject to existing loan.",
        "stacked_tax_foreclosure": "Pay tax arrears in exchange for deed or option; time LP clock.",
        "loan_mod_distress": "Seller failed mod — novation or purchase before re-default.",
        "underwater_creative_takeover": "Short sale coordination or subject-to with lender approval path.",
        "recent_purchase_cash_flow_crunch": "Wrap/ASSIGN exit; seller bought high, needs relief.",
        "contract_for_deed_default": "Buy out vendee equity or reinstate COD with seller.",
        "lease_option_seller": "Exercise option early or master lease + sublet.",
        "quit_claim_heir_dump": "Heir stack — buy multiple QDEEDs or single heir out.",
        "divorce_forced_sale": "Buy from party awarded property; coordinate QDRO timeline.",
        "free_clear_senior_tax_delinquent": "Low-ball cash or life estate retention + tax pay.",
        "rehab_stalled_mlien": "Pay off MLIEN at discount; acquire as-is with contractor lien release.",
        "code_enforcement_motivated": "City lien subordination + fix-and-flip or wholetail.",
        "foreclosure_cancelled_rebound": "REL filed — owner thinks crisis over; still motivated.",
        "tax_sale_redemption": "Redemption period assignment or post-sale deed.",
        "judicial_sale_window": "Bid strategy or pre-sale deed from owner.",
        "wholesale_assignment_chain": "Trace ASSIGN chain; buy last assignor contract.",
    }
    return hints.get(scenario, "Read instrument PDF; match play to parties.")


def _blob(data: dict[str, Any]) -> str:
    return " ".join(
        str(data.get(k) or "")
        for k in (
            "legal_description", "row_text", "grantor", "grantee",
            "owner_name", "property_address", "instrument_type",
        )
    )


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(str(v).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None


def _clamp(n: int) -> int:
    return max(0, min(100, n))
