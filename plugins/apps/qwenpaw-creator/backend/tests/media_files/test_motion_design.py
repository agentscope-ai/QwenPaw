# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=unused-argument,protected-access,redefined-outer-name

from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

import pytest

from domain.errors import ValidationError
from services.media_files import local_execution as local_execution_module
from services.media_files import motion_design
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    LocalMediaInput,
)
from services.media_files.motion_design import (
    design_canvas_size,
    _repair_common_html_slips,
    _select_decoration_ids,
    _validated_design,
    _validate_caption_location,
    _validated_location,
)
from services.media_files.motion_overlay import (
    MotionDocumentProbe,
    MotionLayerPrep,
    PreparedMotionLayer,
)
from services.media_files.motion_blueprints import (
    caption_style_state,
    subtitle_pack_animation,
    subtitle_pack_typography,
    subtitle_style_override_line,
)
from services.media_files.motion_templates import (
    CAPTION_TEMPLATE_VERSION,
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
    ProjectSettings,
    SubtitleStyle,
    Timeline,
    TimelineElement,
    TimelineSpan,
)

_HTML = "<html><body><div class='card'>本喵要发光</div></body></html>"


class TestValidatedDesignTextMode:
    _BASE = {
        "concept": "发光字幕卡",
        "fps": 24,
        "location": {"x": 0.9, "y": 0.3, "width": 0.2, "height": 0.4},
    }

    @pytest.mark.parametrize(
        ("html", "match"),
        [
            (_HTML.replace("本喵要发光", "本喵想发光"), "一字不差"),
            (
                # CSS-only text never counts as verbatim copy.
                "<html><head><style>.card::after{content:'本喵要发光';}"
                "</style></head><body><div class='card'></div></body></html>",
                "一字不差",
            ),
        ],
        ids=["rewritten-copy", "css-only-copy"],
    )
    def test_non_verbatim_text_is_rejected(
        self,
        html: str,
        match: str,
    ) -> None:
        with pytest.raises(ValidationError, match=match):
            _validated_design(
                {**self._BASE, "html": html},
                required_text="本喵要发光",
            )

    def test_wrapping_is_tolerated(self) -> None:
        design = _validated_design(
            {**self._BASE, "html": _HTML.replace("本喵要发光", "本喵\n要发光")},
            required_text="本喵要发光",
            default_loop=False,
        )
        assert not isinstance(design, str)

    def test_scene_mode_allows_visible_text(self) -> None:
        # Full-canvas motion clips may carry copy; only decorations must
        # stay text-free.
        raw = {**self._BASE, "needed": True, "html": _HTML}
        with pytest.raises(ValidationError, match="不允许包含任何可见文字"):
            _validated_design(raw, default_loop=False)
        design = _validated_design(
            raw,
            allow_visible_text=True,
            default_loop=False,
        )
        assert not isinstance(design, str)


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
                {"x": 0.5, "y": 0.5, "width": 1.0, "height": 1.2},
            )

    def test_caption_geometry_gate_rejects_narrow_accepts_wide(self) -> None:
        narrow = ElementLocation(
            x=0.9,
            y=0.3,
            width=0.12,
            height=0.40,
            anchor_x=0.5,
            anchor_y=0.5,
        )
        with pytest.raises(ValidationError, match="location.width 太窄"):
            _validate_caption_location(narrow, "这红色是什么", (1280, 720))
        wide = ElementLocation(
            x=0.5,
            y=0.85,
            width=0.60,
            height=0.20,
            anchor_x=0.5,
            anchor_y=0.5,
        )
        _validate_caption_location(wide, "这红色是什么", (1280, 720))

    def test_default_subtitle_box_fits_two_languages(self) -> None:
        from services.media_files.motion_templates import (
            DEFAULT_CAPTION_LOCATION,
        )

        _validate_caption_location(
            ElementLocation(**DEFAULT_CAPTION_LOCATION),
            "让画面自己讲故事\nLet the picture tell its story",
            (1280, 720),
        )

    # Each caption_role is documented in the agent prompt with the kind of
    # text it carries, so its preset has to render that text rather than an
    # arbitrary sample.  These budgets are the documented worst case.
    _ROLE_TEXTS = {
        "dialogue": [
            "让画面自己讲故事\nLet the picture tell its story",
            "那天晚上他站在门口很久什么都没有说",
        ],
        "narration": [
            "让画面自己讲故事\nLet the picture tell its story",
            "后来的很多年里，我常常想起那个下午",
        ],
        "opening_title": ["星河入梦", "星河入梦·第一幕"],
        "opening_credit": ["导演 张三\n编剧 李四", "主演 王五 赵六"],
        "ending_credit": ["感谢\n联合出品 星辰影业\n特别鸣谢 各位观众"],
        "location": ["巴黎，1942", "三年后"],
        "chapter": ["第二章 雨夜告别", "幕间"],
        "interview_summary": [
            "让画面自己讲故事\nLet the picture tell its story",
            "这座城市的光伏装机量在五年内增长了十二倍",
        ],
    }
    # The guard has to sample the canvases the design path can actually hand
    # it.  ``design_canvas_size`` only ever uses a 720 or 1080 short side, so
    # a hand-written 4K row tested a geometry that never reaches this code.
    _CAPTION_CANVASES = [
        design_canvas_size(
            SimpleNamespace(
                settings=SimpleNamespace(
                    aspect_ratio=ratio,
                    resolution=resolution,
                ),
            ),
        )
        for ratio in ("16:9", "9:16", "1:1", "4:5")
        for resolution in ("1280x720", "1920x1080")
    ]

    @pytest.mark.parametrize("role", sorted(_ROLE_TEXTS))
    def test_caption_role_preset_renders_its_documented_text(
        self,
        role: str,
    ) -> None:
        """A box the renderer rejects silently clips words in the cut.

        Compose only logs a rejected caption geometry and keeps going, so
        this is the layer that catches an illegal preset before it ships.
        """
        from services.media_files.motion_templates import (
            CAPTION_ROLE_LOCATIONS,
        )

        assert role in CAPTION_ROLE_LOCATIONS, f"{role} 没有预设"
        location = ElementLocation(**CAPTION_ROLE_LOCATIONS[role])
        for canvas in self._CAPTION_CANVASES:
            for text in self._ROLE_TEXTS[role]:
                _validate_caption_location(location, text, canvas)

    def test_caption_role_presets_stay_inside_the_safe_area(self) -> None:
        """An off-canvas caption is unreadable no matter how the box is sized.

        The preset table and the validator now read the same numbers, so this
        guard proves the table the gate judges is self-consistent: some
        presets sit exactly on the 0.96 line by construction.
        """
        from services.media_files.motion_templates import (
            CAPTION_ROLE_LOCATIONS,
            CAPTION_SAFE_AREA_EDGES,
            caption_box_edges,
            caption_box_out_of_safe_area,
        )

        safe_left, safe_top, safe_right, safe_bottom = CAPTION_SAFE_AREA_EDGES
        for role, preset in CAPTION_ROLE_LOCATIONS.items():
            assert not caption_box_out_of_safe_area(preset), f"{role} 越出安全区"
            left, top, right, bottom = caption_box_edges(preset)
            assert left >= safe_left, f"{role} 左边越界 {left:.3f}"
            assert top >= safe_top, f"{role} 顶边越界 {top:.3f}"
            assert right <= safe_right, f"{role} 右边越界 {right:.3f}"
            assert bottom <= safe_bottom, f"{role} 底边越界 {bottom:.3f}"

    def test_caption_box_outside_the_safe_area_is_rejected(self) -> None:
        """The size floors alone leave the frame-edge box perfectly legal.

        The prompt used to teach exactly this box: 0.18 high with a centre
        anchor reaches 0.97 and burns the last line into the frame edge, so
        the gate has to reject it by name instead of only warning about it
        in a comment.
        """
        from services.media_files.motion_templates import (
            CAPTION_ROLE_LOCATIONS,
        )

        burnt = ElementLocation(
            x=0.5,
            y=0.88,
            width=0.8,
            height=0.18,
            anchor_x=0.5,
            anchor_y=0.5,
        )
        text = "那天晚上他站在门口很久什么都没有说"
        with pytest.raises(ValidationError, match="安全区"):
            _validate_caption_location(burnt, text, (1280, 720))
        # The role preset that replaces it stays legal on the same canvas, so
        # the gate cannot reject its own table.
        _validate_caption_location(
            ElementLocation(**CAPTION_ROLE_LOCATIONS["dialogue"]),
            text,
            (1280, 720),
        )

    def test_safe_area_gate_skips_overlays_that_are_not_subtitles(
        self,
    ) -> None:
        """气泡卡片走自己的排版，不能被子幕安全区条款误伤。

        The prompt teaches the pet-OS bubble a tall right-edge box that
        describes the whole speech-bubble layer, not a subtitle line, and the
        bubble renderer lays out its tail and padding by itself.  So the
        subtitle safe area is not its contract: the same out-of-safe-area box
        a subtitle is rejected for has to stay acceptable once the caller
        says the overlay is not a subtitle.
        """
        bubble = ElementLocation(
            x=0.90,
            y=0.86,
            width=0.30,
            height=0.20,
            anchor_x=0.5,
            anchor_y=0.5,
        )
        with pytest.raises(ValidationError, match="安全区"):
            _validate_caption_location(bubble, "本喵要发光", (1280, 720))
        _validate_caption_location(
            bubble,
            "本喵要发光",
            (1280, 720),
            check_safe_area=False,
        )
        # The exemption is scoped to the safe area only: the size floors that
        # already governed bubbles keep rejecting the prompt's own 0.18-wide
        # box, so nothing about bubble behaviour shifts with this gate.
        with pytest.raises(ValidationError, match="太窄"):
            _validate_caption_location(
                ElementLocation(
                    x=0.90,
                    y=0.29,
                    width=0.18,
                    height=0.53,
                    anchor_x=0.5,
                    anchor_y=0.5,
                ),
                "本喵要发光",
                (1280, 720),
                check_safe_area=False,
            )

    def test_documented_copy_budget_fits_the_preset_it_promises(self) -> None:
        """A prompt ceiling the preset cannot hold silently clips words.

        The director prompt caps an interview summary at 30 CJK characters,
        so 30 must be legal on that box.  The documented margin is thin (the
        preset holds 33), which is exactly why it is pinned here.
        """
        from services.media_files.motion_templates import (
            CAPTION_ROLE_LOCATIONS,
        )

        preset = ElementLocation(
            **CAPTION_ROLE_LOCATIONS["interview_summary"],
        )
        _validate_caption_location(preset, "访谈要点摘要" * 5, (1280, 720))
        with pytest.raises(ValidationError, match="height"):
            _validate_caption_location(preset, "访" * 40, (1280, 720))

    def test_caption_roles_cover_every_prompted_value(self) -> None:
        """A role the model can write but the preset table lacks would fall
        through to the generic box, silently undoing the layout intent.

        The truth source has to be the model's own Literal, not a list this
        file keeps by hand, or adding a role would leave this guard green.
        """
        from typing import Literal, get_args, get_origin

        from services.media_files.motion_templates import (
            CAPTION_ROLE_LOCATIONS,
        )
        from services.project_files.models import OverlayCreation

        def literal_members(annotation: object) -> set[str]:
            for arg in get_args(annotation):
                if get_origin(arg) is Literal:
                    return set(str(value) for value in get_args(arg))
                nested = literal_members(arg)
                if nested:
                    return nested
            return set()

        prompted = literal_members(
            OverlayCreation.model_fields["caption_role"].annotation,
        )
        assert prompted, "caption_role 不再是 Literal，本守卫已失效"
        assert set(CAPTION_ROLE_LOCATIONS) == prompted
        # The rendering guard above only samples the roles listed here, so a
        # new role must arrive with a text budget, not just a preset.
        assert set(self._ROLE_TEXTS) == prompted

    def test_active_or_embedded_content_is_rejected(self) -> None:
        html = (
            "<html><body><iframe src='file:///etc/passwd'>"
            "</iframe></body></html>"
        )
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
    def test_every_template_is_animated_and_visible_at_t0(
        self,
        motif: str,
    ) -> None:
        """Every motif must be tagged, animated, and show at least one
        shaped element at t=0, or the probe rejects the first frame."""
        html = render_decoration_template(motif)
        assert f'data-motion-motif="{motif}"' in html
        assert "@keyframes" in html
        assert len(html) >= 32

        style_start = html.index("<style>")
        style_end = html.index("</style>")
        css = html[style_start:style_end]
        body = html[style_end:]

        shape_classes = re.findall(r'class="shape\s+([\w-]+)', body)
        assert shape_classes, f"motif {motif!r} has no .shape elements"

        css_props: dict[str, str] = {}
        for cls in set(shape_classes):
            match = re.search(rf"\.{cls}\{{([^}}]+)\}}", css)
            if match:
                css_props[cls] = match.group(1)

        # A shape is visible at t=0 if its base opacity is non-zero, or an
        # immediate (no-delay) animation starts its 0% keyframe above zero.
        for cls in shape_classes:
            props = css_props.get(cls, "")
            opacity_match = re.search(r"(?<!\w)opacity:([^;]+)", props)
            if opacity_match is None or opacity_match.group(1).strip() != "0":
                return
            anim_match = re.search(r"animation:([\w-]+)", props)
            if anim_match and "animation-delay" not in props:
                kf = re.search(
                    rf"@keyframes\s+{anim_match.group(1)}\s*\{{0%{{([^}}]+)",
                    css,
                )
                if kf:
                    kf_opacity = re.search(r"opacity:([^;]+)", kf.group(1))
                    if (
                        kf_opacity is None
                        or kf_opacity.group(1).strip() != "0"
                    ):
                        return

        raise AssertionError(
            f"motif {motif!r} has no shaped element visible at t=0; "
            "the probe will reject it as an empty first frame",
        )

    def test_caption_fallback_keeps_exact_text_and_escapes_markup(
        self,
    ) -> None:
        html = render_caption_template("飞！<安全>", emotion="action")
        assert "飞！&lt;安全&gt;" in html
        assert 'data-motion-motif="caption_card"' in html


