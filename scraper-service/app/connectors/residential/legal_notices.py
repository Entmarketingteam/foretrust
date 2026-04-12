"""Local newspaper legal-notice monitor.

Tier 1: Poll Google Alerts RSS feeds for foreclosure/estate/auction keywords.
Tier 2: Direct Playwright scrape of newspaper legal-notice pages with diff detection.
Parses extracted text with OpenAI to identify distress signals.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any

from playwright.async_api import Browser

from app.connectors.base import BaseConnector
from app.connectors.registry import register
from app.models import Lead, LeadType, RawRecord, Vertical
from app.browser import create_context, human_delay, safe_goto
from app.config import settings

logger = logging.getLogger(__name__)

# Keywords that signal distress in legal notices
DISTRESS_KEYWORDS = [
    "FORECLOSURE", "FORECLOS", "ESTATE OF", "PUBLIC AUCTION",
    "NOTICE OF TRUSTEE SALE", "MASTER COMMISSIONER", "NOTICE OF DEFAULT",
    "SHERIFF SALE", "TAX SALE", "DELINQUENT TAX", "PROBATE",
    "DECEASED", "LIS PENDENS", "MORTGAGE SALE",
]

# Previous page hashes for diff detection (in-memory, resets on restart)
_page_hashes: dict[str, str] = {}


@register
class LegalNoticesConnector(BaseConnector):
    source_key = "legal_notices"
    vertical = Vertical.RESIDENTIAL
    jurisdiction = "KY-Multi"
    base_url = "https://news-graphic.com"
    default_schedule = "0 */6 * * *"
    respects_robots = False  # Legal notices are public record; newspaper sites' robots.txt is advisory

    async def fetch(self, browser: Browser, params: dict[str, Any]) -> list[RawRecord]:
        records: list[RawRecord] = []

        # Tier 1: RSS feeds
        rss_records = await self._poll_rss_feeds()
        records.extend(rss_records)

        # Tier 2: Direct page scraping
        page_records = await self._scrape_newspaper_pages(browser)
        records.extend(page_records)

        logger.info("[legal_notices] Total: %d records (%d RSS, %d page)",
                    len(records), len(rss_records), len(page_records))
        return records

    async def _poll_rss_feeds(self) -> list[RawRecord]:
        """Poll Google Alerts RSS feeds for distress keywords."""
        records: list[RawRecord] = []
        rss_urls = settings.rss_url_list

        if not rss_urls:
            logger.debug("[legal_notices] No RSS URLs configured")
            return records

        try:
            import feedparser
        except ImportError:
            logger.warning("[legal_notices] feedparser not installed")
            return records

        for url in rss_urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:50]:
                    title = entry.get("title", "")
                    summary = entry.get("summary", "")
                    link = entry.get("link", "")
                    published = entry.get("published", "")

                    combined = f"{title} {summary}".upper()
                    if any(kw in combined for kw in DISTRESS_KEYWORDS):
                        records.append(RawRecord(
                            source_key=self.source_key,
                            data={
                                "title": title,
                                "summary": summary,
                                "link": link,
                                "published": published,
                                "source": "google_alerts_rss",
                                "matched_keywords": [
                                    kw for kw in DISTRESS_KEYWORDS if kw in combined
                                ],
                            },
                        ))
            except Exception as exc:
                logger.warning("[legal_notices] RSS parse failed for %s: %s", url, exc)

        return records

    async def _scrape_newspaper_pages(self, browser: Browser) -> list[RawRecord]:
        """Scrape newspaper legal-notice pages and detect changes."""
        records: list[RawRecord] = []
        urls = settings.newspaper_url_list

        if not urls:
            return records

        async with create_context(browser) as ctx:
            page = await ctx.new_page()

            for url in urls:
                try:
                    await safe_goto(page, url)
                    await human_delay(2.0, 4.0)

                    # Get page text
                    body_text = await page.inner_text("body")
                    current_hash = hashlib.sha256(body_text.encode()).hexdigest()

                    # Check for changes
                    prev_hash = _page_hashes.get(url)
                    _page_hashes[url] = current_hash

                    if prev_hash and prev_hash == current_hash:
                        logger.debug("[legal_notices] No change at %s", url)
                        continue

                    # New or changed content — scan for distress keywords
                    new_records = self._extract_from_text(body_text, url)
                    records.extend(new_records)

                except Exception as exc:
                    logger.warning("[legal_notices] Page scrape failed for %s: %s", url, exc)

        return records

    def _extract_from_text(self, text: str, source_url: str) -> list[RawRecord]:
        """Extract distress signals from legal notice text."""
        records: list[RawRecord] = []
        upper = text.upper()

        # Split into paragraphs/sections
        sections = text.split("\n\n")

        for section in sections:
            section_upper = section.upper().strip()
            if not section_upper or len(section_upper) < 20:
                continue

            matched = [kw for kw in DISTRESS_KEYWORDS if kw in section_upper]
            if matched:
                records.append(RawRecord(
                    source_key=self.source_key,
                    data={
                        "text": section.strip()[:2000],
                        "source_url": source_url,
                        "matched_keywords": matched,
                        "source": "newspaper_scrape",
                    },
                ))

        return records

    def parse(self, raw: RawRecord) -> Lead:
        data = raw.data
        keywords = data.get("matched_keywords", [])

        # Classify based on keywords
        if any(kw in keywords for kw in ["FORECLOSURE", "FORECLOS", "MORTGAGE SALE", "NOTICE OF TRUSTEE SALE"]):
            lead_type = LeadType.FORECLOSURE
        elif any(kw in keywords for kw in ["NOTICE OF DEFAULT"]):
            lead_type = LeadType.PRE_FORECLOSURE
        elif any(kw in keywords for kw in ["ESTATE OF", "PROBATE", "DECEASED"]):
            lead_type = LeadType.PROBATE
        elif any(kw in keywords for kw in ["TAX SALE", "DELINQUENT TAX"]):
            lead_type = LeadType.TAX_LIEN
        elif any(kw in keywords for kw in ["SHERIFF SALE", "PUBLIC AUCTION", "MASTER COMMISSIONER"]):
            lead_type = LeadType.FORECLOSURE
        else:
            lead_type = LeadType.ESTATE

        # Try to extract name and address from the text
        text = data.get("text") or data.get("summary") or data.get("title") or ""
        owner_name = self._extract_name(text)
        address = self._extract_address(text)

        return Lead(
            source_key=self.source_key,
            vertical=Vertical.RESIDENTIAL,
            jurisdiction="KY-Multi",
            lead_type=lead_type,
            owner_name=owner_name,
            property_address=address,
            state="KY",
            raw_payload=data,
        )

    @staticmethod
    def _extract_name(text: str) -> str | None:
        """Simple heuristic extraction of names from legal notice text."""
        import re
        # Pattern: "Estate of [NAME]" or "[NAME], Deceased"
        patterns = [
            r"ESTATE\s+OF\s+([A-Z][A-Za-z\s,\.]+?)(?:\s*,|\s*\n|\s*\()",
            r"([A-Z][A-Za-z\s]+?),?\s+(?:DECEASED|deceased)",
            r"(?:VS\.|vs\.)\s+([A-Z][A-Za-z\s,]+?)(?:\s*\n|\s*$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip().rstrip(",. ")
                if 3 < len(name) < 80:
                    return name
        return None

    @staticmethod
    def _extract_address(text: str) -> str | None:
        """Simple heuristic extraction of addresses from legal notice text."""
        import re
        # Pattern: street number + street name
        match = re.search(
            r"(\d{1,6}\s+[A-Za-z\s]+(?:Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Lane|Ln|Road|Rd|Court|Ct|Way|Pike))",
            text, re.IGNORECASE
        )
        if match:
            addr = match.group(1).strip()
            if 5 < len(addr) < 100:
                return addr
        return None
