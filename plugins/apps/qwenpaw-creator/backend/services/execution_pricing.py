# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Local cost estimation for costly media executions.

Price tables are transcribed from the providers' official pricing pages so a
pending execution authorization can show the user an estimated spend and the
calculation behind it *before* any billable request is sent:

- Alibaba Cloud Model Studio pricing: https://help.aliyun.com/zh/model-studio/model-pricing
- OpenAI API pricing:  https://developers.openai.com/api/docs/pricing
- Volcengine Ark pricing: https://www.volcengine.com/docs/82379/1544106

The estimate is best-effort and computed entirely locally: unknown models fall
back to their family's typical price and are flagged ``approximate`` so the UI
can tell the user the number is indicative, not a quote.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any

_CURRENCY_SYMBOLS = {"CNY": "¥", "USD": "$"}


@dataclass(frozen=True, slots=True)
class CostEstimate:
    """One locally computed spend estimate for a pending execution."""

    estimated_cost: float | None
    currency: str
    unit_price_text: str
    formula: str
    pricing_model: str
    pricing_source: str
    approximate: bool
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def display_text(self) -> str:
        if self.estimated_cost is None:
            return "费用未知"
        symbol = _CURRENCY_SYMBOLS.get(self.currency, self.currency)
        prefix = "约 " if self.approximate else ""
        if self.estimated_cost == 0:
            return "限时免费"
        return f"{prefix}{symbol}{self.estimated_cost:.2f}"

    def as_payload(self) -> dict[str, Any]:
        return {
            "estimatedCost": self.estimated_cost,
            "currency": self.currency,
            "displayText": self.display_text,
            "unitPrice": self.unit_price_text,
            "formula": self.formula,
            "pricingModel": self.pricing_model,
            "pricingSource": self.pricing_source,
            "approximate": self.approximate,
            "notes": list(self.notes),
        }


_DISCLAIMER = "本地估算，实际费用以服务商账单为准"

# ── Image: DashScope Model Studio (CNY/image, billed on successful output only)
# Copied 2026-07 from help.aliyun.com/zh/model-studio/model-pricing (cn-beijing).
_DASHSCOPE_IMAGE_SOURCE = "阿里云百炼官网价（元/张）"
_DASHSCOPE_IMAGE_PRICES: tuple[tuple[str, float], ...] = (
    # Longest prefix first: matching walks this list in order.
    ("qwen-image-3.0-pro", 0.0),  # free for a limited time
    ("qwen-image-2.0-pro", 0.5),
    ("qwen-image-2.0", 0.2),
    ("qwen-image-max", 0.5),
    ("qwen-image-plus", 0.2),
    ("qwen-image-edit-max", 0.5),
    ("qwen-image-edit-plus", 0.2),
    ("qwen-image-edit", 0.3),
    ("qwen-image", 0.25),
    ("wan2.7-image-pro", 0.5),
    ("wan2.7-image", 0.2),
    ("wan2.6-image", 0.2),
    ("wan2.6-t2i", 0.2),
    ("wan2.5-t2i-preview", 0.2),
    ("wan2.2-t2i-plus", 0.2),
    ("wan2.2-t2i-flash", 0.14),
    ("wanx2.1-t2i-plus", 0.2),
    ("wanx2.1-t2i-turbo", 0.14),
    ("wanx2.0-t2i-turbo", 0.04),
    ("z-image-turbo", 0.2),
)
_DASHSCOPE_IMAGE_FALLBACK = 0.25

