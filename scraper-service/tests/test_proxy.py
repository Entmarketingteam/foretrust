"""Tests for the proxy manager."""

import os
from unittest.mock import patch

from app.config import settings
from app.proxy import ProxyManager


def test_no_proxy_configured():
    with (
        patch.object(settings, "webshare_username", ""),
        patch.object(settings, "webshare_password", ""),
        patch.object(settings, "proxy_server", ""),
        patch.object(settings, "proxy_username", ""),
    ):
        mgr = ProxyManager()
        session = mgr.create_session()
        assert session.playwright_proxy is None


def test_proxy_session_id_unique():
    mgr = ProxyManager()
    s1 = mgr.create_session()
    s2 = mgr.create_session()
    assert s1.session_id != s2.session_id


def test_bright_data_format():
    with (
        patch.object(settings, "webshare_username", ""),
        patch.object(settings, "webshare_password", ""),
        patch.object(settings, "proxy_server", "http://brd.superproxy.io:22225"),
        patch.object(settings, "proxy_username", "brd-customer-abc"),
        patch.object(settings, "proxy_password", "secret"),
        patch.object(settings, "proxy_country", "us"),
        patch.object(settings, "proxy_state", "ky"),
    ):
        mgr = ProxyManager()
        session = mgr.create_session()
        assert "session-" in session.username
        assert "-country-us" in session.username
        assert "-state-ky" in session.username
