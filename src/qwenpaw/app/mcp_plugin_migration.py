# -*- coding: utf-8 -*-
"""Classify raw MCP upgrade evidence without loading drivers or credentials."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from functools import lru_cache
from types import MappingProxyType
from typing import Any

from ..config.config import MCPConfig
from ..drivers.contracts import CredentialRef, DriverCard


@dataclass(frozen=True)
class MCPWorkspaceSnapshot:
    workspace_id: str
    config: Mapping[str, Any] = field(default_factory=dict)
    cards: tuple[DriverCard, ...] = ()
    errors: tuple[str, ...] = ()
    legacy_mcp: MCPConfig | None = field(default=None, repr=False)
    skipped_sources: bool = False
    legacy_backup: bytes | None = field(default=None, repr=False)
    legacy_skips: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "config", deepcopy(self.config))
        object.__setattr__(self, "cards", tuple(deepcopy(self.cards)))
        object.__setattr__(self, "errors", tuple(self.errors))


@dataclass(frozen=True)
class MCPUsageSnapshot:
    workspaces: tuple[MCPWorkspaceSnapshot, ...]
    plugin_settings: Mapping[str, Any] | None = None
    plugin_uninstalled: bool = False
    config_path: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "workspaces", tuple(self.workspaces))
        object.__setattr__(
            self,
            "plugin_settings",
            deepcopy(self.plugin_settings),
        )


@dataclass(frozen=True)
class MCPUsageDecision:
    status: str
    workspace_statuses: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "workspace_statuses",
            MappingProxyType(dict(self.workspace_statuses)),
        )


@dataclass(frozen=True)
class MCPPluginUpgradeResult:
    status: str
    decision: MCPUsageDecision
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


@lru_cache(maxsize=1)
def _mcp_defaults():
    from ..drivers.adapters.mcp_legacy_config import (
        legacy_mcp_client_to_driver,
    )

    client = MCPConfig().clients["anysearch"]
    card, _ = legacy_mcp_client_to_driver("anysearch", client)
    # The historical static reference alone provides no proof of user intent.
    opaque = replace(
        card,
        endpoint={
            **card.endpoint,
            "headers": {
                "Authorization": {
                    "source": "credential",
                    "credential": "static",
                    "field": "authorization",
                },
            },
        },
        credentials={"static": CredentialRef("static", "mcp/anysearch")},
    )
    return client, card, opaque


def configured_mcp_card(card: DriverCard) -> bool:
    """Recognize saved sources without resolving or launching credentials."""
    if card.name != "anysearch":
        return True
    _, default, opaque = _mcp_defaults()
    return card not in (default, opaque)


def needs_legacy_migration(workspace: MCPWorkspaceSnapshot) -> bool:
    """Honor the old migration watermark before considering saved clients."""
    from ..drivers.adapters.mcp_legacy_config import (
        CURRENT_MCP_MIGRATION_VERSION,
    )

    mcp = workspace.legacy_mcp
    if mcp is None or mcp.migration_version >= CURRENT_MCP_MIGRATION_VERSION:
        return False
    default, _, _ = _mcp_defaults()
    return any(
        name != "anysearch" or client != default
        for name, client in mcp.clients.items()
    ) or any(configured_mcp_card(card) for card in workspace.cards)


def _feature_status(config: Mapping) -> str:
    """Recognize explicit Mail/ACP intent before model defaults are filled."""
    mail = config.get("mail")
    configured = mail is not None
    if configured and not isinstance(mail, Mapping):
        return "needs_review"
    tools = config.get("tools", {})
    if not isinstance(tools, Mapping):
        return "needs_review"
    builtin = tools.get("builtin_tools", {})
    if not isinstance(builtin, Mapping):
        return "needs_review"
    delegate = builtin.get("delegate_external_agent", {})
    if not isinstance(delegate, Mapping):
        return "needs_review"
    configured |= delegate.get("enabled") is True
    acp = config.get("acp", {})
    if not isinstance(acp, Mapping):
        return "needs_review"
    configured |= acp.get("enabled") is True
    agents = acp.get("agents", {})
    if not isinstance(agents, Mapping):
        return "needs_review"
    defaults = {
        "opencode": ("opencode", ["acp"], "update_detail"),
        "qwen_code": ("qwen", ["--acp"], "call_detail"),
        "claude_code": (
            "npx",
            ["-y", "@zed-industries/claude-agent-acp"],
            "update_detail",
        ),
        "codex": ("npx", ["-y", "@zed-industries/codex-acp"], "call_detail"),
    }
    for name, runner in agents.items():
        if not isinstance(runner, Mapping):
            return "needs_review"
        if runner.get("enabled") is not True:
            continue
        if name not in defaults:
            configured = True
            continue
        command, args, parse_mode = defaults[name]
        fingerprint = {
            "enabled": True,
            "command": command,
            "args": args,
            "env": {},
            "trusted": True,
            "tool_parse_mode": parse_mode,
            "stdio_buffer_limit_bytes": 50 * 1024 * 1024,
        }
        configured |= {**fingerprint, **runner} != fingerprint
    return "configured" if configured else "unused"


def _workspace_status(workspace: MCPWorkspaceSnapshot) -> str:
    if workspace.errors:
        return "needs_review"
    if needs_legacy_migration(workspace) or any(
        configured_mcp_card(card) for card in workspace.cards
    ):
        return "configured"
    return _feature_status(workspace.config)


def classify_mcp_usage(snapshot: MCPUsageSnapshot) -> MCPUsageDecision:
    """Decide installation eligibility while preserving each workspace result.

    Callers supply the complete workspace inventory, including inactive ones.
    Diagnostics deliberately contain no file paths, source names or raw errors.
    """
    statuses = {}
    duplicate = False
    for workspace in snapshot.workspaces:
        if workspace.workspace_id in statuses:
            duplicate = True
            statuses[workspace.workspace_id] = "needs_review"
        else:
            statuses[workspace.workspace_id] = _workspace_status(workspace)
    settings = snapshot.plugin_settings
    off = snapshot.plugin_uninstalled or (
        isinstance(settings, Mapping) and settings.get("enabled") is False
    )
    invalid_settings = settings is not None and (
        not isinstance(settings, Mapping)
        or ("enabled" in settings and type(settings["enabled"]) is not bool)
    )
    if off:
        status = "explicit_off"
    elif duplicate or invalid_settings:
        status = "needs_review"
    elif "configured" in statuses.values():
        status = "configured"
    elif "needs_review" in statuses.values():
        status = "needs_review"
    else:
        status = "unused"
    return MCPUsageDecision(status, statuses)