class TestSelectDecorationIds:
    def _elements(self, count: int) -> list[TimelineElement]:
        return [
            TimelineElement(
                element_id=f"seg-{index}",
                span=TimelineSpan(start_tick=index * 1000, duration_tick=1000),
                location=ElementLocation(),
                creation=EditCreation(intent=f"意图 {index}"),
            )
            for index in range(count)
        ]

    def _select(self, elements, budget):
        return asyncio.run(
            _select_decoration_ids(
                edit_elements=elements,
                timeline=Timeline(timeline_id="tl-1"),
                budget=budget,
                brief="",
            ),
        )

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
        assert self._select(self._elements(6), 2) == {"seg-1", "seg-4"}

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
        selected = self._select(elements, 3)
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
        motion,
        location=None,
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

    def test_unsafe_stored_motion_falls_back_during_compose(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        calls: list[str] = []
        safe_motion_args: list[tuple[dict, str]] = []

        def fake_prepare(**kwargs):
            calls.append("prepare")
            safe_motion_args.append((kwargs["location"], kwargs["html"]))
            return _layer_prep(tmp_path)

        def fake_burn(**kwargs):
            calls.append("burn")
            kwargs["output_path"].write_bytes(b"safe motion")
            return OverlayRenderResult(success=True)

        monkeypatch.setattr(
            local_execution_module,
            "prepare_motion_layer",
            fake_prepare,
        )
        monkeypatch.setattr(
            local_execution_module,
            "composite_motion_layers",
            fake_burn,
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
        location, html = safe_motion_args[0]
        assert location["width"] == 0.8 and location["y"] == 0.86
        assert 'data-motion-motif="caption_card"' in html


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [{}, {"captionStyle": "uniform"}, {"captionStyle": "varied"}],
)
async def test_plain_subtitles_need_no_edit_or_design_model(
    tmp_path,
    monkeypatch,
    arguments,
):
    from unittest.mock import AsyncMock
    from services.project_files.facade import CreatorFileServices
    from services.project_files.models import OverlayCreation, Project

    services = CreatorFileServices.create(tmp_path)
    project = Project.new(project_id="plain-subtitle", name="普通字幕")
    elements = project.timelines.items["timeline:main"].elements_by_id
    for index, text in enumerate(("让画面自己讲故事", "Simple words, clear picture")):
        elements[f"caption-{index}"] = TimelineElement(
            element_id=f"caption-{index}",
            span=TimelineSpan(start_tick=index * 3000, duration_tick=3000),
            location=ElementLocation(x=0.5, y=0.5, width=0.12, height=0.4),
            creation=OverlayCreation(text=text),
        )
    services.projects.create(project)
    model = AsyncMock(
        side_effect=AssertionError(
            "Plain subtitles must not request a generated style",
        ),
    )
    monkeypatch.setattr(motion_design, "_design_document", model)
    monkeypatch.setattr(motion_design.vlm_model, "chat_completion", model)
    result = await motion_design.design_motion_overlays(
        services,
        project_id=project.project_id,
        target_ref="timeline:main",
        arguments=arguments,
        idempotency_key="plain-subtitles",
    )
    assert result["designedCount"] == 2
    current = services.projects.read(project.project_id).project
    for element in current.timelines.items[
        "timeline:main"
    ].elements_by_id.values():
        motion = element.creation.motion
        assert (
            motion.format == "html_css"
            and motion.template_version == CAPTION_TEMPLATE_VERSION
        )
        assert element.location.y == 0.86
        assert element.location.y + element.location.height / 2 <= 0.96
        indexed = current.assets.files_by_id[motion.html_file_id]
        html = (
            services.projects.project_root(project.project_id)
            / indexed.relative_uri
        ).read_text()
        assert 'data-caption-style="plain"' in html
        assert element.creation.text in html
        assert "border:" not in html and "border-radius:" not in html
        assert "box-shadow:" not in html and "transform:" not in html
        assert 'data-motion-exit="none"' in html
    model.assert_not_called()


@pytest.mark.asyncio
async def test_plain_subtitle_redesign_preserves_authored_position(tmp_path):
    from services.project_files.facade import CreatorFileServices
    from services.project_files.models import (
        MotionGraphic,
        OverlayCreation,
        Project,
    )

    services = CreatorFileServices.create(tmp_path)
    project = Project.new(project_id="caption-position", name="字幕位置")
    location = ElementLocation(x=0.28, y=0.3, width=0.4, height=0.22)
    project.timelines.items["timeline:main"].elements_by_id[
        "caption"
    ] = TimelineElement(
        element_id="caption",
        span=TimelineSpan(start_tick=0, duration_tick=3000),
        location=location,
        creation=OverlayCreation(
            text="清晰，简单",
            motion=MotionGraphic(html=_HTML, template_version=1),
        ),
    )
    services.projects.create(project)
    preserved = await motion_design.design_motion_overlays(
        services,
        project_id=project.project_id,
        target_ref="timeline:main",
        arguments={},
        idempotency_key="keep-authored",
    )
    assert preserved["designedCount"] == 0
    updated = await motion_design.design_motion_overlays(
        services,
        project_id=project.project_id,
        target_ref="timeline:main",
        arguments={"elementIds": ["caption"]},
        idempotency_key="redesign-caption",
    )
    assert updated["designedCount"] == 1
    element = (
        services.projects.read(project.project_id)
        .project.timelines.items["timeline:main"]
        .elements_by_id["caption"]
    )
    assert element.location == location
    assert element.creation.motion.template_version == CAPTION_TEMPLATE_VERSION


@pytest.mark.asyncio
async def test_late_pack_switch_redescribes_authored_captions(
    tmp_path,
    monkeypatch,
):
    """A pack written behind the style route's back still reaches 动效描述.

    The agent changes settings through the generic patch route, so the design
    pass is the only writer left that can re-sync a description.  An authored
    动效描述 has to gain the style sentence while keeping its own wording, and
    the document has to be redrawn from the very same pack.
    """

    from unittest.mock import AsyncMock
    from services.project_files.facade import CreatorFileServices
    from services.project_files.models import OverlayCreation, Project

    services = CreatorFileServices.create(tmp_path)
    project = Project.new(project_id="late-pack", name="后切换风格包")
    project.timelines.items["timeline:main"].elements_by_id["caption"] = (
        TimelineElement(
            element_id="caption",
            span=TimelineSpan(start_tick=0, duration_tick=3000),
            location=ElementLocation(x=0.5, y=0.86, width=0.8, height=0.18),
            creation=OverlayCreation(
                text="这条字幕先有了自己的描述",
                prompt="镜头推进时轻微抖动",
            ),
        )
    )
    services.projects.create(project)
    model = AsyncMock(
        side_effect=AssertionError("a picked pack is drawn, never generated"),
    )
    monkeypatch.setattr(motion_design, "_design_document", model)

    async def design(key: str) -> None:
        await motion_design.design_motion_overlays(
            services,
            project_id=project.project_id,
            target_ref="timeline:main",
            arguments={},
            idempotency_key=key,
        )

    def caption() -> TimelineElement:
        return (
            services.projects.read(project.project_id)
            .project.timelines.items["timeline:main"]
            .elements_by_id["caption"]
        )

    await design("no-pack")
    # Nothing picked: the authored description stays exactly as written.
    assert caption().creation.prompt == "镜头推进时轻微抖动"

    # Another writer flips only the setting — what the agent's generic patch
    # does — and never touches the description.
    snapshot = services.projects.read(project.project_id)
    candidate = snapshot.project.model_dump(mode="json")
    candidate["settings"]["subtitle_template"] = "variety_pop"
    await services.commit_candidate(
        base=snapshot,
        candidate=candidate,
        origin="frontend_edit",
        review_policy="auto_fix",
    )
    await design("with-pack")

    element = caption()
    assert element.creation.prompt.startswith("【字幕风格：综艺花字】")
    assert element.creation.prompt.endswith("镜头推进时轻微抖动")
    assert "caption_style=variety_pop" in element.creation.motion.design_notes
    model.assert_not_called()


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

    def test_key_tracks_burned_layer_checksum_not_html(self, tmp_path) -> None:
        runner = FfmpegLocalMediaRunner(executable="ffmpeg")
        spec = self._spec(tmp_path)

        def overlay(checksum: str, html: str) -> dict:
            return {
                "kind": "pet_os",
                "text": "第一句",
                "vibe": "chill",
                "appear_at": 0.0,
                "duration": 2.0,
                "location": None,
                "element_id": "overlay-1",
                "motion": {
                    "format": "html_js",
                    "html": html,
                    "checksum": checksum,
                    "fps": 24,
                    "loop": False,
                },
            }

        def key(spec_, item_):
            return runner._segment_cache_key(
                spec_,
                item_,
                segment_duration=4.0,
                freeze_duration=0.0,
            )

        base = key(
            spec,
            self._item(tmp_path, overlays=[overlay("c1", "<html>a")]),
        )
        # Identical content with a different (never-fingerprinted) html
        # body: hydration state must not split the cache.
        assert base == key(
            spec,
            self._item(tmp_path, overlays=[overlay("c1", "<html>b")]),
        )
        assert base != key(
            spec,
            self._item(tmp_path, overlays=[overlay("c2", "<html>a")]),
        )
        # Canvas geometry always reaches the key.
        other_canvas = self._spec(tmp_path)
        object.__setattr__(other_canvas, "canvas_size", (1920, 1080))
        assert base != key(
            other_canvas,
            self._item(tmp_path, overlays=[overlay("c1", "<html>a")]),
        )
        # No stable source checksum -> never cached.
        assert key(spec, self._item(tmp_path, checksum="")) is None


def test_repair_recovers_missing_script_close_tag() -> None:
    # Field run 2026-08-09: the model dropped </script> after the vendor
    # include, browsers swallowed the inline timeline, and every retry
    # died on "__hf 未注册" — a pure syntax slip, fixed deterministically.
    nested = '<script src="vendor/gsap.min.js">\n<script>var tl = 1;</script>'
    fixed = _repair_common_html_slips(nested)
    assert fixed.count("</script>") == 2
    inline_in_src = '<script src="vendor/gsap.min.js">var tl = 2;</script>'
    fixed2 = _repair_common_html_slips(inline_in_src)
    assert fixed2.count("<script") == 2 and "var tl = 2;" in fixed2
    # Well-formed documents pass through unchanged.
    good = '<script src="vendor/gsap.min.js"></script><script>var tl = 3;</script>'
    assert _repair_common_html_slips(good) == good


def test_repair_lifts_zero_starting_opacity() -> None:
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


_LOC = ElementLocation(
    x=0.5,
    y=0.86,
    width=0.8,
    height=0.18,
    anchor_x=0.5,
    anchor_y=0.5,
)


def _font_terms(html: str) -> list[float]:
    """The four ``min()`` terms of the fitted ``.words`` font size."""

    expression = re.search(r"font-size:min\(([^)]+)\)", html).group(1)
    return [
        float(re.sub(r"[a-z]+", "", term)) for term in expression.split(",")
    ]


from services.project_files.models import ProjectSettings, SubtitleAnimation


class TestProjectAnimationOverride:
    """The creation form's default sits between the stamp and the pack."""

    def test_only_set_fields_travel(self) -> None:
        settings = ProjectSettings(
            subtitle_animation=SubtitleAnimation(loop=True),
        )
        assert motion_design.caption_animation_override(settings) == {
            "loop": True,
        }
        assert (
            motion_design.caption_animation_override(ProjectSettings())
            is None
        )

    def test_override_merges_onto_the_pack_field_by_field(self) -> None:
        assert motion_design.resolve_caption_animation(
            None,
            "variety_pop",
            {"entrance": "slide"},
        ) == {**subtitle_pack_animation("variety_pop"), "entrance": "slide"}

    def test_override_reaches_the_pack_switch_path(self) -> None:
        built, _concept = motion_design.build_caption_document(
            text="换包也带着项目默认",
            location=_LOC,
            pack_id="variety_pop",
            style=None,
            animation={"entrance": "type_on", "exit": "none", "loop": False},
        )
        assert motion_design.resolve_caption_animation(
            built,
            "cinematic",
            {"loop": True},
        ) == {**subtitle_pack_animation("cinematic"), "loop": True}

    def test_the_stamp_still_wins_over_the_override(self) -> None:
        built, _concept = motion_design.build_caption_document(
            text="逐条选择优先",
            location=_LOC,
            pack_id="variety_pop",
            style=None,
            animation={"entrance": "slide", "exit": "shrink", "loop": True},
        )
        assert motion_design.resolve_caption_animation(
            built,
            "variety_pop",
            {"entrance": "pop"},
        ) == {"entrance": "slide", "exit": "shrink", "loop": True}


class TestCaptionStyleDerivation:
    """The style stamp, never a schema default, decides what a caption plays.

    A caption document is derived data: the ``caption_animation=`` stamp is
    the one record of what was picked, because ``MotionGraphic.entrance``
    defaults to ``pop`` and would otherwise read as an explicit choice on
    every document written before the triple existed.
    """

    @staticmethod
    def _legacy_document(text: str = "这是一条历史字幕") -> MotionGraphic:
        """Exactly the document the pipeline wrote before style packs."""

        return MotionGraphic(
            html=render_caption_template(text, box_width=0.8, box_height=0.18),
            fps=24,
            loop=False,
            design_notes="简洁无边框字幕：透明背景、清晰字体、稳定排版",
            motif="caption_card",
            template_version=2,
            intensity=0,
        )

    def test_unstamped_document_keeps_the_historical_fade(self) -> None:
        document = self._legacy_document()
        # The schema default must not be mistaken for a user pick: a project
        # that never chose a style may not change appearance on upgrade.
        assert document.entrance == "pop"
        assert motion_design.resolve_caption_animation(document, None) == {
            "entrance": "soft_fade",
            "exit": "none",
            "loop": False,
        }

    def test_unstamped_document_adopts_the_pack_signature(self) -> None:
        document = self._legacy_document()
        assert motion_design.resolve_caption_animation(
            document,
            "variety_pop",
        ) == subtitle_pack_animation("variety_pop")

    def test_the_stamp_wins_over_the_document_fields(self) -> None:
        built, _concept = motion_design.build_caption_document(
            text="这条字幕选过动效",
            location=_LOC,
            pack_id="variety_pop",
            style=None,
            animation={"entrance": "slide", "exit": "shrink", "loop": True},
        )
        drifted = built.model_copy(
            update={"entrance": "pop", "exit": "soft_fade"},
        )
        assert motion_design.resolve_caption_animation(
            drifted,
            "variety_pop",
        ) == {"entrance": "slide", "exit": "shrink", "loop": True}
        # The drift itself is what makes the next pass redraw this document.
        project = SimpleNamespace(
            settings=SimpleNamespace(
                subtitle_template="variety_pop",
                subtitle_style=None,
            ),
        )
        assert motion_design.caption_document_is_stale(built, project) is False
        assert motion_design.caption_document_is_stale(drifted, project) is True

    def test_a_pack_switch_replays_the_new_signature(self) -> None:
        built, _concept = motion_design.build_caption_document(
            text="换风格包",
            location=_LOC,
            pack_id="variety_pop",
            style=None,
            animation={"entrance": "type_on", "exit": "none", "loop": False},
        )
        assert motion_design.resolve_caption_animation(
            built,
            "cinematic",
        ) == subtitle_pack_animation("cinematic")

    def test_no_pack_document_keeps_the_historical_layout(self) -> None:
        built, concept = motion_design.build_caption_document(
            text="今天试试这套七个字的无衬线字体，应该没有硬伤了吧？挺好的",
            location=_LOC,
            pack_id=None,
            style=None,
            animation=None,
        )
        html = built.html
        # Smart recommend promises no look, so the concept stays the old prose.
        assert "caption_style=" not in concept
        assert built.template_version == CAPTION_TEMPLATE_VERSION
        assert built.loop is False
        assert "animation:appear .14s linear both" in html
        assert "text-shadow:0 .025em .05em #000d,0 .04em .14em #000b" in html
        assert "letter-spacing" not in html
        assert 'data-caption-entrance="soft_fade"' in html
        assert 'data-caption-loop="0"' in html

    def test_compose_triple_is_offered_only_for_owned_documents(self) -> None:
        # A free-form design owns its look and never reaches the caption
        # fallback; keeping the field absent also leaves its render fingerprint
        # exactly as it was.
        built, _concept = motion_design.build_caption_document(
            text="这条字幕要带去兜底",
            location=_LOC,
            pack_id="clean_talk",
            style=None,
            animation={"entrance": "type_on", "exit": "shrink", "loop": False},
        )
        assert motion_design.caption_animation_for_compose(
            built,
            "clean_talk",
        ) == {"entrance": "type_on", "exit": "shrink", "loop": False}
        free = MotionGraphic(html=_HTML, format="html_js")
        assert motion_design.caption_animation_for_compose(free, None) is None
        assert motion_design.caption_animation_for_compose(None, None) is None

    def test_compose_triple_re_adopts_after_a_pack_switch(self) -> None:
        built, _concept = motion_design.build_caption_document(
            text="换包之后的兜底",
            location=_LOC,
            pack_id="variety_pop",
            style=None,
            animation={"entrance": "type_on", "exit": "none", "loop": False},
        )
        # The stamp was written under the old pack, and the same rule the
        # document path applies (a pack switch replays the new signature) has
        # to reach the fallback too, or the two would disagree.
        assert motion_design.caption_animation_for_compose(
            built,
            "cinematic",
        ) == motion_design.normalise_caption_animation(
            subtitle_pack_animation("cinematic"),
        )

    def test_pack_tracking_and_leading_enter_the_font_fit(self) -> None:
        text = (
            "这是一行足够长的字幕文案用来验证字距与行高都会挤进字号自适应"
            "再长一点凑满四十多个汉字才够看效果吧"
        )
        plain = render_caption_template(text, box_width=0.8, box_height=0.18)
        spaced = render_caption_template(
            text,
            box_width=0.8,
            box_height=0.18,
            typography=subtitle_pack_typography("cinematic"),
        )
        plain_terms = _font_terms(plain)
        spaced_terms = _font_terms(spaced)
        # The box-driven terms are the document's own geometry and stay.
        assert plain_terms[:2] == spaced_terms[:2]
        # 48 full-width glyphs fit 24 per line historically but only 20.3 once
        # the pack adds .18em of tracking, so the fit has to plan for a third
        # row at 1.5 leading.  Left out, the browser wraps rows the size never
        # reserved and the stage's overflow:hidden clips the caption copy.
        assert plain_terms[2] == pytest.approx(80 / (2 * 1.35), abs=0.01)
        assert spaced_terms[2] == pytest.approx(80 / (3 * 1.5), abs=0.01)
        # The same two numbers also reach the browser, or the fit would be
        # planning for a layout the document never asks for.
        assert "letter-spacing:0.18em" in spaced
        assert "line-height:1.5" in spaced
        assert "line-height:1.35" in plain


class TestComposeCaptionFallbackStyle:
    """A compose-time fallback is still the final cut the user picked."""

    def test_a_caption_pick_survives_the_fallback(self) -> None:
        # The compose worker carries the resolved triple because it only sees
        # a dumped overlay line; without it the last-resort document would
        # replay the pack's signature and the picker would look dead.
        kwargs = local_execution_module._caption_fallback_style_kwargs(
            {
                "subtitle_template": "clean_talk",
                "caption_animation": {
                    "entrance": "type_on",
                    "exit": "shrink",
                    "loop": False,
                },
            },
        )
        assert (kwargs["entrance"], kwargs["exit"]) == ("type_on", "shrink")
        html = render_caption_template(
            "兜底也要演我选的动效",
            box_width=0.8,
            box_height=0.18,
            **kwargs,
        )
        assert 'data-caption-entrance="type_on"' in html
        assert 'data-motion-exit="shrink"' in html

    def test_nothing_picked_reproduces_the_historical_document(self) -> None:
        assert local_execution_module._caption_fallback_style_kwargs({}) == {}

    def test_a_picked_pack_reaches_the_fallback_document(self) -> None:
        kwargs = local_execution_module._caption_fallback_style_kwargs(
            {"subtitle_template": "variety_pop"},
        )
        assert kwargs["typography"] == subtitle_pack_typography("variety_pop")
        assert kwargs["entrance"] == "pop" and kwargs["loop"] is True
        html = render_caption_template(
            "这条走了兜底路径",
            box_width=0.8,
            box_height=0.18,
            **kwargs,
        )
        assert f"font-weight:{kwargs['typography']['fontWeight']}" in html
        assert "capPop" in html

    def test_override_only_projects_keep_the_legacy_family_but_take_the_colour(
        self,
    ) -> None:
        kwargs = local_execution_module._caption_fallback_style_kwargs(
            {"subtitle_style": {"color": "#FFE066"}},
        )
        assert kwargs["style"] == {"color": "#FFE066"}
        html = render_caption_template(
            "只改了颜色",
            box_width=0.8,
            box_height=0.18,
            **kwargs,
        )
        assert "#ffe066" in html

    def test_the_plate_pick_reaches_the_fallback_too(self) -> None:
        kwargs = local_execution_module._caption_fallback_style_kwargs(
            {
                "subtitle_template": "warm_note",
                "subtitle_style": {"background_opacity": 0.2},
            },
        )
        html = render_caption_template(
            "兜底也要按我调的底板",
            box_width=0.8,
            box_height=0.18,
            **kwargs,
        )
        assert "background:rgba(255,248,232,0.200)" in html


class TestCaptionBackgroundOpacity:
    """One pick re-inks the plate a pack already draws, and never invents one.

    ``background_opacity`` is the only subtitle override that edits a colour
    the style pack owns, so what matters here is the byte guarantee: a project
    that never touched it — and a pack that never drew a plate — must render
    exactly what it rendered before, in the template, the fallback PNG and the
    wording an agent reads.
    """

    @staticmethod
    def _plate(html: str) -> str:
        match = re.search(r"background:(rgba?\([^)]*\))", html)
        return match.group(1) if match else ""

    def test_the_pick_replaces_the_pack_alpha(self) -> None:
        html = render_caption_template(
            "把奶油底板调淡一点",
            box_width=0.8,
            box_height=0.18,
            typography=subtitle_pack_typography("warm_note"),
            style={"background_opacity": 0.25},
        )
        # Same colour, the picked alpha: the block is re-inked, not replaced.
        assert self._plate(html) == "rgba(255,248,232,0.250)"

    def test_zero_takes_the_plate_away(self) -> None:
        html = render_caption_template(
            "不要底板",
            box_width=0.8,
            box_height=0.18,
            typography=subtitle_pack_typography("clean_talk"),
            style={"background_opacity": 0.0},
        )
        assert self._plate(html) == ""
        # The pill layout goes with it, so the text keeps filling its box.
        assert "width:100%;" in html

    def test_an_untouched_pick_keeps_the_pack_bytes(self) -> None:
        pack = subtitle_pack_typography("warm_note")
        historical = render_caption_template(
            "升级前后一字不差",
            box_width=0.8,
            box_height=0.18,
            typography=pack,
        )
        explicit_none = render_caption_template(
            "升级前后一字不差",
            box_width=0.8,
            box_height=0.18,
            typography=pack,
            style={"background_opacity": None},
        )
        assert explicit_none == historical
        assert self._plate(historical) == "rgba(255,248,232,0.5)"

    def test_a_pack_without_a_plate_stays_without_one(self) -> None:
        for alpha in (0.0, 0.5, 1.0):
            html = render_caption_template(
                "无底板风格不造底板",
                box_width=0.8,
                box_height=0.18,
                typography=subtitle_pack_typography("cinematic"),
                style={"background_opacity": alpha},
            )
            assert self._plate(html) == ""

    def test_a_broken_value_falls_back_to_the_pack(self) -> None:
        html = render_caption_template(
            "非法值不猜",
            box_width=0.8,
            box_height=0.18,
            typography=subtitle_pack_typography("clean_talk"),
            style={"background_opacity": "lots"},
        )
        assert self._plate(html) == "rgba(14,16,20,0.42)"

    def test_the_stamp_gains_a_token_only_when_touched(self) -> None:
        # Four tokens is what every existing document already carries; adding
        # the fifth only on a pick is what keeps an upgrade from redrawing the
        # whole project.
        assert (
            caption_style_state("warm_note", {"color": "#FFE066"})
            == "warm_note|#ffe066|1|1"
        )
        assert (
            caption_style_state(
                "warm_note",
                {"color": "#FFE066", "background_opacity": 0.5},
            )
            == "warm_note|#ffe066|1|1|0.5"
        )

    def test_a_plate_pick_makes_the_document_stale(self) -> None:
        built, _concept = motion_design.build_caption_document(
            text="调过底板的重绘一次",
            location=_LOC,
            pack_id="warm_note",
            style=SubtitleStyle(background_opacity=0.25).model_dump(
                mode="json",
            ),
            animation=None,
        )
        project = SimpleNamespace(
            settings=ProjectSettings(
                subtitle_template="warm_note",
                subtitle_style=SubtitleStyle(background_opacity=0.25),
            ),
        )
        assert motion_design.caption_document_is_stale(built, project) is False
        lighter = SimpleNamespace(
            settings=ProjectSettings(
                subtitle_template="warm_note",
                subtitle_style=SubtitleStyle(background_opacity=0.75),
            ),
        )
        assert (
            motion_design.caption_document_is_stale(built, lighter) is True
        )
        # And a project that never touched the control still matches the
        # four-token stamp every older document carries.
        untouched = SimpleNamespace(
            settings=ProjectSettings(subtitle_template="warm_note"),
        )
        plain, _plain_concept = motion_design.build_caption_document(
            text="没调过底板",
            location=_LOC,
            pack_id="warm_note",
            style=None,
            animation=None,
        )
        assert (
            motion_design.caption_document_is_stale(plain, untouched) is False
        )

    def test_the_wording_is_spoken_only_where_a_plate_is_drawn(self) -> None:
        assert (
            subtitle_style_override_line(
                SubtitleStyle(background_opacity=0.5).model_dump(mode="json"),
                "clean_talk",
            )
            == "字幕底板不透明度 50%"
        )
        assert (
            subtitle_style_override_line(
                SubtitleStyle(background_opacity=0.0).model_dump(mode="json"),
                "clean_talk",
            )
            == "不加字幕底板"
        )
        for pack_id in ("cinematic", None):
            assert (
                subtitle_style_override_line(
                    SubtitleStyle(
                        background_opacity=0.5,
                    ).model_dump(mode="json"),
                    pack_id,
                )
                == ""
            )
