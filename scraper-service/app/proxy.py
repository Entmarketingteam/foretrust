"""Residential proxy manager with Webshare support and sticky sessions.

Priority order:
  1. Webshare rotating residential proxy (if WEBSHARE_USERNAME is set)
  2. Generic proxy (PROXY_SERVER / PROXY_USERNAME / PROXY_PASSWORD)
  3. No proxy (direct connection)
"""

from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass, field

from app.config import settings

logger = logging.getLogger(__name__)

# Webshare rotating residential proxy endpoint
WEBSHARE_SERVER = "http://p.webshare.io:80"


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

    @property
    def httpx_proxy(self) -> str | None:
        """Returns proxy URL for httpx AsyncClient(proxy=...)."""
        if not self.server:
            return None
        scheme = self.server.split("://")[0] if "://" in self.server else "http"
        host = self.server.split("://")[-1]
        return f"{scheme}://{self.username}:{self.password}@{host}"


class ProxyManager:
    """Manages residential proxy sessions.

    Supports Webshare, Bright Data, Zyte, and generic HTTP proxies.
    Sticky sessions keep the same IP for the duration of a scraper run.
    """

    def __init__(self) -> None:
        # Webshare takes priority
        if settings.webshare_username and settings.webshare_password:
            self._provider = "webshare"
            self._server = WEBSHARE_SERVER
            self._username = settings.webshare_username
            self._password = settings.webshare_password
            self._country = "us"
            self._state = "ky"
            logger.info("ProxyManager: using Webshare residential proxy (US/KY)")
        elif settings.proxy_server and settings.proxy_username:
            self._provider = "generic"
            self._server = settings.proxy_server
            self._username = settings.proxy_username
            self._password = settings.proxy_password
            self._country = settings.proxy_country
            self._state = settings.proxy_state
            logger.info("ProxyManager: using generic proxy %s", self._server)
        else:
            self._provider = "none"
            self._server = ""
            self._username = ""
            self._password = ""
            self._country = ""
            self._state = ""
            logger.warning("ProxyManager: no proxy configured — running direct")

    @property
    def is_configured(self) -> bool:
        return bool(self._server and self._username)

    def create_session(self, sticky_minutes: int = 10) -> ProxySession:
        """Create a new proxy session with a sticky IP.

        Webshare: appends -country-us-state-ky to username for geo-targeting.
        Bright Data: appends session ID + geo suffixes.
        Generic: passes credentials as-is.
        """
        session = ProxySession(server=self._server)

        if not self.is_configured:
            return session

        username = self._username

        if self._provider == "webshare":
            # Webshare geo-routing via username suffix
            username = self._username
            if self._country:
                username = f"{username}-country-{self._country}"
            if self._state:
                username = f"{username}-state-{self._state}"
            # No session pinning needed — Webshare rotates per-request by default

        elif "brd.superproxy.io" in self._server or "zproxy.lum-superproxy.io" in self._server:
            # Bright Data: session ID + geo
            username = f"{username}-session-{session.session_id}"
            if self._country:
                username = f"{username}-country-{self._country}"
            if self._state:
                username = f"{username}-state-{self._state}"

        elif "zyte.com" in self._server:
            username = f"{username}-session-{session.session_id}"

        session.username = username
        session.password = self._password

        logger.debug(
            "Proxy session created: provider=%s, id=%s, geo=%s-%s",
            self._provider, session.session_id, self._country, self._state,
        )
        return session

    def rotate_session(self, old_session: ProxySession) -> ProxySession:
        """Force a new IP by creating a fresh session."""
        logger.info("Rotating proxy session (old=%s)", old_session.session_id)
        return self.create_session()


proxy_manager = ProxyManager()


if __name__ == "__main__":
    import sys
    session = proxy_manager.create_session()
    if session.playwright_proxy:
        print(f"Provider:   {proxy_manager._provider}")
        print(f"Server:     {session.server}")
        print(f"Username:   {session.username}")
        print(f"Session ID: {session.session_id}")
    else:
        print("No proxy configured. Set WEBSHARE_USERNAME/PASSWORD or PROXY_SERVER via Doppler.")
        sys.exit(1)
