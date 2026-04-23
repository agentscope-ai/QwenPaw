# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access
"""Tests for ReMeLightMemoryManager."""
import importlib.metadata
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# All dependencies (agentscope, agentscope_runtime, reme, chromadb) are
# installed in the venv. Do NOT mock installed packages — replacing them
# with MagicMock() breaks submodule resolution for other test modules that
# run in the same process (global sys.modules pollution).
#
# Only mock reme.reme_light so ReMeLight constructor is controllable.
_MOCK_MODULES = [
    "reme",
    "reme.reme_light",
    "reme.memory",
    "reme.memory.file_based",
    "reme.memory.file_based.reme_in_memory_memory",
]
for _mod in _MOCK_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# ---------------------------------------------------------------------------
# Module-level shortcut for the patch target prefix
# ---------------------------------------------------------------------------
_MOD = "qwenpaw.agents.memory.reme_light_memory_manager"


# ---------------------------------------------------------------------------
# Helpers to build a minimal agent config mock
# ---------------------------------------------------------------------------


def _make_agent_config(
    rebuild_on_start=False,
    memory_summary_enabled=True,
):
    cfg = MagicMock()
    cfg.running.memory_summary.rebuild_memory_index_on_start = rebuild_on_start
    cfg.running.memory_summary.enabled = memory_summary_enabled
    # New path (upstream refactor)
    emc = cfg.running.reme_light_memory_config.embedding_model_config
    cfg._emc = emc  # shortcut for tests that need to override api_key
    emc.backend = "openai"
    emc.api_key = "testkey"
    emc.base_url = "http://localhost"
    emc.model_name = "text-emb-3"
    emc.dimensions = 1536
    emc.enable_cache = False
    emc.use_dimensions = False
    emc.max_cache_size = 100
    emc.max_input_length = 8192
    emc.max_batch_size = 32
    # Legacy path (older installed version compat)
    cfg.running.embedding_config.backend = "openai"
    cfg.running.embedding_config.api_key = "testkey"
    cfg.running.embedding_config.base_url = "http://localhost"
    cfg.running.embedding_config.model_name = "text-emb-3"
    cfg.running.embedding_config.dimensions = 1536
    cfg.running.embedding_config.enable_cache = False
    cfg.running.embedding_config.use_dimensions = False
    cfg.running.embedding_config.max_cache_size = 100
    cfg.running.embedding_config.max_input_length = 8192
    cfg.running.embedding_config.max_batch_size = 32
    cfg.running.context_compact.memory_compact_ratio = 0.5
    cfg.running.context_compact.compact_with_thinking_block = False
    cfg.running.tool_result_compact.recent_max_bytes = 1024
    cfg.running.max_input_length = 100000
    cfg.language = "en"
    cfg.workspace_dir = "/tmp/test_ws"
    return cfg


def _build_manager(tmp_path, mock_reme, agent_config):
    """Construct a ReMeLightMemoryManager with all deps patched."""
    with (
        patch("reme.reme_light.ReMeLight", return_value=mock_reme),
        patch(
            f"{_MOD}.load_agent_config",
            return_value=agent_config,
        ),
        patch(
            f"{_MOD}.load_config",
            return_value=MagicMock(user_timezone=None),
        ),
        patch(
            f"{_MOD}.create_model_and_formatter",
            return_value=(MagicMock(), MagicMock()),
        ),
        patch(
            f"{_MOD}.get_token_counter",
            return_value=MagicMock(),
        ),
        patch(f"{_MOD}.EnvVarLoader.get_str", return_value="local"),
        patch(f"{_MOD}.EnvVarLoader.get_bool", return_value=True),
        patch(f"{_MOD}.set_current_workspace_dir"),
        patch(f"{_MOD}.set_current_recent_max_bytes"),
    ):
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        m = ReMeLightMemoryManager(
            working_dir=str(tmp_path),
            agent_id="test-agent",
        )
        # Override the internally created _reme with our controllable mock
        m._reme = mock_reme
        return m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_reme():
    """Mock ReMeLight instance."""
    m = MagicMock()
    m._started = True
    m.start = AsyncMock(return_value=None)
    m.close = AsyncMock(return_value=True)
    m.compact_tool_result = AsyncMock(return_value=None)
    m.check_context = AsyncMock(return_value=([], [], True))
    m.compact_memory = AsyncMock(
        return_value={"is_valid": True, "history_compact": "compact"},
    )
    m.summary_memory = AsyncMock(return_value="summary text")
    m.memory_search = AsyncMock(return_value=MagicMock())
    m.get_in_memory_memory = MagicMock(return_value=MagicMock())
    return m


