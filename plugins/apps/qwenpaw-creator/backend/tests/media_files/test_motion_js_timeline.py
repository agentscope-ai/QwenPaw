# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=protected-access,redefined-outer-name,unused-argument

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import zlib
from collections.abc import Callable
from pathlib import Path

import pytest

from domain.errors import ValidationError
from services.media_files import motion_engine, motion_overlay
from services.media_files.local_execution import (
    FfmpegLocalMediaRunner,
    LocalMediaInput,
    _fingerprint_motion,
    _fingerprint_overlay,
    _materialized_motion,
    _motion_document_payload,
)
from services.media_files.overlay import OverlayRenderResult
from services.media_files.motion_design import (
    _externalized_motion,
    _validated_design,
)
from services.media_files.motion_engine import (
    VendorLib,
    engine_digest,
    referenced_vendor_filenames,
    resolve_vendor_files,
)
from services.media_files.motion_overlay import (
    _PROBE_KEYFRAME_FRACTIONS,
    _loop_seam_stats,
    _probe_keyframe_truth_error,
    _verify_captured_frames,
    frame_cache_identity,
    frame_timestamp_ms,
    probe_motion_document,
    render_motion_poster,
)
from services.project_files.assets import AssetFileStore
from services.project_files.models import MotionGraphic


_STUB_LIB_CONTENT = b"window.stubLib = { timeline: function () {} };"

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


@pytest.fixture()
def stub_vendor(monkeypatch, tmp_path):
    """Register one stub vendored runtime and install its verified file."""

    stub = VendorLib(
        name="stub",
        filename="stub.min.js",
        sha256=hashlib.sha256(_STUB_LIB_CONTENT).hexdigest(),
        size_bytes=len(_STUB_LIB_CONTENT),
        source_url="https://example.invalid/stub.min.js",
        license_note="test stub",
    )
    vendor_dir = tmp_path / "vendor"
    vendor_dir.mkdir()
    (vendor_dir / stub.filename).write_bytes(_STUB_LIB_CONTENT)
    monkeypatch.setattr(motion_engine, "VENDOR_LIBS", {"stub": stub})
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


class TestMotionEngineVendorRegistry:
    def test_referenced_filenames_accepts_whitelisted_src(
        self,
        stub_vendor,
    ) -> None:
        assert referenced_vendor_filenames(_JS_HTML) == ["stub.min.js"]

    def test_referenced_filenames_rejects_external_src(
        self,
        stub_vendor,
    ) -> None:
        html = '<script src="https://cdn.example.com/gsap.min.js"></script>'
        with pytest.raises(ValidationError, match="白名单"):
            referenced_vendor_filenames(html)

    def test_referenced_filenames_rejects_unknown_lib(
        self,
        stub_vendor,
    ) -> None:
        with pytest.raises(ValidationError, match="未收录"):
            referenced_vendor_filenames(
                '<script src="vendor/evil.js"></script>',
            )

    def test_resolve_rejects_missing_or_corrupted_file(
        self,
        stub_vendor,
        tmp_path,
    ) -> None:
        vendor_dir = tmp_path / "vendor"
        (vendor_dir / stub_vendor.filename).write_bytes(b"tampered bytes")
        with pytest.raises(ValidationError, match="校验失败"):
            resolve_vendor_files([stub_vendor.filename])

    def test_resolve_returns_verified_paths(self, stub_vendor) -> None:
        resolved = resolve_vendor_files([stub_vendor.filename])
        assert list(resolved) == [stub_vendor.filename]

    def test_engine_digest_changes_with_lib_pin(
        self,
        stub_vendor,
        monkeypatch,
    ) -> None:
        before = engine_digest([stub_vendor.filename])
        bumped = VendorLib(
            name="stub",
            filename="stub.min.js",
            sha256=hashlib.sha256(b"next version").hexdigest(),
            size_bytes=12,
            source_url=stub_vendor.source_url,
            license_note="test stub",
        )
        monkeypatch.setattr(
            motion_engine,
            "_LIBS_BY_FILENAME",
            {bumped.filename: bumped},
        )
        assert engine_digest([bumped.filename]) != before


