# -*- coding: utf-8 -*-
"""Project QwenPaw runtime capabilities into Qoder SDK options."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from ..capabilities import HarnessRuntimeCapabilities

_PLUGIN_NAME = "qwenpaw-runtime"


def materialize_skill_plugin(
    state_dir: Path,
    capabilities: HarnessRuntimeCapabilities,
) -> Path | None:
    """Create an immutable local Qoder Plugin for effective Skills."""
    if not capabilities.skills:
        return None
    root = state_dir / "qoder" / "skills"
    target = root / capabilities.fingerprint
    if target.is_dir():
        return target

    root.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{capabilities.fingerprint}.",
            dir=root,
        ),
    )
    try:
        manifest_dir = temporary / ".qoder-plugin"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "plugin.json").write_text(
            json.dumps(
                {
                    "name": _PLUGIN_NAME,
                    "version": "1.0.0",
                    "description": (
                        "QwenPaw-managed Skills for this Harness session"
                    ),
                },
                ensure_ascii=True,
                indent=2,
            ),
            encoding="utf-8",
        )
        skill_root = temporary / "skills"
        skill_root.mkdir()
        for skill in capabilities.skills:
            shutil.copytree(
                skill.directory,
                skill_root / skill.name,
            )
        try:
            os.replace(temporary, target)
        except OSError:
            if not target.is_dir():
                raise
        return target
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def skill_names(
    capabilities: HarnessRuntimeCapabilities,
) -> list[str]:
    """Return Qoder's qualified names for projected Skills."""
    return [f"{_PLUGIN_NAME}:{skill.name}" for skill in capabilities.skills]


def mcp_servers(
    capabilities: HarnessRuntimeCapabilities,
) -> dict[str, Any]:
    """Convert resolved MCP servers to Qoder SDK dictionaries."""
    result: dict[str, Any] = {}
    for server in capabilities.mcp_servers:
        if server.tools is None and server.default_policy == "deny":
            continue
        tool_policies = [
            {
                "name": name,
                "permission_policy": _qoder_tool_policy(effect),
            }
            for name, effect in server.tool_policies.items()
        ]
        if server.transport == "stdio":
            config: dict[str, Any] = {
                "type": "stdio",
                "command": server.command,
                "args": list(server.args),
                "env": server.revealed_env(),
            }
        else:
            config = {
                "type": (
                    "http" if server.transport == "streamable_http" else "sse"
                ),
                "url": server.url,
                "headers": server.revealed_headers(),
            }
        if tool_policies:
            config["tools"] = tool_policies
        result[server.name] = config
    return result


def _qoder_tool_policy(effect: str) -> str:
    return {
        "allow": "always_allow",
        "ask": "always_ask",
        "deny": "always_deny",
    }.get(effect, "always_ask")


__all__ = [
    "materialize_skill_plugin",
    "mcp_servers",
    "skill_names",
]
