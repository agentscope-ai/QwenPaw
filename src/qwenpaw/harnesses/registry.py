# -*- coding: utf-8 -*-
"""Third-party agent catalog and adapter factories."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import HarnessAdapter, MissingDependencyAdapter
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
            attachments=True,
            qwenpaw_skills_projection=True,
            qwenpaw_mcp_projection=True,
            provider_skills_discovery=True,
            provider_mcp_discovery=True,
            mcp_tool_allowlist=True,
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
        False,
        HarnessCapabilities(
            authentication=True,
            model_selection=True,
            reasoning_effort=True,
            reasoning_stream=True,
            tool_stream=True,
            session_resume=True,
            attachments=True,
            qwenpaw_skills_projection=True,
            qwenpaw_mcp_projection=True,
            provider_skills_discovery=True,
            provider_mcp_discovery=False,
            mcp_tool_allowlist=True,
            commands=[
                HarnessCommand(
                    name="compact",
                    description="Compact the current Qoder session",
                ),
            ],
            approval_presets=[
                HarnessApprovalPreset(
                    id="ask",
                    name="Ask before actions",
                    description=(
                        "Ask before file changes and command execution."
                    ),
                    settings={"permission_mode": "default"},
                ),
                HarnessApprovalPreset(
                    id="accept-edits",
                    name="Accept edits",
                    description=(
                        "Allow file edits while keeping other safeguards."
                    ),
                    settings={"permission_mode": "acceptEdits"},
                ),
                HarnessApprovalPreset(
                    id="plan",
                    name="Plan only",
                    description="Analyze and plan without changing files.",
                    settings={"permission_mode": "plan"},
                ),
                HarnessApprovalPreset(
                    id="auto",
                    name="Automatic",
                    description=(
                        "Let Qoder decide which safe actions can run."
                    ),
                    settings={"permission_mode": "auto"},
                ),
                HarnessApprovalPreset(
                    id="full-access",
                    name="Full access",
                    description=(
                        "Skip permission checks in a trusted workspace."
                    ),
                    settings={"permission_mode": "bypassPermissions"},
                ),
            ],
        ),
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
    if provider_id in {"codex", "qoder"}:
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
    if provider_id == "qoder":
        binary = str((settings or {}).get("binary") or "").strip() or None
        try:
            from .qoder.adapter import QoderAdapter
        except ModuleNotFoundError as exc:
            if exc.name != "qoder_agent_sdk":
                raise
            return MissingDependencyAdapter("qoder", "Qoder")
        return QoderAdapter(state_dir=state_dir, binary=binary)
    raise ValueError(f"Unsupported third-party agent backend: {provider_id}")


__all__ = [
    "PROVIDER_CATALOG",
    "adapter_config_key",
    "create_adapter",
    "get_provider",
]
