"""Playwright browser launcher with UA rotation and human-like delays."""

from __future__ import annotations

import asyncio
import random
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

import httpx
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.proxy import ProxySession

logger = logging.getLogger(__name__)

# Realistic user-agent strings rotated per session
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


async def human_delay(min_sec: float = 2.0, max_sec: float = 5.0) -> None:
    """Wait a random interval to mimic human browsing behavior.

    Minimum 2 seconds per the legal guardrail — never bypassed.
    """
    delay = max(2.0, random.uniform(min_sec, max_sec))
    await asyncio.sleep(delay)


async def human_type(page: Page, selector: str, text: str) -> None:
    """Type text into a field with human-like delays between keystrokes."""
    await page.click(selector)
    await asyncio.sleep(random.uniform(0.3, 0.6))
    await page.type(selector, text, delay=random.randint(50, 150))


@asynccontextmanager
async def create_browser(
    proxy_session: ProxySession | None = None,
    headless: bool = True,
) -> AsyncGenerator[Browser, None]:
    """Launch a Playwright Chromium browser with optional proxy."""
    async with async_playwright() as p:
        launch_args: dict = {"headless": headless}
        if proxy_session and proxy_session.playwright_proxy:
            launch_args["proxy"] = proxy_session.playwright_proxy

        browser = await p.chromium.launch(**launch_args)
        try:
            yield browser
        finally:
            await browser.close()


@asynccontextmanager
async def create_context(
    browser: Browser,
    proxy_session: ProxySession | None = None,
) -> AsyncGenerator[BrowserContext, None]:
    """Create a browser context with UA rotation and playwright-stealth patches."""
    ua = random.choice(USER_AGENTS)
    ctx_args: dict = {
        "user_agent": ua,
        "viewport": {"width": 1920, "height": 1080},
        "locale": "en-US",
        "timezone_id": "America/New_York",
    }
    context = await browser.new_context(**ctx_args)

    # Wrap new_page to auto-apply playwright-stealth before first navigation.
    # This patches navigator.webdriver, plugins, languages, etc. so bot-detection
    # JS sees a normal browser fingerprint.
    _orig_new_page = context.new_page

    async def _stealth_new_page(**kwargs: Any) -> Page:
        page = await _orig_new_page(**kwargs)
        try:
            from playwright_stealth import stealth_async  # type: ignore[import]
            await stealth_async(page)
        except ImportError:
            logger.debug("playwright-stealth not installed; skipping stealth patches")
        return page

    context.new_page = _stealth_new_page  # type: ignore[method-assign]

    try:
        yield context
    finally:
        await context.close()


@asynccontextmanager
async def create_browserbase_browser() -> AsyncGenerator[Browser, None]:
    """Connect to a Browserbase cloud browser for anti-bot bypass.

    Browserbase handles stealth fingerprinting, CAPTCHA, and residential IP
    rotation automatically at the infrastructure level. Use this for sites
    with aggressive bot detection (e.g. Zillow).

    Requires BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID in Doppler.
    """
    from app.config import settings  # local import — avoids circular at module load

    if not settings.browserbase_api_key:
        raise RuntimeError("BROWSERBASE_API_KEY not configured in Doppler")

    # Create a remote session via Browserbase REST API
    async with httpx.AsyncClient(timeout=30) as http:
        resp = await http.post(
            "https://www.browserbase.com/v1/sessions",
            headers={
                "x-bb-api-key": settings.browserbase_api_key,
                "Content-Type": "application/json",
            },
            json={"projectId": settings.browserbase_project_id},
        )
        resp.raise_for_status()
        session_id = resp.json()["id"]

    logger.info("Browserbase session started: %s", session_id)

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(
            f"wss://connect.browserbase.com?apiKey={settings.browserbase_api_key}"
            f"&sessionId={session_id}",
            timeout=30000,
        )
        try:
            yield browser
        finally:
            await browser.close()


async def safe_goto(page: Page, url: str, timeout: int = 30000) -> None:
    """Navigate to a URL with error handling and wait for network idle."""
    logger.info("Navigating to %s", url)
    try:
        await page.goto(url, wait_until="networkidle", timeout=timeout)
    except Exception:
        # Fall back to domcontentloaded if networkidle times out
        logger.warning("Network idle timeout for %s, falling back to domcontentloaded", url)
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout)


async def check_robots_txt(page: Page, base_url: str) -> bool:
    """Fetch and check robots.txt. Returns True if scraping is allowed."""
    robots_url = base_url.rstrip("/") + "/robots.txt"
    try:
        response = await page.goto(robots_url, timeout=10000)
        if response and response.status == 200:
            text = await page.inner_text("body")
            # Conservative: if we see "Disallow: /" block everything
            if "Disallow: /" in text and "Allow:" not in text:
                logger.warning("robots.txt at %s disallows scraping", robots_url)
                return False
        return True  # No robots.txt or allows scraping
    except Exception as exc:
        logger.warning("Could not fetch robots.txt at %s: %s", robots_url, exc)
        return True  # Assume allowed if we can't fetch
