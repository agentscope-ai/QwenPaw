# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Blueprint catalog: rendering contract and design-validation wiring."""

from __future__ import annotations

import pytest

from domain.errors import ValidationError
from services.media_files.motion_blueprints import (
    CAPTION_BLUEPRINTS,
    CAPTION_BLUEPRINT_ORDER,
    DECORATION_BLUEPRINTS,
    FRAME_BLUEPRINTS,
    render_caption_blueprint,
    render_decoration_blueprint,
    render_frame_blueprint,
    render_scene_blueprint,
    require_chinese_copy,
    subtitle_style_prompt_block,
    sync_subtitle_prompt,
    validated_frame_window,
)
from services.media_files.motion_design import _validated_design
from services.media_files.motion_templates import DEFAULT_CAPTION_LOCATION


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

    @pytest.mark.parametrize(
        ("names", "render"),
        [
            (
                CAPTION_BLUEPRINTS,
                lambda name: render_caption_blueprint(name, "测试 字幕"),
            ),
            (DECORATION_BLUEPRINTS, render_decoration_blueprint),
            (FRAME_BLUEPRINTS, render_frame_blueprint),
        ],
        ids=["caption", "decoration", "frame"],
    )
    def test_every_blueprint_resolves_python_template_braces(
        self,
        names,
        render,
    ) -> None:
        for name in names:
            html, _duration = render(name)
            assert "{{" not in html, name
            assert "}}" not in html, name

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

    def test_tutorial_family_is_modern_seek_safe_and_ui_faithful(self) -> None:
        caption, _ = render_caption_blueprint(
            "precision_subtitle",
            "点击搜索框，输入 QwenPaw",
        )
        ripple, _ = render_decoration_blueprint("cursor_ripple")
        frame, _ = render_frame_blueprint("product_ui")
        assert "backdrop-filter:blur" in caption
        assert "cursor" in ripple and "requestAnimationFrame" not in ripple
        assert 'data-motion-window="' in frame


class TestBlueprintDesignValidation:
    # Design validation now gates the caption box against the 0.04/0.96 safe
    # area, so the fixture has to be a box the product would actually accept.
    # The hand-written 0.88/0.18 centre-anchored version reached 0.97 and was
    # exactly the burnt-into-the-frame-edge geometry the gate exists to stop.
    _LOCATION = dict(DEFAULT_CAPTION_LOCATION)

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


class TestSubtitlePromptSync:
    """Exactly one style sentence per caption, whoever drafted the first line.

    The 动效描述 is the layer the user reads in 更多设置; the pack and the
    burned-in document are the layers the renderer draws.  These tests pin the
    rule that switching a pack moves all three together without ever eating an
    author's own wording.
    """

    def test_clause_owns_the_first_line_and_keeps_the_authored_body(self):
        synced, changed = sync_subtitle_prompt(
            "镜头推进时轻微抖动",
            "variety_pop",
            {"color": "#FFE066"},
            {"entrance": "pop", "exit": "soft_fade", "loop": True},
        )
        assert changed
        lines = synced.splitlines()
        assert lines[0].startswith("【字幕风格：综艺花字】")
        assert "文字颜色 #FFE066" in lines[0]
        assert "动画：入场 弹入／出场 淡出／循环 开" in lines[0]
        assert lines[-1] == "镜头推进时轻微抖动"

    def test_a_pack_switch_replaces_only_its_own_line(self):
        once, _ = sync_subtitle_prompt("正文", "variety_pop", None, None)
        twice, changed = sync_subtitle_prompt(once, "cinematic", None, None)
        assert changed
        assert "综艺花字" not in twice
        assert twice.startswith("【字幕风格：电影叙事】")
        assert twice.endswith("正文")
        # A repeated pick is a no-op, which keeps the design pass idempotent.
        again, unchanged = sync_subtitle_prompt(twice, "cinematic", None, None)
        assert not unchanged and again == twice

    def test_a_sentence_the_model_copied_is_replaced_not_stacked(self):
        # The prompt block shows the catalogue by name, so a model that copies
        # one verbatim has to be recognised: otherwise a pack switch leaves two
        # contradicting sentences on the same caption, forever.
        prompt = "综艺花字：特粗无衬线大字、紧凑字距、高对比白色描边\n慢镜头呼吸感"
        synced, changed = sync_subtitle_prompt(
            prompt,
            "clean_talk",
            None,
            None,
        )
        assert changed
        assert "综艺花字" not in synced
        assert synced.startswith("【字幕风格：简洁讲解】")
        assert synced.endswith("慢镜头呼吸感")

    def test_clearing_the_pack_drops_the_clause_only(self):
        once, _ = sync_subtitle_prompt("正文", "warm_note", None, None)
        cleared, changed = sync_subtitle_prompt(once, None, None, None)
        assert changed and cleared == "正文"

    def test_a_project_that_never_picked_a_style_is_not_touched(self):
        # The design pass calls this for every caption now, so the no-style
        # case has to stay byte-identical — not even a trim of the author's own
        # whitespace, which would churn every legacy project on first open.
        prompt = "  保留原样的一行描述\n  "
        synced, changed = sync_subtitle_prompt(prompt, None, None, None)
        assert synced == prompt
        assert not changed

    def test_prompt_block_tells_the_agent_the_system_owns_the_line(self):
        # The two wordings an agent used to receive contradicted each other
        # ("copy the effective style" vs "the system syncs it"); the block now
        # only asks for content intent.
        block = subtitle_style_prompt_block("neon_music", None)
        assert "生效风格：霓虹音乐" in block
        assert "由系统按上述风格自动维护" in block
        assert "必须沿用" not in block
