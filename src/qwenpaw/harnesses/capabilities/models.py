# -*- coding: utf-8 -*-
"""Provider-neutral runtime capability models."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

MCPTransport = Literal["stdio", "streamable_http", "sse"]
MCPToolPolicy = Literal["allow", "ask", "deny"]


class HarnessSkillDefinition(BaseModel):
    """One QwenPaw Skill exposed to a third-party harness."""

    name: str
    description: str = ""
    directory: Path
    revision: str = ""


class HarnessMCPServerDefinition(BaseModel):
    """One resolved MCP server kept in runtime memory only."""

    name: str
    display_name: str
    transport: MCPTransport
    command: str = ""
    args: list[str] = Field(default_factory=list)
    cwd: Path | None = None
    url: str = ""
    env: dict[str, SecretStr] = Field(default_factory=dict)
    headers: dict[str, SecretStr] = Field(default_factory=dict)
    tools: list[str] | None = None
    tool_policies: dict[str, MCPToolPolicy] = Field(default_factory=dict)
    default_policy: MCPToolPolicy = "ask"
    credential_revision: str = ""
    runtime_revision: str = ""

    def revealed_env(self) -> dict[str, str]:
        """Return environment values at the Provider process boundary."""
        return {
            key: value.get_secret_value() for key, value in self.env.items()
        }

    def revealed_headers(self) -> dict[str, str]:
        """Return header values at the Provider process boundary."""
        return {
            key: value.get_secret_value()
            for key, value in self.headers.items()
        }

    def fingerprint_payload(self) -> dict[str, object]:
        """Return stable non-secret data used for client isolation."""
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": self.args,
            "cwd": str(self.cwd or ""),
            "url": self.url,
            "env_keys": sorted(self.env),
            "header_keys": sorted(self.headers),
            "tools": self.tools,
            "tool_policies": self.tool_policies,
            "default_policy": self.default_policy,
            "credential_revision": self.credential_revision,
            "runtime_revision": self.runtime_revision,
        }


class HarnessRuntimeCapabilities(BaseModel):
    """Effective Skills and MCP servers for one Harness request."""

    skills: list[HarnessSkillDefinition] = Field(default_factory=list)
    mcp_servers: list[HarnessMCPServerDefinition] = Field(
        default_factory=list,
    )

    @property
    def fingerprint(self) -> str:
        """Return a deterministic fingerprint without secret values."""
        payload = {
            "skills": [
                {
                    "name": skill.name,
                    "directory": str(skill.directory),
                    "revision": skill.revision,
                }
                for skill in self.skills
            ],
            "mcp_servers": [
                server.fingerprint_payload() for server in self.mcp_servers
            ],
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "HarnessMCPServerDefinition",
    "HarnessRuntimeCapabilities",
    "HarnessSkillDefinition",
    "MCPToolPolicy",
    "MCPTransport",
]
