"""CAPTCHA solver interface with 2Captcha and CapSolver implementations.

Handles reCAPTCHA v2/v3 and hCaptcha automatically. Includes daily
budget guardrails so we never rack up a surprise bill.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol, runtime_checkable

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Budget tracker
# ---------------------------------------------------------------------------

class _BudgetTracker:
    """Tracks CAPTCHA spend per day to enforce CAPTCHA_DAILY_BUDGET_USD."""

    # Approximate cost per solve (USD)
    COST_PER_SOLVE = 0.003  # ~$3 per 1000 solves

    def __init__(self) -> None:
        self._solves_today: int = 0
        self._day: int = 0

    def _reset_if_new_day(self) -> None:
        today = time.gmtime().tm_yday
        if today != self._day:
            self._day = today
            self._solves_today = 0

    def can_solve(self) -> bool:
        self._reset_if_new_day()
        spent = self._solves_today * self.COST_PER_SOLVE
        return spent < settings.captcha_daily_budget_usd

    def record_solve(self) -> None:
        self._reset_if_new_day()
        self._solves_today += 1


_budget = _BudgetTracker()
logger.warning(
    "CAPTCHA daily budget is tracked in-memory and resets on container restart. "
    "Budget enforcement is approximate."
)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class CaptchaSolver(Protocol):
    async def solve_recaptcha_v2(self, site_key: str, page_url: str) -> str: ...
    async def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str) -> str: ...
    async def solve_hcaptcha(self, site_key: str, page_url: str) -> str: ...
    async def solve_image(self, image_bytes: bytes) -> str: ...


# ---------------------------------------------------------------------------
# 2Captcha implementation
# ---------------------------------------------------------------------------

class TwoCaptchaSolver:
    """Primary solver using 2captcha.com API."""

    def __init__(self) -> None:
        self._api_key = settings.twocaptcha_api_key

    def _check_ready(self) -> None:
        if not self._api_key:
            raise RuntimeError("TWOCAPTCHA_API_KEY not set in Doppler")
        if not _budget.can_solve():
            raise RuntimeError("CAPTCHA daily budget exceeded")

    async def solve_recaptcha_v2(self, site_key: str, page_url: str) -> str:
        self._check_ready()
        import asyncio
        from twocaptcha import TwoCaptcha
        solver = TwoCaptcha(self._api_key)
        result = await asyncio.to_thread(solver.recaptcha, sitekey=site_key, url=page_url)
        _budget.record_solve()
        logger.info("reCAPTCHA v2 solved via 2Captcha")
        return result["code"]

    async def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str) -> str:
        self._check_ready()
        import asyncio
        from twocaptcha import TwoCaptcha
        solver = TwoCaptcha(self._api_key)
        result = await asyncio.to_thread(
            solver.recaptcha, sitekey=site_key, url=page_url, version="v3", action=action, score=0.9
        )
        _budget.record_solve()
        logger.info("reCAPTCHA v3 solved via 2Captcha")
        return result["code"]

    async def solve_hcaptcha(self, site_key: str, page_url: str) -> str:
        self._check_ready()
        import asyncio
        from twocaptcha import TwoCaptcha
        solver = TwoCaptcha(self._api_key)
        result = await asyncio.to_thread(solver.hcaptcha, sitekey=site_key, url=page_url)
        _budget.record_solve()
        logger.info("hCaptcha solved via 2Captcha")
        return result["code"]

    async def solve_image(self, image_bytes: bytes) -> str:
        self._check_ready()
        import asyncio, tempfile, os
        from twocaptcha import TwoCaptcha
        solver = TwoCaptcha(self._api_key)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(image_bytes)
            f.flush()
            path = f.name
        result = await asyncio.to_thread(solver.normal, path)
        os.unlink(path)
        _budget.record_solve()
        return result["code"]


# ---------------------------------------------------------------------------
# CapSolver implementation (fallback)
# ---------------------------------------------------------------------------

class CapSolverSolver:
    """Fallback solver using capsolver.com API."""

    def __init__(self) -> None:
        self._api_key = settings.capsolver_api_key

    async def solve_recaptcha_v2(self, site_key: str, page_url: str) -> str:
        return await self._solve("ReCaptchaV2TaskProxyLess", {
            "websiteURL": page_url, "websiteKey": site_key,
        })

    async def solve_recaptcha_v3(self, site_key: str, page_url: str, action: str) -> str:
        return await self._solve("ReCaptchaV3TaskProxyLess", {
            "websiteURL": page_url, "websiteKey": site_key,
            "pageAction": action,
        })

    async def solve_hcaptcha(self, site_key: str, page_url: str) -> str:
        return await self._solve("HCaptchaTaskProxyLess", {
            "websiteURL": page_url, "websiteKey": site_key,
        })

    async def solve_image(self, image_bytes: bytes) -> str:
        import base64
        return await self._solve("ImageToTextTask", {
            "body": base64.b64encode(image_bytes).decode(),
        })

    async def _solve(self, task_type: str, task_params: dict) -> str:
        if not self._api_key:
            raise RuntimeError("CAPSOLVER_API_KEY not set in Doppler")
        if not _budget.can_solve():
            raise RuntimeError("CAPTCHA daily budget exceeded")

        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.capsolver.com/createTask",
                json={
                    "clientKey": self._api_key,
                    "task": {"type": task_type, **task_params},
                },
            )
            data = resp.json()
            task_id = data.get("taskId")
            if not task_id:
                raise RuntimeError(f"CapSolver createTask failed: {data}")

            # Poll for result
            for _ in range(60):
                import asyncio
                await asyncio.sleep(3)
                resp = await client.post(
                    "https://api.capsolver.com/getTaskResult",
                    json={"clientKey": self._api_key, "taskId": task_id},
                )
                result = resp.json()
                if result.get("status") == "ready":
                    _budget.record_solve()
                    solution = result.get("solution", {})
                    return solution.get("gRecaptchaResponse") or solution.get("text", "")

            raise RuntimeError("CapSolver timeout")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_solver() -> CaptchaSolver:
    """Return the configured solver based on CAPTCHA_PROVIDER in Doppler."""
    provider = settings.captcha_provider.lower()
    if provider == "capsolver":
        return CapSolverSolver()
    return TwoCaptchaSolver()  # default


# ---------------------------------------------------------------------------
# Playwright helpers
# ---------------------------------------------------------------------------

async def detect_and_solve_captcha(page, solver: CaptchaSolver | None = None) -> bool:
    """Check if the current page has a CAPTCHA and solve it.

    Returns True if a CAPTCHA was found and solved, False if none found.
    Raises on failure.
    """
    if solver is None:
        solver = get_solver()

    # Check for reCAPTCHA
    recaptcha_frame = await page.query_selector("iframe[src*='recaptcha']")
    if recaptcha_frame:
        src = await recaptcha_frame.get_attribute("src") or ""
        # Extract site key from parent div
        site_key_el = await page.query_selector("[data-sitekey]")
        if site_key_el:
            site_key = await site_key_el.get_attribute("data-sitekey")
            if site_key:
                token = await solver.solve_recaptcha_v2(site_key, page.url)
                await page.evaluate(
                    f'document.querySelector("#g-recaptcha-response").value = "{token}";'
                )
                # Try to trigger the callback
                await page.evaluate(
                    "try { ___grecaptcha_cfg.clients[0].o.o.callback(arguments[0]); } catch(e) {}"
                    f'("{token}")'
                )
                return True

    # Check for hCaptcha
    hcaptcha_frame = await page.query_selector("iframe[src*='hcaptcha']")
    if hcaptcha_frame:
        site_key_el = await page.query_selector("[data-sitekey]")
        if site_key_el:
            site_key = await site_key_el.get_attribute("data-sitekey")
            if site_key:
                token = await solver.solve_hcaptcha(site_key, page.url)
                await page.evaluate(
                    f'document.querySelector("[name=h-captcha-response]").value = "{token}";'
                )
                return True

    return False
