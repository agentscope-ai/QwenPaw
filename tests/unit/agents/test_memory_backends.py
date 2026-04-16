# -*- coding: utf-8 -*-
"""Tests for the extensible memory backend system."""

# pylint: disable=unused-import,unused-argument,abstract-class-instantiated,
# pylint: disable=protected-access

import asyncio

import pytest

# ---------------------------------------------------------------------------
# 1. InMemoryMemoryProtocol tests
# ---------------------------------------------------------------------------


class TestInMemoryMemoryProtocol:
    """Test the InMemoryMemoryProtocol structural typing."""

    def test_conforming_object_satisfies_protocol(self):
        """An object with the required methods should satisfy the protocol."""
        from qwenpaw.agents.memory.protocols import InMemoryMemoryProtocol

        class FakeMemory:
            _long_term_memory = ""

            def load_state_dict(self, state, **kwargs):
                pass

            def get_compressed_summary(self):
                return None

            async def get_memory(self, prepend_summary=True):
                return []

            async def mark_messages_compressed(self, messages):
                return 0

            async def update_compressed_summary(self, summary):
                pass

        obj = FakeMemory()
        assert isinstance(obj, InMemoryMemoryProtocol)

    def test_non_conforming_object_fails_protocol(self):
        """An object missing required methods should not satisfy protocol."""
        from qwenpaw.agents.memory.protocols import InMemoryMemoryProtocol

        class IncompleteMemory:
            pass

        obj = IncompleteMemory()
        assert not isinstance(obj, InMemoryMemoryProtocol)


# ---------------------------------------------------------------------------
# 2. BaseMemoryManager abstract interface tests
# ---------------------------------------------------------------------------


class TestBaseMemoryManager:
    """Test BaseMemoryManager abstract class behavior."""

    def _make_concrete_class(self):
        """Create a minimal concrete subclass for testing."""
        from qwenpaw.agents.memory import BaseMemoryManager

        class DummyMemoryManager(BaseMemoryManager):
            @classmethod
            def backend_name(cls):
                return "dummy"

            @classmethod
            def backend_label(cls):
                return "Dummy"

            async def start(self):
                pass

            async def close(self):
                return True

            async def compact_tool_result(self, **kwargs):
                pass

            async def check_context(self, **kwargs):
                return ([], [], True)

            async def compact_memory(
                self,
                messages,
                previous_summary="",
                extra_instruction="",
                **kwargs,
            ):
                return ""

            async def summary_memory(self, messages, **kwargs):
                return ""

            async def memory_search(self, query, max_results=5, min_score=0.1):
                from agentscope.tool import ToolResponse

                return ToolResponse(content=[])

            def get_in_memory_memory(self, **kwargs):
                return None

        return DummyMemoryManager

    def test_cannot_instantiate_abstract(self):
        """BaseMemoryManager cannot be instantiated directly."""
        from qwenpaw.agents.memory import BaseMemoryManager

        with pytest.raises(TypeError):
            BaseMemoryManager(working_dir="/tmp", agent_id="test")

    def test_concrete_init_with_backend_config(self):
        """Concrete subclass accepts and stores backend_config."""
        cls = self._make_concrete_class()
        mgr = cls(
            working_dir="/tmp",
            agent_id="test",
            backend_config={"api_key": "abc"},
        )
        assert mgr.backend_config == {"api_key": "abc"}
        assert mgr.working_dir == "/tmp"
        assert mgr.agent_id == "test"

    def test_concrete_init_without_backend_config(self):
        """Concrete subclass works without backend_config."""
        cls = self._make_concrete_class()
        mgr = cls(working_dir="/tmp", agent_id="test")
        assert mgr.backend_config == {}

    def test_backend_name_method(self):
        """backend_name() returns the correct identifier."""
        cls = self._make_concrete_class()
        assert cls.backend_name() == "dummy"

    def test_backend_label_method(self):
        """backend_label() returns the correct display name."""
        cls = self._make_concrete_class()
        assert cls.backend_label() == "Dummy"

    def test_dream_memory_default_noop(self):
        """dream_memory() default implementation does not raise."""
        cls = self._make_concrete_class()
        mgr = cls(working_dir="/tmp", agent_id="test")
        # Should not raise
        asyncio.get_event_loop().run_until_complete(mgr.dream_memory())

    def test_base_backend_name_raises(self):
        """Base class backend_name() raises NotImplementedError."""
        from qwenpaw.agents.memory import BaseMemoryManager

        with pytest.raises(NotImplementedError):
            BaseMemoryManager.backend_name()

    def test_base_backend_label_raises(self):
        """Base class backend_label() raises NotImplementedError."""
        from qwenpaw.agents.memory import BaseMemoryManager

        with pytest.raises(NotImplementedError):
            BaseMemoryManager.backend_label()