class TestMotionGraphicPayloadModel:
    def test_legacy_inline_html_loads(self) -> None:
        motion = MotionGraphic.model_validate({"html": _CSS_HTML})
        assert motion.format == "html_css"
        assert motion.html == _CSS_HTML
        assert motion.html_file_id is None

    def test_externalized_reference_loads(self) -> None:
        motion = MotionGraphic.model_validate(
            {"format": "html_js", "html_file_id": "file-motion-abc123"},
        )
        assert motion.html is None
        assert motion.html_file_id == "file-motion-abc123"

    def test_rejects_both_payloads(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            MotionGraphic.model_validate(
                {"html": _CSS_HTML, "html_file_id": "file-motion-abc123"},
            )

    def test_rejects_missing_payload(self) -> None:
        with pytest.raises(ValueError, match="exactly one"):
            MotionGraphic.model_validate({"fps": 24})


class TestValidatedDesignHtmlJs:
    def test_html_js_text_card_accepted(self, stub_vendor) -> None:
        raw = {**_TEXT_CARD_RAW, "html": _JS_HTML, "format": "html_js"}
        result = _validated_design(raw, required_text="本喵要发光")
        assert not isinstance(result, str)
        motion, _location, _concept = result
        assert motion.format == "html_js"
        assert motion.html == _JS_HTML

    def test_html_js_requires_hf_protocol(self, stub_vendor) -> None:
        html = _JS_HTML.replace("window.__hf", "window.__custom")
        raw = {**_TEXT_CARD_RAW, "html": html, "format": "html_js"}
        with pytest.raises(ValidationError, match="__hf"):
            _validated_design(raw, required_text="本喵要发光")

    def test_html_js_rejects_external_script(self, stub_vendor) -> None:
        html = _JS_HTML.replace(
            'src="vendor/stub.min.js"',
            'src="https://cdn.example.com/gsap.min.js"',
        )
        raw = {**_TEXT_CARD_RAW, "html": html, "format": "html_js"}
        with pytest.raises(ValidationError):
            _validated_design(raw, required_text="本喵要发光")

    def test_html_css_still_rejects_script(self, stub_vendor) -> None:
        raw = {**_TEXT_CARD_RAW, "html": _JS_HTML}
        with pytest.raises(ValidationError, match="script"):
            _validated_design(raw, required_text="本喵要发光")

    def test_inline_script_text_not_counted_as_copy(
        self,
        stub_vendor,
    ) -> None:
        # Script bodies must be stripped before the visible-copy check,
        # otherwise timeline code would be rejected as extra card text.
        raw = {**_TEXT_CARD_RAW, "html": _JS_HTML, "format": "html_js"}
        result = _validated_design(raw, required_text="本喵要发光")
        assert not isinstance(result, str)

    def test_html_js_decoration_allows_free_form(self, stub_vendor) -> None:
        # Decorations may skip the curated motif templates on the JS lane;
        # visible copy stays forbidden, so the doc is text-free graphics.
        html = _JS_HTML.replace(
            "<div class='card'>本喵要发光</div>",
            "<div class='card'></div>",
        )
        raw = {
            "needed": True,
            "concept": "呼应跳跃的弹性线条",
            "format": "html_js",
            "html": html,
            "fps": 24,
            "loop": True,
            "location": _TEXT_CARD_RAW["location"],
        }
        result = _validated_design(raw)
        assert not isinstance(result, str)
        motion, _location, _concept = result
        assert motion.format == "html_js"

    def test_html_css_decoration_still_requires_template(
        self,
        stub_vendor,
    ) -> None:
        raw = {
            "needed": True,
            "concept": "自由 CSS 装饰",
            "html": _CSS_HTML.replace("本喵要发光", ""),
            "fps": 24,
            "loop": True,
            "location": _TEXT_CARD_RAW["location"],
        }
        with pytest.raises(ValidationError, match="受控 motif"):
            _validated_design(raw)


class _ProjectStub:
    class _Assets:
        def __init__(self, files_by_id):
            self.files_by_id = files_by_id

    def __init__(self, files_by_id):
        self.assets = self._Assets(files_by_id)


class TestExternalizedMotionStorage:
    def _motion(self) -> MotionGraphic:
        return MotionGraphic(html=_CSS_HTML, fps=24, loop=False)

    @staticmethod
    def _store(tmp_path) -> AssetFileStore:
        root = tmp_path / "project"
        root.mkdir(exist_ok=True)
        return AssetFileStore(root)

    def test_publish_and_reference(self, tmp_path) -> None:
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

    def test_identical_content_deduplicates(self, tmp_path) -> None:
        store = self._store(tmp_path)
        _first, first_indexed = _externalized_motion(self._motion(), store)
        _second, second_indexed = _externalized_motion(self._motion(), store)
        assert first_indexed.file_id == second_indexed.file_id
        assert first_indexed.relative_uri == second_indexed.relative_uri

    def test_materialized_motion_round_trip(self, tmp_path) -> None:
        store = self._store(tmp_path)
        stored, indexed = _externalized_motion(self._motion(), store)
        project = _ProjectStub({indexed.file_id: indexed})
        payload = _motion_document_payload(project, stored)
        materialized = _materialized_motion(project, store, payload)
        assert materialized["html"] == _CSS_HTML


class TestMotionFingerprintProjection:
    def test_inline_and_indexed_share_checksum(self, tmp_path) -> None:
        inline = MotionGraphic(html=_CSS_HTML, fps=24, loop=False)
        root = tmp_path / "project"
        root.mkdir(exist_ok=True)
        store = AssetFileStore(root)
        stored, indexed = _externalized_motion(inline, store)
        project = _ProjectStub({indexed.file_id: indexed})
        inline_payload = _motion_document_payload(project, inline)
        indexed_payload = _motion_document_payload(project, stored)
        assert inline_payload["checksum"] == indexed_payload["checksum"]

    def test_fingerprint_never_embeds_html(self, tmp_path) -> None:
        inline = MotionGraphic(html=_CSS_HTML, fps=24, loop=False)
        payload = _motion_document_payload(_ProjectStub({}), inline)
        projected = _fingerprint_motion({**payload, "fps": 24})
        assert "html" not in projected
        assert projected["checksum"] == payload["checksum"]

    def test_overlay_projection_strips_nested_html(self) -> None:
        overlay = {
            "kind": "pet_os",
            "text": "本喵要发光",
            "motion": {"html": _CSS_HTML, "checksum": "x" * 64},
        }
        projected = _fingerprint_overlay(overlay)
        assert projected is not None
        assert "html" not in projected["motion"]

    def test_html_js_payload_carries_engine_salt(
        self,
        stub_vendor,
    ) -> None:
        motion = MotionGraphic(
            format="html_js",
            html=_JS_HTML,
            fps=24,
            loop=False,
        )
        payload = _motion_document_payload(_ProjectStub({}), motion)
        assert payload["engine"] == motion_engine.full_engine_digest()


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def _write_rgba_png(
    path: Path,
    width: int,
    height: int,
    pixel: Callable[[int, int], tuple[int, int, int, int]],
) -> None:
    """Write one uncompressed-filter RGBA PNG without an imaging library."""

    raw = b"".join(
        b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width))
        for y in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b""),
    )


