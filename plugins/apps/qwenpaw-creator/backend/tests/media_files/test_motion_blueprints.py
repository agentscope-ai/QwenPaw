# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Blueprint catalog: rendering contract and design-validation wiring."""

from __future__ import annotations

import pytest

from domain.errors import ValidationError
from services.media_files.motion_blueprints import (
    CAPTION_BLUEPRINT_ORDER,
    DECORATION_BLUEPRINTS,
    FRAME_BLUEPRINTS,
    render_caption_blueprint,
    render_decoration_blueprint,
    render_frame_blueprint,
    render_scene_blueprint,
    require_chinese_copy,
    validated_frame_window,
)
from services.media_files.motion_design import _validated_design


class TestBlueprintRendering:
    @pytest.mark.parametrize(
        ("names", "render", "extra_snippet"),
        [
            (
                CAPTION_BLUEPRINT_ORDER,
                lambda name: render_caption_blueprint(
                    name,
                    "海浪带走了所有心事",
                ),
                None,
            ),
            (DECORATION_BLUEPRINTS, render_decoration_blueprint, None),
            # Full-bleed border document: the root floods the viewport
            # and the four strips tile everything outside the window.
            (
                FRAME_BLUEPRINTS,
                render_frame_blueprint,
                "#root{position:absolute;inset:0;}",
            ),
        ],
        ids=["caption", "decoration", "frame"],
    )
    def test_every_blueprint_registers_hf_and_vendor(
        self,
        names,
        render,
        extra_snippet,
    ) -> None:
        for name in names:
            html, duration = render(name)
            assert "window.__hf" in html
            assert 'src="vendor/gsap.min.js"' in html
            assert duration > 0
            if extra_snippet is not None:
                assert extra_snippet in html

    def test_unknown_blueprint_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown caption blueprint"):
            render_caption_blueprint("nope", "文字")
        with pytest.raises(ValueError, match="unknown decoration blueprint"):
            render_decoration_blueprint("nope")

    def test_text_is_escaped(self) -> None:
        html, _ = render_caption_blueprint("ink_reveal", "<b>标签&文字</b>")
        assert "<b>标签" not in html
        assert "&lt;b&gt;" in html

    def test_frame_window_clamps_to_keep_real_borders(self) -> None:
        window = validated_frame_window(
            {"left": -0.5, "top": 0.0, "width": 2.0, "height": 0.01},
        )
        assert 0.02 <= window["left"]
        assert window["left"] + window["width"] <= 0.98
        assert 0.02 <= window["top"]
        assert window["top"] + window["height"] <= 0.98
        assert window["width"] >= 0.40 - 1e-9
        # Garbage input falls back to the default centered window.
        assert validated_frame_window(None)["width"] == pytest.approx(0.86)


class TestBlueprintDesignValidation:
    _LOCATION = {
        "x": 0.5,
        "y": 0.88,
        "width": 0.8,
        "height": 0.18,
        "anchor_x": 0.5,
        "anchor_y": 0.5,
    }

    def test_caption_blueprint_route_validates(self, stub_gsap_vendor) -> None:
        design = _validated_design(
            {
                "concept": "画面取色的逐字弹入卡",
                "blueprint": "stagger_pop",
                "palette": {"primary": "#ffb35c"},
                "intensity": 0.7,
                "location": self._LOCATION,
            },
            required_text="海浪带走了所有心事",
            default_loop=False,
            canvas_size=(1280, 720),
        )
        assert not isinstance(design, str)
        motion, _location, _concept = design
        assert motion.format == "html_js"
        assert motion.html is not None and "window.__hf" in motion.html
        assert motion.loop is False

    def test_unknown_blueprint_feeds_back_as_validation_error(self) -> None:
        with pytest.raises(ValidationError, match="unknown caption blueprint"):
            _validated_design(
                {
                    "concept": "x",
                    "blueprint": "not_a_blueprint",
                    "location": self._LOCATION,
                },
                required_text="台词",
                default_loop=False,
                canvas_size=(1280, 720),
            )


class TestSceneBlueprints:
    """edu_step_card: deterministic skeleton, Chinese-only copy slots."""

    _CONTENT = {
        "badge": "步骤一",
        "title": "去括号",
        "previous": "6(x-1)=24",
        "operation": "两边展开括号",
        "lines": ["6×x=6x", "6×(-1)=-6"],
        "result": "6x-6=24",
    }

    def test_renders_deterministically_with_fixed_chinese_labels(self):
        first, duration = render_scene_blueprint(
            "edu_step_card",
            self._CONTENT,
        )
        again, _ = render_scene_blueprint("edu_step_card", self._CONTENT)
        assert first == again
        assert duration > 0
        # Fixed labels live in the template, never in model output.
        assert "上一步" in first
        assert "得到" in first
        # Full-bleed stage: the coverage gate needs an edge-to-edge root.
        assert "inset:0" in first
        assert 'data-motion-exit="none"' in first

    def test_rejects_english_copy_but_math_tokens_pass(self):
        content = {**self._CONTENT, "lines": ["Move -6 to right"]}
        with pytest.raises(ValueError, match="中文"):
            render_scene_blueprint("edu_step_card", content)
        assert require_chinese_copy("sin(x)+cos(y)=1", "line")
        with pytest.raises(ValueError, match="Step"):
            require_chinese_copy("Step 2 移项", "line")