# ---------------------------------------------------------------------------
# 3. ReMeLightMemoryManager metadata tests
# ---------------------------------------------------------------------------


class TestReMeLightMetadata:
    """Test ReMeLightMemoryManager backend metadata methods."""

    def test_backend_name(self):
        from qwenpaw.agents.memory import ReMeLightMemoryManager

        assert ReMeLightMemoryManager.backend_name() == "remelight"

    def test_backend_label(self):
        from qwenpaw.agents.memory import ReMeLightMemoryManager

        assert ReMeLightMemoryManager.backend_label() == "ReMeLight"


# ---------------------------------------------------------------------------
# 4. PluginRegistry memory backend registration tests
# ---------------------------------------------------------------------------


class TestPluginRegistryMemoryBackends:
    """Test memory backend registration via PluginRegistry."""

    def _setup_registry(self):
        """Get a fresh registry for testing."""
        from qwenpaw.plugins.registry import PluginRegistry

        # Reset singleton for test isolation
        PluginRegistry._instance = None  # pylint: disable=protected-access
        return PluginRegistry()

    def _teardown_registry(self):
        from qwenpaw.plugins.registry import PluginRegistry

        PluginRegistry._instance = None  # pylint: disable=protected-access

    def test_register_and_get_memory_backend(self):
        """Register a memory backend and retrieve it."""
        try:
            registry = self._setup_registry()

            class FakeBackend:
                pass

            registry.register_memory_backend(
                plugin_id="test-plugin",
                backend_id="fake",
                backend_class=FakeBackend,
                label="Fake Backend",
                description="A fake backend for testing",
            )

            reg = registry.get_memory_backend("fake")
            assert reg is not None
            assert reg.backend_id == "fake"
            assert reg.backend_class is FakeBackend
            assert reg.label == "Fake Backend"
            assert reg.description == "A fake backend for testing"
            assert reg.plugin_id == "test-plugin"
        finally:
            self._teardown_registry()

    def test_get_nonexistent_backend_returns_none(self):
        """Getting a non-existent backend returns None."""
        try:
            registry = self._setup_registry()
            assert registry.get_memory_backend("nonexistent") is None
        finally:
            self._teardown_registry()

    def test_duplicate_registration_raises(self):
        """Registering the same backend_id twice raises ValueError."""
        try:
            registry = self._setup_registry()

            class FakeBackend:
                pass

            registry.register_memory_backend(
                plugin_id="p1",
                backend_id="dup",
                backend_class=FakeBackend,
                label="First",
            )
            with pytest.raises(ValueError, match="already registered"):
                registry.register_memory_backend(
                    plugin_id="p2",
                    backend_id="dup",
                    backend_class=FakeBackend,
                    label="Second",
                )
        finally:
            self._teardown_registry()

    def test_get_all_memory_backends(self):
        """get_all_memory_backends returns all registered backends."""
        try:
            registry = self._setup_registry()

            class B1:
                pass

            class B2:
                pass

            registry.register_memory_backend("p1", "b1", B1, "B1")
            registry.register_memory_backend("p2", "b2", B2, "B2")

            all_backends = registry.get_all_memory_backends()
            assert len(all_backends) == 2
            assert "b1" in all_backends
            assert "b2" in all_backends
        finally:
            self._teardown_registry()


