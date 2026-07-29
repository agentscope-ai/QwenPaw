# -*- coding: utf-8 -*-
"""Small normalization helpers shared across grounding stages."""

from __future__ import annotations

import html
import re
from typing import Any


def clean_text(value: Any, *, max_chars: int | None = None) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if max_chars and len(text) > max_chars:
        return text[: max_chars - 3].rstrip() + "..."
    return text


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def split_keywords(value: Any) -> list[str]:
    keywords: list[str] = []
    for item in as_list(value):
        keywords.extend(
            part.strip()
            for part in re.split(r"[,，;；\n]+", item)
            if part.strip()
        )
    return keywords


def string_list(value: Any, *, max_items: int = 6) -> list[str]:
    cleaned = [clean_text(item, max_chars=120) for item in as_list(value)]
    return list(dict.fromkeys(item for item in cleaned if item))[:max_items]


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "需要", "是"}
    return False


def coerce_confidence(value: Any, *, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = default
    if confidence >= 2:
        confidence /= 100
    return round(max(0.0, min(1.0, confidence)), 2)
