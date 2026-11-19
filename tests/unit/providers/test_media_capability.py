# -*- coding: utf-8 -*-
"""Tests for the shared per-media capability policy."""
from __future__ import annotations

import pytest

from qwenpaw.providers.media_capability import (
    MediaDecision,
    get_media_decision,
)
from qwenpaw.providers.model_info import ModelInfo


@pytest.mark.parametrize(
    (f"fields", f"media_type", f"allow_generic", f"expected"),
    [
        pytest.param(
            {
                f"supports_image": True,
                f"supports_multimodal": False,
                f"config_overrides": [
                    f"supports_image",
                    f"supports_multimodal",
                ],
            },
            f"image",
            None,
            MediaDecision(True, True),
            id=f"specific-override-beats-multimodal-opt-out",
        ),
        pytest.param(
            {
                f"supports_video": False,
                f"supports_multimodal": True,
                f"config_overrides": [f"supports_video"],
            },
            f"video",
            None,
            MediaDecision(False, True),
            id=f"specific-override-false",
        ),
        pytest.param(
            {
                f"supports_image": True,
                f"supports_multimodal": False,
                f"config_overrides": [f"supports_multimodal"],
            },
            f"image",
            None,
            MediaDecision(False, True),
            id=f"multimodal-opt-out-blocks-discovery",
        ),
        pytest.param(
            {f"supports_audio": True, f"supports_multimodal": False},
            f"audio",
            None,
            MediaDecision(True, False),
            id=f"specific-discovered-value",
        ),
        pytest.param(
            {f"supports_multimodal": True},
            f"image",
            None,
            MediaDecision(True, False),
            id=f"image-defaults-to-generic-fallback",
        ),
        pytest.param(
            {f"supports_multimodal": True},
            f"video",
            None,
            MediaDecision(None, False),
            id=f"video-defaults-to-no-generic-fallback",
        ),
        pytest.param(
            {f"supports_multimodal": True},
            f"image",
            False,
            MediaDecision(None, False),
            id=f"image-generic-fallback-disabled",
        ),
        pytest.param(
            {},
            f"image",
            None,
            MediaDecision(None, False),
            id=f"all-unknown",
        ),
        pytest.param(
            {f"supports_multimodal": False},
            f"image",
            None,
            MediaDecision(False, False),
            id=f"discovered-text-only",
        ),
    ],
)
def test_get_media_decision(fields, media_type, allow_generic, expected):
    """Explicit settings win, then specific values, then generic fallback."""
    model = ModelInfo(id=f"m", name=f"m", **fields)

    assert (
        get_media_decision(
            model,
            media_type,
            allow_generic=allow_generic,
        )
        == expected
    )


@pytest.mark.parametrize(
    (f"media_type", f"specific", f"overrides", f"generic", f"expected"),
    [
        (f"image", False, [], None, MediaDecision(False, False)),
        (
            f"image",
            False,
            [f"supports_multimodal"],
            None,
            MediaDecision(True, True),
        ),
        (
            f"image",
            False,
            [f"supports_image", f"supports_multimodal"],
            None,
            MediaDecision(False, True),
        ),
        (
            f"image",
            False,
            [f"supports_multimodal"],
            False,
            MediaDecision(False, False),
        ),
        (
            f"image",
            None,
            [f"supports_multimodal"],
            False,
            MediaDecision(None, False),
        ),
        (
            f"audio",
            False,
            [f"supports_multimodal"],
            None,
            MediaDecision(False, False),
        ),
        (
            f"audio",
            None,
            [f"supports_multimodal"],
            None,
            MediaDecision(None, False),
        ),
        (
            f"video",
            False,
            [f"supports_multimodal"],
            None,
            MediaDecision(False, False),
        ),
        (
            f"video",
            None,
            [f"supports_multimodal"],
            None,
            MediaDecision(None, False),
        ),
    ],
)
def test_multimodal_opt_in_respects_per_media_policy(
    media_type,
    specific,
    overrides,
    generic,
    expected,
):
    """全局显式开启仅用于允许 generic fallback 的媒体。"""
    model = ModelInfo(
        id=f"m",
        name=f"m",
        supports_multimodal=True,
        config_overrides=overrides,
        probe_source=f"probed",
        **{f"supports_{media_type}": specific},
    )

    assert get_media_decision(model, media_type, generic) == expected
