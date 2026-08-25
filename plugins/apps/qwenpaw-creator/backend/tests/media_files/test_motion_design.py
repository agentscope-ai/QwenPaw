# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=unused-argument,protected-access,redefined-outer-name

from __future__ import annotations

import asyncio
import re

import pytest

from domain.errors import ValidationError
from services.media_files import local_execution as local_execution_module
from services.media_files import motion_design
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    LocalMediaInput,
)
from services.media_files.motion_design import (
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
        assert location["width"] == 0.8 and location["y"] == 0.88
        assert 'data-motion-motif="caption_card"' in html


class TestUniformCaptionStyle:
    def test_uniform_blueprint_shares_one_style_skeleton(self) -> None:
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

    def test_uniform_blueprint_font_size_adapts_to_text_length(self) -> None:
        """The static capsule uses dynamic font sizing (min(vh, vw)) so
        that text fills its overlay box proportionally. Short text gets
        a larger font; long text shrinks to fit. Both share the same
        style skeleton structure (exit style, entrance, card layout)."""

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
        again, _ = render_caption_blueprint(
            blueprint,
            short_text,
            intensity=intensity,
        )
        assert short_doc == again  # deterministic, no per-card variation
        long_doc, _ = render_caption_blueprint(
            blueprint,
            long_text,
            intensity=intensity,
        )
        # Font size uses dynamic min(vh, vw) clamping from _caption_font_css.
        short_font = re.search(r"font-size:(min\([^)]+\))", short_doc)
        long_font = re.search(r"font-size:(min\([^)]+\))", long_doc)
        assert short_font is not None
        assert long_font is not None
        # Short text gets a larger font than long text.
        assert short_font.group(1) != long_font.group(1)
        # No per-card entrance choreography beyond the single card fade.
        for performance in ("letterSpacing", "scaleY", "stagger"):
            assert performance not in short_doc
        # The t=0 probe rejects fully transparent frames, so the fade
        # starts from partial visibility; exits stay hard cuts so
        # back-to-back captions never double-expose.
        assert "autoAlpha:0}" not in short_doc
        assert "autoAlpha:.35" in short_doc
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
