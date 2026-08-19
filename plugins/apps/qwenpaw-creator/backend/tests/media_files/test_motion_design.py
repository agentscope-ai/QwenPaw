# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=unused-argument,protected-access,redefined-outer-name

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from domain.errors import ValidationError
from services.media_files import local_execution as local_execution_module
from services.media_files import motion_design
from services.media_files import motion_engine
from services.media_files.motion_engine import VendorLib
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    LocalMediaInput,
)
from services.media_files.motion_design import (
    _design_document,
    _select_decoration_ids,
    _story_arc_motifs,
    _validated_story_beats,
    _validated_design,
    _validate_caption_location,
    _validated_location,
)
from services.media_files.motion_overlay import (
    MotionDocumentProbe,
    MotionLayerPrep,
    PreparedMotionLayer,
    _alpha_plane_stats,
)
from services.media_files.motion_templates import (
    MOTION_TEMPLATE_VERSION,
    SUPPORTED_MOTIFS,
    render_caption_template,
    render_decoration_template,
)
from services.media_files.overlay import OverlayRenderResult
from services.project_files.models import (
    EditCreation,
    ElementLocation,
    MotionGraphic,
    OverlayCreation,
    Timeline,
    TimelineElement,
    TimelineSpan,
    overlay_role,
)

_HTML = "<html><body><div class='card'>本喵要发光</div></body></html>"

_FAKE_GSAP = b"window.gsap={timeline:function(){return{}}};"


