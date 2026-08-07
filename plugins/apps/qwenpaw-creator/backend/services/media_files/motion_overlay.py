# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-return-statements,consider-using-with,line-too-long
# pylint: disable=too-many-branches,too-many-statements
"""Deterministic HTML/CSS motion-graphic rendering for overlay Elements.

A ``MotionGraphic`` document is a self-contained HTML page whose visuals move
exclusively through CSS animations.  Rendering follows the seek-and-capture
approach: the page is loaded once in headless Chromium with all network
requests blocked, every animation is paused, and each output frame is produced
by setting the shared animation clock to an exact timestamp before taking a
transparent screenshot.  The resulting PNG sequence is composited onto the
prepared video segment by ffmpeg, so the final overlay is bit-reproducible for
one (html, fps, box, span) tuple.

All Playwright work runs in a dedicated short-lived worker subprocess: the
sync API is not safe inside a host process that also runs an asyncio loop,
and a subprocess gives every capture a hard kill-switch timeout.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import signal
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from typing import Any

from domain.errors import ValidationError
from services.media_files.motion_engine import (
    MOTION_PRELUDE_SCRIPT,
    engine_digest,
    referenced_vendor_filenames,
    resolve_vendor_files,
)
from services.media_files.overlay import OverlayRenderResult
from utils.logger import setup_logger

logger = setup_logger("services.media_files.motion_overlay")

_MAX_FRAMES_PER_OVERLAY = 240
_MIN_EFFECTIVE_FPS = 6
# Post-render truth gate: strongest tolerated alpha contact on the
# outermost pixel rows/columns of a captured frame before the render is
# rejected as overflowing its transparent box.  Looser than the design
# probe thresholds because the viewport-safety CSS reflows legacy docs.
_CAPTURE_MAX_EDGE_CONTACT = 0.10
# Probe fractions sampled across the animation envelope; must stay in
# sync with the fallback tuple inside _WORKER_SOURCE (drift-tested).
_PROBE_KEYFRAME_FRACTIONS = (0.05, 0.15, 0.3, 0.5, 0.7, 0.9, 1.0)
# Loop seam gate: a seamless loop must paint (nearly) identical pixels at
# t=0 and t=duration.  Rejection thresholds over premultiplied RGBA.
_LOOP_SEAM_MAX_MEAN_DIFF = 4.0
_LOOP_SEAM_MAX_CHANGED_FRACTION = 0.05
# Static detection compares every probe frame against t=0 and must stay far
# below any real motion: a genuinely frozen document measures ~0.0002 mean
# diff (GSAP clearing an inline transform), while the subtlest legitimate
# loop already exceeds 0.05.
_STATIC_MAX_MEAN_DIFF = 0.02
_STATIC_MAX_CHANGED_FRACTION = 0.0005
_LOOP_SEAM_CHANGED_CHANNEL_DELTA = 24
_FFMPEG_TIMEOUT_SECONDS = 180
_PROBE_TIMEOUT_SECONDS = 90
_CAPTURE_BASE_TIMEOUT_SECONDS = 120
_CAPTURE_PER_FRAME_SECONDS = 3.0
_PROBE_CACHE_MAX_ITEMS = 128
_FRAME_CACHE_MAX_ITEMS = 32
_probe_cache: OrderedDict[
    tuple[str, int, int, str],
    MotionDocumentProbe,
] = OrderedDict()
_probe_cache_lock = threading.Lock()

# Self-contained capture worker: it imports nothing from this backend, reads
# one JSON job from stdin and writes one JSON result line to stdout.  Keeping
# it dependency-free means the subprocess never re-imports service modules.
_WORKER_SOURCE = r"""
import json
import sys

COLLECT = '''
() => {
  const animations = document.getAnimations({ subtree: true });
  let totalMs = 0;
  for (const animation of animations) {
    try { animation.pause(); } catch (error) {}
    try {
      const timing = animation.effect && animation.effect.getComputedTiming
        ? animation.effect.getComputedTiming()
        : null;
      if (!timing) continue;
      const iterations =
        timing.iterations === Infinity ? 1 : timing.iterations || 1;
      const endMs = (timing.delay || 0) + (timing.duration || 0) * iterations;
      if (Number.isFinite(endMs)) totalMs = Math.max(totalMs, endMs);
    } catch (error) {}
  }
  let hfMs = 0;
  const proto = window.__hf;
  if (proto && typeof proto.seek === 'function') {
    const seconds = Number(proto.duration);
    if (Number.isFinite(seconds) && seconds > 0) hfMs = seconds * 1000;
  }
  const stage = document.querySelector('[data-motion-exit]');
  const exitStyle = stage ? stage.getAttribute('data-motion-exit') : 'none';
  return {
    count: animations.length,
    totalMs,
    hfMs,
    managedExit: exitStyle === 'soft_fade' || exitStyle === 'shrink',
  };
}
'''

SEEK = '''
(payload) => {
  const milliseconds = typeof payload === 'number'
    ? payload : Number(payload.milliseconds || 0);
  const outputMs = typeof payload === 'number'
    ? 0 : Number(payload.outputMs || 0);
  const playheadMs = typeof payload === 'number'
    ? milliseconds : Number(payload.playheadMs || milliseconds);
  if (typeof window.__qpMotionClock === 'function') {
    try { window.__qpMotionClock(milliseconds); } catch (error) {}
  }
  const proto = window.__hf;
  if (proto && typeof proto.seek === 'function') {
    // A throwing seek means the document cannot be driven to this
    // timestamp; surfacing it must fail the whole render, otherwise a
    // broken timeline would ship whatever static DOM happens to paint.
    try {
      proto.seek(milliseconds / 1000, { suppressEvents: true });
    } catch (error) {
      return '__hf.seek(' + (milliseconds / 1000).toFixed(3) +
        's) 抛出异常: ' + String(error);
    }
  }
  for (const animation of document.getAnimations({ subtree: true })) {
    try { animation.currentTime = milliseconds; } catch (error) {}
  }
  const stage = document.querySelector('[data-motion-exit]');
  const exitStyle = stage ? stage.getAttribute('data-motion-exit') : 'none';
  const progress = outputMs > 0 ? playheadMs / outputMs : 0;
  const exitProgress = Math.max(0, Math.min(1, (progress - 0.85) / 0.15));
  document.documentElement.style.opacity =
    exitStyle === 'none' ? '1' : String(1 - exitProgress);
  document.body.style.transformOrigin = 'center';
  document.body.style.transform = exitStyle === 'shrink'
    ? `scale(${1 - exitProgress * 0.18})` : 'none';
  return '';
}
'''

