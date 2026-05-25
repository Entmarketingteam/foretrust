"""Tests for multi-strategy investment scoring."""

from app.pipeline.investment_scorer import best_strategy, score_from_lead_data


def test_raney_style_low_equity_high_creative():
    scores = score_from_lead_data({
        "instrument_type": "LP",
        "owner_name": "RANEY, DAVID & BROOKE",
        "property_address": "123 OLYMPIA WAY",
        "grantor": "RANEY, DAVID",
        "grantee": "TRUIST BANK",
        "legal_description": "LOT NO 49 CHERRY BLOSSOM VILLAGE",
        "estimated_value": 525_000,
        "last_sale_price": 500_000,
        "last_sale_year": 2022,
        "year_built": 2003,
        "lp_active": True,
    })
    assert scores["creative_score"] > scores["fha_203k_score"]
    assert best_strategy(scores) in ("creative_finance", "short_sale")
    assert scores.get("short_sale_score", 0) >= 60


def test_long_ownership_high_wholesale():
    scores = score_from_lead_data({
        "instrument_type": "LP",
        "legal_description": "LOT 5 BLOCK B IRONWORKS ESTATE",
        "estimated_value": 350_000,
        "last_sale_price": 120_000,
        "last_sale_year": 2005,
        "year_built": 1985,
        "lp_active": True,
    })
    assert scores["wholesale_score"] >= 70
    assert scores["fha_203k_score"] >= 55