def _write_rgb_png(
    path: Path,
    width: int,
    height: int,
    pixel: Callable[[int, int], tuple[int, int, int]],
) -> None:
    """Write one RGB PNG without an alpha plane, as Chromium does for
    screenshots whose every pixel ended up fully opaque."""

    raw = b"".join(
        b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(width))
        for y in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", zlib.compress(raw))
        + _png_chunk(b"IEND", b""),
    )


_FFMPEG = shutil.which("ffmpeg")

# _verify_captured_frames samples frames {0, 2, 3} for frame_count=5.
_SAMPLED_INDICES = (0, 2, 3)
_BOX = 16


def _transparent(_x: int, _y: int) -> tuple[int, int, int, int]:
    return (0, 0, 0, 0)


def _centered(x: int, y: int) -> tuple[int, int, int, int]:
    inside = 5 <= x < 11 and 5 <= y < 11
    return (255, 255, 255, 255) if inside else (0, 0, 0, 0)


def _edge_overflow(x: int, y: int) -> tuple[int, int, int, int]:
    return (255, 255, 255, 255) if y == 0 else _centered(x, y)


@pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg is not installed")
class TestCaptureTruthGate:
    """Post-render truth gate over constructed frame samples."""

    @staticmethod
    def _frames(
        tmp_path: Path,
        pixel_by_index: dict[
            int,
            Callable[[int, int], tuple[int, int, int, int]],
        ],
    ) -> Path:
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir(exist_ok=True)
        for index, pixel in pixel_by_index.items():
            _write_rgba_png(
                frames_dir / f"{index:05d}.png",
                _BOX,
                _BOX,
                pixel,
            )
        return frames_dir

    def _verify(self, frames_dir: Path) -> str | None:
        return _verify_captured_frames(
            frames_dir,
            frame_count=5,
            box_width=_BOX,
            box_height=_BOX,
            ffmpeg_path=_FFMPEG,
        )

    def test_accepts_centered_content(self, tmp_path) -> None:
        frames_dir = self._frames(
            tmp_path,
            {index: _centered for index in _SAMPLED_INDICES},
        )
        assert self._verify(frames_dir) is None

    def test_rejects_all_empty_keyframes(self, tmp_path) -> None:
        frames_dir = self._frames(
            tmp_path,
            {index: _transparent for index in _SAMPLED_INDICES},
        )
        error = self._verify(frames_dir)
        assert error is not None and "空帧" in error

    def test_accepts_partially_empty_keyframes(self, tmp_path) -> None:
        # A fade-in may leave the very first frame transparent; only an
        # entirely blank sample set is a deterministic failure.
        frames = {index: _centered for index in _SAMPLED_INDICES}
        frames[0] = _transparent
        assert self._verify(self._frames(tmp_path, frames)) is None

    def test_rejects_edge_overflow(self, tmp_path) -> None:
        frames = {index: _centered for index in _SAMPLED_INDICES}
        frames[2] = _edge_overflow
        error = self._verify(self._frames(tmp_path, frames))
        assert error is not None and "越出透明盒边缘" in error

    def test_ring_frame_accepts_full_edge_border(self, tmp_path) -> None:
        # A variety frame is an opaque border with a transparent window:
        # 100% edge contact is its normal state under the ring gate.
        def border(x: int, y: int) -> tuple[int, int, int, int]:
            on_border = x < 3 or x >= 13 or y < 3 or y >= 13
            return (255, 255, 255, 255) if on_border else (0, 0, 0, 0)

        frames_dir = self._frames(
            tmp_path,
            {index: border for index in _SAMPLED_INDICES},
        )
        assert (
            _verify_captured_frames(
                frames_dir,
                frame_count=5,
                box_width=_BOX,
                box_height=_BOX,
                ffmpeg_path=_FFMPEG,
                frame_ring=True,
            )
            is None
        )
        # Geometric recognition: the same ring form passes WITHOUT the
        # declaration (model-authored html_css frames carry no marker).
        assert (
            _verify_captured_frames(
                frames_dir,
                frame_count=5,
                box_width=_BOX,
                box_height=_BOX,
                ffmpeg_path=_FFMPEG,
            )
            is None
        )

    def test_ring_frame_rejects_opaque_center(self, tmp_path) -> None:
        # An "opaque frame" that paints the middle would cover the
        # wrapped footage: the honest center gate fails it closed.
        def opaque(_x: int, _y: int) -> tuple[int, int, int, int]:
            return (255, 255, 255, 255)

        frames_dir = self._frames(
            tmp_path,
            {index: opaque for index in _SAMPLED_INDICES},
        )
        error = _verify_captured_frames(
            frames_dir,
            frame_count=5,
            box_width=_BOX,
            box_height=_BOX,
            ffmpeg_path=_FFMPEG,
            frame_ring=True,
        )
        assert error is not None and "中心窗口必须保持透明" in error

    def test_inspection_failure_passes(self, tmp_path) -> None:
        # Missing frames or a broken ffmpeg must never reject a render:
        # the gate only acts on positive evidence.
        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        assert self._verify(frames_dir) is None
        good = self._frames(
            tmp_path,
            {index: _centered for index in _SAMPLED_INDICES},
        )
        assert (
            _verify_captured_frames(
                good,
                frame_count=5,
                box_width=_BOX,
                box_height=_BOX,
                ffmpeg_path="/nonexistent/ffmpeg",
            )
            is None
        )


