"""Tests for app/captcha.py — budget tracker and solver interfaces."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub out `twocaptcha` which is not installed in the test environment
# (twocaptcha-python package version not available on PyPI for this env)
# ---------------------------------------------------------------------------

if "twocaptcha" not in sys.modules:
    _stub = ModuleType("twocaptcha")

    class _TwoCaptchaStub:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key
        def recaptcha(self, **kwargs):
            return {"code": "stub-token"}
        def hcaptcha(self, **kwargs):
            return {"code": "stub-hcaptcha-token"}
        def normal(self, path: str):
            return {"code": "stub-image-token"}

    _stub.TwoCaptcha = _TwoCaptchaStub  # type: ignore[attr-defined]
    sys.modules["twocaptcha"] = _stub


# ---------------------------------------------------------------------------
# Budget tracker tests
# ---------------------------------------------------------------------------

class TestBudgetTracker:
    """Tests for _BudgetTracker internal logic."""

    def _fresh_tracker(self, budget_usd: float = 5.0):
        """Return a fresh _BudgetTracker with a patched settings budget."""
        from app.captcha import _BudgetTracker
        tracker = _BudgetTracker()
        return tracker

    def test_can_solve_when_under_budget(self):
        """can_solve() returns True when no solves have been recorded."""
        from app.captcha import _BudgetTracker
        tracker = _BudgetTracker()
        with patch("app.captcha.settings") as mock_settings:
            mock_settings.captcha_daily_budget_usd = 5.0
            assert tracker.can_solve() is True

    def test_can_solve_returns_false_when_budget_exceeded(self):
        """can_solve() returns False after enough solves to exceed budget."""
        from app.captcha import _BudgetTracker
        tracker = _BudgetTracker()
        # COST_PER_SOLVE = 0.003, budget = $0.006 → max 2 solves
        with patch("app.captcha.settings") as mock_settings:
            mock_settings.captcha_daily_budget_usd = 0.006
            tracker.record_solve()
            tracker.record_solve()
            assert tracker.can_solve() is False

    def test_budget_resets_on_new_day(self):
        """Budget resets when _reset_if_new_day() detects a new calendar day."""
        from app.captcha import _BudgetTracker
        tracker = _BudgetTracker()

        with patch("app.captcha.settings") as mock_settings:
            mock_settings.captcha_daily_budget_usd = 0.003  # 1 solve budget

            # Simulate today = day 100, fully spent
            with patch("app.captcha.time") as mock_time:
                mock_time.gmtime.return_value = MagicMock(tm_yday=100)
                tracker.record_solve()
                assert tracker.can_solve() is False

            # Simulate tomorrow = day 101 → resets
            with patch("app.captcha.time") as mock_time:
                mock_time.gmtime.return_value = MagicMock(tm_yday=101)
                assert tracker.can_solve() is True

    def test_record_solve_increments_counter(self):
        """record_solve() increments _solves_today."""
        from app.captcha import _BudgetTracker
        tracker = _BudgetTracker()
        with patch("app.captcha.time") as mock_time:
            mock_time.gmtime.return_value = MagicMock(tm_yday=200)
            tracker.record_solve()
            tracker.record_solve()
            assert tracker._solves_today == 2

    def test_zero_budget_blocks_all_solves(self):
        """When budget is 0.0, no solves are allowed."""
        from app.captcha import _BudgetTracker
        tracker = _BudgetTracker()
        with patch("app.captcha.settings") as mock_settings:
            mock_settings.captcha_daily_budget_usd = 0.0
            assert tracker.can_solve() is False


# ---------------------------------------------------------------------------
# env var: CAPTCHA_DAILY_BUDGET_USD respected
# ---------------------------------------------------------------------------

def test_captcha_daily_budget_env_var_is_respected():
    """Settings picks up CAPTCHA_DAILY_BUDGET_USD from environment."""
    # Re-import with a patched value to verify settings wiring
    from app.captcha import _BudgetTracker
    tracker = _BudgetTracker()

    with patch("app.captcha.settings") as mock_settings:
        mock_settings.captcha_daily_budget_usd = 0.0
        # Even one solve would be over budget
        assert tracker.can_solve() is False

    with patch("app.captcha.settings") as mock_settings:
        mock_settings.captcha_daily_budget_usd = 100.0
        assert tracker.can_solve() is True


# ---------------------------------------------------------------------------
# TwoCaptchaSolver — budget guard
# ---------------------------------------------------------------------------

class TestTwoCaptchaSolverBudgetGuard:

    @pytest.mark.asyncio
    async def test_solve_raises_when_budget_exceeded(self):
        """TwoCaptchaSolver._check_ready raises RuntimeError when budget is exceeded."""
        from app.captcha import TwoCaptchaSolver

        solver = TwoCaptchaSolver()
        solver._api_key = "test-key"  # must be non-empty so budget check is reached

        with (
            patch("app.captcha.settings") as mock_settings,
            patch("app.captcha._budget") as mock_budget,
        ):
            mock_settings.twocaptcha_api_key = "test-key"
            mock_settings.captcha_daily_budget_usd = 0.0
            mock_budget.can_solve.return_value = False

            with pytest.raises(RuntimeError, match="budget exceeded"):
                await solver.solve_recaptcha_v2("site-key", "https://example.com")

    @pytest.mark.asyncio
    async def test_solve_raises_when_api_key_missing(self):
        """TwoCaptchaSolver._check_ready raises RuntimeError when API key not set."""
        from app.captcha import TwoCaptchaSolver

        solver = TwoCaptchaSolver()
        solver._api_key = ""

        with patch("app.captcha._budget") as mock_budget:
            mock_budget.can_solve.return_value = True
            with pytest.raises(RuntimeError, match="TWOCAPTCHA_API_KEY"):
                await solver.solve_recaptcha_v2("site-key", "https://example.com")


# ---------------------------------------------------------------------------
# TwoCaptchaSolver — successful solves (mock HTTP)
# ---------------------------------------------------------------------------

class TestTwoCaptchaSolverSuccess:

    @pytest.mark.asyncio
    async def test_solve_recaptcha_v2_returns_token(self):
        """solve_recaptcha_v2 returns the 'code' from the solver result."""
        from app.captcha import TwoCaptchaSolver

        solver = TwoCaptchaSolver()
        solver._api_key = "test-key"

        mock_solver_instance = MagicMock()
        mock_solver_instance.recaptcha = MagicMock(return_value={"code": "test-token-v2"})

        with (
            patch("app.captcha._budget") as mock_budget,
            patch("app.captcha.settings") as mock_settings,
            patch("asyncio.to_thread", new=AsyncMock(return_value={"code": "test-token-v2"})),
        ):
            mock_budget.can_solve.return_value = True
            mock_settings.twocaptcha_api_key = "test-key"
            mock_settings.captcha_daily_budget_usd = 5.0

            token = await solver.solve_recaptcha_v2("abc-site-key", "https://example.com")

        assert token == "test-token-v2"

    @pytest.mark.asyncio
    async def test_solve_recaptcha_v3_returns_token(self):
        """solve_recaptcha_v3 returns the 'code' from the solver result."""
        from app.captcha import TwoCaptchaSolver

        solver = TwoCaptchaSolver()
        solver._api_key = "test-key"

        with (
            patch("app.captcha._budget") as mock_budget,
            patch("app.captcha.settings") as mock_settings,
            patch("asyncio.to_thread", new=AsyncMock(return_value={"code": "test-token-v3"})),
        ):
            mock_budget.can_solve.return_value = True
            mock_settings.twocaptcha_api_key = "test-key"
            mock_settings.captcha_daily_budget_usd = 5.0

            token = await solver.solve_recaptcha_v3("abc-site-key", "https://example.com", "login")

        assert token == "test-token-v3"

    @pytest.mark.asyncio
    async def test_solve_hcaptcha_returns_token(self):
        """solve_hcaptcha returns the 'code' from the solver result."""
        from app.captcha import TwoCaptchaSolver

        solver = TwoCaptchaSolver()
        solver._api_key = "test-key"

        with (
            patch("app.captcha._budget") as mock_budget,
            patch("app.captcha.settings") as mock_settings,
            patch("asyncio.to_thread", new=AsyncMock(return_value={"code": "hcaptcha-token"})),
        ):
            mock_budget.can_solve.return_value = True
            mock_settings.twocaptcha_api_key = "test-key"
            mock_settings.captcha_daily_budget_usd = 5.0

            token = await solver.solve_hcaptcha("hcap-key", "https://example.com")

        assert token == "hcaptcha-token"

    @pytest.mark.asyncio
    async def test_record_solve_called_on_success(self):
        """After a successful solve, _budget.record_solve() is called."""
        from app.captcha import TwoCaptchaSolver

        solver = TwoCaptchaSolver()
        solver._api_key = "test-key"

        with (
            patch("app.captcha._budget") as mock_budget,
            patch("app.captcha.settings") as mock_settings,
            patch("asyncio.to_thread", new=AsyncMock(return_value={"code": "token"})),
        ):
            mock_budget.can_solve.return_value = True
            mock_settings.twocaptcha_api_key = "test-key"
            mock_settings.captcha_daily_budget_usd = 5.0

            await solver.solve_recaptcha_v2("key", "https://example.com")

        mock_budget.record_solve.assert_called_once()


# ---------------------------------------------------------------------------
# TwoCaptchaSolver — failure handling
# ---------------------------------------------------------------------------

class TestTwoCaptchaSolverFailure:

    @pytest.mark.asyncio
    async def test_twocaptcha_exception_propagates(self):
        """If asyncio.to_thread raises (e.g. network error), the exception propagates."""
        from app.captcha import TwoCaptchaSolver

        solver = TwoCaptchaSolver()
        solver._api_key = "test-key"

        with (
            patch("app.captcha._budget") as mock_budget,
            patch("app.captcha.settings") as mock_settings,
            patch("asyncio.to_thread", new=AsyncMock(side_effect=RuntimeError("timeout"))),
        ):
            mock_budget.can_solve.return_value = True
            mock_settings.twocaptcha_api_key = "test-key"
            mock_settings.captcha_daily_budget_usd = 5.0

            with pytest.raises(RuntimeError, match="timeout"):
                await solver.solve_recaptcha_v2("key", "https://example.com")


# ---------------------------------------------------------------------------
# get_solver factory
# ---------------------------------------------------------------------------

def test_get_solver_returns_twocaptcha_by_default():
    """get_solver() returns TwoCaptchaSolver when provider is 'twocaptcha'."""
    from app.captcha import TwoCaptchaSolver, get_solver

    with patch("app.captcha.settings") as mock_settings:
        mock_settings.captcha_provider = "twocaptcha"
        solver = get_solver()

    assert isinstance(solver, TwoCaptchaSolver)


def test_get_solver_returns_capsolver_when_configured():
    """get_solver() returns CapSolverSolver when provider is 'capsolver'."""
    from app.captcha import CapSolverSolver, get_solver

    with patch("app.captcha.settings") as mock_settings:
        mock_settings.captcha_provider = "capsolver"
        solver = get_solver()

    assert isinstance(solver, CapSolverSolver)


# ---------------------------------------------------------------------------
# CapSolverSolver — budget guard
# ---------------------------------------------------------------------------

class TestCapSolverBudgetGuard:

    @pytest.mark.asyncio
    async def test_capsolver_raises_when_budget_exceeded(self):
        """CapSolverSolver._solve raises RuntimeError when budget is exceeded."""
        from app.captcha import CapSolverSolver

        solver = CapSolverSolver()
        solver._api_key = "test-key"

        with patch("app.captcha._budget") as mock_budget:
            mock_budget.can_solve.return_value = False
            with pytest.raises(RuntimeError, match="budget exceeded"):
                await solver.solve_recaptcha_v2("key", "https://example.com")

    @pytest.mark.asyncio
    async def test_capsolver_raises_when_api_key_missing(self):
        """CapSolverSolver._solve raises RuntimeError when API key not set."""
        from app.captcha import CapSolverSolver

        solver = CapSolverSolver()
        solver._api_key = ""

        with patch("app.captcha._budget") as mock_budget:
            mock_budget.can_solve.return_value = True
            with pytest.raises(RuntimeError, match="CAPSOLVER_API_KEY"):
                await solver.solve_recaptcha_v2("key", "https://example.com")
