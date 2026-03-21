"""Multimodal capability probing for models."""

import logging
from dataclasses import dataclass

from openai import APIError, AsyncOpenAI

logger = logging.getLogger(__name__)

# 1x1 transparent PNG (67 bytes), used as minimal probe image
_PROBE_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "nGNgYPgPAAEDAQAIicLsAAAAASUVORK5CYII="
)

# Minimal 1-frame MP4 (~200 bytes), used as minimal probe video
_PROBE_VIDEO_B64 = "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDE..."


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
    timeout: float = 10,
) -> tuple[bool, str]:
    """Probe image support by sending a 1x1 PNG."""
    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    try:
        res = await client.chat.completions.create(
            model=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{_PROBE_IMAGE_B64}",
                            },
                        },
                        {"type": "text", "text": "hi"},
                    ],
                }
            ],
            max_tokens=1,
            stream=True,
            timeout=timeout,
        )
        async for _ in res:
            break
        return True, "Image supported"
    except APIError as e:
        if e.status_code == 400 or _is_media_keyword_error(e):
            return False, f"Image not supported: {e}"
        return False, f"Probe inconclusive: {e}"
    except Exception as e:
        return False, f"Probe failed: {e}"


async def probe_video_support(
    base_url: str,
    api_key: str,
    model_id: str,
    timeout: float = 10,
) -> tuple[bool, str]:
    """Probe video support by sending a minimal video."""
    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
    try:
        res = await client.chat.completions.create(
            model=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "video_url",
                            "video_url": {
                                "url": f"data:video/mp4;base64,{_PROBE_VIDEO_B64}",
                            },
                        },
                        {"type": "text", "text": "hi"},
                    ],
                }
            ],
            max_tokens=1,
            stream=True,
            timeout=timeout,
        )
        async for _ in res:
            break
        return True, "Video supported"
    except APIError as e:
        if e.status_code == 400 or _is_media_keyword_error(e):
            return False, f"Video not supported: {e}"
        return False, f"Probe inconclusive: {e}"
    except Exception as e:
        return False, f"Probe failed: {e}"


async def probe_multimodal_support(
    base_url: str,
    api_key: str,
    model_id: str,
    timeout: float = 10,
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
