# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from models import config as creator_config
from models.config import (
    DEFAULT_MAINLINE_MAX_MODEL_TURNS,
    DEFAULT_SPECIALIST_MAX_MODEL_TURNS,
    get_mainline_max_model_turns,
    get_specialist_max_model_turns,
    scale_mainline_max_model_turns,
)


pytestmark = pytest.mark.unit


def _patch_user_config(monkeypatch, data: dict) -> None:
    monkeypatch.setattr(creator_config, "_get_user_config", lambda: data)


def test_turn_limits_default_without_config(monkeypatch) -> None:
    _patch_user_config(monkeypatch, {})
    assert get_mainline_max_model_turns() == DEFAULT_MAINLINE_MAX_MODEL_TURNS
    assert (
        get_specialist_max_model_turns() == DEFAULT_SPECIALIST_MAX_MODEL_TURNS
    )


def test_turn_limits_read_agent_runtime_section(monkeypatch) -> None:
    _patch_user_config(
        monkeypatch,
        {
            "agent_runtime": {
                "mainline_max_model_turns": 48,
                "specialist_max_model_turns": 20,
            },
        },
    )
    assert get_mainline_max_model_turns() == 48
    assert get_specialist_max_model_turns() == 20


def test_turn_limits_reject_invalid_values(monkeypatch) -> None:
    _patch_user_config(
        monkeypatch,
        {
            "agent_runtime": {
                "mainline_max_model_turns": 0,
                "specialist_max_model_turns": True,
            },
        },
    )
    assert get_mainline_max_model_turns() == DEFAULT_MAINLINE_MAX_MODEL_TURNS
    assert (
        get_specialist_max_model_turns() == DEFAULT_SPECIALIST_MAX_MODEL_TURNS
    )


def test_turn_budget_scales_with_element_count() -> None:
    # Small projects keep the configured floor.
    assert scale_mainline_max_model_turns(24, 0) == 24
    assert scale_mainline_max_model_turns(24, 5) == 24  # 8 + 15 = 23 < 24
    # Element-heavy projects raise the cap: 8 + 3 * 12 = 44.
    assert scale_mainline_max_model_turns(24, 12) == 44
    # A higher configured value is never lowered.
    assert scale_mainline_max_model_turns(64, 12) == 64
    # Negative counts (defensive) fall back to the base.
    assert scale_mainline_max_model_turns(24, -3) == 24
