"""Connector registry: source_key → connector class mapping.

Import all connectors here. Adding a new source = one import + one dict entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.connectors.base import BaseConnector

_REGISTRY: dict[str, type["BaseConnector"]] = {}


def register(cls: type["BaseConnector"]) -> type["BaseConnector"]:
    """Decorator to register a connector class."""
    _REGISTRY[cls.source_key] = cls
    return cls


def get_connector(source_key: str) -> "BaseConnector":
    """Instantiate a connector by source_key."""
    cls = _REGISTRY.get(source_key)
    if cls is None:
        available = ", ".join(sorted(_REGISTRY.keys()))
        raise KeyError(f"Unknown source_key '{source_key}'. Available: {available}")
    return cls()


def list_connectors() -> dict[str, type["BaseConnector"]]:
    """Return all registered connectors."""
    return dict(_REGISTRY)


def _load_all() -> None:
    """Import all connector modules to trigger @register decorators."""
    # Residential
    import app.connectors.residential.kcoj_courtnet  # noqa: F401
    import app.connectors.residential.fayette_pva  # noqa: F401
    import app.connectors.residential.scott_pva  # noqa: F401
    import app.connectors.residential.oldham_pva  # noqa: F401
    import app.connectors.residential.zillow_public  # noqa: F401
    import app.connectors.residential.ecclix_batch  # noqa: F401
    import app.connectors.residential.ky_state_gis  # noqa: F401
    import app.connectors.residential.legal_notices  # noqa: F401

    # Commercial (stubs)
    import app.connectors.commercial  # noqa: F401

    # Multifamily (stubs)
    import app.connectors.multifamily  # noqa: F401


_load_all()
