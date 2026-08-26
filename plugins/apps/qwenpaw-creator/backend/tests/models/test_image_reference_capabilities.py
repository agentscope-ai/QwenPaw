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
        ("private-gateway-alias", None),
    ],
)
def test_official_reference_limits_are_model_specific(model_name, expected):
    assert image_reference_limit(model_name) == expected


def test_capability_records_the_official_documentation_source():
    capability = image_reference_capability("gpt-image-2")
    assert capability is not None
    assert capability.documentation_url.startswith("https://")