@pytest.fixture
def agent_config():
    return _make_agent_config()


@pytest.fixture
def manager(tmp_path, mock_reme, agent_config):
    """Create ReMeLightMemoryManager with all dependencies mocked."""
    m = _build_manager(tmp_path, mock_reme, agent_config)
    # Pre-set chat_model/formatter so _prepare_model_formatter is a no-op.
    # This avoids the deep import chain from create_model_and_formatter.
    m.chat_model = MagicMock()
    m.formatter = MagicMock()
    return m


# ---------------------------------------------------------------------------
# TestReMeLightMemoryManagerMaskKey
# ---------------------------------------------------------------------------


class TestReMeLightMemoryManagerMaskKey:
    """P0: Static helper _mask_key."""

    def test_masks_key_longer_than_5(self, manager):
        result = manager._mask_key("abcdefgh")
        assert result == "abcde***"

    def test_short_key_returned_as_is(self, manager):
        result = manager._mask_key("abc")
        assert result == "abc"

    def test_exactly_5_chars_not_masked(self, manager):
        result = manager._mask_key("abcde")
        assert result == "abcde"

    def test_long_key_stars_count(self, manager):
        key = "12345678"  # 8 chars
        result = manager._mask_key(key)
        assert result.startswith("12345")
        assert result.count("*") == 3


# ---------------------------------------------------------------------------
# TestReMeLightMemoryManagerResolveRebuildOnStart
# ---------------------------------------------------------------------------


class TestReMeLightMemoryManagerResolveRebuildOnStart:
    """P0: _resolve_rebuild_on_start logic (MEM-008/009)."""

    def test_no_sentinel_forces_rebuild_true(self, tmp_path):
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        result = ReMeLightMemoryManager._resolve_rebuild_on_start(
            working_dir=str(tmp_path),
            store_version="v1",
            rebuild_on_start=False,
        )
        assert result is True

    def test_no_sentinel_creates_sentinel_file(self, tmp_path):
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        ReMeLightMemoryManager._resolve_rebuild_on_start(
            working_dir=str(tmp_path),
            store_version="v1",
            rebuild_on_start=False,
        )
        assert (tmp_path / ".reme_store_v1").exists()

    def test_sentinel_present_uses_caller_value_false(
        self,
        tmp_path,
    ):
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        (tmp_path / ".reme_store_v1").touch()
        result = ReMeLightMemoryManager._resolve_rebuild_on_start(
            working_dir=str(tmp_path),
            store_version="v1",
            rebuild_on_start=False,
        )
        assert result is False

    def test_sentinel_present_uses_caller_value_true(self, tmp_path):
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        (tmp_path / ".reme_store_v1").touch()
        result = ReMeLightMemoryManager._resolve_rebuild_on_start(
            working_dir=str(tmp_path),
            store_version="v1",
            rebuild_on_start=True,
        )
        assert result is True

    def test_old_sentinels_are_removed(self, tmp_path):
        """Stale sentinel from an old version should be deleted."""
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        old_sentinel = tmp_path / ".reme_store_v0"
        old_sentinel.touch()
        ReMeLightMemoryManager._resolve_rebuild_on_start(
            working_dir=str(tmp_path),
            store_version="v99",
            rebuild_on_start=False,
        )
        assert not old_sentinel.exists()


# ---------------------------------------------------------------------------
# TestReMeLightMemoryManagerCheckRemeVersion
# ---------------------------------------------------------------------------


class TestReMeLightMemoryManagerCheckRemeVersion:
    """P0: _check_reme_version static method."""

    def test_returns_true_when_package_not_found(self):
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        with patch(
            "importlib.metadata.version",
            side_effect=importlib.metadata.PackageNotFoundError,
        ):
            result = ReMeLightMemoryManager._check_reme_version()
        assert result is True

    def test_returns_false_when_version_mismatches(self):
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
        )

        with patch(
            "importlib.metadata.version",
            return_value="0.0.0",
        ):
            result = ReMeLightMemoryManager._check_reme_version()
        assert result is False

    def test_returns_true_when_version_matches(self):
        from qwenpaw.agents.memory.reme_light_memory_manager import (
            ReMeLightMemoryManager,
            _EXPECTED_REME_VERSION,
        )

        with patch(
            "importlib.metadata.version",
            return_value=_EXPECTED_REME_VERSION,
        ):
            result = ReMeLightMemoryManager._check_reme_version()
        assert result is True


# ---------------------------------------------------------------------------
# TestReMeLightMemoryManagerStart
# ---------------------------------------------------------------------------


