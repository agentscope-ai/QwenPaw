"""Tests for ADBPG-owned configuration."""

from plugins.memory.adbpg.backend.config import ADBPGMemoryConfig


def test_auto_memory_search_defaults():
    config = ADBPGMemoryConfig()

    assert config.auto_memory_search_config.enabled is True
    assert config.auto_memory_search_config.max_results == 3
