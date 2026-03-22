# -*- coding: utf-8 -*-
"""Multimodal capability probing for models."""

import logging
import time
from dataclasses import dataclass

from openai import APIError, AsyncOpenAI

logger = logging.getLogger(__name__)

# 16x16 red PNG (82 bytes), used as minimal probe image.
# Some providers (e.g. DashScope) reject images smaller than 10x10,
# so we use 16x16 to avoid false negatives.
_PROBE_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAAGUlEQVR4"
    "nGP4z8DwnxLMMGrAqAGjBgwXAwAwxP4QHCfkAAAAAABJRU5ErkJggg=="
)

# HTTP URL for providers that accept external video
# URLs (e.g. Gemini file_data).
# Moonshot and similar providers require base64 data
# URLs instead.
_PROBE_VIDEO_URL = (
    "https://help-static-aliyun-doc.aliyuncs.com"
    "/file-manage-files/zh-CN/20241115/cqqkru/1.mp4"
)

# 64x64 solid-blue H.264 MP4 (10 frames @ 10fps,
# ~1.8 KB), used for video probe.
# Generated with OpenCV; 64x64 avoids ffmpeg
# transcoding failures on providers
# (e.g. Moonshot) that reject very small resolutions
# like 16x16.
# Some providers only accept base64 data URLs for
# video, not external HTTP URLs,
# so we embed the video directly.
_PROBE_VIDEO_B64 = (
    "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAAIZnJlZQAAA2Vt"
    "ZGF0AAACrgYF//+q3EXpvebZSLeWLNgg2SPu73gyNjQgLSBjb3JlIDE2NCBy"
    "MzEwOCAzMWUxOWY5IC0gSC4yNjQvTVBFRy00IEFWQyBjb2RlYyAtIENvcHls"
    "ZWZ0IDIwMDMtMjAyMyAtIGh0dHA6Ly93d3cudmlkZW9sYW4ub3JnL3gyNjQu"
    "aHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEgcmVmPTMgZGVibG9jaz0xOjA6MCBh"
    "bmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBwc3lfcmQ9"
    "MS4wMDowLjAwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0x"
    "IHRyZWxsaXM9MSA4eDhkY3Q9MSBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0"
    "X3Bza2lwPTEgY2hyb21hX3FwX29mZnNldD0tMiB0aHJlYWRzPTIgbG9va2Fo"
    "ZWFkX3RocmVhZHM9MSBzbGljZWRfdGhyZWFkcz0wIG5yPTAgZGVjaW1hdGU9"
    "MSBpbnRlcmxhY2VkPTAgYmx1cmF5X2NvbXBhdD0wIGNvbnN0cmFpbmVkX2lu"
    "dHJhPTAgYmZyYW1lcz0zIGJfcHlyYW1pZD0yIGJfYWRhcHQ9MSBiX2JpYXM9"
    "MCBkaXJlY3Q9MSB3ZWlnaHRiPTEgb3Blbl9nb3A9MCB3ZWlnaHRwPTIga2V5"
    "aW50PTI1MCBrZXlpbnRfbWluPTEwIHNjZW5lY3V0PTQwIGludHJhX3JlZnJl"
    "c2g9MCByY19sb29rYWhlYWQ9NDAgcmM9Y3JmIG1idHJlZT0xIGNyZj0yMy4w"
    "IHFjb21wPTAuNjAgcXBtaW49MCBxcG1heD02OSBxcHN0ZXA9NCBpcF9yYXRp"
    "bz0xLjQwIGFxPTE6MS4wMACAAAAAJ2WIhAAR//7n4/wKbYEB8Tpk2PtANbXc"
    "qLo1x7YozakvH3bhD2xGfwAAAApBmiRsQQ/+qlfeAAAACEGeQniHfwW9AAAA"
    "CAGeYXRDfwd8AAAACAGeY2pDfwd9AAAAEEGaaEmoQWiZTAh3//6pnTUAAAAK"
    "QZ6GRREsO/8FvQAAAAgBnqV0Q38HfQAAAAgBnqdqQ38HfAAAABBBmqlJqEFs"
    "mUwIb//+p4+IAAADoG1vb3YAAABsbXZoZAAAAAAAAAAAAAAAAAAAA+gAAAPo"
    "AAEAAAEAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAA"
    "AAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIAAALLdHJhawAA"
    "AFx0a2hkAAAAAwAAAAAAAAAAAAAAAQAAAAAAAAPoAAAAAAAAAAAAAAAAAAAA"
    "AAABAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAQAAAAABAAAAAQAAA"
    "AAAAJGVkdHMAAAAcZWxzdAAAAAAAAAABAAAD6AAACAAAAQAAAAACQ21kaWEA"
    "AAAgbWRoZAAAAAAAAAAAAAAAAAAAKAAAACgAVcQAAAAAAC1oZGxyAAAAAAAA"
    "AAB2aWRlAAAAAAAAAAAAAAAAVmlkZW9IYW5kbGVyAAAAAe5taW5mAAAAFHZt"
    "aGQAAAABAAAAAAAAAAAAAAAkZGluZgAAABxkcmVmAAAAAAAAAAEAAAAMdXJs"
    "IAAAAAEAAAGuc3RibAAAAK5zdHNkAAAAAAAAAAEAAACeYXZjMQAAAAAAAAAB"
    "AAAAAAAAAAAAAAAAAAAAAABAAEAASAAAAEgAAAAAAAAAAQAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAABj//wAAADRhdmNDAWQACv/hABdnZAAK"
    "rNlEJoQAAAMABAAAAwBQPEiWWAEABmjr48siwP34+AAAAAAUYnRydAAAAAAA"
    "AE4gAAAa6AAAABhzdHRzAAAAAAAAAAEAAAAKAAAEAAAAABRzdHNzAAAAAAAA"
    "AAEAAAABAAAAYGN0dHMAAAAAAAAACgAAAAEAAAgAAAAAAQAAFAAAAAABAAAI"
    "AAAAAAEAAAAAAAAAAQAABAAAAAABAAAUAAAAAAEAAAgAAAAAAQAAAAAAAAAB"
    "AAAEAAAAAAEAAAgAAAAAHHN0c2MAAAAAAAAAAQAAAAEAAAAKAAAAAQAAADxz"
    "dHN6AAAAAAAAAAAAAAAKAAAC3QAAAA4AAAAMAAAADAAAAAwAAAAUAAAADgAA"
    "AAwAAAAMAAAAFAAAABRzdGNvAAAAAAAAAAEAAAAwAAAAYXVkdGEAAABZbWV0"
    "YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwAAAAAAAAAAAAAAAAsaWxz"
    "dAAAACSpdG9vAAAAHGRhdGEAAAABAAAAAExhdmY2MS43LjEwMA=="
)