class TestProbeKeyframeTruthRules:
    _FULL = [0.4] * len(_PROBE_KEYFRAME_FRACTIONS)

    def test_all_visible_passes(self) -> None:
        assert _probe_keyframe_truth_error(list(self._FULL)) is None

    def test_empty_first_frame_rejected(self) -> None:
        coverages = list(self._FULL)
        coverages[0] = 0.0
        error = _probe_keyframe_truth_error(coverages)
        assert error is not None and "首帧" in error

    def test_empty_settled_entrance_rejected(self) -> None:
        coverages = list(self._FULL)
        coverages[2] = 0.0
        error = _probe_keyframe_truth_error(coverages)
        assert error is not None and "入场" in error

    def test_empty_midpoint_rejected(self) -> None:
        coverages = list(self._FULL)
        coverages[3] = 0.0
        error = _probe_keyframe_truth_error(coverages)
        assert error is not None and "中点" in error

    def test_self_made_exit_rejected(self) -> None:
        # Probe frames carry raw timeline states (no renderer-managed
        # exit), so an empty final state always means a self-made exit.
        coverages = list(self._FULL)
        coverages[6] = 0.0
        error = _probe_keyframe_truth_error(coverages)
        assert error is not None and "末态" in error

    def test_unexpected_sample_count_passes(self) -> None:
        assert _probe_keyframe_truth_error([]) is None

    def test_probe_surfaces_truth_error(self, monkeypatch) -> None:
        # End-to-end through probe_motion_document with a faked worker:
        # an empty final keyframe must fail the probe so the design loop
        # regenerates the document.
        monkeypatch.setattr(
            motion_overlay,
            "_run_capture_worker",
            lambda job, *, timeout_seconds: {
                "count": 1,
                "totalMs": 2000.0,
                "managedExit": False,
            },
        )
        coverages = [0.4] * (len(_PROBE_KEYFRAME_FRACTIONS) + 1)
        coverages[-1] = 0.0
        monkeypatch.setattr(
            motion_overlay,
            "_frames_visible_stats",
            lambda *args: (0.4, 0.0, list(coverages)),
        )
        probe = probe_motion_document(
            "<html><body>truth-gate-probe-sample</body></html>",
            ffmpeg_path="ffmpeg",
        )
        assert not probe.ok
        assert "末态" in probe.error


