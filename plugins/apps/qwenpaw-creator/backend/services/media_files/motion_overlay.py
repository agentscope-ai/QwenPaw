# -*- coding: utf-8 -*-
# flake8: noqa: E501
# pylint: disable=too-many-return-statements,consider-using-with,line-too-long
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

from services.media_files.overlay import OverlayRenderResult
from utils.logger import setup_logger

logger = setup_logger("services.media_files.motion_overlay")

_MAX_FRAMES_PER_OVERLAY = 240
_MIN_EFFECTIVE_FPS = 6
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
  return { count: animations.length, totalMs };
}
'''

SEEK = '''
(payload) => {
  const milliseconds = typeof payload === 'number'
    ? payload : Number(payload.milliseconds || 0);
  const outputMs = typeof payload === 'number'
    ? 0 : Number(payload.outputMs || 0);
  for (const animation of document.getAnimations({ subtree: true })) {
    try { animation.currentTime = milliseconds; } catch (error) {}
  }
  const stage = document.querySelector('[data-motion-exit]');
  const exitStyle = stage ? stage.getAttribute('data-motion-exit') : 'none';
  const progress = outputMs > 0 ? milliseconds / outputMs : 0;
  const exitProgress = Math.max(0, Math.min(1, (progress - 0.85) / 0.15));
  document.documentElement.style.opacity =
    exitStyle === 'none' ? '1' : String(1 - exitProgress);
  document.body.style.transformOrigin = 'center';
  document.body.style.transform = exitStyle === 'shrink'
    ? `scale(${1 - exitProgress * 0.18})` : 'none';
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

                doc_uri = doc_path.as_uri()

                def gate(route):
                    # Only the generated document itself may come from the
                    # local filesystem. Generated HTML must not probe other
                    # file: URLs or reach the network.
                    if route.request.url == doc_uri:
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
                if job["mode"] == "probe" and count > 0 and job.get("frames_dir"):
                    # Sample the whole animation envelope. Two midpoints miss
                    # entrance overshoot, late rotation and end-frame clipping.
                    for index, fraction in enumerate(
                        (0.05, 0.15, 0.3, 0.5, 0.7, 0.9, 1.0)
                    ):
                        page.evaluate(
                            SEEK,
                            {
                                "milliseconds": (
                                    total_ms * fraction
                                    if total_ms > 1.0
                                    else 0.0
                                ),
                                "outputMs": total_ms,
                            },
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
                    for index in range(int(job["frame_count"])):
                        timestamp_ms = index * 1000.0 / fps
                        if loop and total_ms > 1.0:
                            timestamp_ms = timestamp_ms % total_ms
                        elif total_ms > 1.0:
                            timestamp_ms = min(timestamp_ms, total_ms)
                        page.evaluate(
                            SEEK,
                            {
                                "milliseconds": timestamp_ms,
                                "outputMs": (
                                    int(job["frame_count"]) * 1000.0 / fps
                                ),
                            },
                        )
                        page.screenshot(
                            path="%s/%05d.png" % (frames_dir, index),
                            omit_background=True,
                            timeout=15000,
                        )
            finally:
                browser.close()
    print(json.dumps({"count": count, "totalMs": total_ms}))


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


def _frames_visible_stats(
    frames_dir: Path,
    ffmpeg_path: str,
    width: int,
    height: int,
) -> tuple[float, float]:
    """Return the largest (coverage, edge contact) across the probe frames.

    The alpha plane is extracted with ffmpeg so no imaging library is
    required; when the inspection itself fails ``(-1.0, -1.0)`` is returned
    so the document is given the benefit of the doubt instead of being
    rejected.
    """

    frames = sorted(frames_dir.glob("*.png"))
    if not frames:
        return -1.0, -1.0
    coverage = 0.0
    edge_contact = 0.0
    for frame in frames:
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
            return -1.0, -1.0
        frame_coverage, frame_edge = _alpha_plane_stats(
            result.stdout,
            width,
            height,
        )
        if frame_coverage < 0.0:
            visible = sum(1 for byte in result.stdout if byte > 16)
            frame_coverage = visible / len(result.stdout)
            frame_edge = -1.0
        coverage = max(coverage, frame_coverage)
        edge_contact = max(edge_contact, frame_edge)
    return coverage, edge_contact


def probe_motion_document(
    html: str,
    *,
    box_width: int = 640,
    box_height: int = 360,
    ffmpeg_path: str | None = None,
) -> MotionDocumentProbe:
    """Load a motion document once and report its animation facts."""

    cache_key = (
        hashlib.sha256(html.encode("utf-8")).hexdigest(),
        int(box_width),
        int(box_height),
        str(ffmpeg_path or ""),
    )
    with _probe_cache_lock:
        cached = _probe_cache.get(cache_key)
        if cached is not None:
            _probe_cache.move_to_end(cache_key)
            return cached

    with tempfile.TemporaryDirectory(prefix="motion-probe-") as probe_dir:
        result = _run_capture_worker(
            {
                "mode": "probe",
                "html": html,
                "box_width": int(box_width),
                "box_height": int(box_height),
                "frames_dir": probe_dir,
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
        if count <= 0:
            return MotionDocumentProbe(
                False,
                "动效文档没有任何 CSS 动画，无法产生运动",
                animation_count=0,
            )
        coverage, edge_contact = (
            _frames_visible_stats(
                Path(probe_dir),
                ffmpeg_path,
                int(box_width),
                int(box_height),
            )
            if ffmpeg_path
            else (-1.0, -1.0)
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
        probe = MotionDocumentProbe(
            True,
            animation_count=count,
            animation_total_ms=total_ms,
            visible_coverage=coverage,
            edge_contact=edge_contact,
        )
        with _probe_cache_lock:
            _probe_cache[cache_key] = probe
            _probe_cache.move_to_end(cache_key)
            while len(_probe_cache) > _PROBE_CACHE_MAX_ITEMS:
                _probe_cache.popitem(last=False)
        return probe


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
) -> str | None:
    """Seek-and-capture one transparent PNG per output frame."""

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
        },
        timeout_seconds=timeout_seconds,
    )
    if result.get("error"):
        return f"动效帧渲染失败: {result['error']}"
    if int(result.get("count") or 0) <= 0:
        return "动效文档没有任何 CSS 动画"
    missing = [
        index
        for index in range(frame_count)
        if not (frames_dir / f"{index:05d}.png").is_file()
    ]
    if missing:
        return f"动效帧渲染不完整，缺少 {len(missing)} 帧"
    return None


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
) -> OverlayRenderResult:
    """Render one motion document and composite it over a prepared segment."""

    if duration <= 0 or not math.isfinite(duration):
        return OverlayRenderResult(False, "动效持续时间必须为正数")
    box_width, box_height, left, top, opacity = _normalized_box(
        location,
        video_size,
    )
    effective_fps = float(min(max(int(fps), _MIN_EFFECTIVE_FPS), 60))
    frame_count = math.ceil(duration * effective_fps)
    if frame_count > _MAX_FRAMES_PER_OVERLAY:
        frame_count = _MAX_FRAMES_PER_OVERLAY
        effective_fps = max(_MIN_EFFECTIVE_FPS, frame_count / duration)
    if viewport_inset > 0:
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
    frame_identity = json.dumps(
        {
            "html": hashlib.sha256(html.encode("utf-8")).hexdigest(),
            "box": [box_width, box_height],
            "frames": frame_count,
            "fps": round(effective_fps, 6),
            "loop": loop,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    cache_key = hashlib.sha256(frame_identity.encode("utf-8")).hexdigest()
    cache_root = Path(tempfile.gettempdir()) / "qwenpaw-motion-frame-cache-v1"
    cache_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    frames_dir = cache_root / cache_key
    if not _complete_frame_cache(frames_dir, frame_count):
        staged_dir = Path(
            tempfile.mkdtemp(prefix=f"{cache_key[:12]}-", dir=cache_root),
        )
        error = _capture_frames(
            html=html,
            frames_dir=staged_dir,
            box_width=box_width,
            box_height=box_height,
            frame_count=frame_count,
            effective_fps=effective_fps,
            loop=loop,
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
        command = [
            ffmpeg_path,
            "-y",
            "-i",
            os.fspath(input_path),
            "-framerate",
            f"{effective_fps:.6f}",
            "-i",
            os.fspath(frames_dir / "%05d.png"),
            "-filter_complex",
            (
                f"[1:v]{alpha_filter}"
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
    "MotionDocumentProbe",
    "probe_motion_document",
    "render_motion_overlay",
]
