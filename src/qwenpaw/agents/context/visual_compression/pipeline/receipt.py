# -*- coding: utf-8 -*-
"""Aggregate statistics for accepted visual replacements."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CompressionReceipt:
    """Aggregate observability without retaining source text."""

    compressed_chars: int = 0
    image_count: int = 0
    source_estimated_tokens: int = 0
    replacement_estimated_tokens: int = 0
    regions: dict[str, int] = field(default_factory=dict)


def record_pages(
    receipt: CompressionReceipt,
    page_count: int,
    text: str,
    region: str,
    *,
    source_estimated_tokens: int = 0,
    replacement_estimated_tokens: int = 0,
) -> None:
    """Count the source represented by accepted visual pages."""
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
    "record_pages",
]
