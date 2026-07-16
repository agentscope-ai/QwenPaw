# -*- coding: utf-8 -*-
"""Tests for memory backend configuration defaults."""

from types import SimpleNamespace

import pytest

import qwenpaw.config.utils as config_utils
from qwenpaw.config.config import ADBPGMemoryConfig, ReMeLightMemoryConfig


def test_adbpg_auto_memory_search_defaults():
    cfg = ADBPGMemoryConfig()

    assert cfg.auto_memory_search_config.enabled is True
    assert cfg.auto_memory_search_config.max_results == 3


def test_reme_light_inbox_push_defaults_to_enabled():
    cfg = ReMeLightMemoryConfig()

    assert cfg.inbox_push_enabled is True


def test_dream_cron_is_enabled_by_default():
    cfg = ReMeLightMemoryConfig()

    assert cfg.dream_cron_enabled is True


def test_dream_cron_can_be_disabled_without_changing_expression():
    cfg = ReMeLightMemoryConfig(
        dream_cron_enabled=False,
        dream_cron="0 23 * * *",
    )

    assert cfg.dream_cron_enabled is False
    assert cfg.dream_cron == "0 23 * * *"


def test_dream_cron_rejects_empty_expression_when_enabled():
    with pytest.raises(ValueError, match="dream_cron must not be empty"):
        ReMeLightMemoryConfig(
            dream_cron_enabled=True,
            dream_cron="",
        )


def test_dream_cron_rejects_invalid_expression_when_enabled():
    with pytest.raises(ValueError, match="valid 5-field cron expression"):
        ReMeLightMemoryConfig(
            dream_cron_enabled=True,
            dream_cron="60 23 * * *",
        )


def test_legacy_empty_dream_cron_migrates_to_disabled():
    cfg = ReMeLightMemoryConfig(dream_cron="")

    assert cfg.dream_cron_enabled is False


def test_get_dream_cron_honors_the_enable_switch(monkeypatch):
    cfg = ReMeLightMemoryConfig(
        dream_cron_enabled=False,
        dream_cron="0 23 * * *",
    )
    agent_config = SimpleNamespace(
        running=SimpleNamespace(reme_light_memory_config=cfg),
    )
    monkeypatch.setattr(
        config_utils,
        "load_agent_config",
        lambda _agent_id: agent_config,
    )

    assert config_utils.get_dream_cron("agent") == ""


def test_get_dream_cron_returns_expression_when_enabled(monkeypatch):
    cfg = ReMeLightMemoryConfig(
        dream_cron_enabled=True,
        dream_cron="0 3 * * *",
    )
    agent_config = SimpleNamespace(
        running=SimpleNamespace(reme_light_memory_config=cfg),
    )
    monkeypatch.setattr(
        config_utils,
        "load_agent_config",
        lambda _agent_id: agent_config,
    )

    assert config_utils.get_dream_cron("agent") == "0 3 * * *"
