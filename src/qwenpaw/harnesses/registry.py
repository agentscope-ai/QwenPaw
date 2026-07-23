# -*- coding: utf-8 -*-
"""Third-party agent catalog and adapter factories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import HarnessAdapter
from .codex.adapter import CodexAdapter
from .events import (
    HarnessApprovalPreset,
    HarnessCapabilities,
    HarnessCommand,
)


@dataclass(frozen=True)
class ProviderCatalogItem:
    """Static provider metadata."""

    id: str
    name: str
    coming_soon: bool
    capabilities: HarnessCapabilities


PROVIDER_CATALOG = (
    ProviderCatalogItem(
        "codex",
        "Codex",
        False,
        HarnessCapabilities(
            authentication=True,
            model_selection=True,
            reasoning_effort=True,
            reasoning_stream=True,
            tool_stream=True,
            session_resume=True,
            commands=[
                HarnessCommand(
                    name="compact",
                    description="Compact the current Codex thread",
                ),
                HarnessCommand(
                    name="review",
                    description="Review uncommitted workspace changes",
                ),
                HarnessCommand(
                    name="skills",
                    description="List skills available to Codex",
                ),
                HarnessCommand(
                    name="status",
                    description="Show Codex account and session status",
                ),
            ],
            approval_presets=[
                HarnessApprovalPreset(
                    id="ask",
                    name="Ask before changes",
                    description=(
                        "Allow workspace changes and ask before elevated "
                        "actions."
                    ),
                    settings={
                        "sandbox": "workspace-write",
                        "approval_policy": "on-request",
                    },
                ),
                HarnessApprovalPreset(
                    id="read-only",
                    name="Read only",
                    description="Inspect files without changing them.",
                    settings={
                        "sandbox": "read-only",
                        "approval_policy": "on-request",
                    },
                ),
                HarnessApprovalPreset(
                    id="workspace",
                    name="Workspace access",
                    description=(
                        "Allow workspace changes without confirmation."
                    ),
                    settings={
                        "sandbox": "workspace-write",
                        "approval_policy": "never",
                    },
                ),
                HarnessApprovalPreset(
                    id="full-access",
                    name="Full access",
                    description=(
                        "Allow unrestricted local execution without "
                        "confirmation."
                    ),
                    settings={
                        "sandbox": "danger-full-access",
                        "approval_policy": "never",
                    },
                ),
            ],
        ),
    ),
    ProviderCatalogItem(
        "claude",
        "Claude Code",
        True,
        HarnessCapabilities(),
    ),
    ProviderCatalogItem(
        "qoder",
        "Qoder",
        True,
        HarnessCapabilities(),
    ),
)


def get_provider(provider_id: str) -> ProviderCatalogItem:
    """Return catalog metadata for one backend."""
    for item in PROVIDER_CATALOG:
        if item.id == provider_id:
            return item
    raise ValueError(f"Unknown third-party agent backend: {provider_id}")


def adapter_config_key(
    provider_id: str,
    settings: dict[str, Any] | None = None,
) -> tuple[Any, ...]:
    """Return settings that require recreating one provider adapter."""
    values = settings or {}
    if provider_id == "codex":
        return (str(values.get("binary") or "").strip(),)
    return ()


def create_adapter(
    provider_id: str,
    state_dir: Path,
    settings: dict[str, Any] | None = None,
) -> HarnessAdapter:
    """Create one supported provider adapter."""
    if provider_id == "codex":
        binary = str((settings or {}).get("binary") or "").strip() or None
        return CodexAdapter(state_dir=state_dir, binary=binary)
    raise ValueError(f"Unsupported third-party agent backend: {provider_id}")


__all__ = [
    "PROVIDER_CATALOG",
    "adapter_config_key",
    "create_adapter",
    "get_provider",
]