# ---------------------------------------------------------------------------
# 5. PluginApi register_memory_backend tests
# ---------------------------------------------------------------------------


class TestPluginApiMemoryBackend:
    """Test register_memory_backend via PluginApi."""

    def test_api_registers_memory_backend(self):
        """PluginApi.register_memory_backend delegates to registry."""
        from qwenpaw.plugins.api import PluginApi
        from qwenpaw.plugins.registry import PluginRegistry

        # Reset singleton
        PluginRegistry._instance = None  # pylint: disable=protected-access
        try:
            registry = PluginRegistry()
            api = PluginApi(plugin_id="test-plugin", config={})
            api.set_registry(registry)

            class FakeBackend:
                pass

            api.register_memory_backend(
                backend_id="fake",
                backend_class=FakeBackend,
                label="Fake",
                description="Test backend",
            )

            reg = registry.get_memory_backend("fake")
            assert reg is not None
            assert reg.backend_class is FakeBackend
            assert reg.plugin_id == "test-plugin"
        finally:
            PluginRegistry._instance = None  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# 6. _resolve_memory_class tests
# ---------------------------------------------------------------------------


class TestResolveMemoryClass:
    """Test workspace._resolve_memory_class resolution logic."""

    def _call_resolve(self, backend: str):
        from qwenpaw.app.workspace.workspace import _resolve_memory_class

        return _resolve_memory_class(backend)

    def test_builtin_remelight(self):
        """Built-in 'remelight' backend resolves correctly."""
        from qwenpaw.agents.memory import ReMeLightMemoryManager

        cls = self._call_resolve("remelight")
        assert cls is ReMeLightMemoryManager

    def test_plugin_registered_backend(self):
        """Plugin-registered backend resolves correctly."""
        from qwenpaw.plugins.registry import PluginRegistry

        PluginRegistry._instance = None  # pylint: disable=protected-access
        try:
            registry = PluginRegistry()

            class FakeBackend:
                pass

            registry.register_memory_backend(
                plugin_id="test",
                backend_id="fake",
                backend_class=FakeBackend,
                label="Fake",
            )

            cls = self._call_resolve("fake")
            assert cls is FakeBackend
        finally:
            PluginRegistry._instance = None  # pylint: disable=protected-access

    def test_unknown_backend_raises(self):
        """Unknown backend raises ConfigurationException."""
        from agentscope_runtime.engine.schemas.exception import (
            ConfigurationException,
        )

        with pytest.raises(ConfigurationException):
            self._call_resolve("nonexistent_backend")


# ---------------------------------------------------------------------------
# 7. Config schema tests
# ---------------------------------------------------------------------------


class TestMemoryConfigSchema:
    """Test that the config schema accepts extended memory backends."""

    def test_default_backend_is_remelight(self):
        """Default memory_manager_backend is 'remelight'."""
        from qwenpaw.config.config import AgentsRunningConfig

        cfg = AgentsRunningConfig()
        assert cfg.memory_manager_backend == "remelight"

    def test_default_backend_config_is_empty(self):
        """Default memory_backend_config is an empty dict."""
        from qwenpaw.config.config import AgentsRunningConfig

        cfg = AgentsRunningConfig()
        assert cfg.memory_backend_config == {}

    def test_custom_backend_string_accepted(self):
        """Custom backend string is accepted by the schema."""
        from qwenpaw.config.config import AgentsRunningConfig

        cfg = AgentsRunningConfig(
            memory_manager_backend="mem0",
            memory_backend_config={"api_key": "test123"},
        )
        assert cfg.memory_manager_backend == "mem0"
        assert cfg.memory_backend_config["api_key"] == "test123"

    def test_backward_compat_remelight_literal(self):
        """String 'remelight' still works (backward compat)."""
        from qwenpaw.config.config import AgentsRunningConfig

        cfg = AgentsRunningConfig(memory_manager_backend="remelight")
        assert cfg.memory_manager_backend == "remelight"