@dataclass
class ProbeResult:
    """Result of multimodal capability probing."""

    supports_image: bool = False
    supports_video: bool = False
    image_message: str = ""
    video_message: str = ""

    @property
    def supports_multimodal(self) -> bool:
        return self.supports_image or self.supports_video


async def probe_image_support(
    base_url: str,
    api_key: str,
    model_id: str,
    timeout: float = 15,
) -> tuple[bool, str]:
    """Probe image support by sending a solid-red 16x16 PNG.

    Uses a two-stage check:
    1. If the API rejects the request
       (400 / media-keyword error) → not supported.
    2. If the API accepts, ask the model to name the colour.  A truly
       vision-capable model will answer "red"; a text-only model that
       silently ignores the image will not.
    """
    logger.info(
        "Image probe start: model=%s url=%s",
        model_id,
        base_url,
    )
    start_time = time.monotonic()
    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    try:
        # Use a generous max_tokens because "thinking" models (e.g. Kimi K2.5)
        # consume tokens for internal reasoning_content before producing the
        # visible answer in `content`.  With too few tokens the reasoning
        # exhausts the budget and `content` comes back empty.
        res = await client.chat.completions.create(
            model=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": (
                                    "data:image/png;base64,"
                                    f"{_PROBE_IMAGE_B64}"
                                ),
                            },
                        },
                        {
                            "type": "text",
                            "text": (
                                "What is the single dominant color of this "
                                "image? Reply with ONLY the color name, "
                                "nothing else."
                            ),
                        },
                    ],
                },
            ],
            max_tokens=200,
            timeout=timeout,
        )
        answer = (res.choices[0].message.content or "").lower().strip()
        # The probe image is solid red – accept common red-ish answers
        if any(kw in answer for kw in ("red", "红")):
            result = True, f"Image supported (answer={answer!r})"
            elapsed = time.monotonic() - start_time
            logger.info(
                "Image probe done: model=%s result=%s %.2fs",
                model_id,
                result[0],
                elapsed,
            )
            return result
        # Some thinking models put the real answer in reasoning_content
        # and leave content empty when token budget is tight.  Check
        # reasoning_content as a fallback.
        reasoning = ""
        msg = res.choices[0].message
        if hasattr(msg, "reasoning_content") and msg.reasoning_content:
            reasoning = msg.reasoning_content.lower()
        if reasoning and any(kw in reasoning for kw in ("red", "红")):
            result = (
                True,
                f"Image supported (via reasoning, answer={answer!r})",
            )
            elapsed = time.monotonic() - start_time
            logger.info(
                "Image probe done: model=%s result=%s %.2fs",
                model_id,
                result[0],
                elapsed,
            )
            return result
        result = False, f"Model did not recognise image (answer={answer!r})"
        elapsed = time.monotonic() - start_time
        logger.info(
            "Image probe done: model=%s result=%s %.2fs",
            model_id,
            result[0],
            elapsed,
        )
        return result
    except APIError as e:
        elapsed = time.monotonic() - start_time
        logger.warning(
            "Image probe error: model=%s type=%s msg=%s %.2fs",
            model_id,
            type(e).__name__,
            e,
            elapsed,
        )
        if e.status_code == 400 or _is_media_keyword_error(e):
            return False, f"Image not supported: {e}"
        return False, f"Probe inconclusive: {e}"
    except Exception as e:
        elapsed = time.monotonic() - start_time
        logger.warning(
            "Image probe error: model=%s type=%s msg=%s %.2fs",
            model_id,
            type(e).__name__,
            e,
            elapsed,
        )
        return False, f"Probe failed: {e}"