class TestReMeLightMemoryManagerStart:
    """P1: start() delegates to _reme.start()."""

    async def test_start_calls_reme_start(self, manager, mock_reme):
        await manager.start()
        mock_reme.start.assert_called_once()

    async def test_start_returns_none_when_reme_is_none(
        self,
        manager,
    ):
        manager._reme = None
        result = await manager.start()
        assert result is None


# ---------------------------------------------------------------------------
# TestReMeLightMemoryManagerClose
# ---------------------------------------------------------------------------


class TestReMeLightMemoryManagerClose:
    """P1: close() delegates to _reme.close()."""

    async def test_close_calls_reme_close(self, manager, mock_reme):
        mock_reme.close.return_value = True
        result = await manager.close()
        mock_reme.close.assert_called_once()
        assert result is True

    async def test_close_returns_true_when_reme_is_none(
        self,
        manager,
    ):
        manager._reme = None
        result = await manager.close()
        assert result is True


# ---------------------------------------------------------------------------
# TestReMeLightMemoryManagerMemorySearch
# ---------------------------------------------------------------------------


class TestReMeLightMemoryManagerMemorySearch:
    """P1: memory_search() — MEM-007 force params."""

    async def test_search_delegates_to_reme(
        self,
        manager,
        mock_reme,
    ):
        mock_reme._started = True
        mock_result = MagicMock()
        mock_reme.memory_search = AsyncMock(return_value=mock_result)

        result = await manager.memory_search(
            query="test query",
            max_results=3,
            min_score=0.2,
        )
        mock_reme.memory_search.assert_called_once_with(
            query="test query",
            max_results=3,
            min_score=0.2,
        )
        assert result is mock_result

    async def test_search_returns_response_when_not_started(
        self,
        manager,
    ):
        manager._reme._started = False
        result = await manager.memory_search(query="test")
        assert result is not None

    async def test_search_returns_response_when_reme_none(
        self,
        manager,
    ):
        manager._reme = None
        result = await manager.memory_search(query="test")
        assert result is not None

    async def test_search_uses_force_max_results(
        self,
        manager,
        mock_reme,
    ):
        """MEM-007: force_max_results honored via max_results param."""
        mock_reme._started = True
        mock_reme.memory_search = AsyncMock(return_value=MagicMock())
        await manager.memory_search(
            query="q",
            max_results=10,
            min_score=0.05,
        )
        _, kwargs = mock_reme.memory_search.call_args
        assert kwargs["max_results"] == 10
        assert kwargs["min_score"] == 0.05

    async def test_search_uses_defaults(self, manager, mock_reme):
        """Default max_results=5, min_score=0.1."""
        mock_reme._started = True
        mock_reme.memory_search = AsyncMock(return_value=MagicMock())
        await manager.memory_search(query="q")
        _, kwargs = mock_reme.memory_search.call_args
        assert kwargs["max_results"] == 5
        assert kwargs["min_score"] == 0.1


# ---------------------------------------------------------------------------
# TestReMeLightMemoryManagerGetEmbeddingConfig
# ---------------------------------------------------------------------------


class TestReMeLightMemoryManagerGetEmbeddingConfig:
    """P1: get_embedding_config() returns merged config."""

    def test_returns_dict_with_expected_keys(
        self,
        manager,
        agent_config,
    ):
        with patch(
            f"{_MOD}.load_agent_config",
            return_value=agent_config,
        ):
            cfg = manager.get_embedding_config()
        for key in (
            "backend",
            "api_key",
            "base_url",
            "model_name",
            "dimensions",
        ):
            assert key in cfg

    def test_uses_config_api_key(self, manager, agent_config):
        agent_config._emc.api_key = "mykey"
        agent_config.running.embedding_config.api_key = "mykey"
        with patch(
            f"{_MOD}.load_agent_config",
            return_value=agent_config,
        ):
            cfg = manager.get_embedding_config()
        assert cfg["api_key"] == "mykey"

    def test_falls_back_to_env_api_key(
        self,
        manager,
        agent_config,
    ):
        """When config api_key is empty, use EnvVarLoader."""
        agent_config._emc.api_key = ""
        agent_config.running.embedding_config.api_key = ""
        env_key = "env-api-key"
        with (
            patch(
                f"{_MOD}.load_agent_config",
                return_value=agent_config,
            ),
            patch(
                f"{_MOD}.EnvVarLoader.get_str",
                return_value=env_key,
            ),
        ):
            cfg = manager.get_embedding_config()
        assert cfg["api_key"] == env_key