class TestLoopSemantics:
    def test_loop_wraps_playhead_modulo_period(self) -> None:
        # 24 fps over a 2 s period: frame 60 sits half a period into the
        # second cycle.
        assert frame_timestamp_ms(
            60,
            24.0,
            loop=True,
            total_ms=2000.0,
        ) == pytest.approx(500.0)

    def test_loop_restart_matches_first_frame(self) -> None:
        assert frame_timestamp_ms(
            48,
            24.0,
            loop=True,
            total_ms=2000.0,
        ) == pytest.approx(
            frame_timestamp_ms(0, 24.0, loop=True, total_ms=2000.0),
        )

    def test_non_loop_holds_final_state(self) -> None:
        assert frame_timestamp_ms(
            60,
            24.0,
            loop=False,
            total_ms=2000.0,
        ) == pytest.approx(2000.0)

    def test_degenerate_period_never_wraps(self) -> None:
        assert frame_timestamp_ms(
            10,
            24.0,
            loop=True,
            total_ms=0.5,
        ) == pytest.approx(10 * 1000.0 / 24.0)

    def test_worker_source_mirrors_schedule(self) -> None:
        # The capture worker is a dependency-free source string; keep its
        # inline schedule in lockstep with frame_timestamp_ms.
        source = motion_overlay._WORKER_SOURCE
        assert "timestamp_ms % total_ms" in source
        assert "min(timestamp_ms, total_ms)" in source
        assert '"playheadMs": playhead_ms' in source

    def test_worker_source_mirrors_probe_fractions(self) -> None:
        literal = ", ".join(
            str(fraction) for fraction in _PROBE_KEYFRAME_FRACTIONS
        )
        assert literal in motion_overlay._WORKER_SOURCE


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

    def test_loop_flag_salts_identity(self) -> None:
        looped = frame_cache_identity(**self._BASE, loop=True)
        held = frame_cache_identity(**self._BASE, loop=False)
        assert looped != held
        assert json.loads(looped)["loop"] is True

    def test_engine_salt_salts_identity(self) -> None:
        first = frame_cache_identity(**self._BASE, loop=True)
        bumped = frame_cache_identity(
            **{**self._BASE, "engine_salt": "salt-b"},
            loop=True,
        )
        assert first != bumped

    def test_period_mode_salts_identity(self) -> None:
        # Period sequences carry no baked exit, so their frames must never
        # be confused with a same-length unique-frame capture.
        full = frame_cache_identity(**self._BASE, loop=True)
        period = frame_cache_identity(
            **self._BASE,
            loop=True,
            period_mode=True,
        )
        assert full != period
        assert json.loads(period)["mode"] == "period"

    def test_html_css_identity_has_no_engine_fields(self) -> None:
        identity = frame_cache_identity(
            **{**self._BASE, "doc_format": "html_css", "engine_salt": ""},
            loop=True,
        )
        parsed = json.loads(identity)
        assert "engine" not in parsed
        assert "format" not in parsed
        assert "mode" not in parsed


