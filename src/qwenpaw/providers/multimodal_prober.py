# -*- coding: utf-8 -*-
"""Multimodal capability probing — shared constants and data types.

Provider-specific probe logic lives in each provider class
(e.g. ``OpenAIProvider._probe_image_support``).
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# 32x32 red PNG (96 bytes), used as minimal probe image.
# Some providers (e.g. Ollama) reject images smaller than 32x32,
# so we use 32x32 to avoid false negatives.
_PROBE_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAJ0lEQVR42u3NsQkAAAjA"
    "sP7/tF7hIASyp6lTCQQCgUAgEAgEgi/BAjLD/C5w/SM9AAAAAElFTkSuQmCC"
)

# HTTP URL for providers that accept external video
# URLs (e.g. Gemini file_data).
_PROBE_VIDEO_URL = (
    "https://help-static-aliyun-doc.aliyuncs.com"
    "/file-manage-files/zh-CN/20241115/cqqkru/1.mp4"
)

# 64x64 solid-blue H.264 MP4 (10 frames @ 10fps,
# ~1.8 KB), used for video probe.
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


def _is_media_keyword_error(exc: Exception) -> bool:
    """Check if an exception message contains media-related keywords."""
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


# Shared prompt for image color-probe across all providers.
_IMAGE_PROBE_PROMPT = (
    "What is the single dominant color of this image? "
    "Reply with ONLY the color name, nothing else."
)

# Red-family keywords the probe image (solid red) should elicit.
_RED_KW = ("red", "scarlet", "crimson", "vermilion", "maroon", "红")


def evaluate_image_probe_answer(
    answer: str,
    model_id: str,
    start_time: float,
    reasoning: str = "",
) -> tuple[bool, str]:
    """Shared evaluation for image color-probe answers.

    Args:
        answer: The model's primary text answer (auto-lowercased).
        model_id: Model identifier (for logging).
        start_time: ``time.monotonic()`` when the probe started.
        reasoning: Optional reasoning/thinking text (auto-lowercased)
            for models that put analysis in a separate field.

    Returns:
        ``(supported, message)`` tuple.
    """
    import time as _time  # deferred to keep module-level imports light

    answer = answer.lower().strip()
    reasoning = reasoning.lower().strip()

    if any(kw in answer for kw in _RED_KW):
        elapsed = _time.monotonic() - start_time
        logger.info(
            "Image probe done: model=%s result=True %.2fs",
            model_id,
            elapsed,
        )
        return True, f"Image supported (answer={answer!r})"

    if reasoning and any(kw in reasoning for kw in _RED_KW):
        elapsed = _time.monotonic() - start_time
        logger.info(
            "Image probe done: model=%s result=True %.2fs",
            model_id,
            elapsed,
        )
        return True, f"Image supported (reasoning, answer={answer!r})"

    elapsed = _time.monotonic() - start_time
    logger.info(
        "Image probe done: model=%s result=False %.2fs",
        model_id,
        elapsed,
    )
    return False, f"Model did not recognise image (answer={answer!r})"
