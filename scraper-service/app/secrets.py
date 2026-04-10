"""Doppler SDK wrapper for runtime secret re-fetch.

Default path is os.environ (populated by `doppler run --` at process start).
This module is only used when a long-running job needs to refresh a secret
(e.g., rotated proxy creds) without restarting the process.
"""

from __future__ import annotations

import os
import logging

logger = logging.getLogger(__name__)


class DopplerSecrets:
    """Thin wrapper around the Doppler SDK for runtime rotation."""

    def __init__(self) -> None:
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return
        token = os.environ.get("DOPPLER_TOKEN", "")
        if not token:
            logger.warning("DOPPLER_TOKEN not set; runtime re-fetch disabled")
            return
        try:
            from doppler_sdk import DopplerSDK
            self._client = DopplerSDK()
            self._client.set_access_token(token)
        except ImportError:
            logger.warning("doppler-sdk not installed; runtime re-fetch disabled")

    def get(self, key: str, default: str = "") -> str:
        """Get a secret value. Falls back to os.environ, then default."""
        # Fast path: os.environ (populated by doppler run)
        val = os.environ.get(key, "")
        if val:
            return val

        # Slow path: SDK fetch for runtime-rotated secrets
        self._ensure_client()
        if self._client is not None:
            try:
                result = self._client.secrets.get(
                    project=os.environ.get("DOPPLER_PROJECT", "foretrust-scraper"),
                    config=os.environ.get("DOPPLER_CONFIG", "dev"),
                    name=key,
                )
                if result and hasattr(result, "value") and result.value:
                    return result.value.raw
            except Exception as exc:
                logger.warning("Doppler SDK fetch failed for %s: %s", key, exc)

        return default

    def refresh(self, key: str) -> str:
        """Force re-fetch a secret from Doppler, bypassing os.environ cache."""
        self._ensure_client()
        if self._client is None:
            return os.environ.get(key, "")
        try:
            result = self._client.secrets.get(
                project=os.environ.get("DOPPLER_PROJECT", "foretrust-scraper"),
                config=os.environ.get("DOPPLER_CONFIG", "dev"),
                name=key,
            )
            if result and hasattr(result, "value") and result.value:
                val = result.value.raw
                os.environ[key] = val  # Update cache
                return val
        except Exception as exc:
            logger.warning("Doppler SDK refresh failed for %s: %s", key, exc)
        return os.environ.get(key, "")


doppler_secrets = DopplerSecrets()
