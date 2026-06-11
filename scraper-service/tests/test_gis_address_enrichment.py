"""Tests for app/pipeline/gis_address_enrichment.py"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
import pytest

from app.pipeline.gis_address_enrichment import (
    _woodford_situs,
    gis_lookup,
    enrich_county_gis,
    enrich_all_counties_gis,
    COUNTY_GIS,
)

def test_woodford_situs_normalization():
    assert _woodford_situs("ELM ST 123") == "123 ELM ST"
    assert _woodford_situs("MAIN ROAD 45B") == "45B MAIN ROAD"
    assert _woodford_situs("NO NUMBER") is None
    assert _woodford_situs(None) is None


@patch("urllib.request.urlopen")
def test_gis_lookup_scott_success(mock_urlopen):
    # Mock Scott county ArcGIS REST query response
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "features": [
            {
                "attributes": {
                    "Name1": "SMITH JOHN",
                    "Complete_A": "123 OAK ST",
                    "MapNumber": "SC-123",
                    "YearBuilt": 1995,
                    "fcv": 250000.0
                }
            }
        ]
    }).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    cfg = COUNTY_GIS["Scott"]
    res = gis_lookup(cfg, "JOHN SMITH")
    assert res is not None
    addr, extras = res
    assert addr == "123 OAK ST"
    assert extras["parcel"] == "SC-123"
    assert extras["year_built"] == 1995
    assert extras["fcv"] == 250000.0


@patch("urllib.request.urlopen")
def test_gis_lookup_ambiguous_skips(mock_urlopen):
    # Mock multiple matching results (ambiguous owner name) -> should skip
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "features": [
            {"attributes": {"Name1": "SMITH JOHN", "Complete_A": "123 OAK ST"}},
            {"attributes": {"Name1": "SMITH JOHN", "Complete_A": "456 PINE ST"}}
        ]
    }).encode()
    mock_urlopen.return_value.__enter__.return_value = mock_resp

    cfg = COUNTY_GIS["Scott"]
    assert gis_lookup(cfg, "JOHN SMITH") is None


@patch("urllib.request.urlopen")
def test_gis_lookup_franklin_spatial_join(mock_urlopen):
    # Mock Franklin county parcel lookups + spatial point-in-polygon join
    mock_parcel_resp = MagicMock()
    mock_parcel_resp.read.return_value = json.dumps({
        "features": [
            {
                "attributes": {
                    "OwnerName": "SMITH JOHN",
                    "PARCEL_ID": "FR-999"
                },
                "geometry": {
                    "rings": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]
                }
            }
        ]
    }).encode()
    
    mock_911_resp = MagicMock()
    mock_911_resp.read.return_value = json.dumps({
        "features": [
            {
                "attributes": {
                    "Add_Number": "456",
                    "St_Name": "MAIN",
                    "St_PosTyp": "ST"
                }
            }
        ]
    }).encode()
    
    mock_urlopen.return_value.__enter__.side_effect = [mock_parcel_resp, mock_911_resp]

    cfg = COUNTY_GIS["Franklin"]
    res = gis_lookup(cfg, "JOHN SMITH")
    assert res is not None
    addr, extras = res
    assert addr == "456 MAIN ST"
    assert extras["parcel"] == "FR-999"


@pytest.mark.asyncio
@patch("app.pipeline.gis_address_enrichment.gis_lookup")
async def test_enrich_county_gis_updates_supabase(mock_lookup):
    # Mock gis_lookup response
    mock_lookup.return_value = ("123 OAK ST", {"parcel": "SC-123", "year_built": 1995, "fcv": 250000.0})

    # Mock Supabase Client
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.range.return_value.execute.return_value.data = [
        {"id": "lead-1", "owner_name": "SMITH JOHN", "property_address": ""}
    ]

    count = await enrich_county_gis("Scott", mock_client)
    assert count == 1
    
    # Check that update was called with the correctly structured payload and patch parameters
    mock_client.table.assert_called_with("ft_leads")
    mock_client.table().update.assert_called_once()
    patch_args = mock_client.table().update.call_args[0][0]
    assert patch_args["property_address"] == "123 OAK ST"
    assert patch_args["parcel_number"] == "SC-123"
    assert patch_args["year_built"] == 1995
    assert patch_args["estimated_value"] == 250000.0
    assert patch_args["raw_payload"]["pva_gis_enriched"] is True


@pytest.mark.asyncio
@patch("app.pipeline.gis_address_enrichment.enrich_county_gis")
async def test_enrich_all_counties_gis(mock_enrich_county):
    mock_enrich_county.return_value = 5
    
    mock_client = MagicMock()
    res = await enrich_all_counties_gis(mock_client)
    
    assert "Scott" in res
    assert "Woodford" in res
    assert "Franklin" in res
    assert res["Scott"] == 5
    assert res["Woodford"] == 5
    assert res["Franklin"] == 5
