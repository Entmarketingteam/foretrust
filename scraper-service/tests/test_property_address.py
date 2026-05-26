"""Tests for property address parser — run before PVA batch."""

from __future__ import annotations

import pytest

from app.pipeline.property_address import (
    extract_address_from_legal,
    is_likely_legal_description,
    is_valid_street_address,
    normalize_property_address,
    sanitize_tax_row,
)

# Manually verified Scott County situs addresses (good)
GOOD = [
    "292 SOARDS RD",
    "115 HIDDEN CREEK DR",
    "848 FINNELL PIKE",
    "225 W MAIN ST",
    "105 ASHWOOD CIR",
    "2022 NEWTOWN PIKE",
    "411 CHESTNUT ST",
    "204 POCAHONTAS TRL",
]

# Legal / map junk (bad as property_address)
BAD = [
    "5 256 LOT 6 BLOCK A UNIT 3 PHASE 1 MALLARD POINT",
    "LOT 49 CHERRY BLOSSOM VILLAGE",
    "17.92 ACRES MINORS BRANCH ROAD",
    "TRACT B BOURBON STREET",
    "5256",
    "MC58 656",
    "UPI REAL ESTATE OF KENTUCKY LLC\tLEASE\tMC58 656",
]


@pytest.mark.parametrize("addr", GOOD)
def test_valid_street_addresses(addr: str) -> None:
    assert is_valid_street_address(addr), addr


@pytest.mark.parametrize("addr", BAD)
def test_rejects_legal_and_junk(addr: str) -> None:
    assert not is_valid_street_address(addr), addr


def test_legal_markers() -> None:
    assert is_likely_legal_description("LOT 6 BLOCK A PHASE 1")
    assert not is_likely_legal_description("115 HIDDEN CREEK DR")


def test_extract_from_legal() -> None:
    legal = "LOT 5 BLOCK B IRONWORKS ESTATE BEING 123 OLYMPIA WAY CHERRY BLOSSOM"
    assert extract_address_from_legal(legal) == "123 OLYMPIA WAY"


def test_sanitize_tax_row_swaps_legal() -> None:
    row = sanitize_tax_row({
        "bill_number": "5256",
        "owner_name": "SMITH, JOHN",
        "property_address": "5 256 LOT 6 BLOCK A UNIT 3 PHASE 1 MALLARD POINT",
        "map_id": "12345",
        "cells": ["5256", "2025", "SMITH, JOHN", "115 HIDDEN CREEK DR", "12345", "0", "1200"],
    })
    assert row.get("property_address") == "115 HIDDEN CREEK DR"


def test_normalize_rejects_bill() -> None:
    assert normalize_property_address("5256") is None
    assert normalize_property_address("292 SOARDS RD") == "292 SOARDS RD"