TEXT_OCCLUSION = '''
() => {
  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_TEXT,
  );
  let covered = 0;
  let sampled = 0;
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.textContent || !node.textContent.trim()) continue;
    const parent = node.parentElement;
    if (!parent) continue;
    const style = getComputedStyle(parent);
    if (
      style.display === 'none' || style.visibility === 'hidden' ||
      Number(style.opacity || 1) < 0.05
    ) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    for (const rect of range.getClientRects()) {
      if (rect.width < 1 || rect.height < 1) continue;
      const points = [];
      for (const xFraction of [0.2, 0.5, 0.8]) {
        for (const yFraction of [0.2, 0.5, 0.8]) {
          points.push([
            rect.left + rect.width * xFraction,
            rect.top + rect.height * yFraction,
          ]);
        }
      }
      for (const [x, y] of points) {
        if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) {
          covered += 1;
          sampled += 1;
          continue;
        }
        const top = document.elementFromPoint(x, y);
        // elementFromPoint returns the text node's parent when the glyph is
        // actually painted.  Returning an ancestor means this sample was
        // clipped by an overflow container or covered by another layer.
        const textIsTopmost = top === parent;
        if (!textIsTopmost) covered += 1;
        sampled += 1;
      }
    }
  }
  return sampled > 0 ? covered / sampled : 0;
}
'''


def main():
    job = json.loads(sys.stdin.read())
    import pathlib
    import tempfile
    from playwright.sync_api import sync_playwright

    with tempfile.TemporaryDirectory(prefix="motion-doc-") as doc_dir:
        doc_path = pathlib.Path(doc_dir) / "motion.html"
        doc_path.write_text(job["html"], encoding="utf-8")
        allowed = {doc_path.as_uri()}
        vendor_files = job.get("vendor_files") or {}
        if vendor_files:
            vendor_dir = pathlib.Path(doc_dir) / "vendor"
            vendor_dir.mkdir()
            for filename, source in vendor_files.items():
                target = vendor_dir / filename
                target.write_bytes(pathlib.Path(source).read_bytes())
                allowed.add(target.as_uri())
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(
                    viewport={
                        "width": job["box_width"],
                        "height": job["box_height"],
                    },
                    device_scale_factor=1,
                )
                if job.get("prelude"):
                    page.add_init_script(job["prelude"])

                doc_uri = doc_path.as_uri()

                def gate(route):
                    # Only the generated document and its vendored runtime
                    # copies may load from the local filesystem. Generated
                    # HTML must not probe other file: URLs or reach the
                    # network.
                    if route.request.url in allowed:
                        route.continue_()
                    else:
                        route.abort()

                page.route("**/*", gate)
                page.goto(
                    doc_uri, wait_until="load", timeout=15000,
                )
                page.add_style_tag(
                    content=(
                        "html,body{background:transparent !important;"
                        "margin:0;padding:0;overflow:hidden;"
                        "width:100%;height:100%;}"
                    ),
                )
                info = page.evaluate(COLLECT)
                count = int(info.get("count") or 0)
                total_ms = float(info.get("totalMs") or 0.0)
                hf_ms = float(info.get("hfMs") or 0.0)
                managed_exit = bool(info.get("managedExit"))
                text_occlusion = 0.0
                if job.get("format") == "html_js":
                    if hf_ms <= 0:
                        print(json.dumps({
                            "error": "html_js 文档未注册 window.__hf 协议或 duration 无效",
                        }))
                        return
                    # The registered timeline owns the document clock; CSS
                    # animations, if any, follow the same seek below.
                    total_ms = hf_ms
                    count = max(count, 1)
                if job["mode"] == "probe" and count > 0 and job.get("frames_dir"):
                    # The host chooses the sampled envelope fractions (a
                    # loop probe prepends 0.0 for the seam comparison).
                    fractions = job.get("fractions") or [
                        0.05, 0.15, 0.3, 0.5, 0.7, 0.9, 1.0,
                    ]
                    for index, fraction in enumerate(fractions):
                        seek_error = page.evaluate(
                            SEEK,
                            {
                                "milliseconds": (
                                    total_ms * fraction
                                    if total_ms > 1.0
                                    else 0.0
                                ),
                                # Probes inspect raw timeline states;
                                # renderer-managed exits are applied at
                                # capture/composite time, never here.
                                "outputMs": 0.0,
                            },
                        )
                        if seek_error:
                            print(json.dumps({"error": seek_error}))
                            return
                        text_occlusion = max(
                            text_occlusion,
                            float(page.evaluate(TEXT_OCCLUSION) or 0.0),
                        )
                        page.screenshot(
                            path="%s/%05d.png" % (job["frames_dir"], index),
                            omit_background=True,
                            timeout=15000,
                        )
                if job["mode"] == "capture" and count > 0:
                    frames_dir = job["frames_dir"]
                    fps = float(job["effective_fps"])
                    loop = bool(job["loop"])
                    # Period captures reuse one loop of frames across the
                    # whole output window; exits are applied by ffmpeg
                    # instead of being baked into per-frame pixels.
                    bake_exit = bool(job.get("bake_exit", True))
                    for index in range(int(job["frame_count"])):
                        # Keep in sync with frame_timestamp_ms in the
                        # host module: looping documents wrap the seek
                        # time modulo one declared period.
                        playhead_ms = index * 1000.0 / fps
                        timestamp_ms = playhead_ms
                        if loop and total_ms > 1.0:
                            timestamp_ms = timestamp_ms % total_ms
                        elif total_ms > 1.0:
                            timestamp_ms = min(timestamp_ms, total_ms)
                        seek_error = page.evaluate(
                            SEEK,
                            {
                                "milliseconds": timestamp_ms,
                                # Renderer-managed exits track the real
                                # playhead, not the wrapped loop time.
                                "playheadMs": playhead_ms,
                                "outputMs": (
                                    int(job["frame_count"]) * 1000.0 / fps
                                    if bake_exit
                                    else 0.0
                                ),
                            },
                        )
                        if seek_error:
                            print(json.dumps({"error": seek_error}))
                            return
                        page.screenshot(
                            path="%s/%05d.png" % (frames_dir, index),
                            omit_background=True,
                            timeout=15000,
                        )
            finally:
                browser.close()
    print(json.dumps({
        "count": count,
        "totalMs": total_ms,
        "managedExit": managed_exit,
        "textOcclusion": text_occlusion,
    }))


try:
    main()
except Exception as exc:  # noqa: BLE001
    print(json.dumps({"error": "%s: %s" % (type(exc).__name__, exc)}))
