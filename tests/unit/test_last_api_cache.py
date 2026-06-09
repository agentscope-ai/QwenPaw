# -*- coding: utf-8 -*-
"""Tests for the in-process _runtime_last_api cache in config/utils.py.

Covers the cache added in fix/session-filename-duplication-4988-v3:
- write_last_api() stores value in both cache and disk
- read_last_api() prefers cache over disk
- Cache survives config.json overwrites (the core Desktop scenario)

Note on thread safety: _runtime_last_api is a module-level immutable
tuple reference.  Python's GIL guarantees atomic reference assignment,
so no lock is needed for the current single-writer pattern (only the
server startup thread calls write_last_api).
"""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from qwenpaw.config import utils as config_utils


@pytest.fixture(autouse=True)
def _reset_runtime_cache():
    """Reset the module-level cache before and after each test."""
    original = config_utils._runtime_last_api
    config_utils._runtime_last_api = None
    yield
    config_utils._runtime_last_api = original


class TestWriteLastApiCache:
    """write_last_api() must populate both cache and disk."""

    @patch.object(config_utils, "save_config")
    @patch.object(config_utils, "load_config")
    def test_sets_runtime_cache(self, mock_load, _mock_save):
        mock_load.return_value = MagicMock()

        config_utils.write_last_api("127.0.0.1", 9999)

        assert config_utils._runtime_last_api == ("127.0.0.1", 9999)

    @patch.object(config_utils, "save_config")
    @patch.object(config_utils, "load_config")
    def test_persists_to_config(self, mock_load, mock_save):
        mock_config = MagicMock()
        mock_load.return_value = mock_config

        config_utils.write_last_api("127.0.0.1", 8080)

        mock_save.assert_called_once_with(mock_config)
        assert mock_config.last_api.host == "127.0.0.1"
        assert mock_config.last_api.port == 8080


class TestReadLastApiCache:
    """read_last_api() must prefer cache, fall back to disk."""

    def test_returns_cache_when_set(self):
        config_utils._runtime_last_api = ("10.0.0.1", 12345)

        result = config_utils.read_last_api()

        assert result == ("10.0.0.1", 12345)

    @patch.object(config_utils, "load_config")
    def test_cache_hit_skips_disk(self, mock_load):
        config_utils._runtime_last_api = ("10.0.0.1", 12345)

        config_utils.read_last_api()

        mock_load.assert_not_called()

    @patch.object(config_utils, "load_config")
    def test_falls_back_to_disk_when_cache_empty(self, mock_load):
        mock_config = MagicMock()
        mock_config.last_api.host = "192.168.1.1"
        mock_config.last_api.port = 8088
        mock_load.return_value = mock_config

        result = config_utils.read_last_api()

        assert result == ("192.168.1.1", 8088)
        mock_load.assert_called_once()

    @patch.object(config_utils, "load_config")
    def test_returns_none_when_both_empty(self, mock_load):
        mock_config = MagicMock()
        mock_config.last_api.host = None
        mock_config.last_api.port = None
        mock_load.return_value = mock_config

        result = config_utils.read_last_api()

        assert result is None


class TestCacheSurvivesConfigOverwrite:
    """Core Desktop scenario: cache must survive config.json rewrites."""

    @patch.object(config_utils, "save_config")
    @patch.object(config_utils, "load_config")
    def test_cache_survives_after_external_save(self, mock_load, _mock_save):
        """Simulates: write_last_api(random_port) → migration overwrites
        config.json → read_last_api() should still return cached port."""
        mock_load.return_value = MagicMock()

        config_utils.write_last_api("127.0.0.1", 54321)

        # Simulate migration overwriting config.json (disk has stale data)
        stale_config = MagicMock()
        stale_config.last_api.host = "127.0.0.1"
        stale_config.last_api.port = 8088  # wrong port
        mock_load.return_value = stale_config

        result = config_utils.read_last_api()

        assert result == (
            "127.0.0.1",
            54321,
        ), "Cache must win over stale disk value"
