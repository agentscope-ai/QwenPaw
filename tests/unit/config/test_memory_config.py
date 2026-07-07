# -*- coding: utf-8 -*-
"""Tests for memory backend configuration defaults."""

from qwenpaw.config.config import ADBPGMemoryConfig


def test_adbpg_auto_memory_search_defaults():
    cfg = ADBPGMemoryConfig()

    assert cfg.auto_memory_search_config.enabled is True
    assert cfg.auto_memory_search_config.max_results == 3
