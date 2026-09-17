# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,redefined-outer-name,unused-argument

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from domain.errors import ValidationError
from services.media_files import motion_overlay
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    LocalMediaInput,
    _materialized_motion,
    _motion_document_payload,
)
from services.media_files.motion_design import (
    _externalized_motion,
    _validated_design,
)
from services.media_files.motion_engine import (
    referenced_vendor_filenames,
    resolve_vendor_files,
)
from services.media_files.motion_overlay import (
    _PROBE_KEYFRAME_FRACTIONS,
    _probe_keyframe_truth_error,
    _verify_captured_frames,
    frame_cache_identity,
    probe_motion_document,
)
from services.project_files.assets import AssetFileStore
from services.project_files.models import MotionGraphic

from .conftest import write_png

_CSS_HTML = (
    "<html><head><style>.card{animation:pop 1s}</style></head>"
    "<body><div class='card'>本喵要发光</div></body></html>"
)

_JS_HTML = (
    "<html><head><style>.card{opacity:1}</style></head>"
    "<body><div class='card'>本喵要发光</div>"
    '<script src="vendor/stub.min.js"></script>'
    "<script>window.__hf = { duration: 2, "
    "seek: function (t) { window.__t = t; } };</script>"
    "</body></html>"
)

_TEXT_CARD_RAW = {
    "concept": "发光字幕卡",
    "fps": 24,
    "location": {"x": 0.5, "y": 0.3, "width": 0.4, "height": 0.3},
}


class TestMotionEngineVendorRegistry:
    def test_whitelisted_src_is_referenced_and_resolved(
        self,
        stub_vendor,
    ) -> None:
        assert referenced_vendor_filenames(_JS_HTML) == ["stub.min.js"]
        assert list(resolve_vendor_files(["stub.min.js"])) == ["stub.min.js"]

    @pytest.mark.parametrize(
        ("html", "match"),
        [
            (
                '<script src="https://cdn.example.com/gsap.min.js"></script>',
                "白名单",
            ),
        ],
        ids=["external-src"],
    )
    def test_referenced_filenames_rejects_untrusted_src(
        self,
        stub_vendor,
        html: str,
        match: str,
    ) -> None:
        with pytest.raises(ValidationError, match=match):
            referenced_vendor_filenames(html)

    def test_resolve_rejects_missing_or_corrupted_file(
        self,
        stub_vendor,
        tmp_path,
    ) -> None:
        vendor_dir = tmp_path / "vendor"
        (vendor_dir / stub_vendor.filename).write_bytes(b"tampered bytes")
        with pytest.raises(ValidationError, match="校验失败"):
            resolve_vendor_files([stub_vendor.filename])


class TestValidatedDesignHtmlJs:
    def test_html_js_text_card_accepted(self, stub_vendor) -> None:
        raw = {**_TEXT_CARD_RAW, "html": _JS_HTML, "format": "html_js"}
        result = _validated_design(raw, required_text="本喵要发光")
        assert not isinstance(result, str)
        motion, _location, _concept = result
        assert motion.format == "html_js"
        assert motion.html == _JS_HTML

    @pytest.mark.parametrize(
        ("html", "extra", "match"),
        [
            (
                _JS_HTML.replace("window.__hf", "window.__custom"),
                {"format": "html_js"},
                "__hf",
            ),
            (_JS_HTML, {}, "script"),
        ],
        ids=[
            "missing-hf-protocol",
            "html-css-rejects-script",
        ],
    )
    def test_untrusted_or_misdeclared_scripts_rejected(
        self,
        stub_vendor,
        html: str,
        extra: dict,
        match: str | None,
    ) -> None:
        with pytest.raises(ValidationError, match=match):
            _validated_design(
                {**_TEXT_CARD_RAW, "html": html, **extra},
                required_text="本喵要发光",
            )


class _ProjectStub:
    class _Assets:
        def __init__(self, files_by_id):
            self.files_by_id = files_by_id

    def __init__(self, files_by_id):
        self.assets = self._Assets(files_by_id)