def _fake_probe_worker(
    pixels_by_index: dict[
        int,
        Callable[[int, int], tuple[int, int, int, int]],
    ],
    *,
    managed_exit: bool = False,
    seen_jobs: list[dict] | None = None,
):
    """Worker stand-in painting constructed frames for probe jobs."""

    def runner(job, *, timeout_seconds):  # noqa: ARG001
        if seen_jobs is not None:
            seen_jobs.append(dict(job))
        for index, pixel in pixels_by_index.items():
            _write_rgba_png(
                Path(job["frames_dir"]) / f"{index:05d}.png",
                _BOX,
                _BOX,
                pixel,
            )
        return {"count": 1, "totalMs": 2000.0, "managedExit": managed_exit}

    return runner


def _drifting(
    shift: int,
) -> Callable[[int, int], tuple[int, int, int, int]]:
    def pixel(x: int, y: int) -> tuple[int, int, int, int]:
        inside = 3 + shift <= x < 9 + shift and 5 <= y < 11
        return (255, 255, 255, 255) if inside else (0, 0, 0, 0)

    return pixel


class TestSeekErrorPropagation:
    def test_worker_source_surfaces_seek_errors(self) -> None:
        # The SEEK script returns a timestamped error instead of
        # swallowing it, and both worker loops abort on that signal.
        source = motion_overlay._WORKER_SOURCE
        assert "抛出异常" in source
        assert source.count("seek_error = page.evaluate") == 2
        assert source.count("if seek_error:") == 2

    def test_probe_fails_on_seek_error(self, monkeypatch) -> None:
        monkeypatch.setattr(
            motion_overlay,
            "_run_capture_worker",
            lambda job, *, timeout_seconds: {
                "error": "__hf.seek(1.000s) 抛出异常: Error: boom",
            },
        )
        probe = probe_motion_document(
            "<html><body>seek-error-sample</body></html>",
            doc_format="html_js",
        )
        assert not probe.ok
        assert "__hf.seek(1.000s)" in probe.error


