# -*- coding: utf-8 -*-
# pylint: disable=too-many-return-statements,too-many-branches
"""Grok Imagine video generation tool.

Wraps xAI's video-generation surface (``POST /v1/videos/generations`` to
submit, ``GET /v1/videos/{request_id}`` to poll).  Generation is async
on the xAI side, but this tool blocks until the video is ready (or the
poll timeout fires) so the agent gets back a final URL/path in a single
call.

Single tool with optional ``image_url``: when present, switches to
image-to-video mode (Grok animates the supplied image); otherwise pure
text-to-video.  The xAI endpoint accepts both shapes on the same path.

Credential resolution mirrors the grok-image plugin: plugin config →
xAI OAuth (~/.xai/auth.json) → ``XAI_API_KEY`` env var.
"""

import asyncio
import logging
import os
import time
from typing import Optional

import httpx
from agentscope.message import TextBlock, VideoBlock
from agentscope.tool import ToolResponse

from qwenpaw.constant import DEFAULT_MEDIA_DIR

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "grok-imagine-video"
DEFAULT_BASE = "https://api.x.ai/v1"
DEFAULT_DURATION_S = 5
DEFAULT_POLL_INTERVAL_S = 5.0
# Empirical: xAI's grok-imagine-video tier routinely takes 4–8 minutes
# end-to-end (queue + gen).  Sized to clear that with margin while still
# bounded so a stuck job doesn't hang the agent forever.
DEFAULT_POLL_TIMEOUT_S = 600.0
DEFAULT_HTTP_TIMEOUT_S = 60.0

# Valid xAI-side enums — keep these in sync with the docs (last
# checked: 2026-05).  The agent gets a Pythonic enum so it doesn't
# emit invalid combinations like "16x9".
_VALID_ASPECT = {"16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3"}
_VALID_RESOLUTION = {"480p", "540p", "720p", "1080p"}


