# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Blueprint catalog: rendering contract and design-validation wiring."""

from __future__ import annotations

import hashlib

import pytest

from domain.errors import ValidationError
from services.media_files import motion_engine
from services.media_files.motion_blueprints import (
    CAPTION_BLUEPRINT_ORDER,
    DECORATION_BLUEPRINTS,
    FRAME_BLUEPRINTS,
    blueprint_catalog_text,
    render_caption_blueprint,
    render_decoration_blueprint,
    render_frame_blueprint,
    validated_frame_window,
    validated_palette,
)
from services.media_files.motion_design import _validated_design
from services.media_files.motion_engine import VendorLib

_FAKE_GSAP = b"window.gsap={timeline:function(){return{}}};"


@pytest.fixture()
def stub_gsap_vendor(monkeypatch, tmp_path):
    """Install a verified stand-in for the pinned GSAP runtime.

    CI never runs the vendor fetch CLI, so blueprint documents (which
    reference vendor/gsap.min.js) must resolve against a stub file.
    """

    stub = VendorLib(
        name="gsap",
        filename="gsap.min.js",
        sha256=hashlib.sha256(_FAKE_GSAP).hexdigest(),
        size_bytes=len(_FAKE_GSAP),
        source_url="https://example.invalid/gsap.min.js",
        license_note="test stub",
    )
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    (vendor_dir / stub.filename).write_bytes(_FAKE_GSAP)
    monkeypatch.setattr(motion_engine, "VENDOR_LIBS", {"gsap": stub})
    monkeypatch.setattr(
        motion_engine,
        "_LIBS_BY_FILENAME",
        {stub.filename: stub},
    )
    monkeypatch.setenv(
        "QWENPAW_CREATOR_MOTION_VENDOR_DIR",
        str(vendor_dir),
    )
    return stub


class TestBlueprintRendering:
    def test_every_caption_blueprint_registers_hf_and_vendor(self) -> None:
        for name in CAPTION_BLUEPRINT_ORDER:
            html, duration = render_caption_blueprint(name, "海浪带走了所有心事")
            assert "window.__hf" in html
            assert 'src="vendor/gsap.min.js"' in html
            assert duration > 0

    def test_every_decoration_blueprint_registers_hf_and_vendor(self) -> None:
        for name in DECORATION_BLUEPRINTS:
            html, period = render_decoration_blueprint(name)
            assert "window.__hf" in html
            assert 'src="vendor/gsap.min.js"' in html
            assert period > 0

    def test_caption_blueprints_are_visually_distinct(self) -> None:
        rendered = {
            render_caption_blueprint(name, "同一句台词")[0]
            for name in CAPTION_BLUEPRINT_ORDER
        }
        assert len(rendered) == len(CAPTION_BLUEPRINT_ORDER)

    def test_unknown_blueprint_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown caption blueprint"):
            render_caption_blueprint("nope", "文字")
        with pytest.raises(ValueError, match="unknown decoration blueprint"):
            render_decoration_blueprint("nope")

    def test_palette_clamps_invalid_colors(self) -> None:
        palette = validated_palette(
            {"primary": "red", "secondary": "#12345", "ink": None},
        )
        assert palette.primary.startswith("#") and len(palette.primary) == 7
        assert palette.secondary.startswith("#")

    def test_text_is_escaped(self) -> None:
        html, _ = render_caption_blueprint(
            "ink_reveal",
            "<b>标签&文字</b>",
        )
        assert "<b>标签" not in html
        assert "&lt;b&gt;" in html

    def test_catalog_text_lists_all_names(self) -> None:
        caption = blueprint_catalog_text("caption")
        decoration = blueprint_catalog_text("decoration")
        for name in CAPTION_BLUEPRINT_ORDER:
            assert name in caption
        for name in DECORATION_BLUEPRINTS:
            assert name in decoration

    def test_every_frame_blueprint_registers_hf_and_vendor(self) -> None:
        for name in FRAME_BLUEPRINTS:
            html, period = render_frame_blueprint(name)
            assert "window.__hf" in html
            assert 'src="vendor/gsap.min.js"' in html
            assert period > 0
            # Full-bleed border document: the root floods the viewport
            # and the four strips tile everything outside the window.
            assert "#root{position:absolute;inset:0;}" in html

    def test_frame_window_mirrors_edit_placement_box(self) -> None:
        # A centered 0.84 x 0.80 edit placement produces matching strip
        # geometry: top strip 10%, left strip 8%.
        html, _ = render_frame_blueprint(
            "pop_variety",
            window={"left": 0.08, "top": 0.10, "width": 0.84, "height": 0.80},
        )
        assert ".st{left:0;right:0;top:0;height:10.00%}" in html
        assert ".sl{left:0;top:10.00%;bottom:10.00%;width:8.00%}" in html

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
        default = validated_frame_window(None)
        assert default["width"] == pytest.approx(0.86)
        assert default["left"] == pytest.approx(0.07)

    def test_unknown_frame_blueprint_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown frame blueprint"):
            render_frame_blueprint("nope")


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

    def test_decoration_blueprint_route_validates(
        self,
        stub_gsap_vendor,
    ) -> None:
        design = _validated_design(
            {
                "needed": True,
                "concept": "呼应海浪的波动线条",
                "blueprint": "wave_flow",
                "palette": {"primary": "#70f0dc"},
                "location": {
                    "x": 0.8,
                    "y": 0.2,
                    "width": 0.3,
                    "height": 0.24,
                    "anchor_x": 0.5,
                    "anchor_y": 0.5,
                },
            },
        )
        assert not isinstance(design, str)
        motion, _location, _concept = design
        assert motion.format == "html_js"
        assert motion.loop is True
        assert motion.motif == "blueprint:wave_flow"

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

    def test_blueprint_satisfies_verbatim_text_gate(
        self,
        stub_gsap_vendor,
    ) -> None:
        # stagger_pop wraps every character in its own tag; the verbatim
        # gate strips markup so the copy must still read through.
        design = _validated_design(
            {
                "concept": "逐字弹入",
                "blueprint": "stagger_pop",
                "location": self._LOCATION,
            },
            required_text="每一道浪，都是温柔",
            default_loop=False,
            canvas_size=(1280, 720),
        )
        assert not isinstance(design, str)


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
        from services.media_files.motion_blueprints import (
            render_scene_blueprint,
        )

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

    def test_rejects_english_copy_in_any_slot(self):
        from services.media_files.motion_blueprints import (
            render_scene_blueprint,
        )

        for slot, poisoned in (
            ("title", "PREVIOUS STEP"),
            ("lines", ["Move -6 to right"]),
            ("result", "Verification Process"),
        ):
            content = {**self._CONTENT, slot: poisoned}
            with pytest.raises(ValueError, match="中文"):
                render_scene_blueprint("edu_step_card", content)

    def test_math_tokens_and_variables_pass(self):
        from services.media_files.motion_blueprints import (
            require_chinese_copy,
        )

        assert require_chinese_copy("sin(x)+cos(y)=1", "line")
        assert require_chinese_copy("6(x-1)=24", "line")
        with pytest.raises(ValueError, match="Step"):
            require_chinese_copy("Step 2 移项", "line")
