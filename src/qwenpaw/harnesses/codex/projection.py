# -*- coding: utf-8 -*-
"""Project QwenPaw runtime capabilities into Codex configuration."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from ..capabilities import HarnessRuntimeCapabilities

_ENV_KEY_PATTERN = re.compile(r"[^A-Za-z0-9_]")
_CONFIG_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class CodexRuntimeProjection:
    """Codex process configuration without persisted secret values."""

    config_overrides: tuple[str, ...] = ()
    environment: dict[str, str] = field(default_factory=dict)
    skill_roots: tuple[str, ...] = ()


def project_runtime(
    capabilities: HarnessRuntimeCapabilities,
) -> CodexRuntimeProjection:
    """Convert shared capabilities into Codex app-server settings."""
    overrides: list[str] = []
    environment: dict[str, str] = {}
    forwarded_stdio_env: dict[str, str] = {}
    for server in capabilities.mcp_servers:
        prefix = f"mcp_servers.{_config_key(server.name)}"
        if server.transport == "stdio":
            overrides.extend(
                [
                    _override(prefix, "command", server.command),
                    _override(prefix, "args", server.args),
                ],
            )
            if server.cwd is not None:
                overrides.append(
                    _override(prefix, "cwd", str(server.cwd)),
                )
            env_names: list[str] = []
            for name, value in server.revealed_env().items():
                previous = forwarded_stdio_env.get(name)
                if previous is not None and previous != value:
                    raise ValueError(
                        f"Codex MCP servers require conflicting values for "
                        f"environment variable {name}.",
                    )
                forwarded_stdio_env[name] = value
                environment[name] = value
                env_names.append(name)
            if env_names:
                overrides.append(
                    _override(prefix, "env_vars", sorted(env_names)),
                )
        else:
            overrides.append(_override(prefix, "url", server.url))
            header_env: dict[str, str] = {}
            for header, value in server.revealed_headers().items():
                env_name = _header_env_name(server.name, header)
                environment[env_name] = value
                header_env[header] = env_name
            if header_env:
                overrides.append(
                    _override(
                        prefix,
                        "env_http_headers",
                        header_env,
                    ),
                )
        _append_tool_policy(overrides, prefix, server)
    return CodexRuntimeProjection(
        config_overrides=tuple(overrides),
        environment=environment,
        skill_roots=tuple(
            str(skill.directory) for skill in capabilities.skills
        ),
    )


def _append_tool_policy(
    overrides: list[str],
    prefix: str,
    server,
) -> None:
    if server.tools is not None:
        enabled = [
            name
            for name in server.tools
            if server.tool_policies.get(name, server.default_policy) != "deny"
        ]
        overrides.append(_override(prefix, "enabled_tools", enabled))
    elif server.default_policy == "deny":
        overrides.append(_override(prefix, "enabled_tools", []))
    overrides.append(
        _override(
            prefix,
            "default_tools_approval_mode",
            {
                "allow": "approve",
                "ask": "prompt",
                "deny": "prompt",
            }[server.default_policy],
        ),
    )
    for name, effect in sorted(server.tool_policies.items()):
        if effect == "deny" or not _CONFIG_KEY_PATTERN.fullmatch(name):
            continue
        tool_prefix = f"{prefix}.tools.{name}"
        overrides.append(
            _override(
                tool_prefix,
                "approval_mode",
                "approve" if effect == "allow" else "prompt",
            ),
        )


def _override(prefix: str, name: str, value) -> str:
    return f"{prefix}.{name}={_toml_value(value)}"


def _toml_value(value) -> str:
    if isinstance(value, dict):
        items = ", ".join(
            f"{json.dumps(str(key))} = {_toml_value(item)}"
            for key, item in sorted(value.items())
        )
        return f"{{ {items} }}"
    return json.dumps(value, ensure_ascii=True)


def _header_env_name(server_name: str, header: str) -> str:
    normalized = _ENV_KEY_PATTERN.sub(
        "_",
        f"{server_name}_{header}",
    ).upper()
    digest = (
        hashlib.sha256(
            f"{server_name}:{header}".encode("utf-8"),
        )
        .hexdigest()[:12]
        .upper()
    )
    return f"QWENPAW_MCP_{normalized[:32]}_{digest}"


def _config_key(name: str) -> str:
    if _CONFIG_KEY_PATTERN.fullmatch(name):
        return name
    normalized = _ENV_KEY_PATTERN.sub("_", name).strip("_") or "server"
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:10]
    return f"{normalized[:32]}_{digest}"


__all__ = ["CodexRuntimeProjection", "project_runtime"]