@pytest.fixture()
def stub_gsap_vendor(monkeypatch, tmp_path):
    """Install a verified stand-in for the pinned GSAP runtime.

    CI never runs the vendor fetch CLI, so html_js documents (which
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


def _motion() -> MotionGraphic:
    return MotionGraphic(html=_HTML, fps=24, loop=False)


class TestOverlayCreationMotionValidator:
    def test_caption_accepts_motion_styling(self) -> None:
        creation = OverlayCreation(
            text="本喵要发光",
            motion=_motion(),
        )
        assert creation.motion is not None

    def test_decoration_accepts_motion_with_prompt(self) -> None:
        creation = OverlayCreation(
            prompt="呼应跳跃的弹性线条",
            motion=_motion(),
        )
        assert creation.motion is not None

    def test_text_free_overlay_requires_prompt_or_refs(self) -> None:
        with pytest.raises(ValueError, match="prompt or reference"):
            OverlayCreation(motion=_motion())


class TestValidatedDesignTextMode:
    _BASE = {
        "concept": "发光字幕卡",
        "fps": 24,
        "location": {"x": 0.9, "y": 0.3, "width": 0.2, "height": 0.4},
    }

    def test_verbatim_text_required(self) -> None:
        raw = {**self._BASE, "html": _HTML.replace("本喵要发光", "本喵想发光")}
        with pytest.raises(ValidationError, match="一字不差"):
            _validated_design(raw, required_text="本喵要发光")

    def test_text_may_wrap_across_lines(self) -> None:
        raw = {
            **self._BASE,
            "html": _HTML.replace("本喵要发光", "本喵\n要发光"),
        }
        design = _validated_design(
            raw,
            required_text="本喵要发光",
            default_loop=False,
        )
        assert not isinstance(design, str)

    def test_text_mode_ignores_needed_and_defaults_loop_false(self) -> None:
        raw = {**self._BASE, "html": _HTML, "needed": False}
        design = _validated_design(
            raw,
            required_text="本喵要发光",
            default_loop=False,
        )
        assert not isinstance(design, str)
        motion, _location, _concept = design
        assert motion.loop is False

    def test_scene_mode_allows_visible_text(self) -> None:
        """Full-canvas motion clips may carry copy (teaching panels,
        title cards); only decorations must stay text-free."""

        raw = {**self._BASE, "needed": True, "html": _HTML}
        with pytest.raises(ValidationError, match="不允许包含任何可见文字"):
            _validated_design(raw, default_loop=False)
        design = _validated_design(
            raw,
            allow_visible_text=True,
            default_loop=False,
        )
        assert not isinstance(design, str)

    def test_extra_visible_text_is_rejected(self) -> None:
        raw = {
            **self._BASE,
            "html": _HTML.replace(
                "本喵要发光",
                "os-04-pond → 本喵要发光",
            ),
        }
        with pytest.raises(ValidationError, match="台词本身"):
            _validated_design(raw, required_text="本喵要发光")

    def test_small_decorative_text_is_tolerated(self) -> None:
        raw = {
            **self._BASE,
            "html": _HTML.replace("本喵要发光", "本喵要发光！"),
        }
        design = _validated_design(
            raw,
            required_text="本喵要发光",
            default_loop=False,
        )
        assert not isinstance(design, str)

    def test_css_only_text_fails_verbatim_check(self) -> None:
        raw = {
            **self._BASE,
            "html": (
                "<html><head><style>.card::after{content:'本喵要发光';}"
                "</style></head><body><div class='card'></div></body></html>"
            ),
        }
        with pytest.raises(ValidationError, match="一字不差"):
            _validated_design(raw, required_text="本喵要发光")

    def test_decoration_mode_still_honors_needed(self) -> None:
        raw = {
            **self._BASE,
            "html": _HTML,
            "needed": False,
            "skip_reason": "画面已经很满",
        }
        assert _validated_design(raw) == "画面已经很满"


class TestMotionDesignSafety:
    _DECOR = {
        "needed": True,
        "concept": "纯图形闪光",
        "fps": 24,
        "location": {
            "x": 0.1,
            "y": 0.1,
            "width": 0.2,
            "height": 0.2,
            "anchor_x": 0,
            "anchor_y": 0,
        },
    }

    def test_location_box_must_stay_inside_canvas(self) -> None:
        # An overshooting box is translated back inside (the size and
        # edge-hugging intent are unambiguous), never rejected outright.
        clamped = _validated_location(
            {
                "x": 0.95,
                "y": 0.1,
                "width": 0.2,
                "height": 0.2,
                "anchor_x": 0,
                "anchor_y": 0,
            },
        )
        assert clamped.x == pytest.approx(0.8)
        assert clamped.y == pytest.approx(0.1)
        left = clamped.x - clamped.anchor_x * clamped.width
        assert 0.0 <= left and left + clamped.width <= 1.0 + 1e-9
        # A box larger than the canvas is stopped by the size gate.
        with pytest.raises(ValidationError, match="1% 到 100%"):
            _validated_location(
                {
                    "x": 0.5,
                    "y": 0.5,
                    "width": 1.0,
                    "height": 1.2,
                },
            )

    def test_caption_rejects_narrow_vertical_box(self) -> None:
        location = ElementLocation(
            x=0.9,
            y=0.3,
            width=0.12,
            height=0.40,
            anchor_x=0.5,
            anchor_y=0.5,
        )

        with pytest.raises(ValidationError, match="location.width 太窄"):
            _validate_caption_location(location, "这红色是什么", (1280, 720))

    def test_caption_accepts_readable_horizontal_box(self) -> None:
        location = ElementLocation(
            x=0.5,
            y=0.85,
            width=0.60,
            height=0.20,
            anchor_x=0.5,
            anchor_y=0.5,
        )

        _validate_caption_location(location, "这红色是什么", (1280, 720))

    def test_text_design_applies_caption_geometry_validation(self) -> None:
        raw = {
            **TestValidatedDesignTextMode._BASE,
            "html": _HTML,
            "location": {
                "x": 0.9,
                "y": 0.3,
                "width": 0.12,
                "height": 0.40,
                "anchor_x": 0.5,
                "anchor_y": 0.5,
            },
        }

        with pytest.raises(ValidationError, match="location.width 太窄"):
            _validated_design(
                raw,
                required_text="本喵要发光",
                canvas_size=(1280, 720),
            )

    def test_caption_rejects_dom_text_occlusion(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_chat(*args, **kwargs):
            return (
                '{"concept":"警告字幕卡","html":'
                + json.dumps(_HTML)
                + ',"location":{"x":0.5,"y":0.8,"width":0.6,'
                '"height":0.2,"anchor_x":0.5,"anchor_y":0.5}}'
            )

        monkeypatch.setattr(
            motion_design.vlm_model,
            "chat_completion",
            fake_chat,
        )
        monkeypatch.setattr(
            motion_design,
            "probe_motion_document",
            lambda *args, **kwargs: MotionDocumentProbe(
                ok=True,
                animation_count=1,
                visible_coverage=0.5,
                edge_contact=0.0,
                text_occlusion=0.5,
            ),
        )

        with pytest.raises(ValidationError, match="图标或装饰遮挡"):
            asyncio.run(
                _design_document(
                    system_prompt="caption",
                    task_text="caption",
                    frame_paths=[],
                    canvas_size=(1280, 720),
                    required_text="本喵要发光",
                    max_attempts=1,
                ),
            )

    @pytest.mark.parametrize(
        "html",
        [
            "<html><body onload='alert(1)'><i></i></body></html>",
            "<html><body><iframe src='file:///etc/passwd'>"
            "</iframe></body></html>",
            "<html><body><a href='javascript:alert(1)'></a></body></html>",
        ],
    )
    def test_active_or_embedded_content_is_rejected(self, html: str) -> None:
        with pytest.raises(ValidationError):
            _validated_design({**self._DECOR, "html": html})

    def test_allowlisted_motif_uses_trusted_template(self) -> None:
        design = _validated_design(
            {
                **self._DECOR,
                "motif": "approval_checks",
                "primary_color": "#66aa55",
                "secondary_color": "#224422",
                "html": "",
            },
        )
        assert not isinstance(design, str)
        motion, _location, _concept = design
        assert motion.motif == "approval_checks"
        assert motion.template_version == MOTION_TEMPLATE_VERSION
        assert 'data-motion-motif="approval_checks"' in motion.html
        assert "#66aa55" in motion.html


class TestMotionTemplates:
    @pytest.mark.parametrize("motif", sorted(SUPPORTED_MOTIFS))
    def test_every_template_is_text_free_and_animated(
        self,
        motif: str,
    ) -> None:
        html = render_decoration_template(motif)
        assert f'data-motion-motif="{motif}"' in html
        assert "@keyframes" in html
        assert len(html) >= 32

    def test_paw_trail_uses_the_trusted_three_paw_sequence(self) -> None:
        html = render_decoration_template("paw_trail")

        assert html.count('class="shape paw p') == 3
        assert "animation-delay:.08s" in html
        assert "animation-delay:.38s" in html
        assert "animation-delay:.68s" in html
        assert ".toe{width:20%;height:20%" in html
        assert ".t2{left:27%;top:7%}" in html
        assert ".t3{right:27%;top:3%}" in html

    def test_alert_mark_keeps_the_dot_above_the_triangle_border(self) -> None:
        html = render_decoration_template("alert_mark")

        assert ".dot{left:45%;top:62%;width:10%" in html

    def test_template_metadata_survives_loading_older_project_json(
        self,
    ) -> None:
        html = render_decoration_template(
            "alert_mark",
            theme="neon_night",
            variant="neon",
            emotion="surprise",
            entrance="stamp",
            exit="shrink",
            intensity=0.85,
        )
        motion = MotionGraphic.model_validate({"html": html})

        assert motion.motif == "alert_mark"
        assert motion.template_version == MOTION_TEMPLATE_VERSION
        assert motion.theme == "neon_night"
        assert motion.variant == "neon"
        assert motion.emotion == "surprise"
        assert motion.entrance == "stamp"
        assert motion.exit == "shrink"
        assert motion.intensity == pytest.approx(0.85)

    def test_caption_fallback_keeps_exact_text_and_escapes_markup(
        self,
    ) -> None:
        html = render_caption_template("飞！<安全>", emotion="action")

        assert "飞！&lt;安全&gt;" in html
        assert 'data-motion-motif="caption_card"' in html
        design = _validated_design(
            {
                "concept": "可靠动态字幕卡",
                "html": html,
                "location": {
                    "x": 0.78,
                    "y": 0.23,
                    "width": 0.34,
                    "height": 0.30,
                    "anchor_x": 0.5,
                    "anchor_y": 0.5,
                },
            },
            required_text="飞！<安全>",
            default_loop=False,
        )
        assert not isinstance(design, str)

    def test_caption_fallback_shrinks_long_copy_to_stay_inside_card(
        self,
    ) -> None:
        html = render_caption_template("大家快看它挺淡定，还有点意思")

        assert "font-size:8.5vh" in html
        assert "line-height:1.08" in html
        assert "overflow:hidden" in html

    def test_caption_font_size_uses_box_dimensions_for_short_text(
        self,
    ) -> None:
        html = render_caption_template(
            "快看",
            box_width=0.80,
            box_height=0.18,
        )
        assert "font-size:13.5vh" in html

    def test_caption_font_size_uses_box_dimensions_for_long_text(self) -> None:
        html = render_caption_template(
            "大家快看它挺淡定，还有点意思",
            box_width=0.80,
            box_height=0.18,
        )
        assert "font-size:11.6vh" in html

    def test_caption_font_size_larger_box_produces_larger_font(self) -> None:
        small = render_caption_template("测试", box_width=0.40, box_height=0.10)
        large = render_caption_template("测试", box_width=0.80, box_height=0.30)
        small_size = float(small.split("font-size:")[1].split("vh")[0])
        large_size = float(large.split("font-size:")[1].split("vh")[0])
        assert large_size > small_size

    def test_decoration_css_content_text_is_rejected(self) -> None:
        html = (
            "<html><head><style>.x:after{content:'WOW'}</style></head>"
            "<body><i class='x'></i></body></html>"
        )
        with pytest.raises(ValidationError, match="CSS content"):
            _validated_design(
                {**TestMotionDesignSafety._DECOR, "html": html},
            )


class TestMotionStoryArc:
    def test_neutral_fallback_has_three_connected_beats(self) -> None:
        arc = _story_arc_motifs(["opening", "meeting", "ending"])

        assert arc["opening"][1] == "focus_target"
        assert arc["opening"][2]["entrance"] == "draw_in"
        assert arc["meeting"][1] == "sparkles"
        assert arc["ending"][1] == "approval_checks"

    def test_free_form_plan_is_used_without_story_categories(self) -> None:
        beats = [
            ("雨滴出现", "leaf_accent", {"emotion": "chill"}),
            ("突然加速", "paw_trail", {"emotion": "action"}),
            ("停在门前", "focus_target", {"emotion": "curious"}),
        ]
        arc = _story_arc_motifs(["opening", "turn", "ending"], beats)

        assert arc["opening"] == beats[0]
        assert arc["turn"] == beats[1]
        assert arc["ending"] == beats[2]

    def test_story_plan_rejects_unknown_visual_vocabulary(self) -> None:
        assert (
            _validated_story_beats(
                [
                    {
                        "role": "开场",
                        "motif": "invented_shape",
                        "emotion": "chill",
                        "entrance": "pop",
                        "exit": "soft_fade",
                        "intensity": 0.5,
                    },
                ]
                * 3,
            )
            is None
        )


class TestAlphaPlaneStats:
    def _plane(
        self,
        width: int,
        height: int,
        visible: set[tuple[int, int]],
    ) -> bytes:
        return bytes(
            255 if (x, y) in visible else 0
            for y in range(height)
            for x in range(width)
        )

    def test_centered_content_has_no_edge_contact(self) -> None:
        visible = {(x, y) for x in range(2, 8) for y in range(2, 8)}
        coverage, edge, center, edge_floor = _alpha_plane_stats(
            self._plane(10, 10, visible),
            10,
            10,
        )
        assert coverage == pytest.approx(0.36)
        assert edge == 0.0
        assert edge_floor == 0.0
        # The whole 3..7 center window is painted.
        assert center == pytest.approx(1.0)

    def test_clipped_content_touches_edge(self) -> None:
        visible = {(9, y) for y in range(3, 8)}
        coverage, edge, center, edge_floor = _alpha_plane_stats(
            self._plane(10, 10, visible),
            10,
            10,
        )
        assert coverage == pytest.approx(0.05)
        assert edge == pytest.approx(0.5)
        # One-sided overflow: the other edges stay empty.
        assert edge_floor == 0.0
        # Edge column stays outside the center window.
        assert center == 0.0

    def test_geometry_mismatch_returns_unknown(self) -> None:
        assert _alpha_plane_stats(b"\xff" * 10, 10, 10) == (
            -1.0,
            -1.0,
            -1.0,
            -1.0,
        )


def _edit_element(
    element_id: str,
    start_tick: int,
    intent: str,
) -> TimelineElement:
    return TimelineElement(
        element_id=element_id,
        span=TimelineSpan(start_tick=start_tick, duration_tick=1000),
        location=ElementLocation(),
        creation=EditCreation(intent=intent),
    )


class TestSelectDecorationIds:
    def _elements(self, count: int) -> list[TimelineElement]:
        return [
            _edit_element(f"seg-{index}", index * 1000, f"意图 {index}")
            for index in range(count)
        ]

    def _timeline(self) -> Timeline:
        return Timeline(timeline_id="tl-1")

    def test_zero_budget_selects_nothing(self) -> None:
        selected = asyncio.run(
            _select_decoration_ids(
                edit_elements=self._elements(5),
                timeline=self._timeline(),
                budget=0,
                brief="",
            ),
        )
        assert selected == set()

    def test_few_segments_all_selected_without_model_call(self) -> None:
        selected = asyncio.run(
            _select_decoration_ids(
                edit_elements=self._elements(2),
                timeline=self._timeline(),
                budget=3,
                brief="",
            ),
        )
        assert selected == {"seg-0", "seg-1"}

    def test_model_answer_is_filtered_and_truncated(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def fake_chat(*args, **kwargs):
            return (
                '{"selected": ["seg-1", "ghost", "seg-4", "seg-0", "seg-2"]}'
            )

        monkeypatch.setattr(
            motion_design.vlm_model,
            "chat_completion",
            fake_chat,
        )
        selected = asyncio.run(
            _select_decoration_ids(
                edit_elements=self._elements(6),
                timeline=self._timeline(),
                budget=2,
                brief="轻快",
            ),
        )
        assert selected == {"seg-1", "seg-4"}

    def test_model_failure_falls_back_to_even_sampling(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def broken_chat(*args, **kwargs):
            raise RuntimeError("model down")

        monkeypatch.setattr(
            motion_design.vlm_model,
            "chat_completion",
            broken_chat,
        )
        elements = self._elements(9)
        selected = asyncio.run(
            _select_decoration_ids(
                edit_elements=elements,
                timeline=self._timeline(),
                budget=3,
                brief="",
            ),
        )
        assert len(selected) == 3
        assert selected <= {element.element_id for element in elements}


def _layer_prep(tmp_path) -> MotionLayerPrep:
    """A minimal prepared layer for mocking the capture stage."""

    return MotionLayerPrep(
        layer=PreparedMotionLayer(
            frames_dir=tmp_path,
            frame_count=1,
            effective_fps=24.0,
            appear_at=0.0,
            duration=1.0,
            left=0,
            top=0,
            opacity=1.0,
            period_mode=False,
            managed_exit=False,
        ),
    )


class TestApplyOverlayStyledRouting:
    def _runner(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> FfmpegLocalMediaRunner:
        runner = FfmpegLocalMediaRunner(executable="ffmpeg")
        monkeypatch.setattr(
            FfmpegLocalMediaRunner,
            "_probe_video_size",
            lambda self, path: (1280, 720),
        )
        monkeypatch.setattr(
            local_execution_module,
            "probe_motion_document",
            lambda *args, **kwargs: MotionDocumentProbe(
                ok=True,
                animation_count=1,
                edge_contact=0.0,
                text_occlusion=0.0,
            ),
        )
        return runner

    def _input(
        self,
        tmp_path,
        *,
        motion: dict | None,
        location: dict | None = None,
    ) -> tuple[LocalMediaInput, object]:
        segment = tmp_path / "segment.mp4"
        segment.write_bytes(b"original")
        overlay = {
            "kind": "pet_os",
            "text": "本喵要发光",
            "vibe": "chill",
            "appear_at": 0.0,
            "duration": 4.0,
            "motion": motion,
            "location": location,
        }
        item = LocalMediaInput(
            version_id="ver-1",
            file_id=None,
            checksum="0" * 64,
            media_type="video/mp4",
            path=segment,
            source_ref="source:src-1",
            start_seconds=0.0,
            end_seconds=4.0,
            overlays=(overlay,),
        )
        return item, segment

    def test_motion_success_skips_fixed_template(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []

        def fake_prepare(**kwargs):
            calls.append("prepare")
            return _layer_prep(tmp_path)

        def fake_composite(**kwargs):
            calls.append("burn")
            kwargs["output_path"].write_bytes(b"styled")
            return OverlayRenderResult(success=True)

        def fake_pet_os(**kwargs):
            calls.append("pet_os")
            return OverlayRenderResult(success=True)

        monkeypatch.setattr(
            local_execution_module,
            "prepare_motion_layer",
            fake_prepare,
        )
        monkeypatch.setattr(
            local_execution_module,
            "composite_motion_layers",
            fake_composite,
        )
        monkeypatch.setattr(
            local_execution_module,
            "render_pet_os_overlay",
            fake_pet_os,
        )
        runner = self._runner(monkeypatch)
        item, segment = self._input(
            tmp_path,
            motion={"html": _HTML, "fps": 24, "loop": False},
        )
        warnings = runner._apply_overlay(item, segment)
        assert not warnings
        assert calls == ["prepare", "burn"]
        assert segment.read_bytes() == b"styled"

    def test_motion_failure_falls_back_with_warning(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []

        def fake_prepare(**kwargs):
            calls.append("prepare")
            return MotionLayerPrep(error="capture crashed")

        def fake_pet_os(**kwargs):
            calls.append("pet_os")
            kwargs["output_path"].write_bytes(b"bubble")
            return OverlayRenderResult(success=True)

        monkeypatch.setattr(
            local_execution_module,
            "prepare_motion_layer",
            fake_prepare,
        )
        monkeypatch.setattr(
            local_execution_module,
            "render_pet_os_overlay",
            fake_pet_os,
        )
        runner = self._runner(monkeypatch)
        item, segment = self._input(
            tmp_path,
            motion={"html": _HTML, "fps": 24, "loop": False},
        )
        warnings = runner._apply_overlay(item, segment)
        assert len(warnings) == 1
        assert "回退固定样式" in warnings[0]
        assert "capture crashed" in warnings[0]
        assert calls == ["prepare", "prepare", "pet_os"]
        assert segment.read_bytes() == b"bubble"

    def test_without_motion_uses_fixed_template(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []

        def fake_motion(**kwargs):
            calls.append("motion")
            return OverlayRenderResult(success=True)

        def fake_pet_os(**kwargs):
            calls.append("pet_os")
            kwargs["output_path"].write_bytes(b"bubble")
            return OverlayRenderResult(success=True)

        monkeypatch.setattr(
            local_execution_module,
            "render_motion_overlay",
            fake_motion,
        )
        monkeypatch.setattr(
            local_execution_module,
            "render_pet_os_overlay",
            fake_pet_os,
        )
        runner = self._runner(monkeypatch)
        item, segment = self._input(tmp_path, motion=None)
        warnings = runner._apply_overlay(item, segment)
        assert not warnings
        assert calls == ["pet_os"]

    def test_unsafe_stored_motion_falls_back_during_compose(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []
        safe_motion_locations: list[dict] = []
        safe_motion_html: list[str] = []

        def fake_prepare(**kwargs):
            calls.append("prepare")
            safe_motion_locations.append(kwargs["location"])
            safe_motion_html.append(kwargs["html"])
            return _layer_prep(tmp_path)

        def fake_composite(**kwargs):
            calls.append("burn")
            kwargs["output_path"].write_bytes(b"safe motion")
            return OverlayRenderResult(success=True)

        def fake_pet_os(**kwargs):
            calls.append("pet_os")
            kwargs["output_path"].write_bytes(b"safe bubble")
            return OverlayRenderResult(success=True)

        monkeypatch.setattr(
            local_execution_module,
            "prepare_motion_layer",
            fake_prepare,
        )
        monkeypatch.setattr(
            local_execution_module,
            "composite_motion_layers",
            fake_composite,
        )
        monkeypatch.setattr(
            local_execution_module,
            "render_pet_os_overlay",
            fake_pet_os,
        )
        runner = self._runner(monkeypatch)
        item, segment = self._input(
            tmp_path,
            motion={"html": _HTML, "fps": 24, "loop": False},
            location={
                "x": 0.9,
                "y": 0.3,
                "width": 0.12,
                "height": 0.4,
                "anchor_x": 0.5,
                "anchor_y": 0.5,
            },
        )

        warnings = runner._apply_overlay(item, segment)

        assert calls == ["prepare", "burn"]
        assert segment.read_bytes() == b"safe motion"
        assert len(warnings) == 1
        assert "未通过合成安全检查" in warnings[0]
        assert "location.width 太窄" in warnings[0]
        assert "统一安全动效模板" in warnings[0]
        assert safe_motion_locations == [
            {
                "x": 0.5,
                "y": 0.88,
                "width": 0.8,
                "height": 0.18,
                "anchor_x": 0.5,
                "anchor_y": 0.5,
                "opacity": 1.0,
            },
        ]
        assert 'data-motion-motif="caption_card"' in safe_motion_html[0]


class TestVarietyFrameDesign:
    """Deterministic variety frame: window derivation and conventions."""

    def test_window_mirrors_shrunk_edit_placement(self) -> None:
        location = ElementLocation(
            x=0.5,
            y=0.48,
            width=0.84,
            height=0.80,
            anchor_x=0.5,
            anchor_y=0.5,
        )
        window = motion_design._frame_window_from_edit(location)
        assert window == {
            "left": pytest.approx(0.08),
            "top": pytest.approx(0.08),
            "width": pytest.approx(0.84),
            "height": pytest.approx(0.80),
        }

    def test_full_frame_or_rotated_edit_keeps_default_window(self) -> None:
        assert motion_design._frame_window_from_edit(None) is None
        assert motion_design._frame_window_from_edit(ElementLocation()) is None
        rotated = ElementLocation(width=0.8, height=0.8, rotation_degrees=8.0)
        assert motion_design._frame_window_from_edit(rotated) is None

    def test_frame_overlay_convention_is_text_free_with_prompt(self) -> None:
        # The director creates the declaration (text-free, vibe="frame",
        # prompt states the intent); the design tool fills creation.motion.
        creation = OverlayCreation(vibe="frame", prompt="家庭高光时刻包裹框")
        assert overlay_role(creation) == "decoration"
        assert creation.motion is None


class TestUniformCaptionStyle:
    def test_bad_caption_style_is_rejected_before_any_read(self) -> None:
        with pytest.raises(ValidationError, match="captionStyle"):
            asyncio.run(
                motion_design.design_motion_overlays(
                    object(),
                    project_id="p1",
                    target_ref="timeline:main",
                    arguments={"captionStyle": "rainbow"},
                    idempotency_key="k1",
                ),
            )

    def test_uniform_blueprint_renders_identically_across_cards(self) -> None:
        """Uniform narration captions share one deterministic skeleton:
        two cards differ only by their words, never by style."""

        from services.media_files.motion_blueprints import (
            render_caption_blueprint,
        )

        blueprint = motion_design._UNIFORM_CAPTION_BLUEPRINT
        intensity = motion_design._UNIFORM_CAPTION_INTENSITY
        first, _ = render_caption_blueprint(
            blueprint,
            "第一句旁白。",
            intensity=intensity,
        )
        again, _ = render_caption_blueprint(
            blueprint,
            "第一句旁白。",
            intensity=intensity,
        )
        assert first == again  # deterministic, no per-card variation
        second, _ = render_caption_blueprint(
            blueprint,
            "第二句旁白。",
            intensity=intensity,
        )
        assert first.replace("第一句旁白。", "") == second.replace(
            "第二句旁白。",
            "",
        )

    def test_uniform_blueprint_font_size_ignores_text_length(self) -> None:
        """The static capsule keeps one fixed font size: a long sentence
        wraps instead of shrinking, so short and long captions share the
        exact same style skeleton (the hyperframes caption-bar contract)."""

        from services.media_files.motion_blueprints import (
            render_caption_blueprint,
        )

        blueprint = motion_design._UNIFORM_CAPTION_BLUEPRINT
        intensity = motion_design._UNIFORM_CAPTION_INTENSITY
        short_text = "所以x等于3。"
        long_text = "这道题要求我们解一元一次方程，6乘以括号x加2，等于30。"
        short_doc, _ = render_caption_blueprint(
            blueprint,
            short_text,
            intensity=intensity,
        )
        long_doc, _ = render_caption_blueprint(
            blueprint,
            long_text,
            intensity=intensity,
        )
        # Style skeleton (all CSS, including font-size) is byte-identical
        # across very different text lengths -- only the words differ.
        assert short_doc.replace(short_text, "") == long_doc.replace(
            long_text,
            "",
        )
        # No adaptive vw/text-length term ever reaches the font size.
        assert "font-size:24vh" in short_doc
        # No per-card entrance choreography beyond the single card fade.
        for performance in ("letterSpacing", "scaleY", "stagger"):
            assert performance not in short_doc
        # Compose probes reject documents whose t=0 frame is fully
        # transparent, so the fade must start from partial visibility.
        assert "autoAlpha:0}" not in short_doc
        assert "autoAlpha:.35" in short_doc
        # Captions hand over back-to-back: a managed exit fade would
        # double-expose neighbouring cards, so the exit is a hard cut.
        assert 'data-motion-exit="none"' in short_doc


class TestSegmentCache:
    """Finished-segment cache: identity coverage and round trip."""

    def _spec(self, tmp_path):
        from domain.enums import CreatorCommandType
        from services.media_files.local_execution import (
            LocalMediaExecutionSpec,
        )

        return LocalMediaExecutionSpec(
            command=CreatorCommandType.COMPOSE_FINAL_VIDEO,
            target_ref="timeline:main",
            task_id="task-1",
            work_dir=tmp_path,
            output_path=tmp_path / "out.mp4",
            inputs=(),
            transitions=(),
            audio_plan="",
            expected_duration_seconds=None,
            canvas_size=(1280, 720),
        )

    def _item(self, tmp_path, *, checksum="a" * 64, overlays=()):
        segment = tmp_path / "src.mp4"
        segment.write_bytes(b"src")
        return LocalMediaInput(
            version_id="ver-1",
            file_id=None,
            checksum=checksum,
            media_type="video/mp4",
            path=segment,
            source_ref="element:clip-1",
            start_seconds=0.0,
            end_seconds=4.0,
            overlays=tuple(overlays),
        )

    def test_key_tracks_burned_layer_checksum_not_html(
        self,
        tmp_path,
    ) -> None:
        runner = FfmpegLocalMediaRunner(executable="ffmpeg")
        spec = self._spec(tmp_path)

        def overlay(checksum: str, html: str) -> dict:
            return {
                "kind": "pet_os",
                "text": "第一句",
                "vibe": "chill",
                "appear_at": 0.0,
                "duration": 2.0,
                "motion": {
                    "format": "html_js",
                    "html": html,
                    "checksum": checksum,
                    "fps": 24,
                    "loop": False,
                },
                "location": None,
                "element_id": "overlay-1",
            }

        base = runner._segment_cache_key(
            spec,
            self._item(tmp_path, overlays=[overlay("c1", "<html>a")]),
            segment_duration=4.0,
            freeze_duration=0.0,
        )
        # Identical content with a different (never-fingerprinted) html
        # body: hydration state must not split the cache.
        same = runner._segment_cache_key(
            spec,
            self._item(tmp_path, overlays=[overlay("c1", "<html>b")]),
            segment_duration=4.0,
            freeze_duration=0.0,
        )
        changed = runner._segment_cache_key(
            spec,
            self._item(tmp_path, overlays=[overlay("c2", "<html>a")]),
            segment_duration=4.0,
            freeze_duration=0.0,
        )
        assert base == same
        assert base != changed
        # Canvas geometry always reaches the key.
        other_canvas = self._spec(tmp_path)
        object.__setattr__(other_canvas, "canvas_size", (1920, 1080))
        assert base != runner._segment_cache_key(
            other_canvas,
            self._item(tmp_path, overlays=[overlay("c1", "<html>a")]),
            segment_duration=4.0,
            freeze_duration=0.0,
        )
        # No stable source checksum -> never cached.
        assert (
            runner._segment_cache_key(
                spec,
                self._item(tmp_path, checksum=""),
                segment_duration=4.0,
                freeze_duration=0.0,
            )
            is None
        )

    def test_store_and_restore_round_trip(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        runner = FfmpegLocalMediaRunner(executable="ffmpeg")
        monkeypatch.setattr(
            FfmpegLocalMediaRunner,
            "_segment_cache_root",
            staticmethod(lambda: tmp_path / "cache"),
        )
        (tmp_path / "cache").mkdir()
        rendered = tmp_path / "rendered.mp4"
        rendered.write_bytes(b"finished segment")
        runner._store_cached_segment("k" * 64, rendered, ["warn-1"])
        restored = tmp_path / "restored.mp4"
        warnings = runner._restore_cached_segment("k" * 64, restored)
        assert warnings == ("warn-1",)
        assert restored.read_bytes() == b"finished segment"
        assert runner._restore_cached_segment("m" * 64, restored) is None


def test_frame_overlay_recognition_covers_field_variants() -> None:
    # Taught convention: vibe="frame". Field variant: emotional vibe,
    # frame wording in the label, hand-written thin-border css motion —
    # recognised so the blueprint pass can upgrade it.
    def overlay(vibe: str, label: str, motion=None) -> TimelineElement:
        return TimelineElement(
            element_id="elem:ov-frame-x",
            label=label,
            span=TimelineSpan(start_tick=0, duration_tick=3000),
            location=ElementLocation(),
            creation=OverlayCreation(
                vibe=vibe,
                prompt="综艺感手绘边框，包裹画面",
                motion=motion,
            ),
        )

    assert motion_design._is_frame_overlay(overlay("frame", "框"))
    hand_written = MotionGraphic(
        format="html_css",
        html="<html><body><div style='border:2px solid pink'>"
        + "x" * 32
        + "</div></body></html>",
        motif="custom",
    )
    assert motion_design._is_frame_overlay(
        overlay("playful", "综艺框·鬼脸", motion=hand_written),
    )
    blueprint_done = MotionGraphic(
        format="html_js",
        html="<html><body>" + "y" * 40 + "</body></html>",
        motif="variety_frame",
    )
    assert not motion_design._is_frame_overlay(
        overlay("frame", "综艺框", motion=blueprint_done),
    )
    # Plain decorations without frame wording stay untouched.
    plain = TimelineElement(
        element_id="elem:ov-decor",
        label="装饰",
        span=TimelineSpan(start_tick=0, duration_tick=3000),
        location=ElementLocation(),
        creation=OverlayCreation(vibe="chill", prompt="微光粒子点缀"),
    )
    assert not motion_design._is_frame_overlay(plain)


def test_required_text_tolerates_punctuation_reexpression(
    stub_gsap_vendor,
) -> None:
    # Expressive lettering replaces the comma with a line break and the
    # exclamation mark with an accent shape; characters stay verbatim.
    hf = (
        "<script src='vendor/gsap.min.js'></script>"
        "<script>var tl = gsap.timeline({paused:true});"
        "window.__hf={duration:2.0,seek:function(t){tl.totalTime(t)}};"
        "</script>"
    )
    html = (
        "<!DOCTYPE html><html><body><div class='l1'>整蛊老爸</div>"
        "<div class='l2'>行动</div><i class='accent'></i>"
        + hf
        + "</body></html>"
    )
    motion, _loc, _concept = _validated_design(
        {
            "concept": "斜角花字",
            "format": "html_js",
            "html": html,
            "fps": 24,
            "loop": False,
            "location": {
                "x": 0.5,
                "y": 0.3,
                "width": 0.5,
                "height": 0.24,
            },
        },
        required_text="整蛊老爸，行动！",
        default_loop=False,
        canvas_size=(1280, 720),
    )
    assert motion.format == "html_js"
    # Rewriting the words themselves is still rejected.
    with pytest.raises(ValidationError, match="一字不差"):
        _validated_design(
            {
                "concept": "改词",
                "format": "html_js",
                "html": (
                    "<!DOCTYPE html><html><body><div>整老爸行动</div>"
                    + hf
                    + "</body></html>"
                ),
                "fps": 24,
                "loop": False,
                "location": {
                    "x": 0.5,
                    "y": 0.3,
                    "width": 0.5,
                    "height": 0.24,
                },
            },
            required_text="整蛊老爸，行动！",
            default_loop=False,
            canvas_size=(1280, 720),
        )


def test_repair_recovers_missing_script_close_tag() -> None:
    # Field run 2026-08-09: the model dropped </script> after the vendor
    # include, browsers swallowed the inline timeline, and every retry
    # died on "__hf 未注册" — a pure syntax slip, fixed deterministically.
    from services.media_files.motion_design import _repair_common_html_slips

    nested = '<script src="vendor/gsap.min.js">\n<script>var tl = 1;</script>'
    fixed = _repair_common_html_slips(nested)
    assert (
        'vendor/gsap.min.js">\n</script><script>var tl = 1;</script>'
        in (fixed.replace('vendor/gsap.min.js">', 'vendor/gsap.min.js">', 1))
        or fixed.count("</script>") == 2
    )
    inline_in_src = '<script src="vendor/gsap.min.js">var tl = 2;</script>'
    fixed2 = _repair_common_html_slips(inline_in_src)
    assert fixed2.count("<script") == 2 and "var tl = 2;" in fixed2
    # Well-formed documents pass through unchanged.
    good = (
        '<script src="vendor/gsap.min.js"></script>'
        "<script>var tl = 3;</script>"
    )
    assert _repair_common_html_slips(good) == good


def test_repair_lifts_zero_starting_opacity() -> None:
    from services.media_files.motion_design import _repair_common_html_slips

    html = (
        "<style>.a{opacity:0;} .b{opacity:0.8}</style>"
        '<script src="vendor/gsap.min.js"></script>'
        "<script>tl.from('.a',{autoAlpha:0,y:20});"
        "tl.fromTo('.b',{opacity: 0.0},{opacity:1});"
        "tl.to('.c',{opacity:0.6});</script>"
    )
    fixed = _repair_common_html_slips(html)
    assert "autoAlpha:0.25" in fixed
    assert "opacity: 0.25" in fixed or "opacity:0.25" in fixed
    # Non-zero values stay untouched.
    assert "opacity:0.8" in fixed and "opacity:0.6" in fixed