async def generate_video_grok(
    prompt: str,
    duration: Optional[int] = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    image_url: Optional[str] = None,
) -> ToolResponse:
    """Generate a short video with xAI Grok Imagine.

    Args:
        prompt (str):
            What the video should show.  Describe action, subject,
            camera movement, and style — Aurora handles cinematic
            cues well.
        duration (int, optional):
            Clip length in seconds (1-15).  Falls back to the plugin's
            configured default (5s) if omitted.
        aspect_ratio (str, optional):
            One of "16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3".
            Defaults to "16:9".
        resolution (str, optional):
            One of "480p", "540p", "720p", "1080p".  Defaults to "720p".
            Higher resolutions cost more and may require a Premium+
            xAI subscription.
        image_url (str, optional):
            HTTPS URL of a reference image.  When provided, switches to
            image-to-video mode and animates the supplied image.

    Returns:
        ToolResponse: Contains the generated video as a local file path
        (downloaded from xAI's CDN) plus a brief text description.
        Errors are returned as text-only ToolResponses with the failure
        reason — the tool never raises.
    """
    try:
        cfg = _get_tool_config() or {}

        if aspect_ratio not in _VALID_ASPECT:
            return _text_error(
                f"Invalid aspect_ratio '{aspect_ratio}'. "
                f"Must be one of: {', '.join(sorted(_VALID_ASPECT))}",
            )
        if resolution not in _VALID_RESOLUTION:
            return _text_error(
                f"Invalid resolution '{resolution}'. "
                f"Must be one of: {', '.join(sorted(_VALID_RESOLUTION))}",
            )

        effective_duration = duration
        if effective_duration is None:
            cfg_dur = cfg.get("default_duration")
            effective_duration = (
                int(cfg_dur)
                if isinstance(cfg_dur, (int, float)) and cfg_dur > 0
                else DEFAULT_DURATION_S
            )
        if not 1 <= effective_duration <= 15:
            return _text_error(
                f"duration must be 1-15 seconds (got {effective_duration})",
            )

        model = (cfg.get("model") or DEFAULT_MODEL).strip()
        base_url = (cfg.get("base_url") or DEFAULT_BASE).strip().rstrip("/")
        poll_timeout = float(
            cfg.get("poll_timeout") or DEFAULT_POLL_TIMEOUT_S,
        )

        bearer, source = await _resolve_bearer(cfg)
        if not bearer:
            return _text_error(
                "No xAI credentials available. Run `qwenpaw xai login` "
                "or set XAI_API_KEY in your environment, or paste a key "
                "into the plugin config.",
            )

        modality = "image" if image_url else "text"
        logger.info(
            "[grok-video] model=%s ratio=%s res=%s dur=%ds "
            "modality=%s creds=%s",
            model,
            aspect_ratio,
            resolution,
            effective_duration,
            modality,
            source,
        )

        payload = {
            "model": model,
            "prompt": prompt,
            "duration": effective_duration,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }
        if image_url:
            payload["image"] = {"url": image_url}

        async with httpx.AsyncClient(timeout=DEFAULT_HTTP_TIMEOUT_S) as client:
            submit_resp = await client.post(
                f"{base_url}/videos/generations",
                headers={
                    "Authorization": f"Bearer {bearer}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if submit_resp.status_code != 200:
                return _text_error(_format_http_error(submit_resp))
            submit_body = submit_resp.json()
            request_id = submit_body.get("request_id") or submit_body.get(
                "id",
            )
            if not request_id:
                return _text_error(
                    f"xAI accepted the job but returned no request_id: "
                    f"{submit_body!r}",
                )

            video_url = await _poll_for_video(
                client=client,
                base_url=base_url,
                bearer=bearer,
                request_id=request_id,
                timeout_s=poll_timeout,
            )

        if not video_url:
            return _text_error(
                f"Video job {request_id} did not finish within "
                f"{poll_timeout:.0f}s.",
            )

        local_path = await _download_video(video_url)

        return ToolResponse(
            content=[
                VideoBlock(
                    type="video",
                    source={"type": "url", "url": str(local_path)},
                ),
                TextBlock(
                    type="text",
                    text=(
                        f"Generated video with {model} "
                        f"(ratio={aspect_ratio}, res={resolution}, "
                        f"dur={effective_duration}s, modality={modality}, "
                        f"creds={source})\n"
                        f"Prompt: {prompt}\n"
                        f"Saved to: {local_path}"
                    ),
                ),
            ],
        )

    except httpx.TimeoutException:
        return _text_error("Video request timed out at the HTTP layer.")
    except Exception as e:
        logger.error("[grok-video] failed: %s", e, exc_info=True)
        return _text_error(f"Video generation failed: {e}")


async def _poll_for_video(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    bearer: str,
    request_id: str,
    timeout_s: float,
    interval_s: float = DEFAULT_POLL_INTERVAL_S,
) -> Optional[str]:
    """Poll the xAI job-status endpoint until the video URL appears.

    Returns the URL on success, ``None`` if the timeout fires before
    the job reaches a terminal state.  Raises on unexpected errors so
    the caller can surface them.
    """
    deadline = time.monotonic() + timeout_s
    headers = {"Authorization": f"Bearer {bearer}"}
    while time.monotonic() < deadline:
        await asyncio.sleep(interval_s)
        resp = await client.get(
            f"{base_url}/videos/{request_id}",
            headers=headers,
        )
        if resp.status_code != 200:
            # 404 here is common right after submission — the job hasn't
            # propagated to the read replica yet — so log and keep polling.
            logger.debug(
                "[grok-video] poll %s → HTTP %d: %s",
                request_id,
                resp.status_code,
                resp.text[:120],
            )
            continue
        body = resp.json()
        status = (body.get("status") or "").lower()
        # xAI uses ``"done"`` (observed against grok-imagine-video).  The
        # other strings here are defensive — different model families on
        # the same surface may use slightly different vocabularies and
        # the docs don't pin one down.
        if status in ("done", "completed", "succeeded", "finished"):
            # xAI surfaces the asset under data[0].url; tolerate either
            # the wrapped or flat shape since the API has flipped between
            # them across versions.
            data = body.get("data")
            if isinstance(data, list) and data:
                row = data[0]
                if isinstance(row, dict) and row.get("url"):
                    return row["url"]
            if body.get("video", {}).get("url"):
                return body["video"]["url"]
            if body.get("url"):
                return body["url"]
            raise RuntimeError(
                f"Job {request_id} completed but no video URL in: {body!r}",
            )
        if status in ("failed", "error", "cancelled"):
            raise RuntimeError(
                f"xAI job {request_id} terminated with status={status}: "
                f"{body.get('error') or body}",
            )
    return None


async def _download_video(url: str) -> str:
    media_dir = DEFAULT_MEDIA_DIR / "grok_video"
    media_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time() * 1000)
    # xAI URLs end in .mp4 most of the time; if not, default to mp4 —
    # the container is always H.264/AAC right now.
    ext = ".mp4"
    for candidate in (".mp4", ".mov", ".webm"):
        if candidate in url.lower():
            ext = candidate
            break
    path = media_dir / f"grok_video_{timestamp}{ext}"
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with path.open("wb") as f:
                async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                    f.write(chunk)
    return str(path)


def _text_error(msg: str) -> ToolResponse:
    return ToolResponse(
        content=[TextBlock(type="text", text=f"Error: {msg}")],
    )


def _format_http_error(resp: httpx.Response) -> str:
    msg = f"xAI API error: HTTP {resp.status_code}"
    try:
        body = resp.json()
        if isinstance(body, dict):
            inner = body.get("error")
            if isinstance(inner, dict):
                msg += f" — {inner.get('message')}"
            elif isinstance(inner, str):
                msg += f" — {inner}"
            elif body.get("message"):
                msg += f" — {body['message']}"
    except Exception:
        snippet = resp.text[:200].strip()
        if snippet:
            msg += f" — {snippet}"
    if resp.status_code == 403:
        msg += (
            "  (403 typically means your xAI account lacks an active "
            "Premium+ or SuperGrok subscription required for video "
            "generation.)"
        )
    return msg


async def _resolve_bearer(cfg: dict) -> tuple[Optional[str], str]:
    user_key = (cfg.get("api_key") or "").strip()
    if user_key:
        return user_key, "plugin-config"
    try:
        from qwenpaw.providers.xai_auth import XaiAuth

        auth = XaiAuth()
        creds = await auth.ensure_fresh()
        return creds.access_token, "oauth"
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.debug("[grok-video] XaiAuth unavailable: %s", e)
    env_key = (os.environ.get("XAI_API_KEY") or "").strip()
    if env_key:
        return env_key, "env"
    return None, "none"


def _get_tool_config() -> Optional[dict]:
    try:
        from qwenpaw.app.agent_context import get_current_agent_id
        from qwenpaw.plugins.registry import PluginRegistry

        registry = PluginRegistry()
        if not registry:
            return None
        agent_id = get_current_agent_id()
        if not agent_id:
            return None
        return registry.get_tool_config("generate_video_grok", agent_id)
    except Exception as e:
        logger.debug("[grok-video] _get_tool_config: %s", e)
        return None
