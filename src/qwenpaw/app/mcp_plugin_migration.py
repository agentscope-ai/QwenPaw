# -*- coding: utf-8 -*-
"""Classify raw MCP upgrade evidence without loading drivers or credentials."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class MCPWorkspaceSnapshot:
    workspace_id: str
    config: Mapping[str, Any] = field(default_factory=dict)
    cards: tuple[Mapping[str, Any], ...] = ()
    errors: tuple[str, ...] = ()

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
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "workspace_statuses",
            MappingProxyType(dict(self.workspace_statuses)),
        )
        object.__setattr__(self, "reasons", tuple(self.reasons))


@dataclass(frozen=True)
class MCPPluginUpgradeResult:
    status: str
    decision: MCPUsageDecision
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


def inventory_mcp_usage(*, config_path=None, plugins_dir=None):
    """Read raw evidence without hydrating or migrating workspace models."""
    from .mcp_plugin_upgrade import inventory_mcp_usage as inventory

    return inventory(config_path=config_path, plugins_dir=plugins_dir)


async def ensure_mcp_plugin_for_upgrade(snapshot, *, loader):
    """Reuse the loader-owned offline protocol installation coordinator."""
    from .mcp_plugin_upgrade import get_coordinator

    return await get_coordinator(loader).ensure(snapshot)


def validate_mcp_upgrade_preflight(snapshot):
    """Stop repairing root migrations when their raw input needs review."""
    if any(
        {"invalid_root_config", "invalid_legacy_root_mcp"}.intersection(
            item.errors,
        )
        for item in snapshot.workspaces
    ):
        raise RuntimeError("Root configuration requires review before startup")


# Fingerprints from MCPConfig and legacy_mcp_client_to_driver, versions 0/1/2.
# Names alone never identify a default: all configuration and bindings match.
_CLIENT_DEFAULTS = {
    "description": "",
    "enabled": True,
    "transport": "stdio",
    "url": "",
    "headers": {},
    "command": "",
    "args": [],
    "env": {},
    "cwd": "",
    "http_timeout": None,
    "tools": None,
    "oauth": None,
}
_DEFAULT_CLIENT = {
    **_CLIENT_DEFAULTS,
    "name": "anysearch_mcp",
    "description": "AnySearch web search via MCP",
    "enabled": False,
    "transport": "streamable_http",
    "url": "https://api.anysearch.com/mcp",
    "headers": {"Authorization": "Bearer ${ANYSEARCH_API_KEY}"},
}
_DEFAULT_CARD: dict[str, Any] = {
    "name": "anysearch",
    "protocol": "mcp",
    "enabled": False,
    "endpoint": {
        "transport": "streamable_http",
        "url": "https://api.anysearch.com/mcp",
        "headers": {
            "Authorization": {
                "source": "credential",
                "credential": "env_anysearch_api_key",
                "field": "value",
                "format": "Bearer {value}",
            },
        },
    },
    "credentials": {
        "env_anysearch_api_key": {
            "kind": "static",
            "ref": "env:ANYSEARCH_API_KEY",
        },
    },
    "config": {
        "display_name": "anysearch_mcp",
        "description": "AnySearch web search via MCP",
    },
    "policy": {
        "default_effect": "deny",
        "rules": [
            {
                "subject": "*",
                "effect": "ask",
                "target": {"kind": "tool", "name": "*"},
                "principal": {
                    "source_type": "*",
                    "source_value": "*",
                    "subject_type": "*",
                    "subject_value": "*",
                },
                "condition": None,
            },
        ],
    },
}
_OPAQUE_DEFAULT_CARD = deepcopy(_DEFAULT_CARD)
_OPAQUE_DEFAULT_CARD["credentials"] = {
    "static": {"kind": "static", "ref": "mcp/anysearch"},
}
_OPAQUE_DEFAULT_CARD["endpoint"]["headers"]["Authorization"] = {
    "source": "credential",
    "credential": "static",
    "field": "authorization",
}


def _text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _strings(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and all(
        isinstance(x, str) for x in value
    )


def _binding(value: Any, credentials: Mapping | None) -> bool:
    if isinstance(value, str):
        return True
    if credentials is None or not isinstance(value, Mapping):
        return False
    if value.get("source") == "literal":
        return value.get("value") is None or isinstance(value["value"], str)
    return (
        value.get("source") == "credential"
        and _text(value.get("credential"))
        and value["credential"] in credentials
        and _text(value.get("field"))
        and (value.get("format") is None or isinstance(value["format"], str))
    )


def _bindings(value: Any, credentials: Mapping | None) -> bool:
    if value is None and credentials is not None:
        return True
    if not isinstance(value, Mapping):
        return False
    if credentials is not None and (
        "public" in value or "secret_refs" in value
    ):
        return all(
            section is None
            or (
                isinstance(section, Mapping)
                and all(
                    _text(k) and isinstance(v, str) for k, v in section.items()
                )
            )
            for section in (
                value.get("public", {}),
                value.get("secret_refs", {}),
            )
        )
    return all(_text(k) and _binding(v, credentials) for k, v in value.items())


def _endpoint(
    value: Mapping[str, Any],
    credentials: Mapping | None = None,
) -> bool:
    transport = value.get("transport", "stdio")
    if transport == "stdio":
        if not _text(value.get("command")):
            return False
    elif transport in ("streamable_http", "sse"):
        if not _text(value.get("url")):
            return False
    else:
        return False
    timeout = value.get("http_timeout")
    bindings = [value.get(key, {}) for key in ("env", "headers")]
    return (
        _strings(value.get("args", []))
        and isinstance(value.get("cwd", ""), str)
        and all(_bindings(section, credentials) for section in bindings)
        and (
            timeout is None or (type(timeout) in (int, float) and timeout > 0)
        )
    )


def _client(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    result = dict(value)
    for alias, canonical in (
        ("isActive", "enabled"),
        ("baseUrl", "url"),
        ("type", "transport"),
        ("timeout", "http_timeout"),
    ):
        if alias in result:
            if canonical in result and result[canonical] != result[alias]:
                return None
            result[canonical] = result.pop(alias)
    if (
        "transport" not in result
        and result.get("url")
        and not result.get("command")
    ):
        result["transport"] = "streamable_http"
    transport = result.get("transport", "stdio")
    if isinstance(transport, str):
        transport = transport.strip().lower()
        result["transport"] = {
            "http": "streamable_http",
            "streamable-http": "streamable_http",
            "streamablehttp": "streamable_http",
        }.get(transport, transport)
    result = {**_CLIENT_DEFAULTS, **result}
    if any(
        (
            set(result) - set(_DEFAULT_CLIENT),
            not _text(result.get("name")),
            type(result["enabled"]) is not bool,
            not isinstance(result["description"], str),
            not _endpoint(result),
            (result["tools"] is not None and not _strings(result["tools"])),
            (
                result["oauth"] is not None
                and not isinstance(result["oauth"], Mapping)
            ),
        ),
    ):
        return None
    return result


def _policy_selectors(target: Mapping, principal: Mapping) -> bool:
    return (
        target.get("kind", "*") in ("tool", "*")
        and _text(target.get("name", "*"))
        and all(
            isinstance(principal.get(key, "*"), str)
            for key in (
                "source_type",
                "source_value",
                "subject_type",
                "subject_value",
            )
        )
        and not (
            principal.get("subject_type", "*").strip().lower() == "user"
            and not principal.get("subject_value", "*").strip()
        )
    )


def _policy(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list):
        value = {"default_effect": "deny", "rules": value}
    if not isinstance(value, Mapping):
        return None
    effect = value.get("default_effect", "deny")
    rules = value.get("rules", [])
    if effect not in ("allow", "deny", "ask") or not isinstance(rules, list):
        return None
    normalized = []
    for rule in rules:
        if not isinstance(rule, Mapping):
            return None
        if rule.get("effect", "ask") not in ("allow", "deny", "ask"):
            return None
        target = rule.get("target", {})
        principal = rule.get("principal", {})
        if (
            not isinstance(target, Mapping)
            or not isinstance(principal, Mapping)
            or not _policy_selectors(target, principal)
        ):
            return None
        normalized.append(
            {
                "subject": "*",
                "effect": "ask",
                "condition": None,
                **rule,
                "target": {"kind": "*", "name": "*", **target},
                "principal": {
                    "source_type": "*",
                    "source_value": "*",
                    "subject_type": "*",
                    "subject_value": "*",
                    **principal,
                },
            },
        )
    return {**value, "default_effect": effect, "rules": normalized}


def _card_status(value: Any) -> str:
    if not isinstance(value, Mapping) or set(value) - set(_DEFAULT_CARD):
        return "needs_review"
    endpoint = value.get("endpoint")
    credentials = value.get("credentials", {})
    config = value.get("config", {})
    policy = _policy(value.get("policy", {}))
    if any(
        (
            not _text(value.get("name")),
            value.get("protocol") != "mcp",
            type(value.get("enabled", True)) is not bool,
            not isinstance(config, Mapping),
            not isinstance(credentials, Mapping),
            policy is None,
        ),
    ):
        return "needs_review"
    if not isinstance(endpoint, Mapping) or not _endpoint(
        endpoint,
        credentials,
    ):
        return "needs_review"
    for alias, ref in credentials.items():
        if (
            not _text(alias)
            or not isinstance(ref, Mapping)
            or not _text(ref.get("kind"))
            or not _text(ref.get("ref"))
        ):
            return "needs_review"
    normalized = {
        "enabled": True,
        "credentials": {},
        "config": {},
        **value,
        "policy": policy,
    }
    if normalized == _DEFAULT_CARD:
        return "unused"
    # A historical static binding can hide either a default template or a real
    # secret. Without decrypting, neither unused nor auto-install is justified.
    return (
        "needs_review" if normalized == _OPAQUE_DEFAULT_CARD else "configured"
    )


def _workspace_status(workspace: MCPWorkspaceSnapshot) -> str:
    if workspace.errors or not isinstance(workspace.config, Mapping):
        return "needs_review"
    mcp = workspace.config.get("mcp", {})
    if not isinstance(mcp, Mapping) or set(mcp) - {
        "clients",
        "migration_version",
    }:
        return "needs_review"
    version = mcp.get("migration_version", 0)
    clients = mcp.get("clients", {})
    if (
        type(version) is not int
        or version not in (0, 1, 2)
        or not isinstance(clients, Mapping)
    ):
        return "needs_review"
    statuses = []
    for name, raw in clients.items():
        client = _client(raw)
        if not _text(name) or client is None:
            return "needs_review"
        statuses.append(
            (
                "unused"
                if name == "anysearch" and client == _DEFAULT_CLIENT
                else "configured"
            ),
        )
    names = set()
    for card in workspace.cards:
        if (
            not isinstance(card, Mapping)
            or not _text(card.get("name"))
            or not _text(card.get("protocol"))
            or not isinstance(card.get("endpoint"), Mapping)
        ):
            return "needs_review"
        if card["protocol"] != "mcp":
            continue
        name = card["name"]
        if name in names:
            statuses.append("needs_review")
            continue
        names.add(name)
        statuses.append(_card_status(card))
    return (
        "needs_review"
        if "needs_review" in statuses
        else "configured"
        if "configured" in statuses
        else "unused"
    )


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
    reasons = ["workspace_" + value for value in statuses.values()]
    if off:
        reasons.append("plugin_explicit_off")
    if invalid_settings:
        reasons.append("invalid_plugin_settings")
    return MCPUsageDecision(status, statuses, tuple(dict.fromkeys(reasons)))
