# -*- coding: utf-8 -*-
"""Canonical [Image N] markers render to each provider's documented syntax."""
from __future__ import annotations

import re

import pytest

from models.reference_markers import (
    ReferenceMarkerSpec,
    canonical_marker,
    canonical_marker_indices,
    render_reference_markers,
)
from models.video_capabilities import video_reference_marker_spec

pytestmark = pytest.mark.unit

_AUTHORED = "[Image 1] 的护士靠窗，[Image 2] 的司机看后视镜，背景 [Image 3]。"


@pytest.mark.parametrize(
    ("model_name", "backend", "expected"),
    [
        # wan3 documents 图N: "数组中的第 1 个 reference_image 对应 图1".
        ("wan3.0-video", "", "图1 的护士靠窗，图2 的司机看后视镜，背景 图3。"),
        (
            "happyhorse-video",
            "",
            "[Image 1] 的护士靠窗，[Image 2] 的司机看后视镜，背景 [Image 3]。",
        ),
        (
            "doubao-seedance-2.0",
            "seedance2",
            "图片1 的护士靠窗，图片2 的司机看后视镜，背景 图片3。",
        ),
        (
            "provider/kling-v2",
            "kling",
            "<<<image_1>>> 的护士靠窗，<<<image_2>>> 的司机看后视镜，背景 <<<image_3>>>。",
        ),
        (
            "kling-v2",
            "kling",
            "@image_1 的护士靠窗，@image_2 的司机看后视镜，背景 @image_3。",
        ),
        (
            "wan2.6-i2v",
            "wan",
            "character1 的护士靠窗，character2 的司机看后视镜，背景 character3。",
        ),
    ],
)
def test_one_authored_form_renders_to_each_provider_dialect(
    model_name: str,
    backend: str,
    expected: str,
) -> None:
    spec = video_reference_marker_spec(model_name, backend)
    assert render_reference_markers(_AUTHORED, spec) == expected


def test_provider_without_documented_addressing_gets_prose() -> None:
    """OpenAI's image family documents array order only, no per-image syntax.

    Passing "[Image 1]" through would send literal text the provider has no
    contract for, so it becomes ordinal prose instead.
    """
    rendered = render_reference_markers(_AUTHORED, None)
    assert "[Image" not in rendered
    assert "第1张参考图" in rendered and "第3张参考图" in rendered
    english = render_reference_markers(
        "[Image 2] shows the bus",
        None,
        language="en",
    )
    assert english == "reference image 2 shows the bus"


def test_prompts_stored_before_this_layer_are_untouched() -> None:
    """A legacy prompt already holds provider-native markers and no canonical
    ones, so rendering must be a no-op — and stable if applied twice.
    """
    spec = video_reference_marker_spec("wan3.0-video", "")
    legacy = "图1 的护士靠窗，图2 的司机看后视镜。"
    once = render_reference_markers(legacy, spec)
    assert once == legacy
    assert render_reference_markers(once, spec) == once


def test_authoring_tolerates_case_and_spacing() -> None:
    spec = video_reference_marker_spec("wan3.0-video", "")
    assert (
        render_reference_markers("[image  2] 与 [IMAGE 3]", spec) == "图2 与 图3"
    )


def test_marker_helpers_round_trip() -> None:
    assert canonical_marker(4) == "[Image 4]"
    assert canonical_marker_indices("[Image 2] then [Image 1]") == (2, 1)
    assert not canonical_marker_indices("no markers here")


def test_spec_records_where_the_syntax_came_from() -> None:
    """The marker table used to assert a syntax with no citation."""
    spec = video_reference_marker_spec("wan3.0-video", "")
    assert spec is not None
    assert "wan3-video-generation-api-reference" in spec.documentation_url


@pytest.mark.parametrize(
    ("model_name", "backend", "expected"),
    [
        ("wan3.0-video", "", "图12"),
        ("happyhorse-video", "", "[Image 12]"),
        ("doubao-seedance-2.0", "seedance2", "图片12"),
        ("provider/kling-v2", "kling", "<<<image_12>>>"),
        ("kling-v2", "kling", "@image_12"),
        ("wan2.6-i2v", "wan", "character12"),
    ],
)
def test_multi_digit_indices_render_intact(
    model_name: str,
    backend: str,
    expected: str,
) -> None:
    """Index substitution must be templated, not a digit string-replace.

    The earlier implementation built marker N by replacing "1" inside the
    literal for image 1, which turns index 12 into nonsense and breaks any
    dialect whose literal carries another digit.
    """
    spec = video_reference_marker_spec(model_name, backend)
    assert spec is not None
    assert spec.render_index(12) == expected
    assert render_reference_markers("看 [Image 12]", spec) == f"看 {expected}"


def test_render_index_uses_the_template() -> None:
    spec = ReferenceMarkerSpec(
        template="图{index}",
        pattern=re.compile(r"图(\d+)"),
        documentation_url="https://example.invalid",
    )
    assert spec.render_index(7) == "图7"
