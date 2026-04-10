"""Residential proxy manager with sticky sessions and geofencing."""

from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ProxySession:
    session_id: str = field(default_factory=lambda: f"session-{uuid.uuid4().hex[:12]}")
    server: str = ""
    username: str = ""
    password: str = ""

    @property
    def playwright_proxy(self) -> dict | None:
        """Returns proxy dict for Playwright browser.new_context(proxy=...)."""
        if not self.server:
            return None
        return {
            "server": self.server,
            "username": self.username,
            "password": self.password,
        }


class ProxyManager:
    """Manages residential proxy sessions with sticky IPs and geofencing.

    Supports Bright Data, Zyte, and generic HTTP/SOCKS5 proxies.
    Sticky sessions keep the same IP for the duration of a scraper run
    so government portals don't kick us mid-search.
    """

    def __init__(self) -> None:
        self._server = settings.proxy_server
        self._username = settings.proxy_username
        self._password = settings.proxy_password
        self._country = settings.proxy_country
        self._state = settings.proxy_state

    @property
    def is_configured(self) -> bool:
        return bool(self._server and self._username)

    def create_session(self, sticky_minutes: int = 10) -> ProxySession:
        """Create a new proxy session with a sticky IP.

        For Bright Data, the session ID is appended to the username:
          username-session-abc123-country-us-state-ky

        For generic proxies, we just pass through as-is.
        """
        session = ProxySession(server=self._server)

        if not self.is_configured:
            logger.warning("Proxy not configured; running without proxy")
            return session

        # Detect Bright Data format and apply session/geo suffixes
        username = self._username
        if "brd.superproxy.io" in self._server or "zproxy.lum-superproxy.io" in self._server:
            # Bright Data convention
            username = f"{username}-session-{session.session_id}"
            if self._country:
                username = f"{username}-country-{self._country}"
            if self._state:
                username = f"{username}-state-{self._state}"
        elif "zyte.com" in self._server:
            # Zyte uses X-Crawlera-Session header, but for proxy auth
            # we just pass session via username suffix
            username = f"{username}-session-{session.session_id}"

        session.username = username
        session.password = self._password

        logger.info(
            "Proxy session created: id=%s, geo=%s-%s",
            session.session_id, self._country, self._state,
        )
        return session

    def rotate_session(self, old_session: ProxySession) -> ProxySession:
        """Create a new session after the old one was blocked."""
        logger.info("Rotating proxy session (old=%s)", old_session.session_id)
        return self.create_session()


proxy_manager = ProxyManager()


if __name__ == "__main__":
    # Smoke test: python -m app.proxy --check
    import sys
    session = proxy_manager.create_session()
    if session.playwright_proxy:
        print(f"Proxy configured: {session.server}")
        print(f"Session ID: {session.session_id}")
        print(f"Username: {session.username}")
    else:
        print("No proxy configured. Set PROXY_SERVER/PROXY_USERNAME via Doppler.")
        sys.exit(1)