class TestExternalizedMotionAndFingerprint:
    @staticmethod
    def _store(tmp_path) -> AssetFileStore:
        root = tmp_path / "project"
        root.mkdir(exist_ok=True)
        return AssetFileStore(root)

    def _motion(self) -> MotionGraphic:
        return MotionGraphic(html=_CSS_HTML, fps=24, loop=False)

    def test_publish_dedupes_references_and_round_trips(
        self,
        tmp_path,
    ) -> None:
        import hashlib

        store = self._store(tmp_path)
        stored, indexed = _externalized_motion(self._motion(), store)
        checksum = hashlib.sha256(_CSS_HTML.encode("utf-8")).hexdigest()
        assert stored.html is None
        assert stored.html_file_id == indexed.file_id
        assert indexed.sha256 == checksum
        assert indexed.relative_uri == f"assets/motion/{checksum}.html"
        assert indexed.schema_name == "motion_document"
        target = (tmp_path / "project").joinpath(
            *indexed.relative_uri.split("/"),
        )
        assert target.read_text(encoding="utf-8") == _CSS_HTML
        # Identical content deduplicates to the same stored file.
        _again, again_indexed = _externalized_motion(self._motion(), store)
        assert again_indexed.file_id == indexed.file_id
        project = _ProjectStub({indexed.file_id: indexed})
        payload = _motion_document_payload(project, stored)
        assert (
            _materialized_motion(project, store, payload)["html"] == _CSS_HTML
        )
        inline_payload = _motion_document_payload(project, self._motion())
        assert inline_payload["checksum"] == payload["checksum"]


_FFMPEG = shutil.which("ffmpeg")

# _verify_captured_frames samples frames {0, 2, 3} for frame_count=5.
_SAMPLED_INDICES = (0, 2, 3)
_BOX = 16


def _transparent(_x: int, _y: int) -> tuple[int, int, int, int]:
    return (0, 0, 0, 0)


def _centered(x: int, y: int) -> tuple[int, int, int, int]:
    inside = 5 <= x < 11 and 5 <= y < 11
    return (255, 255, 255, 255) if inside else (0, 0, 0, 0)


def _drifting(shift: int) -> Callable[[int, int], tuple[int, int, int, int]]:
    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        inside = 3 + shift <= x < 9 + shift and 5 <= y < 11
        return (255, 255, 255, 255) if inside else (0, 0, 0, 0)

    return pixel


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg is not installed")
class TestCaptureTruthGate:
    """Post-render truth gate over constructed frame samples."""

    @staticmethod
    def _frames(tmp_path: Path, pixel_by_index: dict[int, Callable]) -> Path:
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir(exist_ok=True)
        for index, pixel in pixel_by_index.items():
            write_png(frames_dir / f"{index:05d}.png", _BOX, _BOX, pixel)
        return frames_dir

    def _verify(
        self,
        frames_dir: Path,
        *,
        ffmpeg_path: str | None = None,
        **kw,
    ) -> str | None:
        return _verify_captured_frames(
            frames_dir,
            frame_count=5,
            box_width=_BOX,
            box_height=_BOX,
            ffmpeg_path=ffmpeg_path or _FFMPEG,
            **kw,
        )

    def test_accepts_centered_and_partially_empty_keyframes(
        self,
        tmp_path,
    ) -> None:
        frames = {index: _centered for index in _SAMPLED_INDICES}
        assert self._verify(self._frames(tmp_path, frames)) is None
        # A fade-in may leave the very first frame transparent; only an
        # entirely blank sample set is a deterministic failure.
        frames[0] = _transparent
        assert self._verify(self._frames(tmp_path, frames)) is None

    def test_rejects_all_empty_keyframes(self, tmp_path) -> None:
        frames_dir = self._frames(
            tmp_path,
            {index: _transparent for index in _SAMPLED_INDICES},
        )
        error = self._verify(frames_dir)
        assert error is not None and "空帧" in error

    def test_rejects_edge_overflow(self, tmp_path) -> None:
        def edge_overflow(x: int, y: int) -> tuple[int, int, int, int]:
            return (255, 255, 255, 255) if y == 0 else _centered(x, y)

        frames = {index: _centered for index in _SAMPLED_INDICES}
        frames[2] = edge_overflow
        error = self._verify(self._frames(tmp_path, frames))
        assert error is not None and "越出透明盒边缘" in error

    def test_ring_frame_rejects_opaque_center(self, tmp_path) -> None:
        # An "opaque frame" that paints the middle would cover the
        # wrapped footage: the honest center gate fails it closed.
        frames_dir = self._frames(
            tmp_path,
            {
                index: (lambda _x, _y: (255, 255, 255, 255))
                for index in _SAMPLED_INDICES
            },
        )
        error = self._verify(frames_dir, frame_ring=True)
        assert error is not None and "中心窗口必须保持透明" in error

    def test_ring_frame_accepts_declared_asymmetric_transparent_window(
        self,
        tmp_path,
    ) -> None:
        window = (0.40, 0.20, 0.56, 0.56)

        def asymmetric_ring(x: int, y: int) -> tuple[int, int, int, int]:
            inside = 7 <= x < 15 and 4 <= y < 12
            return (0, 0, 0, 0) if inside else (255, 255, 255, 255)

        frames_dir = self._frames(
            tmp_path,
            {index: asymmetric_ring for index in _SAMPLED_INDICES},
        )
        assert (
            self._verify(
                frames_dir,
                frame_ring=True,
                frame_window=window,
            )
            is None
        )


