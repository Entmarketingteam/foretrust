"""Tests for app/connectors/registry.py."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_connector_class(source_key: str):
    """Create a minimal mock connector class with the required source_key attribute."""
    from app.connectors.base import BaseConnector
    from app.models import Vertical

    # Build a real subclass so isinstance checks pass
    cls = type(
        f"Mock{source_key.title().replace('_', '')}Connector",
        (),
        {
            "source_key": source_key,
            "vertical": Vertical.RESIDENTIAL,
            "jurisdiction": "KY-Test",
            "base_url": "https://example.com",
            "default_schedule": "0 6 * * *",
            "fetch": MagicMock(),
            "parse": MagicMock(),
        },
    )
    return cls


# ---------------------------------------------------------------------------
# get_connector
# ---------------------------------------------------------------------------

class TestGetConnector:

    def test_get_connector_returns_instance_for_known_key(self):
        """get_connector() returns an instance of the registered class."""
        from app.connectors import registry

        test_cls = _make_connector_class("test_source_a")

        # Temporarily patch the registry
        original = dict(registry._REGISTRY)
        try:
            registry._REGISTRY["test_source_a"] = test_cls
            result = registry.get_connector("test_source_a")
            assert isinstance(result, test_cls)
        finally:
            registry._REGISTRY.clear()
            registry._REGISTRY.update(original)

    def test_get_connector_raises_key_error_for_unknown_key(self):
        """get_connector() raises KeyError for an unregistered source_key."""
        from app.connectors import registry

        with pytest.raises(KeyError, match="Unknown source_key"):
            registry.get_connector("definitely_not_registered_xyz")

    def test_get_connector_error_message_lists_available_keys(self):
        """The KeyError message includes available connector keys."""
        from app.connectors import registry

        original = dict(registry._REGISTRY)
        try:
            test_cls = _make_connector_class("test_source_b")
            registry._REGISTRY["test_source_b"] = test_cls
            with pytest.raises(KeyError) as exc_info:
                registry.get_connector("no_such_source")
            assert "test_source_b" in str(exc_info.value)
        finally:
            registry._REGISTRY.clear()
            registry._REGISTRY.update(original)

    def test_get_connector_instantiates_new_object_each_call(self):
        """Each call to get_connector() returns a fresh instance."""
        from app.connectors import registry

        test_cls = _make_connector_class("test_source_c")
        original = dict(registry._REGISTRY)
        try:
            registry._REGISTRY["test_source_c"] = test_cls
            inst1 = registry.get_connector("test_source_c")
            inst2 = registry.get_connector("test_source_c")
            assert inst1 is not inst2
        finally:
            registry._REGISTRY.clear()
            registry._REGISTRY.update(original)


# ---------------------------------------------------------------------------
# list_connectors
# ---------------------------------------------------------------------------

class TestListConnectors:

    def test_list_connectors_returns_dict(self):
        """list_connectors() returns a dict."""
        from app.connectors import registry

        result = registry.list_connectors()
        assert isinstance(result, dict)

    def test_list_connectors_returns_all_registered_keys(self):
        """list_connectors() includes all registered connector keys."""
        from app.connectors import registry

        # After _load_all() runs on import, we know some connectors are registered
        result = registry.list_connectors()
        # At minimum the residential connectors from _load_all should be present
        assert "kcoj_courtnet" in result
        assert "fayette_pva" in result

    def test_list_connectors_returns_copy_not_original(self):
        """list_connectors() returns a copy so mutating it doesn't affect the registry."""
        from app.connectors import registry

        result = registry.list_connectors()
        original_len = len(result)
        result["injected_key"] = None

        # The real registry should be unaffected
        assert "injected_key" not in registry._REGISTRY

    def test_list_connectors_includes_newly_registered(self):
        """A connector added to _REGISTRY appears in list_connectors()."""
        from app.connectors import registry

        test_cls = _make_connector_class("test_list_source")
        original = dict(registry._REGISTRY)
        try:
            registry._REGISTRY["test_list_source"] = test_cls
            result = registry.list_connectors()
            assert "test_list_source" in result
        finally:
            registry._REGISTRY.clear()
            registry._REGISTRY.update(original)


# ---------------------------------------------------------------------------
# @register decorator
# ---------------------------------------------------------------------------

class TestRegisterDecorator:

    def test_register_adds_connector_to_registry(self):
        """@register adds a connector class to _REGISTRY under its source_key."""
        from app.connectors import registry

        original = dict(registry._REGISTRY)
        try:
            @registry.register
            class DummyConnectorForTest:
                source_key = "dummy_test_connector"

            assert "dummy_test_connector" in registry._REGISTRY
            assert registry._REGISTRY["dummy_test_connector"] is DummyConnectorForTest
        finally:
            registry._REGISTRY.pop("dummy_test_connector", None)
            # Restore any keys removed (should be none, we only added)
            for k, v in original.items():
                if k not in registry._REGISTRY:
                    registry._REGISTRY[k] = v

    def test_register_returns_original_class_unchanged(self):
        """@register is a transparent decorator — it returns the original class."""
        from app.connectors import registry

        original = dict(registry._REGISTRY)
        try:
            class AnotherDummyConnector:
                source_key = "another_dummy_connector"

            result = registry.register(AnotherDummyConnector)
            assert result is AnotherDummyConnector
        finally:
            registry._REGISTRY.pop("another_dummy_connector", None)

    def test_register_overwrites_existing_key(self):
        """Registering a second class with the same source_key overwrites the first."""
        from app.connectors import registry

        original = dict(registry._REGISTRY)
        try:
            class ConnectorV1:
                source_key = "overwrite_test"

            class ConnectorV2:
                source_key = "overwrite_test"

            registry.register(ConnectorV1)
            registry.register(ConnectorV2)
            assert registry._REGISTRY["overwrite_test"] is ConnectorV2
        finally:
            registry._REGISTRY.pop("overwrite_test", None)


# ---------------------------------------------------------------------------
# Known connectors are registered (smoke test for _load_all)
# ---------------------------------------------------------------------------

class TestKnownConnectorsRegistered:
    """Verify that _load_all() has registered the expected residential connectors."""

    @pytest.mark.parametrize("source_key", [
        "kcoj_courtnet",
        "fayette_pva",
        "scott_pva",
        "oldham_pva",
        "zillow_public",
        "ecclix_batch",
        "ky_state_gis",
        "legal_notices",
    ])
    def test_known_connector_is_registered(self, source_key):
        from app.connectors import registry

        assert source_key in registry._REGISTRY, (
            f"Expected '{source_key}' to be registered but only found: "
            f"{sorted(registry._REGISTRY.keys())}"
        )
