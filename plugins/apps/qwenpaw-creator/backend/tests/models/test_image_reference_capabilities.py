# -*- coding: utf-8 -*-
"""Official per-model reference-image limits."""

import pytest

from models.image.base import image_reference_capability, image_reference_limit


@pytest.mark.parametrize(
    ("model_name", "expected"),
    [
        ("qwen-image-3.0-pro", 3),
        ("qwen-image-2.0-pro-2026-06-22", 3),
        ("qwen-image-edit-plus-2025-12-15", 3),
        ("qwen-mt-image", 1),
        ("qwen-image-plus", 0),
        ("gpt-image-2-2026-04-21", 16),
        ("gpt-image-1-mini", 16),
        ("dall-e-2", 1),
        ("dall-e-3", 0),
        ("gemini-3-pro-image", 14),
        ("gemini-3.1-flash-image", 14),
        ("gemini-2.5-flash-image", 3),
        ("doubao-seedream-5-0-pro-260628", 10),
        ("doubao-seedream-4-5-251128", 14),
        ("flux-2-pro", 8),
        ("flux-2-klein-4b", 4),
        ("flux-2-klein-9b", 4),
        ("ideogram-v3", 1),
        ("ideogram-v4", 0),
        ("gemini-42-image", None),
        ("private-gateway-alias", None),
    ],
)
def test_official_reference_limits_are_model_specific(model_name, expected):
    assert image_reference_limit(model_name) == expected


def test_capability_records_the_official_documentation_source():
    capability = image_reference_capability("gpt-image-2")
    assert capability is not None
    assert capability.documentation_url.startswith("https://")