class TestProbeKeyframeTruthRules:
    _FULL = [0.4] * len(_PROBE_KEYFRAME_FRACTIONS)

    # Probe frames carry raw timeline states (no renderer-managed exit),
    # so an empty final state always means a self-made exit.
    @pytest.mark.parametrize(
        ("index", "token"),
        [(0, "首帧"), (6, "末态")],
        ids=["first-frame", "self-made-exit"],
    )
    def test_empty_keyframe_rejected(self, index: int, token: str) -> None:
        assert _probe_keyframe_truth_error(list(self._FULL)) is None
        coverages = list(self._FULL)
        coverages[index] = 0.0
        error = _probe_keyframe_truth_error(coverages)
        assert error is not None and token in error


class TestFrameCacheIdentity:
    _BASE = {
        "html": _JS_HTML,
        "box_width": 640,
        "box_height": 360,
        "frame_count": 48,
        "effective_fps": 24.0,
        "doc_format": "html_js",
        "engine_salt": "salt-a",
    }

    def test_flags_and_engine_salt_the_identity(self) -> None:
        looped = frame_cache_identity(**self._BASE, loop=True)
        assert json.loads(looped)["loop"] is True
        # Loop flag, engine pin and period mode each split the cache.
        assert looped != frame_cache_identity(**self._BASE, loop=False)
        assert looped != frame_cache_identity(
            **{**self._BASE, "engine_salt": "salt-b"},
            loop=True,
        )
        # Period sequences carry no baked exit, so their frames must never
        # be confused with a same-length unique-frame capture.
        period = frame_cache_identity(
            **self._BASE,
            loop=True,
            period_mode=True,
        )
        assert looped != period
        assert json.loads(period)["mode"] == "period"


def _fake_probe_worker(
    pixels_by_index: dict[int, Callable],
    *,
    managed_exit: bool = False,
    seen_jobs: list[dict] | None = None,
):
    """Worker stand-in painting constructed frames for probe jobs."""

    def runner(job, *, timeout_seconds):  # noqa: ARG001
        if seen_jobs is not None:
            seen_jobs.append(dict(job))
        for index, pixel in pixels_by_index.items():
            write_png(
                Path(job["frames_dir"]) / f"{index:05d}.png",
                _BOX,
                _BOX,
                pixel,
            )
        return {"count": 1, "totalMs": 2000.0, "managedExit": managed_exit}

    return runner


class TestStaticDocumentGate:
    # Probes always sample t=0 plus the base envelope fractions.
    _SAMPLE_COUNT = len(_PROBE_KEYFRAME_FRACTIONS) + 1

    @pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg is not installed")
    def test_subpixel_wobble_rejected_as_static(self, monkeypatch) -> None:
        # GSAP clearing an inline transform on the final keyframe leaves a
        # one-channel-delta wobble: bytes differ, pixels don't move.
        def wobble(x: int, y: int) -> tuple[int, int, int, int]:
            value = 254 if (x, y) == (6, 6) else 255
            inside = 5 <= x < 11 and 5 <= y < 11
            return (value, 255, 255, 255) if inside else (0, 0, 0, 0)

        pixels = {index: _centered for index in range(self._SAMPLE_COUNT - 1)}
        pixels[self._SAMPLE_COUNT - 1] = wobble
        monkeypatch.setattr(
            motion_overlay,
            "_run_capture_worker",
            _fake_probe_worker(pixels),
        )
        probe = probe_motion_document(
            "<html><body>wobble-doc-sample</body></html>",
            doc_format="html_js",
            box_width=_BOX,
            box_height=_BOX,
            ffmpeg_path=_FFMPEG,
        )
        assert not probe.ok
        assert "完全静止" in probe.error


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg is not installed")
class TestOpaqueFrameAlphaFallback:
    """Fully opaque frames must not bypass the alpha truth gates."""

    def test_rgb_png_reports_full_coverage_and_edge_contact(
        self,
        tmp_path,
    ) -> None:
        # Chromium writes RGB PNGs (no alpha plane) when every pixel is
        # opaque; ``alphaextract`` fails on them, and the old sentinel
        # (-1, -1) let exactly the full-bleed documents skip the gates.
        frame = tmp_path / "opaque.png"
        write_png(
            frame,
            _BOX,
            _BOX,
            lambda _x, _y: (240, 240, 240),
            alpha=False,
        )
        coverage, edge, _center, _floor = motion_overlay._frame_alpha_stats(
            frame,
            _FFMPEG,
            _BOX,
            _BOX,
        )
        assert coverage == pytest.approx(1.0)
        assert edge == pytest.approx(1.0)


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg is not installed")
class TestLoopSeamGate:
    _LOOP_FRACTIONS = [0.0, *_PROBE_KEYFRAME_FRACTIONS]

    def _probe(self, monkeypatch, pixels, html):
        seen_jobs: list[dict] = []
        monkeypatch.setattr(
            motion_overlay,
            "_run_capture_worker",
            _fake_probe_worker(pixels, seen_jobs=seen_jobs),
        )
        probe = probe_motion_document(
            html,
            doc_format="html_js",
            box_width=_BOX,
            box_height=_BOX,
            ffmpeg_path=_FFMPEG,
            loop=True,
        )
        assert seen_jobs and seen_jobs[0]["fractions"] == self._LOOP_FRACTIONS
        return probe

    def _loop_pixels(self, last_shift: int) -> dict[int, Callable]:
        pixels = {
            index: _drifting(index % 3 + 1)
            for index in range(1, len(self._LOOP_FRACTIONS) - 1)
        }
        pixels[0] = _drifting(0)
        pixels[len(self._LOOP_FRACTIONS) - 1] = _drifting(last_shift)
        return pixels

    def test_seam_boundary_gate(self, monkeypatch) -> None:
        assert self._probe(
            monkeypatch,
            self._loop_pixels(0),
            "<html><body>seamless-loop-sample</body></html>",
        ).ok
        probe = self._probe(
            monkeypatch,
            self._loop_pixels(6),
            "<html><body>seam-jump-sample</body></html>",
        )
        assert not probe.ok
        assert "循环首尾不无缝" in probe.error


