# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=unused-argument,protected-access

from __future__ import annotations

import asyncio

import pytest

from domain.errors import ValidationError
from services.media_files import local_execution as local_execution_module
from services.media_files import motion_design
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    LocalMediaInput,
)
from services.media_files.motion_design import (
    _select_decoration_ids,
    _story_arc_motifs,
    _validated_story_beats,
    _validated_design,
    _validated_location,
)
from services.media_files.motion_overlay import _alpha_plane_stats
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
)

_HTML = "<html><body><div class='card'>本喵要发光</div></body></html>"


def _motion() -> MotionGraphic:
    return MotionGraphic(html=_HTML, fps=24, loop=False)


class TestOverlayCreationMotionValidator:
    def test_pet_os_accepts_motion_styling(self) -> None:
        creation = OverlayCreation(
            overlay_kind="pet_os",
            text="本喵要发光",
            motion=_motion(),
        )
        assert creation.motion is not None

    def test_interview_summary_accepts_motion_styling(self) -> None:
        creation = OverlayCreation(
            overlay_kind="interview_summary",
            text="核心观点",
            motion=_motion(),
        )
        assert creation.motion is not None

    def test_media_rejects_motion(self) -> None:
        with pytest.raises(ValueError, match="overlay_kind=media"):
            OverlayCreation(
                overlay_kind="media",
                prompt="一张贴纸",
                motion=_motion(),
            )


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
        with pytest.raises(ValidationError, match="超出画布边界"):
            _validated_location(
                {
                    "x": 0.95,
                    "y": 0.1,
                    "width": 0.2,
                    "height": 0.2,
                    "anchor_x": 0,
                    "anchor_y": 0,
                },
            )

    @pytest.mark.parametrize(
        "html",
        [
            "<html><body onload='alert(1)'><i></i></body></html>",
            "<html><body><iframe src='file:///etc/passwd'></iframe></body></html>",
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
        coverage, edge = _alpha_plane_stats(
            self._plane(10, 10, visible),
            10,
            10,
        )
        assert coverage == pytest.approx(0.36)
        assert edge == 0.0

    def test_clipped_content_touches_edge(self) -> None:
        visible = {(9, y) for y in range(3, 8)}
        coverage, edge = _alpha_plane_stats(
            self._plane(10, 10, visible),
            10,
            10,
        )
        assert coverage == pytest.approx(0.05)
        assert edge == pytest.approx(0.5)

    def test_geometry_mismatch_returns_unknown(self) -> None:
        assert _alpha_plane_stats(b"\xff" * 10, 10, 10) == (-1.0, -1.0)


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
        return runner

    def _input(
        self,
        tmp_path,
        *,
        motion: dict | None,
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
            overlay=overlay,
        )
        return item, segment

    def test_motion_success_skips_fixed_template(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []

        def fake_motion(**kwargs):
            calls.append("motion")
            kwargs["output_path"].write_bytes(b"styled")
            return OverlayRenderResult(success=True)

        def fake_pet_os(**kwargs):
            calls.append("pet_os")
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
        item, segment = self._input(
            tmp_path,
            motion={"html": _HTML, "fps": 24, "loop": False},
        )
        warning = runner._apply_overlay(item, segment)
        assert warning is None
        assert calls == ["motion"]
        assert segment.read_bytes() == b"styled"

    def test_motion_failure_falls_back_with_warning(
        self,
        tmp_path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[str] = []

        def fake_motion(**kwargs):
            calls.append("motion")
            return OverlayRenderResult(success=False, error="capture crashed")

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
        item, segment = self._input(
            tmp_path,
            motion={"html": _HTML, "fps": 24, "loop": False},
        )
        warning = runner._apply_overlay(item, segment)
        assert warning is not None
        assert "回退固定样式" in warning
        assert "capture crashed" in warning
        assert calls == ["motion", "pet_os"]
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
        warning = runner._apply_overlay(item, segment)
        assert warning is None
        assert calls == ["pet_os"]
