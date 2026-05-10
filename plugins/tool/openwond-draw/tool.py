# -*- coding: utf-8 -*-
"""OpenWond image generation tool for QwenPaw agents.

Generate images via OpenWond relay service. Supports GPT Image 2
as the primary model and Nano Banana series as fallback.

Timeout: 900s default — GPT Image 2 is slow but delivers high quality.
"""

import json
import logging
import os
import time

import httpx
from agentscope.message import ImageBlock, TextBlock
from agentscope.tool import ToolResponse
from qwenpaw.constant import DEFAULT_MEDIA_DIR

logger = logging.getLogger(__name__)

_AVAILABLE_MODELS = {
    "gpt-image2": {
        "description": "GPT Image 2 (4 credits, primary)",
        "priority": 1,
    },
    "nano-banana-v2": {
        "description": "Nano Banana V2 (4 credits, fallback)",
        "priority": 2,
    },
    "nano-banana-pro": {
        "description": "Nano Banana Pro (6 credits, premium fallback)",
        "priority": 3,
    },
}

_DEFAULT_TIMEOUT = 900  # proven stable in practice
_MAX_TIMEOUT = 900


def _get_tool_config() -> dict | None:
    """Retrieve tool configuration from plugin settings."""
    try:
        from qwenpaw.app.agent_context import get_current_agent_id
        from qwenpaw.config.config import load_agent_config

        agent_id = get_current_agent_id()
        if not agent_id:
            return None

        agent_config = load_agent_config(agent_id)
        if not agent_config or not agent_config.tools:
            return None

        tool_configs = (
            agent_config.tools.plugin_tools or []
        )
        for cfg in tool_configs:
            if getattr(cfg, "name", "") == "openwond-draw-tool":
                return getattr(cfg, "config", {}) or {}
    except Exception as e:
        logger.debug(f"Failed to load tool config: {e}")
    return None


async def generate_image_openwond(
    prompt: str,
    model: str = "gpt-image2",
    resolution: str = "2K",
    timeout: int = _DEFAULT_TIMEOUT,
) -> ToolResponse:
    """Generate an image using OpenWond relay service.

    Supports GPT Image 2 (primary) and Nano Banana series as fallback.
    The OpenWond relay handles model inference; results are saved locally.

    Args:
        prompt:
            Text description of the image to generate. Be detailed for
            best results. Include style, palette, composition cues.
        model:
            Model to use. Options:
            - ``"gpt-image2"`` (default, 4 credits, highest quality)
            - ``"nano-banana-v2"`` (4 credits, fast fallback)
            - ``"nano-banana-pro"`` (6 credits, premium fallback)
        resolution:
            Output resolution. Options: ``"1K"``, ``"2K"`` (default),
            ``"4K"``. Higher resolutions consume more credits.
        timeout:
            Maximum wait time in seconds. GPT Image 2 is slow —
            900s recommended (default). Capped at 900s.

    Returns:
        ToolResponse:
            Contains the generated image and generation metadata.

    Example:
        >>> result = await generate_image_openwond(
        ...     prompt="Epic cinematic poster of a divine dragon",
        ...     model="gpt-image2",
        ...     resolution="2K",
        ... )
    """
    # ── Validate & clamp ──
    model = model.lower().replace(" ", "-")
    if model not in _AVAILABLE_MODELS:
        available = ", ".join(_AVAILABLE_MODELS)
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        f"Unknown model '{model}'. "
                        f"Available: {available}"
                    ),
                ),
            ],
        )

    timeout = min(max(timeout, 60), _MAX_TIMEOUT)

    # ── Load config ──
    config = _get_tool_config()
    api_key = (
        config.get("api_key")
        if config
        else os.environ.get("OPENWOND_API_KEY", "")
    )
    endpoint = (
        config.get("endpoint")
        if config
        else os.environ.get(
            "OPENWOND_ENDPOINT",
            "https://image.openwond.com/v1/draw",
        )
    )

    if not api_key:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "Error: OpenWond API key not configured.\n"
                        "Set it in Agent Settings → Tools or via "
                        "OPENWOND_API_KEY env var."
                    ),
                ),
            ],
        )

    # ── Build request ──
    payload = {
        "model": model,
        "prompt": prompt,
        "resolution": resolution,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    logger.info(
        f"🎨 [OpenWond] Generating with {model} @ {resolution} "
        f"(timeout={timeout}s)...",
    )

    start = time.time()

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout)) as client:
            resp = await client.post(
                endpoint,
                json=payload,
                headers=headers,
            )

        elapsed = time.time() - start
        logger.info(
            f"✅ [OpenWond] Response in {elapsed:.1f}s "
            f"(status={resp.status_code})",
        )

        if resp.status_code != 200:
            try:
                err = resp.json()
                detail = err.get("detail", err.get("error", resp.text))
            except Exception:
                detail = resp.text[:300]
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"Error {resp.status_code}: {detail}"
                        ),
                    ),
                ],
            )

        result = resp.json()

        # ── Extract image URL — try multiple response formats ──
        image_url = (
            result.get("data", {}).get("url")
            or result.get("url")
            or result.get("image_url")
            or result.get("data", "")
        )
        if not image_url:
            return ToolResponse(
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            "Error: No image URL in response. "
                            f"Raw: {json.dumps(result, ensure_ascii=False)[:500]}"
                        ),
                    ),
                ],
            )

        # ── Download and save locally ──
        media_dir = DEFAULT_MEDIA_DIR or os.path.join(
            os.getcwd(),
            "media",
        )
        os.makedirs(media_dir, exist_ok=True)

        timestamp = int(time.time())
        safe_name = "".join(
            c for c in prompt[:30] if c.isalnum() or c in " _-"
        ).strip().replace(" ", "_") or "openwond"
        filename = f"openwond_{safe_name}_{timestamp}.jpeg"
        filepath = os.path.join(media_dir, filename)

        async with httpx.AsyncClient(timeout=60) as dl_client:
            dl_resp = await dl_client.get(image_url)
            dl_resp.raise_for_status()
            with open(filepath, "wb") as f:
                f.write(dl_resp.content)

        size_kb = os.path.getsize(filepath) / 1024
        logger.info(
            f"💾 Saved to {filepath} ({size_kb:.0f}KB)",
        )

        return ToolResponse(
            content=[
                ImageBlock(
                    type="image",
                    source={
                        "type": "url",
                        "url": f"file://{os.path.abspath(filepath)}",
                    },
                ),
                TextBlock(
                    type="text",
                    text=(
                        f"Generated image using {model}\n"
                        f"Prompt: {prompt}\n"
                        f"Resolution: {resolution}\n"
                        f"Time: {elapsed:.1f}s | Size: {size_kb:.0f}KB\n"
                        f"Saved to: {filepath}"
                    ),
                ),
            ],
        )

    except httpx.TimeoutException:
        logger.error(
            f"[OpenWond] Timeout after {timeout}s — "
            f"GPT Image 2 can be slow. Consider retrying with "
            f"a shorter prompt or using nano-banana-v2 fallback.",
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "⏱️ Image generation timed out after "
                        f"{timeout} seconds.\n\n"
                        "GPT Image 2 can be slow. Try:\n"
                        f"1. Retry with `model='nano-banana-v2'` "
                        f"(faster, 4 credits)\n"
                        "2. Shorten the prompt\n"
                        "3. Increase timeout if your config allows"
                    ),
                ),
            ],
        )

    except Exception as e:
        logger.error(
            f"[OpenWond] Generation failed: {e}",
            exc_info=True,
        )
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text=(
                        f"Error: Image generation failed - {str(e)}"
                    ),
                ),
            ],
        )