class TestStaticDocumentGate:
    # Probes always sample t=0 plus the base envelope fractions.
    _SAMPLE_COUNT = len(_PROBE_KEYFRAME_FRACTIONS) + 1

    def test_identical_probe_frames_rejected(self, monkeypatch) -> None:
        pixels = {index: _centered for index in range(self._SAMPLE_COUNT)}
        monkeypatch.setattr(
            motion_overlay,
            "_run_capture_worker",
            _fake_probe_worker(pixels),
        )
        probe = probe_motion_document(
            "<html><body>static-doc-sample</body></html>",
            doc_format="html_js",
        )
        assert not probe.ok
        assert "完全静止" in probe.error

    def test_varying_frames_pass_static_gate(self, monkeypatch) -> None:
        pixels = {
            index: _drifting(index % 4) for index in range(self._SAMPLE_COUNT)
        }
        monkeypatch.setattr(
            motion_overlay,
            "_run_capture_worker",
            _fake_probe_worker(pixels),
        )
        probe = probe_motion_document(
            "<html><body>moving-doc-sample</body></html>",
            doc_format="html_js",
        )
        assert probe.ok

    @pytest.mark.skipif(_FFMPEG is None, reason="ffmpeg is not installed")
    def test_varying_frames_pass_static_gate_with_ffmpeg(
        self,
        monkeypatch,
    ) -> None:
        pixels = {
            index: _drifting(index % 4) for index in range(self._SAMPLE_COUNT)
        }
        monkeypatch.setattr(
            motion_overlay,
            "_run_capture_worker",
            _fake_probe_worker(pixels),
        )
        probe = probe_motion_document(
            "<html><body>moving-doc-ffmpeg-sample</body></html>",
            doc_format="html_js",
            box_width=_BOX,
            box_height=_BOX,
            ffmpeg_path=_FFMPEG,
        )
        assert probe.ok

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
        _write_rgb_png(frame, _BOX, _BOX, lambda _x, _y: (240, 240, 240))
        coverage, edge, _center, _floor = motion_overlay._frame_alpha_stats(
            frame,
            _FFMPEG,
            _BOX,
            _BOX,
        )
        assert coverage == pytest.approx(1.0)
        assert edge == pytest.approx(1.0)

    def test_probe_reports_edge_contact_for_opaque_frames(
        self,
        monkeypatch,
    ) -> None:
        def opaque_drifting(
            shift: int,
        ) -> Callable[[int, int], tuple[int, int, int]]:
            def pixel(x: int, y: int) -> tuple[int, int, int]:
                inside = 3 + shift <= x < 9 + shift and 5 <= y < 11
                return (30, 30, 30) if inside else (240, 240, 240)

            return pixel

        sample_count = len(_PROBE_KEYFRAME_FRACTIONS) + 1

        def runner(job, *, timeout_seconds):  # noqa: ARG001
            for index in range(sample_count):
                _write_rgb_png(
                    Path(job["frames_dir"]) / f"{index:05d}.png",
                    _BOX,
                    _BOX,
                    opaque_drifting(index % 4),
                )
            return {"count": 1, "totalMs": 2000.0, "managedExit": False}

        monkeypatch.setattr(motion_overlay, "_run_capture_worker", runner)
        probe = probe_motion_document(
            "<html><body>opaque-doc-sample</body></html>",
            doc_format="html_js",
            box_width=_BOX,
            box_height=_BOX,
            ffmpeg_path=_FFMPEG,
        )
        assert probe.ok
        assert probe.visible_coverage == pytest.approx(1.0)
        assert probe.edge_contact == pytest.approx(1.0)


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

    def test_seamless_boundary_passes(self, monkeypatch) -> None:
        pixels = {
            index: _drifting(index % 3 + 1)
            for index in range(1, len(self._LOOP_FRACTIONS) - 1)
        }
        pixels[0] = _drifting(0)
        pixels[len(self._LOOP_FRACTIONS) - 1] = _drifting(0)
        probe = self._probe(
            monkeypatch,
            pixels,
            "<html><body>seamless-loop-sample</body></html>",
        )
        assert probe.ok

    def test_visible_seam_rejected(self, monkeypatch) -> None:
        pixels = {
            index: _drifting(index % 3 + 1)
            for index in range(1, len(self._LOOP_FRACTIONS) - 1)
        }
        pixels[0] = _drifting(0)
        pixels[len(self._LOOP_FRACTIONS) - 1] = _drifting(6)
        probe = self._probe(
            monkeypatch,
            pixels,
            "<html><body>seam-jump-sample</body></html>",
        )
        assert not probe.ok
        assert "循环首尾不无缝" in probe.error

    def test_empty_loop_start_rejected(self, monkeypatch) -> None:
        pixels = {
            index: _drifting(1)
            for index in range(1, len(self._LOOP_FRACTIONS))
        }
        pixels[0] = _transparent
        probe = self._probe(
            monkeypatch,
            pixels,
            "<html><body>empty-loop-start-sample</body></html>",
        )
        assert not probe.ok
        assert "t=0 是空帧" in probe.error

    def test_loop_seam_stats_measure_difference(self, tmp_path) -> None:
        first = tmp_path / "first.png"
        last_same = tmp_path / "last-same.png"
        last_moved = tmp_path / "last-moved.png"
        _write_rgba_png(first, _BOX, _BOX, _drifting(0))
        _write_rgba_png(last_same, _BOX, _BOX, _drifting(0))
        _write_rgba_png(last_moved, _BOX, _BOX, _drifting(6))
        same_mean, same_changed = _loop_seam_stats(first, last_same, _FFMPEG)
        moved_mean, moved_changed = _loop_seam_stats(
            first,
            last_moved,
            _FFMPEG,
        )
        assert same_mean == 0.0 and same_changed == 0.0
        assert moved_mean > motion_overlay._LOOP_SEAM_MAX_MEAN_DIFF
        assert moved_changed > motion_overlay._LOOP_SEAM_MAX_CHANGED_FRACTION

    def test_inspection_failure_gives_benefit_of_doubt(
        self,
        tmp_path,
    ) -> None:
        stats = _loop_seam_stats(
            tmp_path / "missing-a.png",
            tmp_path / "missing-b.png",
            _FFMPEG,
        )
        assert stats == (-1.0, -1.0)


