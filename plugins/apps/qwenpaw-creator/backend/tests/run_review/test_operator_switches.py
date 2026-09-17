# -*- coding: utf-8 -*-
"""Advanced self-review operator switches: registry, auto and gating."""

from __future__ import annotations

import pytest

from services.run_review import operator_registry
from services.run_review.operator_registry import (
    REVIEW_OPERATORS,
    is_operator_enabled,
    operator_keys,
    operator_status_report,
)

pytestmark = pytest.mark.unit


def test_registry_integrity() -> None:
    keys = operator_keys()
    assert len(keys) == len(set(keys))
    tiers = {operator.tier for operator in REVIEW_OPERATORS}
    assert tiers == {0, 1, 2, 3}
    # Every APE-imported switchable capability is present.
    assert set(keys) >= {
        "video_index",
        "av_sync",
        "audio_content",
        "machine_params",
        "light_metrics",
        "cross_shot_consistency",
        "camera_motion",
        "ocr_text",
        "script_check",
        "defect_bank",
        "faithfulness",
        "focused_frames",
        "challenge",
    }


def test_auto_resolution_follows_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        operator_registry,
        "_configured_operators",
        dict,
    )
    # Dependency-free operators are on by default (能开尽开).
    assert is_operator_enabled("video_index") is True
    assert is_operator_enabled("defect_bank") is True
    assert is_operator_enabled("challenge") is True
    # ASR-backed operator follows the configured key.
    from models import config as model_config

    monkeypatch.setattr(model_config, "get_asr_api_key", lambda: "")
    assert is_operator_enabled("av_sync") is False
    monkeypatch.setattr(model_config, "get_asr_api_key", lambda: "key")
    assert is_operator_enabled("av_sync") is True
    # Self-degrading operator stays on even without its optional lib.
    monkeypatch.setattr(
        operator_registry,
        "_dependency_available",
        lambda dependency: False,
    )
    assert is_operator_enabled("camera_motion") is True
    # Unknown keys never enable a code path.
    assert is_operator_enabled("no_such_operator") is False


def test_explicit_user_choice_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        operator_registry,
        "_configured_operators",
        lambda: {"video_index": False, "av_sync": True},
    )
    monkeypatch.setattr(
        operator_registry,
        "_dependency_available",
        lambda dependency: False,
    )
    assert is_operator_enabled("video_index") is False
    assert is_operator_enabled("av_sync") is True


def test_status_report_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        operator_registry,
        "_configured_operators",
        lambda: {"defect_bank": False},
    )
    rows = {row["key"]: row for row in operator_status_report()}
    assert rows["defect_bank"]["source"] == "user"
    assert rows["defect_bank"]["enabled"] is False
    assert rows["video_index"]["source"] == "auto"
    assert rows["video_index"]["enabled"] is True
    assert {"key", "tier", "dependency", "capability_ok", "enabled"} <= set(
        rows["av_sync"],
    )


def test_disabled_operator_records_visible_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user-disabled operator leaves a self-explaining marker.

    Exercises the ``_safe`` gate directly (the ffmpeg end-to-end path is
    already covered by test_objective_facts).
    """
    from services.run_review.objective import facts as facts_mod

    monkeypatch.setattr(
        operator_registry,
        "_configured_operators",
        lambda: {"ocr_text": False, "cross_shot_consistency": False},
    )
    collected: dict = {}
    facts_mod._safe(  # pylint: disable=protected-access
        collected,
        "text_render",
        lambda: {"measured": True},
        switch="ocr_text",
    )
    facts_mod._safe(  # pylint: disable=protected-access
        collected,
        "cross_shot_consistency",
        lambda: {"measured": True},
    )
    facts_mod._safe(  # pylint: disable=protected-access
        collected,
        "video_index",
        lambda: {"cut_count": 1},
    )
    assert collected["text_render"]["status"] == "disabled"
    assert collected["cross_shot_consistency"]["status"] == "disabled"
    # Untouched operators keep running.
    assert collected["video_index"]["cut_count"] == 1


def test_render_challenge_switch_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from models import config as model_config

    monkeypatch.delenv("CREATOR_RENDER_CHALLENGE_ENABLED", raising=False)
    monkeypatch.setattr(
        operator_registry,
        "_configured_operators",
        lambda: {"challenge": False},
    )
    assert model_config.is_render_challenge_enabled() is False
    monkeypatch.setattr(operator_registry, "_configured_operators", dict)
    assert model_config.is_render_challenge_enabled() is True
    # An explicitly set environment variable keeps full control.
    monkeypatch.setenv("CREATOR_RENDER_CHALLENGE_ENABLED", "0")
    assert model_config.is_render_challenge_enabled() is False