# ── Image: OpenAI Images API (USD/image, by quality × size) ──────────────────
# developers.openai.com/api/docs/pricing · official per-image prices for
# gpt-image-1; the rest of the gpt-image family (incl. gpt-image-2)
# approximates with the same table.
_OPENAI_IMAGE_SOURCE = "OpenAI 官网价（美元/张，按质量×尺寸）"
_OPENAI_IMAGE_PRICES: dict[str, dict[str, float]] = {
    # quality -> {size: USD}
    "low": {"1024x1024": 0.011, "1024x1536": 0.016, "1536x1024": 0.016},
    "medium": {"1024x1024": 0.042, "1024x1536": 0.063, "1536x1024": 0.063},
    "high": {"1024x1024": 0.167, "1024x1536": 0.25, "1536x1024": 0.25},
}
_OPENAI_EXACT_MODELS = ("gpt-image-1",)
_OPENAI_SIZE_BY_RATIO = {
    "16:9": "1536x1024",
    "9:16": "1024x1536",
    "1:1": "1024x1024",
    "4:3": "1024x768",
    "3:4": "768x1024",
    "21:9": "2560x1080",
    "3:2": "1536x1024",
    "2:3": "1024x1536",
}
# Non-catalog sizes bill by the closest catalog size (per-token in practice).
_OPENAI_SIZE_ALIAS = {
    "1024x768": "1024x1024",
    "768x1024": "1024x1024",
    "2560x1080": "1536x1024",
}

# ── Video: DashScope Wan / HappyHorse (CNY/second, by output resolution) ──────
# Copied 2026-07 from help.aliyun.com/zh/model-studio/model-pricing (cn-beijing).
_WAN_VIDEO_SOURCE = "阿里云百炼官网价（元/秒，按输出分辨率）"
_WAN_VIDEO_PRICES: tuple[tuple[str, dict[str, float]], ...] = (
    # The audio=false flash tier is cheaper, see _WAN_VIDEO_MUTED_PRICES.
    ("wan2.7-t2v", {"720P": 0.6, "1080P": 1.0}),
    ("wan2.7-i2v", {"720P": 0.6, "1080P": 1.0}),
    ("wan2.7-r2v", {"720P": 0.6, "1080P": 1.0}),
    ("wan2.6-r2v-flash", {"720P": 0.3, "1080P": 0.5}),
    ("wan2.6-t2v", {"720P": 0.6, "1080P": 1.0}),
    ("wan2.6-i2v", {"720P": 0.6, "1080P": 1.0}),
    ("wan2.6-r2v", {"720P": 0.6, "1080P": 1.0}),
    ("wan2.5-t2v-preview", {"480P": 0.3, "720P": 0.6, "1080P": 1.0}),
    ("wan2.5-i2v-preview", {"480P": 0.3, "720P": 0.6, "1080P": 1.0}),
    ("wan2.2-t2v-plus", {"480P": 0.14, "1080P": 0.7}),
    ("wan2.2-i2v-flash", {"480P": 0.1, "720P": 0.1, "1080P": 0.1}),
    ("wanx2.1-t2v-turbo", {"480P": 0.24, "720P": 0.24}),
    ("wanx2.1-t2v-plus", {"720P": 0.7}),
    # HappyHorse reference-to-video: copied at the official list price (the
    # site currently advertises limited-time 60%/80% discounts; estimating
    # high during the discount window is the safe side — the bill is
    # authoritative). No muted-discount tier.
    ("happyhorse-1.1-r2v", {"720P": 0.9, "1080P": 1.2}),
    ("happyhorse-1.0-r2v", {"720P": 0.9, "1080P": 1.6}),
)
_WAN_VIDEO_MUTED_PRICES: dict[str, dict[str, float]] = {
    "wan2.6-r2v-flash": {"720P": 0.15, "1080P": 0.25},
}
_WAN_VIDEO_FALLBACK = {"480P": 0.3, "720P": 0.6, "1080P": 1.0}

# ── Video: Volcengine Ark Seedance (CNY/million tokens; tokens derived from ───
# pixels × fps × duration) · volcengine.com/docs/82379/1544106
# tokens = width × height × fps × duration ÷ 1024
# Only the Seedance 2.0 family is integrated; prices are the tiers without
# video input.
_SEEDANCE_VIDEO_SOURCE = "火山方舟官网价（元/百万tokens）"
_SEEDANCE_TOKEN_PRICES: tuple[tuple[str, float], ...] = (
    ("doubao-seedance-2.0-mini", 23.0),
    ("doubao-seedance-2.0-fast", 37.0),
    ("doubao-seedance-2.0", 46.0),
    ("seedance-2.0-mini", 23.0),
    ("seedance-2.0-fast", 37.0),
    ("seedance-2.0", 46.0),
)
_SEEDANCE_TOKEN_FALLBACK = 46.0
_SEEDANCE_FPS = 24
_VIDEO_PIXELS_BY_RESOLUTION = {
    "480P": 848 * 480,
    "720P": 1280 * 720,
    "1080P": 1920 * 1080,
}


