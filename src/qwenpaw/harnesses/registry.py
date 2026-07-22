# -*- coding: utf-8 -*-
"""Coding harness catalog and adapter factories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .base import HarnessAdapter
from .codex.adapter import CodexAdapter


@dataclass(frozen=True)
class ProviderCatalogItem:
    """Static provider metadata."""

    id: str
    name: str
    coming_soon: bool


PROVIDER_CATALOG = (
    ProviderCatalogItem("codex", "Codex", False),
    ProviderCatalogItem("claude", "Claude Code", True),
    ProviderCatalogItem("qoder", "Qoder", True),
)


def create_adapter(provider_id: str, state_dir: Path) -> HarnessAdapter:
    """Create one supported provider adapter."""
    if provider_id == "codex":
        return CodexAdapter(state_dir=state_dir)
    raise ValueError(f"Unsupported third-party agent backend: {provider_id}")


__all__ = ["PROVIDER_CATALOG", "create_adapter"]
