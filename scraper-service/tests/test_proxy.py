"""Tests for the proxy manager."""

import os
from unittest.mock import patch

from app.proxy import ProxyManager


def test_no_proxy_configured():
    with patch.dict(os.environ, {"PROXY_SERVER": "", "PROXY_USERNAME": ""}, clear=False):
        mgr = ProxyManager()
        session = mgr.create_session()
        assert session.playwright_proxy is None


def test_proxy_session_id_unique():
    mgr = ProxyManager()
    s1 = mgr.create_session()
    s2 = mgr.create_session()
    assert s1.session_id != s2.session_id


def test_bright_data_format():
    with patch.dict(os.environ, {
        "PROXY_SERVER": "http://brd.superproxy.io:22225",
        "PROXY_USERNAME": "brd-customer-abc",
        "PROXY_PASSWORD": "secret",
        "PROXY_COUNTRY": "us",
        "PROXY_STATE": "ky",
    }, clear=False):
        mgr = ProxyManager()
        mgr._server = "http://brd.superproxy.io:22225"
        mgr._username = "brd-customer-abc"
        mgr._password = "secret"
        mgr._country = "us"
        mgr._state = "ky"
        session = mgr.create_session()
        assert "session-" in session.username
        assert "-country-us" in session.username
        assert "-state-ky" in session.username