# Official snapshot naming: a dated version of a model (e.g.
# qwen-image-2.0-pro-2026-06-22) shares the base model's price; any other
# version suffix is a distinct version whose price may differ, so it can only
# be flagged as approximate.
_DATED_VERSION_SUFFIX = re.compile(r"^-\d{4}-\d{2}-\d{2}$")


def _match_prefix_price(
    model: str,
    table: tuple[tuple[str, Any], ...],
) -> tuple[str, Any] | None:
    """Return the longest matching catalog prefix regardless of table order."""

    lowered = model.casefold()
    best: tuple[str, Any] | None = None
    for prefix, value in table:
        if not lowered.startswith(prefix):
            continue
        # pylint: disable-next=unsubscriptable-object
        if best is not None and len(prefix) <= len(best[0]):
            continue
        best = (prefix, value)
    return best


def _is_same_priced_version(model: str, prefix: str) -> bool:
    """True only for the exact catalog model or its dated official snapshot."""

    remainder = model.casefold()[len(prefix) :]
    return remainder == "" or bool(_DATED_VERSION_SUFFIX.match(remainder))


def _normalize_resolution(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text if text in _VIDEO_PIXELS_BY_RESOLUTION else "720P"


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def estimate_image_cost(
    *,
    backend: str,
    model: str,
    aspect_ratio: str = "16:9",
    quality: str = "",
    count: int = 1,
) -> CostEstimate:
    """Per-image estimate for the configured image provider."""

    count = max(1, count)
    if backend.casefold() == "dashscope":
        matched = _match_prefix_price(model, _DASHSCOPE_IMAGE_PRICES)
        notes = [_DISCLAIMER]
        if matched is None:
            approximate = True
            prefix, unit = "万相/千问生图档位", _DASHSCOPE_IMAGE_FALLBACK
        else:
            prefix, unit = matched
            approximate = not _is_same_priced_version(model, prefix)
        return CostEstimate(
            estimated_cost=round(unit * count, 4),
            currency="CNY",
            unit_price_text=f"{unit}元/张",
            formula=f"{unit}元/张 × {count}张 = ¥{unit * count:.2f}",
            pricing_model=prefix,
            pricing_source=_DASHSCOPE_IMAGE_SOURCE,
            approximate=approximate,
            notes=tuple(notes),
        )

    # OpenAI Images API: per-image price keyed by quality × size.
    quality_key = (
        quality.casefold()
        if quality.casefold() in _OPENAI_IMAGE_PRICES
        else "low"
    )
    size = _OPENAI_SIZE_BY_RATIO.get(aspect_ratio, "1536x1024")
    billed_size = _OPENAI_SIZE_ALIAS.get(size, size)
    unit = _OPENAI_IMAGE_PRICES[quality_key].get(
        billed_size,
        _OPENAI_IMAGE_PRICES[quality_key]["1536x1024"],
    )
    exact = any(model.casefold() == item for item in _OPENAI_EXACT_MODELS)
    notes = [_DISCLAIMER]
    return CostEstimate(
        estimated_cost=round(unit * count, 4),
        currency="USD",
        unit_price_text=f"${unit}/张（{quality_key} 质量 · {size}）",
        formula=f"${unit}/张 × {count}张 = ${unit * count:.3f}",
        pricing_model=model if exact else "gpt-image-1（近似）",
        pricing_source=_OPENAI_IMAGE_SOURCE,
        approximate=not exact,
        notes=tuple(notes),
    )


def _estimate_wan_video_cost(
    *,
    model: str,
    duration_seconds: int,
    resolution: str,
    audio: bool,
) -> CostEstimate:
    matched = _match_prefix_price(model, _WAN_VIDEO_PRICES)
    notes = [_DISCLAIMER]
    if matched is None:
        approximate = True
        prefix, table = "万相视频生成档位", _WAN_VIDEO_FALLBACK
    else:
        prefix, table = matched
        approximate = not _is_same_priced_version(model, prefix)
    if not audio and prefix in _WAN_VIDEO_MUTED_PRICES:
        table = _WAN_VIDEO_MUTED_PRICES[prefix]
    unit = table.get(resolution)
    if unit is None:
        unit = max(table.values())
        approximate = True
    cost = round(unit * duration_seconds, 4)
    return CostEstimate(
        estimated_cost=cost,
        currency="CNY",
        unit_price_text=f"{unit}元/秒（{resolution}）",
        formula=f"{unit}元/秒 × {duration_seconds}秒 = ¥{cost:.2f}",
        pricing_model=prefix,
        pricing_source=_WAN_VIDEO_SOURCE,
        approximate=approximate,
        notes=tuple(notes),
    )


def _estimate_seedance_video_cost(
    *,
    model: str,
    duration_seconds: int,
    resolution: str,
) -> CostEstimate:
    matched = _match_prefix_price(model, _SEEDANCE_TOKEN_PRICES)
    notes = [_DISCLAIMER]
    if matched is None:
        approximate = True
        prefix, price_per_million = "seedance 档位", _SEEDANCE_TOKEN_FALLBACK
    else:
        prefix, price_per_million = matched
        approximate = not _is_same_priced_version(model, prefix)
    pixels = _VIDEO_PIXELS_BY_RESOLUTION[resolution]
    tokens = pixels * _SEEDANCE_FPS * duration_seconds / 1024
    cost = round(tokens / 1_000_000 * price_per_million, 4)
    return CostEstimate(
        estimated_cost=cost,
        currency="CNY",
        unit_price_text=f"{price_per_million}元/百万tokens",
        formula=(
            f"{tokens:,.0f} tokens × {price_per_million}元/百万tokens"
            f" = ¥{cost:.2f}"
        ),
        pricing_model=prefix,
        pricing_source=_SEEDANCE_VIDEO_SOURCE,
        approximate=approximate,
        notes=tuple(notes),
    )


def estimate_video_cost(
    *,
    backend: str,
    model: str,
    duration_seconds: int,
    resolution: str = "720P",
    audio: bool = True,
) -> CostEstimate:
    """Per-clip estimate for the configured video provider."""

    duration_seconds = _positive_int(duration_seconds, 5)
    resolution = _normalize_resolution(resolution)
    if backend.casefold().startswith("seedance"):
        return _estimate_seedance_video_cost(
            model=model,
            duration_seconds=duration_seconds,
            resolution=resolution,
        )
    return _estimate_wan_video_cost(
        model=model,
        duration_seconds=duration_seconds,
        resolution=resolution,
        audio=audio,
    )


def estimate_execution_cost(
    *,
    provider_kind: str | None,
    provider: str,
    model: str,
    arguments: Mapping[str, Any],
) -> CostEstimate | None:
    """Estimate one costly specialist-tool execution before authorization.

    ``arguments`` is the tool-call ``arguments`` object (prompt, aspectRatio,
    durationSeconds, resolution...). Returns ``None`` for tool kinds that have
    no provider-billed media cost (e.g. local ffmpeg composition).
    """

    if provider_kind == "image":
        quality = ""
        if provider.casefold() == "openai":
            try:
                from models.image import get_image_model

                quality = str(get_image_model().quality or "")
            except Exception:
                quality = ""
        return estimate_image_cost(
            backend=provider,
            model=model,
            aspect_ratio=str(arguments.get("aspectRatio") or "16:9"),
            quality=quality,
        )
    if provider_kind == "video":
        return estimate_video_cost(
            backend=provider,
            model=model,
            duration_seconds=_positive_int(
                arguments.get("durationSeconds"),
                5,
            ),
            resolution=str(arguments.get("resolution") or "720P"),
            audio=bool(arguments.get("generateAudio", True)),
        )
    return None


__all__ = [
    "CostEstimate",
    "estimate_execution_cost",
    "estimate_image_cost",
    "estimate_video_cost",
]
