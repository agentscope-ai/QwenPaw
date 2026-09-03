# -*- coding: utf-8 -*-
"""Tests for memory backend configuration defaults."""

import pytest
from pydantic import ValidationError

from qwenpaw.config.config import (
    ADBPGMemoryConfig,
    EmbeddingModelConfig,
    ReMeLightMemoryConfig,
)


def test_adbpg_auto_memory_search_defaults():
    cfg = ADBPGMemoryConfig()

    assert cfg.auto_memory_search_config.enabled is True
    assert cfg.auto_memory_search_config.max_results == 3


def test_reme_light_job_notifications_default_to_enabled():
    cfg = ReMeLightMemoryConfig()

    assert cfg.auto_memory_inbox_push_enabled is True
    assert cfg.auto_dream_inbox_push_enabled is True
    assert cfg.daily_paper_inbox_push_enabled is True
    assert cfg.auto_fin_inbox_push_enabled is True
    assert "inbox_push_enabled" not in cfg.model_dump()


def test_legacy_inbox_switch_initializes_independent_notifications():
    cfg = ReMeLightMemoryConfig(inbox_push_enabled=False)

    assert cfg.auto_memory_inbox_push_enabled is False
    assert cfg.auto_dream_inbox_push_enabled is False
    assert cfg.daily_paper_inbox_push_enabled is False
    assert cfg.auto_fin_inbox_push_enabled is False


def test_explicit_notification_setting_wins_over_legacy_switch():
    cfg = ReMeLightMemoryConfig(
        inbox_push_enabled=False,
        daily_paper_inbox_push_enabled=True,
    )

    assert cfg.auto_memory_inbox_push_enabled is False
    assert cfg.auto_dream_inbox_push_enabled is False
    assert cfg.daily_paper_inbox_push_enabled is True


def test_memory_search_tool_defaults_to_enabled():
    assert ReMeLightMemoryConfig().memory_search_enabled is True


def test_legacy_rebuild_on_start_setting_is_ignored():
    cfg = ReMeLightMemoryConfig(rebuild_memory_index_on_start=True)

    assert "rebuild_memory_index_on_start" not in cfg.model_dump()


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


def test_legacy_empty_dream_cron_remains_loadable():
    cfg = ReMeLightMemoryConfig(dream_cron="")

    assert cfg.dream_cron_enabled is True
    assert cfg.dream_cron == ""


def test_daily_paper_cron_is_disabled_by_default():
    cfg = ReMeLightMemoryConfig()

    assert cfg.daily_paper_cron_enabled is False
    assert cfg.daily_paper_cron == "0 9 * * *"
    assert cfg.daily_paper_use_hf_mirror is False
    assert cfg.daily_paper_topics == ""


def test_auto_fin_cron_is_disabled_by_default():
    cfg = ReMeLightMemoryConfig()

    assert cfg.auto_fin_cron_enabled is False
    assert cfg.auto_fin_cron == "0 18 * * *"
    assert cfg.auto_fin_topics == "gold,robotics,semiconductors"
    assert cfg.auto_fin_window_hours == 24


@pytest.mark.parametrize("window_hours", [0, 0.5, -1, 169])
def test_auto_fin_window_rejects_values_outside_boundaries(window_hours):
    with pytest.raises(ValidationError):
        ReMeLightMemoryConfig(auto_fin_window_hours=window_hours)


@pytest.mark.parametrize("window_hours", [1, 168])
def test_auto_fin_window_accepts_boundaries(window_hours):
    cfg = ReMeLightMemoryConfig(auto_fin_window_hours=window_hours)

    assert cfg.auto_fin_window_hours == window_hours


@pytest.mark.parametrize(
    "window_hours",
    [float("inf"), float("-inf"), float("nan")],
)
def test_auto_fin_window_rejects_non_finite_values(window_hours):
    with pytest.raises(ValidationError):
        ReMeLightMemoryConfig(auto_fin_window_hours=window_hours)


def test_enabled_auto_fin_requires_non_empty_cron():
    with pytest.raises(
        ValidationError,
        match="auto_fin_cron must not be empty",
    ):
        ReMeLightMemoryConfig(
            auto_fin_cron_enabled=True,
            auto_fin_cron="  ",
        )


def test_disabled_auto_fin_allows_empty_cron():
    cfg = ReMeLightMemoryConfig(
        auto_fin_cron_enabled=False,
        auto_fin_cron="",
    )

    assert cfg.auto_fin_cron == ""


@pytest.mark.parametrize(
    "field",
    ["dream_cron", "daily_paper_cron", "auto_fin_cron"],
)
def test_service_cron_rejects_values_the_scheduler_cannot_parse(field):
    with pytest.raises(ValidationError, match="Invalid cron expression"):
        ReMeLightMemoryConfig.model_validate({field: "61 * * * *"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("backend", "unsupported"),
        ("dimensions", 0),
        ("max_cache_size", 0),
        ("max_input_length", 0),
        ("max_batch_size", 0),
    ],
)
def test_embedding_config_rejects_unsupported_or_non_positive_values(
    field,
    value,
):
    with pytest.raises(ValidationError):
        EmbeddingModelConfig.model_validate({field: value})