class TestMotionRenderFailurePropagation:
    @staticmethod
    def _runner(monkeypatch) -> FfmpegLocalMediaRunner:
        runner = FfmpegLocalMediaRunner(executable="ffmpeg")
        monkeypatch.setattr(
            FfmpegLocalMediaRunner,
            "_probe_video_size",
            lambda self, path: (1280, 720),
        )
        return runner

    @staticmethod
    def _item(path: Path, **extra) -> LocalMediaInput:
        return LocalMediaInput(
            version_id="ver-1",
            file_id=None,
            checksum="0" * 64,
            media_type="video/mp4",
            path=path,
            source_ref="source:src-1",
            start_seconds=0.0,
            end_seconds=4.0,
            **extra,
        )

    def test_failed_decoration_aborts_the_execution(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        # A dropped decoration must never ship as a successful final cut:
        # the error aborts the task so the rejection feedback loop can
        # regenerate or remove the design.
        runner = self._runner(monkeypatch)
        monkeypatch.setattr(
            "services.media_files.local_execution.prepare_motion_layer",
            lambda **kwargs: motion_overlay.MotionLayerPrep(
                error="html_js 文档未注册 window.__hf 协议或 duration 无效",
            ),
        )
        segment = tmp_path / "segment.mp4"
        segment.write_bytes(b"original")
        item = self._item(
            segment,
            motions=(
                {
                    "element_id": "edit-1-motion",
                    "html": _JS_HTML,
                    "format": "html_js",
                    "fps": 24,
                    "loop": True,
                    "appear_at": 0.0,
                    "duration": 2.0,
                },
            ),
        )
        with pytest.raises(ValidationError, match="中止合成"):
            runner._apply_motion_overlays(item, segment)
        # The prepared segment stays untouched for the retry.
        assert segment.read_bytes() == b"original"


class TestRenderTimeProbeGate:
    def test_html_js_render_reruns_the_loop_aware_probe(
        self,
        tmp_path,
        monkeypatch,
        stub_vendor,
    ) -> None:
        # A reused externalized document with flipped flags (for example
        # loop toggled on a non-loop design) must not skip the seam and
        # static gates: the render fails before any frame is captured.
        probes: list[dict] = []

        def fake_probe(html, **kwargs):
            probes.append(dict(kwargs))
            return motion_overlay.MotionDocumentProbe(
                False,
                "循环首尾不无缝：t=0 与 t=duration 的画面均差 38.5",
            )

        def forbidden_capture(job, *, timeout_seconds):
            raise AssertionError("capture must not run when the gate fails")

        monkeypatch.setattr(
            motion_overlay,
            "probe_motion_document",
            fake_probe,
        )
        monkeypatch.setattr(
            motion_overlay,
            "_run_capture_worker",
            forbidden_capture,
        )
        result = motion_overlay.render_motion_overlay(
            ffmpeg_path="ffmpeg",
            input_path=tmp_path / "in.mp4",
            output_path=tmp_path / "out.mp4",
            html=_JS_HTML,
            fps=24,
            loop=True,
            video_size=(640, 360),
            appear_at=0.0,
            duration=4.0,
            location={"x": 0.5, "y": 0.5, "width": 0.5, "height": 0.5},
            doc_format="html_js",
        )
        assert not result.success
        assert "渲染前真值自查未通过" in result.error
        assert probes and probes[0]["loop"] is True
