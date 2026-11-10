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