async def probe_video_support(
    base_url: str,
    api_key: str,
    model_id: str,
    timeout: float = 30,
) -> tuple[bool, str]:
    """Probe video support with automatic format fallback.

    Some providers (e.g. Moonshot) only accept base64 data URLs for
    video_url, while others (e.g. DashScope) only accept HTTP URLs.
    We try base64 first; if the provider rejects it with a 400 error
    we fall back to an HTTP URL.

    Uses semantic verification: asks the model to name the colour shown
    in the video.  A truly video-capable model will answer "blue"; a
    text-only model that silently ignores the video will not.
    """
    # Try base64 first, then HTTP URL as fallback
    logger.info(
        "Video probe start: model=%s url=%s",
        model_id,
        base_url,
    )
    start_time = time.monotonic()
    video_urls = [
        f"data:video/mp4;base64,{_PROBE_VIDEO_B64}",
        _PROBE_VIDEO_URL,
    ]
    last_error_msg = ""
    for video_url in video_urls:
        # HTTP URL fallback needs extra time for the provider to
        # download the video before processing it.
        req_timeout = timeout * 3 if video_url == _PROBE_VIDEO_URL else timeout
        client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=req_timeout,
        )
        try:
            res = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "video_url",
                                "video_url": {"url": video_url},
                            },
                            {
                                "type": "text",
                                "text": (
                                    "What is the single dominant color shown "
                                    "in this video? Reply with ONLY the color "
                                    "name, nothing else."
                                ),
                            },
                        ],
                    },
                ],
                max_tokens=200,
                timeout=req_timeout,
            )
            answer = (res.choices[0].message.content or "").lower().strip()
            # The probe video is solid blue
            if any(kw in answer for kw in ("blue", "蓝")):
                elapsed = time.monotonic() - start_time
                logger.info(
                    "Video probe done: model=%s result=True %.2fs",
                    model_id,
                    elapsed,
                )
                return True, f"Video supported (answer={answer!r})"
            # Fallback: check reasoning_content for thinking models
            reasoning = ""
            msg = res.choices[0].message
            if hasattr(msg, "reasoning_content") and msg.reasoning_content:
                reasoning = msg.reasoning_content.lower()
            if reasoning and any(kw in reasoning for kw in ("blue", "蓝")):
                elapsed = time.monotonic() - start_time
                logger.info(
                    "Video probe done: model=%s result=True %.2fs",
                    model_id,
                    elapsed,
                )
                return (
                    True,
                    f"Video supported (via reasoning, answer={answer!r})",
                )
            # Model accepted the request but didn't recognise the video.
            # For the HTTP URL fallback the video content differs (not
            # solid blue), so accept any non-trivial answer as evidence
            # that the model can process video.
            if video_url == _PROBE_VIDEO_URL and answer:
                elapsed = time.monotonic() - start_time
                logger.info(
                    "Video probe done: model=%s result=True %.2fs",
                    model_id,
                    elapsed,
                )
                return True, f"Video supported (answer={answer!r})"
            elapsed = time.monotonic() - start_time
            logger.info(
                "Video probe done: model=%s result=False %.2fs",
                model_id,
                elapsed,
            )
            return False, f"Model did not recognise video (answer={answer!r})"
        except APIError as e:
            status = getattr(e, "status_code", None)
            if status == 400:
                # Provider rejected this format; try next
                last_error_msg = str(e)
                logger.debug(
                    "Video probe format rejected (400), trying next: %s",
                    e,
                )
                continue
            if _is_media_keyword_error(e):
                elapsed = time.monotonic() - start_time
                logger.warning(
                    "Video probe error: model=%s type=%s msg=%s %.2fs",
                    model_id,
                    type(e).__name__,
                    e,
                    elapsed,
                )
                return False, f"Video not supported: {e}"
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Video probe error: model=%s type=%s msg=%s %.2fs",
                model_id,
                type(e).__name__,
                e,
                elapsed,
            )
            return False, f"Probe inconclusive: {e}"
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.warning(
                "Video probe error: model=%s type=%s msg=%s %.2fs",
                model_id,
                type(e).__name__,
                e,
                elapsed,
            )
            return False, f"Probe failed: {e}"
    # All formats exhausted
    elapsed = time.monotonic() - start_time
    logger.info(
        "Video probe done: model=%s result=False %.2fs",
        model_id,
        elapsed,
    )
    return False, f"Video not supported: {last_error_msg}"


async def probe_multimodal_support(
    base_url: str,
    api_key: str,
    model_id: str,
    timeout: float = 30,
) -> ProbeResult:
    """Probe all multimodal capabilities (image + video)."""
    img_ok, img_msg = await probe_image_support(
        base_url,
        api_key,
        model_id,
        timeout,
    )
    vid_ok, vid_msg = await probe_video_support(
        base_url,
        api_key,
        model_id,
        timeout,
    )
    return ProbeResult(
        supports_image=img_ok,
        supports_video=vid_ok,
        image_message=img_msg,
        video_message=vid_msg,
    )


def _is_media_keyword_error(exc: Exception) -> bool:
    error_str = str(exc).lower()
    keywords = [
        "image",
        "video",
        "vision",
        "multimodal",
        "image_url",
        "video_url",
        "does not support",
    ]
    return any(kw in error_str for kw in keywords)