class TestMotionPoster:
    def test_poster_rendered_once_then_cached(
        self,
        monkeypatch,
        tmp_path,
    ) -> None:
        import tempfile as tempfile_module

        monkeypatch.setattr(
            tempfile_module,
            "gettempdir",
            lambda: str(tmp_path),
        )
        calls: list[dict] = []

        def worker(job, *, timeout_seconds):  # noqa: ARG001
            calls.append(dict(job))
            assert job["fractions"] == [motion_overlay._POSTER_FRACTION]
            _write_rgba_png(
                Path(job["frames_dir"]) / "00000.png",
                _BOX,
                _BOX,
                _centered,
            )
            return {"count": 1, "totalMs": 2000.0, "managedExit": False}

        monkeypatch.setattr(motion_overlay, "_run_capture_worker", worker)
        html = "<html><body>poster-cache-sample</body></html>"
        first = render_motion_poster(
            html,
            doc_format="html_js",
            box_width=_BOX,
            box_height=_BOX,
        )
        second = render_motion_poster(
            html,
            doc_format="html_js",
            box_width=_BOX,
            box_height=_BOX,
        )
        assert first is not None and first.startswith(b"\x89PNG")
        assert second == first
        # The second call must come from the on-disk poster cache.
        assert len(calls) == 1

    def test_poster_failure_degrades_to_none(self, monkeypatch) -> None:
        monkeypatch.setattr(
            motion_overlay,
            "_run_capture_worker",
            lambda job, *, timeout_seconds: {"error": "boom"},
        )
        assert (
            render_motion_poster(
                "<html><body>poster-error-sample</body></html>",
                doc_format="html_js",
                box_width=_BOX,
                box_height=_BOX,
            )
            is None
        )


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
    def _item(tmp_path: Path) -> tuple[LocalMediaInput, Path]:
        segment = tmp_path / "segment.mp4"
        segment.write_bytes(b"original")
        item = LocalMediaInput(
            version_id="ver-1",
            file_id=None,
            checksum="0" * 64,
            media_type="video/mp4",
            path=segment,
            source_ref="source:src-1",
            start_seconds=0.0,
            end_seconds=4.0,
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
        return item, segment

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
        item, segment = self._item(tmp_path)
        with pytest.raises(ValidationError, match="中止合成"):
            runner._apply_motion_overlays(item, segment)
        # The prepared segment stays untouched for the retry.
        assert segment.read_bytes() == b"original"

    def test_successful_decoration_replaces_the_segment(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        runner = self._runner(monkeypatch)

        def fake_prepare(**kwargs):
            return motion_overlay.MotionLayerPrep(
                layer=motion_overlay.PreparedMotionLayer(
                    frames_dir=tmp_path,
                    frame_count=1,
                    effective_fps=24.0,
                    appear_at=0.0,
                    duration=2.0,
                    left=0,
                    top=0,
                    opacity=1.0,
                    period_mode=False,
                    managed_exit=False,
                ),
            )

        def fake_composite(**kwargs):
            Path(kwargs["output_path"]).write_bytes(b"with-motion")
            return OverlayRenderResult(True)

        monkeypatch.setattr(
            "services.media_files.local_execution.prepare_motion_layer",
            fake_prepare,
        )
        monkeypatch.setattr(
            "services.media_files.local_execution.composite_motion_layers",
            fake_composite,
        )
        item, segment = self._item(tmp_path)
        warnings = runner._apply_motion_overlays(item, segment)
        assert not warnings
        assert segment.read_bytes() == b"with-motion"

    def test_failed_caption_fallback_aborts_the_execution(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        # The fixed bubble template is the last carrier of the caption
        # copy; when it fails too, the cut would silently lose mandatory
        # content, so the execution must abort instead of warning.
        runner = self._runner(monkeypatch)
        monkeypatch.setattr(
            "services.media_files.local_execution.render_pet_os_overlay",
            lambda **kwargs: OverlayRenderResult(False, "bubble render boom"),
        )
        segment = tmp_path / "segment.mp4"
        segment.write_bytes(b"original")
        item = LocalMediaInput(
            version_id="ver-1",
            file_id=None,
            checksum="0" * 64,
            media_type="video/mp4",
            path=segment,
            source_ref="source:src-1",
            start_seconds=0.0,
            end_seconds=4.0,
            overlays=(
                {
                    "kind": "pet_os",
                    "text": "本喵要发光",
                    "vibe": "chill",
                    "appear_at": 0.0,
                    "duration": 4.0,
                    "motion": None,
                },
            ),
        )
        with pytest.raises(ValidationError, match="台词内容不得"):
            runner._apply_overlay(item, segment)
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