"""


@dataclass(frozen=True, slots=True)
class MotionDocumentProbe:
    ok: bool
    error: str = ""
    animation_count: int = 0
    animation_total_ms: float = 0.0
    visible_coverage: float = -1.0
    edge_contact: float = -1.0
    text_occlusion: float = -1.0


def _normalized_box(
    location: Mapping[str, Any] | None,
    video_size: tuple[int, int],
) -> tuple[int, int, int, int, float]:
    """Resolve one anchor-based normalized location to pixel geometry.

    Returns ``(box_width, box_height, left, top, opacity)`` using the same
    anchor semantics as ``ElementLocation``: ``x/y`` place the selected anchor
    point of the content box on the canvas.
    """

    video_width, video_height = video_size
    defaults = {
        "x": 0.5,
        "y": 0.5,
        "width": 1.0,
        "height": 1.0,
        "anchor_x": 0.5,
        "anchor_y": 0.5,
        "opacity": 1.0,
    }
    values = dict(defaults)
    if isinstance(location, Mapping):
        for key, fallback in defaults.items():
            try:
                value = float(location.get(key, fallback))
            except (TypeError, ValueError):
                value = fallback
            values[key] = value if math.isfinite(value) else fallback
    box_width = max(
        2,
        round(video_width * max(1e-6, values["width"])) // 2 * 2,
    )
    box_height = max(
        2,
        round(video_height * max(1e-6, values["height"])) // 2 * 2,
    )
    anchor_x = min(1.0, max(0.0, values["anchor_x"]))
    anchor_y = min(1.0, max(0.0, values["anchor_y"]))
    left = round(values["x"] * video_width - anchor_x * box_width)
    top = round(values["y"] * video_height - anchor_y * box_height)
    opacity = min(1.0, max(0.0, values["opacity"]))
    return box_width, box_height, left, top, opacity


def caption_layout_error(
    location: Mapping[str, Any] | None,
    text: str,
    video_size: tuple[int, int],
) -> str | None:
    """Return a deterministic reason when a caption viewport is unreadable."""

    canvas_width, canvas_height = video_size
    if canvas_width <= 0 or canvas_height <= 0:
        return "字幕卡画布尺寸必须为正数"
    box_width, box_height, _left, _top, _opacity = _normalized_box(
        location,
        video_size,
    )
    compact_text = re.sub(r"\s+", "", text)
    character_count = max(1, len(compact_text))
    scale = min(canvas_width / 1280.0, canvas_height / 720.0)
    nominal_font = max(18.0, 30.0 * scale)
    minimum_width = max(
        canvas_width * 0.24,
        min(
            canvas_width * 0.68,
            min(character_count, 14) * nominal_font * 0.72
            + nominal_font * 2.0,
        ),
    )
    if box_width < minimum_width:
        return (
            "字幕卡 location.width 太窄，文字会逐字竖排或被装饰遮挡；"
            f"当前约 {box_width:.0f}px，至少需要 {minimum_width:.0f}px"
        )
    if character_count >= 4 and box_width / max(1.0, box_height) < 1.25:
        return "字幕卡必须保持横向布局，location 宽高比至少为 1.25，" "避免文字竖排并与图标重叠"
    usable_width = max(1.0, box_width - nominal_font * 2.0)
    characters_per_line = max(1, int(usable_width / (nominal_font * 0.9)))
    estimated_lines = math.ceil(character_count / characters_per_line)
    minimum_height = max(
        canvas_height * 0.12,
        estimated_lines * nominal_font * 1.25 + nominal_font * 1.5,
    )
    if box_height < minimum_height:
        return (
            "字幕卡 location.height 不足以完整容纳换行文字和装饰；"
            f"当前约 {box_height:.0f}px，至少需要 {minimum_height:.0f}px"
        )
    return None


def _kill_worker_session(process: subprocess.Popen) -> None:
    """Terminate a worker and every process in its session or tree."""

    try:
        if os.name == "nt":
            # Windows has no process sessions; taskkill /T removes the tree
            # so headless Chromium descendants cannot survive as orphans.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                timeout=15,
                check=False,
            )
        elif hasattr(os, "killpg") and hasattr(os, "getpgid"):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
    except (
        ProcessLookupError,
        PermissionError,
        OSError,
        subprocess.SubprocessError,
    ):
        process.kill()
    try:
        process.communicate(timeout=10)
    except Exception:  # noqa: BLE001 - best-effort reap
        pass


def _run_capture_worker(
    job: Mapping[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Run one Playwright capture job in an isolated subprocess.

    Returns the worker's JSON result; a crash, timeout or malformed reply
    surfaces as ``{"error": ...}`` so both callers share one failure shape.
    """

    try:
        import playwright  # noqa: F401  # pylint: disable=unused-import
    except ImportError:
        return {"error": "playwright 未安装，无法渲染动效"}
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", _WORKER_SOURCE],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"error": f"动效渲染子进程启动失败: {exc}"}
    try:
        stdout, stderr = process.communicate(
            input=json.dumps(job),
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        # Kill the whole session so headless Chromium descendants cannot
        # survive their parent worker as orphans.
        _kill_worker_session(process)
        return {"error": f"动效渲染超时（{timeout_seconds:.0f} 秒）"}
    except Exception as exc:  # noqa: BLE001
        _kill_worker_session(process)
        return {"error": f"动效渲染子进程通信失败: {exc}"}
    if process.returncode != 0:
        detail = (stderr or stdout or "").strip()[-300:]
        return {"error": f"动效渲染子进程异常退出: {detail}"}
    last_line = (stdout or "").strip().splitlines()
    try:
        result = json.loads(last_line[-1]) if last_line else {}
    except json.JSONDecodeError:
        result = {}
    if not isinstance(result, dict) or (
        "error" not in result and "count" not in result
    ):
        return {"error": "动效渲染子进程返回了无法解析的结果"}
    return result


def _alpha_plane_stats(
    plane: bytes,
    width: int,
    height: int,
) -> tuple[float, float]:
    """Return (visible fraction, strongest edge-contact fraction) of one plane.

    Edge contact measures how much visible content sits on the outermost
    pixel rows/columns; a high value means the content overflows the
    viewport and is being clipped. ``(-1.0, -1.0)`` when the buffer does
    not match the expected geometry.
    """

    total = width * height
    if width <= 0 or height <= 0 or len(plane) < total:
        return -1.0, -1.0
    visible = sum(1 for byte in plane[:total] if byte > 16)
    edges = (
        plane[0:width],
        plane[(height - 1) * width : total],
        plane[0:total:width],
        plane[width - 1 : total : width],
    )
    edge_contact = max(
        sum(1 for byte in edge if byte > 16) / len(edge) for edge in edges
    )
    return visible / total, edge_contact


def _frame_alpha_stats(
    frame: Path,
    ffmpeg_path: str,
    width: int,
    height: int,
) -> tuple[float, float]:
    """Return (coverage, edge contact) for one frame, ``(-1.0, -1.0)`` when
    the alpha plane cannot be inspected."""

    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-v",
                "error",
                "-i",
                os.fspath(frame),
                "-vf",
                "alphaextract",
                "-f",
                "rawvideo",
                "pipe:1",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except Exception:  # noqa: BLE001 - inspection is best-effort
        return -1.0, -1.0
    if result.returncode != 0 or not result.stdout:
        # Fully opaque frames are written as RGB PNGs without an alpha
        # plane, which makes ``alphaextract`` fail exactly for the
        # documents that flood the whole viewport. Rebuild the plane from
        # the RGBA raw decode (alpha defaults to 255) instead of giving
        # such frames the benefit of the doubt.
        rgba = _frame_rgba_bytes(frame, ffmpeg_path)
        if rgba is None:
            return -1.0, -1.0
        return _alpha_plane_stats(bytes(rgba[3::4]), width, height)
    coverage, edge = _alpha_plane_stats(result.stdout, width, height)
    if coverage < 0.0:
        visible = sum(1 for byte in result.stdout if byte > 16)
        coverage = visible / len(result.stdout)
        edge = -1.0
    return coverage, edge


def _frames_visible_stats(
    frames_dir: Path,
    ffmpeg_path: str,
    width: int,
    height: int,
) -> tuple[float, float, list[float]]:
    """Alpha statistics across every probe frame in one directory.

    Returns ``(max coverage, max edge contact, per-frame coverages)``. The
    alpha plane is extracted with ffmpeg so no imaging library is required;
    when the inspection itself fails ``(-1.0, -1.0, [])`` is returned so the
    document is given the benefit of the doubt instead of being rejected.
    """

    frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        return -1.0, -1.0, []
    coverage = 0.0
    edge_contact = 0.0
    coverages: list[float] = []
    for frame in frames:
        frame_coverage, frame_edge = _frame_alpha_stats(
            frame,
            ffmpeg_path,
            width,
            height,
        )
        if frame_coverage < 0.0:
            return -1.0, -1.0, []
        coverages.append(frame_coverage)
        coverage = max(coverage, frame_coverage)
        edge_contact = max(edge_contact, frame_edge)
    return coverage, edge_contact, coverages


def _probe_keyframe_truth_error(coverages: list[float]) -> str | None:
    """Deterministic empty-keyframe rules over the probe frame samples.

    Checks the first sampled frame, the settled entrance, the midpoint and
    the final state of the envelope (fractions 0.05 / 0.3 / 0.5 / 1.0 of
    ``_PROBE_KEYFRAME_FRACTIONS``).  Probe frames carry raw timeline
    states — renderer-managed exits are never applied during probing — so
    the final state must be visible for every document.
    """

    if len(coverages) != len(_PROBE_KEYFRAME_FRACTIONS):
        return None
    if coverages[0] <= 0.0:
        return "动画首帧是空帧；从第一帧起就必须有可见内容，不要从完全透明开始入场"
    if coverages[2] <= 0.0:
        return "入场完成后画面仍是空帧，动画中段必须有可见内容"
    if coverages[3] <= 0.0:
        return "动画中点是空帧，时间线中段必须有可见内容"
    if coverages[6] <= 0.0:
        return "时间线末态是空帧；不要自己做退场，末态必须保持完整可见" "（如需退场请声明 data-motion-exit）"
    return None


def _frame_rgba_bytes(
    frame: Path,
    ffmpeg_path: str,
) -> bytes | None:
    """Raw RGBA plane of one PNG frame, ``None`` when inspection fails."""

    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-v",
                "error",
                "-i",
                os.fspath(frame),
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgba",
                "pipe:1",
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except Exception:  # noqa: BLE001 - inspection is best-effort
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    return result.stdout


def _loop_seam_stats(
    first_frame: Path,
    last_frame: Path,
    ffmpeg_path: str,
) -> tuple[float, float]:
    """(mean abs diff, changed-pixel fraction) between two boundary frames.

    Pixels are compared premultiplied so RGB noise under fully transparent
    alpha never counts.  ``(-1.0, -1.0)`` when inspection fails, giving the
    document the benefit of the doubt.
    """

    first = _frame_rgba_bytes(first_frame, ffmpeg_path)
    last = _frame_rgba_bytes(last_frame, ffmpeg_path)
    if first is None or last is None or len(first) != len(last):
        return -1.0, -1.0
    total_pixels = len(first) // 4
    if total_pixels <= 0:
        return -1.0, -1.0
    diff_sum = 0
    changed = 0
    for offset in range(0, total_pixels * 4, 4):
        alpha_a = first[offset + 3]
        alpha_b = last[offset + 3]
        pixel_changed = False
        for channel in range(3):
            value_a = first[offset + channel] * alpha_a // 255
            value_b = last[offset + channel] * alpha_b // 255
            delta = abs(value_a - value_b)
            diff_sum += delta
            pixel_changed = (
                pixel_changed or delta > _LOOP_SEAM_CHANGED_CHANNEL_DELTA
            )
        delta = abs(alpha_a - alpha_b)
        diff_sum += delta
        if pixel_changed or delta > _LOOP_SEAM_CHANGED_CHANNEL_DELTA:
            changed += 1
    return diff_sum / (total_pixels * 4), changed / total_pixels


def _frames_visually_static(
    frame_paths: list[Path],
    ffmpeg_path: str | None,
) -> bool:
    """True when every sampled frame is visually identical to the first.

    Byte equality alone misses documents whose timeline only produces a
    sub-perceptual wobble (e.g. GSAP clearing an inline transform on the
    final keyframe), so frames that differ as bytes are re-compared at
    pixel level with the dedicated static tolerances.
    """

    if len(frame_paths) <= 1:
        return False
    if len({path.read_bytes() for path in frame_paths}) == 1:
        return True
    if not ffmpeg_path:
        return False
    for other in frame_paths[1:]:
        if other.read_bytes() == frame_paths[0].read_bytes():
            continue
        mean_diff, changed = _loop_seam_stats(
            frame_paths[0],
            other,
            ffmpeg_path,
        )
        if mean_diff < 0.0:
            return False
        if (
            mean_diff > _STATIC_MAX_MEAN_DIFF
            or changed > _STATIC_MAX_CHANGED_FRACTION
        ):
            return False
    return True


def _verify_captured_frames(
    frames_dir: Path,
    *,
    frame_count: int,
    box_width: int,
    box_height: int,
    ffmpeg_path: str,
    full_canvas: bool = False,
) -> str | None:
    """Post-render truth gate over the captured output frames.

    Samples the first, middle and pre-exit tail frame (80% of the window,
    before any renderer-managed exit fade) and applies deterministic
    rules: a render whose sampled frames are all empty, or whose visible
    alpha reaches the outermost pixel rows/columns beyond
    ``_CAPTURE_MAX_EDGE_CONTACT``, is rejected so bad frames never enter
    the frame cache or the composited segment.  Inspection failures pass:
    the gate must never turn tooling problems into lost overlays.
    """

    if frame_count <= 0:
        return None
    indices = sorted(
        {
            0,
            (frame_count - 1) // 2,
            max(0, math.floor(0.8 * (frame_count - 1))),
        },
    )
    coverages: list[float] = []
    for index in indices:
        coverage, edge = _frame_alpha_stats(
            frames_dir / f"{index:05d}.png",
            ffmpeg_path,
            box_width,
            box_height,
        )
        if coverage < 0.0:
            return None
        # A full-canvas motion clip IS the picture: touching the box edge
        # is its normal state, so only the empty-frame rule applies.
        if not full_canvas and edge > _CAPTURE_MAX_EDGE_CONTACT:
            return (
                f"动效渲染真值自查失败: 第 {index} 帧可见内容越出透明盒边缘"
                f"（边缘接触率 {edge:.0%}），拒绝入库"
            )
        coverages.append(coverage)
    if all(coverage <= 0.0 for coverage in coverages):
        return "动效渲染真值自查失败: 抽检的首/中/尾帧全部为空帧，拒绝入库"
    if full_canvas and min(coverages) < 0.85:
        # The document is the segment's whole picture: a "card" floating
        # on the transparent box would ship black bars into the final cut.
        return (
            f"动效渲染真值自查失败: 全屏动效片段的画面只覆盖了视口的 "
            f"{min(coverages):.0%}，根容器必须铺满整个视口（禁止外边距/内缩/圆角卡片）"
        )
    return None


def _engine_job_fields(html: str, doc_format: str) -> dict[str, Any]:
    """Worker job fields for one document format.

    ``html_js`` documents get the determinism prelude plus verified local
    copies of every referenced vendor runtime; failures raise before any
    subprocess is spawned.
    """

    if doc_format != "html_js":
        return {"format": "html_css"}
    vendor_files = resolve_vendor_files(referenced_vendor_filenames(html))
    return {
        "format": "html_js",
        "prelude": MOTION_PRELUDE_SCRIPT,
        "vendor_files": vendor_files,
    }


def _engine_salt(html: str, doc_format: str) -> str:
    """Cache/fingerprint salt for out-of-document render inputs.

    Empty for ``html_css`` so every existing cache entry and fingerprint
    stays valid; ``html_js`` output additionally depends on the prelude
    and the pinned vendor runtimes.
    """

    if doc_format != "html_js":
        return ""
    return engine_digest(referenced_vendor_filenames(html))


def probe_motion_document(
    html: str,
    *,
    doc_format: str = "html_css",
    box_width: int = 640,
    box_height: int = 360,
    ffmpeg_path: str | None = None,
    loop: bool = False,
) -> MotionDocumentProbe:
    """Load a motion document once and report its animation facts.

    ``loop`` additionally samples the exact period boundary (t=0 and
    t=duration) and rejects documents whose loop seam visibly jumps.
    """

    try:
        engine_fields = _engine_job_fields(html, doc_format)
        engine_salt = _engine_salt(html, doc_format)
    except ValidationError as exc:
        # Expected contract failures (unknown/missing/corrupted vendor
        # runtime) feed back to the design loop; programming errors must
        # propagate instead of burning VLM regeneration cycles.
        return MotionDocumentProbe(False, str(exc))
    cache_key = (
        hashlib.sha256(html.encode("utf-8")).hexdigest(),
        int(box_width),
        int(box_height),
        f"{ffmpeg_path or ''}|{doc_format}|{engine_salt}|loop:{bool(loop)}",
    )
    with _probe_cache_lock:
        cached = _probe_cache.get(cache_key)
        if cached is not None:
            _probe_cache.move_to_end(cache_key)
            return cached

    # Every probe prepends the exact timeline start: t=0 is what the
    # first composited frame shows, so it must never be empty; for loop
    # documents it doubles as the seam-comparison boundary.
    fractions = (0.0, *_PROBE_KEYFRAME_FRACTIONS)
    with tempfile.TemporaryDirectory(prefix="motion-probe-") as probe_dir:
        result = _run_capture_worker(
            {
                "mode": "probe",
                "html": html,
                "box_width": int(box_width),
                "box_height": int(box_height),
                "frames_dir": probe_dir,
                "fractions": list(fractions),
                **engine_fields,
            },
            timeout_seconds=_PROBE_TIMEOUT_SECONDS,
        )
        if result.get("error"):
            return MotionDocumentProbe(
                False,
                f"动效文档加载失败: {result['error']}",
            )
        count = int(result.get("count") or 0)
        total_ms = float(result.get("totalMs") or 0.0)
        text_occlusion = float(result.get("textOcclusion", -1.0))
        if count <= 0:
            return MotionDocumentProbe(
                False,
                "动效文档没有任何 CSS 动画，无法产生运动",
                animation_count=0,
            )
        frame_paths = sorted(Path(probe_dir).glob("*.png"))
        if doc_format == "html_js" and _frames_visually_static(
            frame_paths,
            ffmpeg_path,
        ):
            # Every sampled timestamp painted identical pixels: the seek
            # protocol is registered but drives no visible motion.
            return MotionDocumentProbe(
                False,
                "动效文档在所有采样时间点画面完全静止：时间线必须真正驱动可见运动，不要注册空的 seek 或只摆静态内容",
                animation_count=count,
                animation_total_ms=total_ms,
            )
        coverage, edge_contact, frame_coverages = (
            _frames_visible_stats(
                Path(probe_dir),
                ffmpeg_path,
                int(box_width),
                int(box_height),
            )
            if ffmpeg_path
            else (-1.0, -1.0, [])
        )
        if coverage == 0.0:
            return MotionDocumentProbe(
                False,
                "动效文档渲染出来没有任何可见内容：请给 html 和 body 显式设置 "
                "width:100% 与 height:100%，确保动画元素在文档可视区域内，"
                "并且动画过程中元素有可见的不透明度",
                animation_count=count,
                animation_total_ms=total_ms,
            )
        # The t=0 sample participates in the start/seam gates below; the
        # base keyframe rules keep their canonical fraction indices.
        start_coverage = frame_coverages[0] if frame_coverages else -1.0
        base_coverages = frame_coverages[1:]
        truth_error = _probe_keyframe_truth_error(base_coverages)
        if truth_error is None and start_coverage == 0.0:
            truth_error = (
                "动效在 t=0 是空帧；合成的第一帧就是 t=0，入场不得从完全透明开始，请从部分可见状态（不透明度 ≥0.2）起步"
            )
        if (
            truth_error is None
            and loop
            and ffmpeg_path
            and len(frame_paths) == len(fractions)
        ):
            seam_mean, seam_changed = _loop_seam_stats(
                frame_paths[0],
                frame_paths[-1],
                ffmpeg_path,
            )
            if (
                seam_mean > _LOOP_SEAM_MAX_MEAN_DIFF
                or seam_changed > _LOOP_SEAM_MAX_CHANGED_FRACTION
            ):
                truth_error = (
                    f"循环首尾不无缝：t=0 与 t=duration 的画面均差 "
                    f"{seam_mean:.1f}、{seam_changed:.0%} 像素发生变化。"
                    "GSAP 时间线首尾状态必须完全一致才能无缝循环"
                )
        if truth_error is not None:
            return MotionDocumentProbe(
                False,
                truth_error,
                animation_count=count,
                animation_total_ms=total_ms,
                visible_coverage=coverage,
                edge_contact=edge_contact,
            )
        probe = MotionDocumentProbe(
            True,
            animation_count=count,
            animation_total_ms=total_ms,
            visible_coverage=coverage,
            edge_contact=edge_contact,
            text_occlusion=text_occlusion,
        )
        with _probe_cache_lock:
            _probe_cache[cache_key] = probe
            _probe_cache.move_to_end(cache_key)
            while len(_probe_cache) > _PROBE_CACHE_MAX_ITEMS:
                _probe_cache.popitem(last=False)
        return probe


_POSTER_CACHE_MAX_ITEMS = 64
# Sampled after the entrance has settled, before any managed exit.
_POSTER_FRACTION = 0.35


def render_motion_poster(
    html: str,
    *,
    doc_format: str = "html_css",
    box_width: int = 640,
    box_height: int = 360,
) -> bytes | None:
    """One deterministic PNG poster frame of a motion document.

    Backs the live-preview representation of ``html_js`` documents, whose
    scripts must never execute inside the frontend preview iframe: the
    same sandboxed engine that produces final frames renders one settled
    frame here instead.  Results are content-addressed on disk; ``None``
    means no poster could be produced (callers degrade gracefully).
    """

    try:
        engine_fields = _engine_job_fields(html, doc_format)
        engine_salt = _engine_salt(html, doc_format)
    except Exception:  # noqa: BLE001 - posters are best-effort
        return None
    identity = json.dumps(
        {
            "html": hashlib.sha256(html.encode("utf-8")).hexdigest(),
            "box": [int(box_width), int(box_height)],
            "fraction": _POSTER_FRACTION,
            "format": doc_format,
            "engine": engine_salt,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    cache_root = Path(tempfile.gettempdir()) / "qwenpaw-motion-poster-cache-v1"
    try:
        cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        return None
    target = cache_root / (
        hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".png"
    )
    if target.is_file():
        try:
            return target.read_bytes()
        except OSError:
            pass
    with tempfile.TemporaryDirectory(prefix="motion-poster-") as poster_dir:
        result = _run_capture_worker(
            {
                "mode": "probe",
                "html": html,
                "box_width": int(box_width),
                "box_height": int(box_height),
                "frames_dir": poster_dir,
                "fractions": [_POSTER_FRACTION],
                **engine_fields,
            },
            timeout_seconds=_PROBE_TIMEOUT_SECONDS,
        )
        if result.get("error") or int(result.get("count") or 0) <= 0:
            return None
        frame = Path(poster_dir) / "00000.png"
        if not frame.is_file():
            return None
        payload = frame.read_bytes()
    try:
        target.write_bytes(payload)
        stale = sorted(
            cache_root.glob("*.png"),
            key=lambda entry: entry.stat().st_mtime,
            reverse=True,
        )[_POSTER_CACHE_MAX_ITEMS:]
        for entry in stale:
            entry.unlink(missing_ok=True)
    except OSError:
        pass
    return payload


def _complete_frame_cache(frames_dir: Path, frame_count: int) -> bool:
    return frames_dir.is_dir() and all(
        (frames_dir / f"{index:05d}.png").is_file()
        for index in range(frame_count)
    )


def _prune_frame_cache(cache_root: Path) -> None:
    entries = sorted(
        (entry for entry in cache_root.iterdir() if entry.is_dir()),
        key=lambda entry: entry.stat().st_mtime,
        reverse=True,
    )
    for stale in entries[_FRAME_CACHE_MAX_ITEMS:]:
        shutil.rmtree(stale, ignore_errors=True)


def _capture_frames(
    *,
    html: str,
    frames_dir: Path,
    box_width: int,
    box_height: int,
    frame_count: int,
    effective_fps: float,
    loop: bool,
    engine_fields: Mapping[str, Any] | None = None,
    bake_exit: bool = True,
) -> tuple[str | None, bool]:
    """Seek-and-capture one transparent PNG per output frame.

    Returns ``(error, managed_exit)``; ``bake_exit=False`` captures pure
    timeline pixels so a period sequence can be looped by ffmpeg with the
    exit applied at composite time instead.
    """

    timeout_seconds = (
        _CAPTURE_BASE_TIMEOUT_SECONDS
        + _CAPTURE_PER_FRAME_SECONDS * frame_count
    )
    result = _run_capture_worker(
        {
            "mode": "capture",
            "html": html,
            "box_width": int(box_width),
            "box_height": int(box_height),
            "frames_dir": os.fspath(frames_dir),
            "frame_count": int(frame_count),
            "effective_fps": float(effective_fps),
            "loop": bool(loop),
            "bake_exit": bool(bake_exit),
            **(dict(engine_fields) if engine_fields else {}),
        },
        timeout_seconds=timeout_seconds,
    )
    managed_exit = bool(result.get("managedExit"))
    if result.get("error"):
        return f"动效帧渲染失败: {result['error']}", managed_exit
    if int(result.get("count") or 0) <= 0:
        return "动效文档没有任何 CSS 动画", managed_exit
    missing = [
        index
        for index in range(frame_count)
        if not (frames_dir / f"{index:05d}.png").is_file()
    ]
    if missing:
        return f"动效帧渲染不完整，缺少 {len(missing)} 帧", managed_exit
    return None, managed_exit


def frame_timestamp_ms(
    index: int,
    effective_fps: float,
    *,
    loop: bool,
    total_ms: float,
) -> float:
    """Timeline time sought for one output frame.

    Host-side mirror of the capture-worker schedule (the worker is a
    dependency-free source string and cannot import this module): looping
    documents wrap the playhead modulo one declared period, non-looping
    documents hold their final state.  Drift between the two is caught by
    the loop-semantics unit tests asserting on the worker source.
    """

    timestamp_ms = index * 1000.0 / effective_fps
    if loop and total_ms > 1.0:
        return timestamp_ms % total_ms
    if total_ms > 1.0:
        return min(timestamp_ms, total_ms)
    return timestamp_ms


def frame_cache_identity(
    *,
    html: str,
    box_width: int,
    box_height: int,
    frame_count: int,
    effective_fps: float,
    loop: bool,
    doc_format: str,
    engine_salt: str,
    period_mode: bool = False,
) -> str:
    """Canonical identity of one captured frame sequence.

    Every input that can change captured pixels must appear here: the
    document bytes, box geometry, frame schedule (count, fps and the loop
    flag, because looping wraps seek times), the period-capture mode (its
    frames carry no baked exit) and, for ``html_js``, the engine salt over
    prelude + pinned vendor runtimes.
    """

    return json.dumps(
        {
            "html": hashlib.sha256(html.encode("utf-8")).hexdigest(),
            "box": [box_width, box_height],
            "frames": frame_count,
            "fps": round(effective_fps, 6),
            "loop": loop,
            # Optional keys stay absent on the default path so every
            # existing cache entry keeps its identity.
            **({"mode": "period"} if period_mode else {}),
            **(
                {"format": doc_format, "engine": engine_salt}
                if engine_salt
                else {}
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def render_motion_overlay(
    *,
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    html: str,
    fps: int,
    loop: bool,
    video_size: tuple[int, int],
    appear_at: float,
    duration: float,
    location: Mapping[str, Any] | None = None,
    viewport_inset: float = 0.0,
    doc_format: str = "html_css",
    full_canvas: bool = False,
) -> OverlayRenderResult:
    """Render one motion document and composite it over a prepared segment."""

    if duration <= 0 or not math.isfinite(duration):
        return OverlayRenderResult(False, "动效持续时间必须为正数")
    try:
        engine_fields = _engine_job_fields(html, doc_format)
        engine_salt = _engine_salt(html, doc_format)
    except Exception as exc:  # noqa: BLE001 - render must fail soft
        return OverlayRenderResult(False, str(exc))
    box_width, box_height, left, top, opacity = _normalized_box(
        location,
        video_size,
    )
    if doc_format == "html_js":
        # Render-time truth gate: every html_js document passes the full
        # loop-aware probe (seam, static-document, empty-keyframe and
        # coverage rules) against the authored body before any frame is
        # captured. Documents normally arrive pre-probed through the
        # design pipeline, but a reused reference with flipped flags (for
        # example loop toggled on a non-loop document) must not skip the
        # gates; probe results are cached per (html, box, loop).
        gate = probe_motion_document(
            html,
            doc_format=doc_format,
            box_width=box_width,
            box_height=box_height,
            ffmpeg_path=ffmpeg_path,
            loop=loop,
        )
        if not gate.ok:
            return OverlayRenderResult(
                False,
                f"渲染前真值自查未通过: {gate.error}",
            )
    effective_fps = float(min(max(int(fps), _MIN_EFFECTIVE_FPS), 60))
    frame_count = math.ceil(duration * effective_fps)
    # Long looping overlays capture exactly one period and let ffmpeg
    # repeat it: a capped unique-frame capture would freeze after
    # _MAX_FRAMES_PER_OVERLAY / _MIN_EFFECTIVE_FPS seconds because the
    # image sequence simply runs out of frames.
    period_mode = False
    if loop and frame_count > _MAX_FRAMES_PER_OVERLAY:
        probe = probe_motion_document(
            html,
            doc_format=doc_format,
            box_width=box_width,
            box_height=box_height,
            ffmpeg_path=ffmpeg_path,
            loop=True,
        )
        period_seconds = probe.animation_total_ms / 1000.0 if probe.ok else 0.0
        period_frames = (
            math.ceil(period_seconds * effective_fps)
            if period_seconds > 0.001
            else 0
        )
        if 0 < period_frames <= _MAX_FRAMES_PER_OVERLAY:
            period_mode = True
            frame_count = period_frames
    if not period_mode and frame_count > _MAX_FRAMES_PER_OVERLAY:
        frame_count = _MAX_FRAMES_PER_OVERLAY
        effective_fps = max(_MIN_EFFECTIVE_FPS, frame_count / duration)
    # The viewport-safety override exists for legacy html_css templates
    # whose free-form styling predates the truth gates: its wildcard
    # [class*=text] !important font rules would stomp the precise
    # two-axis clamps of html_js blueprint documents (posters render
    # without it, so the final cut would silently diverge from every
    # preview). Seek-driven documents are already guarded by the
    # design-time and render-time probe gates and skip the injection.
    if viewport_inset > 0 and doc_format != "html_js":
        inset_percent = min(12.0, max(0.0, viewport_inset * 100.0))
        safety_css = (
            "<style data-qwenpaw-viewport-safety>"
            f"html{{padding:{inset_percent:.3f}%!important;"
            "box-sizing:border-box!important;overflow:hidden!important}"
            "body{width:100%!important;height:100%!important;box-sizing:border-box!important;"
            "overflow:visible!important;transform:scale(.9)!important;"
            "transform-origin:center!important}"
            "p,[class*=text],[class*=title],[class*=caption]{"
            "max-width:100%!important;font-size:min(18vh,20vw)!important;line-height:1.15!important;"
            "white-space:normal!important;overflow-wrap:anywhere!important;"
            "word-break:break-word!important;"
            "letter-spacing:.02em!important;-webkit-text-stroke:0!important;"
            "text-shadow:1px 1px 0 rgba(0,0,0,.22)!important}"
            "[data-motion-motif=caption_card] [class*=text]{"
            "font-size:min(25vh,30vw)!important;line-height:1.08!important;"
            "max-height:100%!important}"
            "[data-motion-motif=paw_trail] .p4,"
            "[data-motion-motif=paw_trail] .p5{display:none!important}"
            "[data-motion-motif=paw_trail] .toe{width:20%!important;height:20%!important}"
            "[data-motion-motif=paw_trail] .t1{left:2%!important;top:28%!important}"
            "[data-motion-motif=paw_trail] .t2{left:27%!important;top:7%!important}"
            "[data-motion-motif=paw_trail] .t3{left:auto!important;"
            "right:27%!important;top:3%!important}"
            "[data-motion-motif=paw_trail] .t4{left:auto!important;"
            "right:2%!important;top:24%!important}"
            "[data-motion-motif=paw_trail] .p1,[data-motion-motif=paw_trail] .p2,"
            "[data-motion-motif=paw_trail] .p3{opacity:0;animation:qwenpaw-paw-appear .36s "
            "cubic-bezier(.2,.85,.2,1) forwards!important}"
            "[data-motion-motif=paw_trail] .p1{animation-delay:.08s!important}"
            "[data-motion-motif=paw_trail] .p2{animation-delay:.38s!important}"
            "[data-motion-motif=paw_trail] .p3{animation-delay:.68s!important}"
            "[data-motion-motif=alert_mark] .bar{top:29%!important;height:29%!important}"
            "[data-motion-motif=alert_mark] .dot{left:45%!important;"
            "top:62%!important;width:10%!important}"
            "@keyframes qwenpaw-paw-appear{0%{opacity:0}100%{opacity:1}}"
            "</style>"
        )
        html = (
            re.sub(
                r"</head>",
                lambda _match: f"{safety_css}</head>",
                html,
                count=1,
                flags=re.IGNORECASE,
            )
            if re.search(r"</head>", html, re.IGNORECASE)
            else safety_css + html
        )
    frame_identity = frame_cache_identity(
        html=html,
        box_width=box_width,
        box_height=box_height,
        frame_count=frame_count,
        effective_fps=effective_fps,
        loop=loop,
        doc_format=doc_format,
        engine_salt=engine_salt,
        period_mode=period_mode,
    )
    cache_key = hashlib.sha256(
        (frame_identity + ("|full_canvas" if full_canvas else "")).encode(
            "utf-8",
        ),
    ).hexdigest()
    # v2: seek exit progress switched to the real playhead; html_css
    # identities carry no engine salt, so the namespace bump is what
    # invalidates their pre-fix cached frames.
    cache_root = Path(tempfile.gettempdir()) / "qwenpaw-motion-frame-cache-v2"
    cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    frames_dir = cache_root / cache_key
    # Period sequences carry no baked exit, so the composite needs the
    # document's declared exit style even on a warm frame cache.
    managed_exit = (
        bool(
            re.search(
                r"""data-motion-exit\s*=\s*["'](?:soft_fade|shrink)["']""",
                html,
                re.IGNORECASE,
            ),
        )
        if period_mode
        else False
    )
    if not _complete_frame_cache(frames_dir, frame_count):
        staged_dir = Path(
            tempfile.mkdtemp(prefix=f"{cache_key[:12]}-", dir=cache_root),
        )
        error, captured_exit = _capture_frames(
            html=html,
            frames_dir=staged_dir,
            box_width=box_width,
            box_height=box_height,
            frame_count=frame_count,
            effective_fps=effective_fps,
            loop=loop,
            engine_fields=engine_fields,
            bake_exit=not period_mode,
        )
        if period_mode and error is None:
            managed_exit = captured_exit
        if error is None:
            # Truth gate before cache admission: rejected frames are
            # discarded so neither the cache nor the composite sees them;
            # the caller records the reason and falls back.
            error = _verify_captured_frames(
                staged_dir,
                frame_count=frame_count,
                box_width=box_width,
                box_height=box_height,
                ffmpeg_path=ffmpeg_path,
                full_canvas=full_canvas,
            )
        if error is not None:
            shutil.rmtree(staged_dir, ignore_errors=True)
            return OverlayRenderResult(False, error)
        if not _complete_frame_cache(frames_dir, frame_count):
            shutil.rmtree(frames_dir, ignore_errors=True)
            try:
                staged_dir.replace(frames_dir)
            except OSError:
                # A concurrent renderer may have populated the same key.
                shutil.rmtree(staged_dir, ignore_errors=True)
        else:
            shutil.rmtree(staged_dir, ignore_errors=True)
        _prune_frame_cache(cache_root)
    try:
        alpha_filter = (
            f"format=rgba,colorchannelmixer=aa={opacity:.6f},"
            if opacity < 1.0
            else "format=rgba,"
        )
        end_at = appear_at + duration
        # Period mode: the one-period sequence is repeated by ffmpeg just
        # enough times to cover the window (an unbounded -stream_loop -1
        # never reaches EOF and stalls the encode), and a renderer-managed
        # exit becomes an alpha fade over the last 15% (shrink degrades to
        # the same fade here).
        exit_filter = (
            (
                f"fade=t=out:st={0.85 * duration:.6f}:"
                f"d={0.15 * duration:.6f}:alpha=1,"
            )
            if period_mode and managed_exit
            else ""
        )
        loop_args: list[str] = []
        if period_mode:
            extra_loops = max(
                0,
                math.ceil(duration * effective_fps / frame_count) - 1,
            )
            loop_args = ["-stream_loop", str(extra_loops)]
        command = [
            ffmpeg_path,
            "-y",
            "-i",
            os.fspath(input_path),
            *loop_args,
            "-framerate",
            f"{effective_fps:.6f}",
            "-i",
            os.fspath(frames_dir / "%05d.png"),
            "-filter_complex",
            (
                f"[1:v]{alpha_filter}{exit_filter}"
                f"setpts=PTS-STARTPTS+{appear_at:.6f}/TB[motion];"
                f"[0:v][motion]overlay={left}:{top}:"
                f"enable='between(t,{appear_at:.6f},{end_at:.6f})',"
                "scale=trunc(iw/2)*2:trunc(ih/2)*2"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            os.fspath(output_path),
        ]
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=_FFMPEG_TIMEOUT_SECONDS,
                check=False,
            )
        except Exception as exc:
            return OverlayRenderResult(False, str(exc))
        if result.returncode != 0 or not output_path.exists():
            return OverlayRenderResult(False, (result.stderr or "")[-300:])
        return OverlayRenderResult(True)
    finally:
        # Frames are content-addressed and reused across preview/export runs.
        # The cache is bounded by _FRAME_CACHE_MAX_ITEMS above.
        pass


__all__ = [
    "caption_layout_error",
    "MotionDocumentProbe",
    "frame_cache_identity",
    "frame_timestamp_ms",
    "probe_motion_document",
    "render_motion_overlay",
    "render_motion_poster",
]
