# -*- coding: utf-8 -*-
"""Transform result and request-local exact recovery sources."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompressionReceipt:
    """Exact sources and aggregate observability for accepted replacements."""

    recoverable: list[dict[str, Any]] = field(default_factory=list)
    compressed_chars: int = 0
    image_count: int = 0
    source_estimated_tokens: int = 0
    replacement_estimated_tokens: int = 0
    regions: dict[str, int] = field(default_factory=dict)


def make_recovery_id(
    text: str,
    region: str = "visual",
    provenance: str = "",
) -> str:
    """Build an id without conflating equal text from different sources."""
    payload = "\0".join((region, provenance, text)).encode("utf-8")
    return "vctx_" + hashlib.sha256(payload).hexdigest()[:12]


def record_pages(
    receipt: CompressionReceipt,
    page_count: int,
    text: str,
    region: str,
    provenance: str = "",
    *,
    source_estimated_tokens: int = 0,
    replacement_estimated_tokens: int = 0,
) -> None:
    """Register the exact source represented by accepted visual pages."""
    receipt.recoverable.append(
        {
            "id": make_recovery_id(text, region, provenance),
            "region": region,
            **({"provenance": provenance} if provenance else {}),
            "text": text,
            "image_count": page_count,
        },
    )
    receipt.compressed_chars += len(text)
    receipt.image_count += page_count
    receipt.source_estimated_tokens += max(
        0,
        int(source_estimated_tokens),
    )
    receipt.replacement_estimated_tokens += max(
        0,
        int(replacement_estimated_tokens),
    )
    receipt.regions[region] = receipt.regions.get(region, 0) + 1


__all__ = [
    "CompressionReceipt",
    "make_recovery_id",
    "record_pages",
]
