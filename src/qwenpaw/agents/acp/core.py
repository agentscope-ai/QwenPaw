# -*- coding: utf-8 -*-
"""ACP shared definitions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, model_validator


class ACPAgentConfig(BaseModel):
    """Configuration for one ACP agent."""

    enabled: bool = False
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    trusted: bool = True
    tool_parse_mode: str = "call_title"


def _default_agents() -> Dict[str, ACPAgentConfig]:
    return {
        "opencode": ACPAgentConfig(
            enabled=True,
            command="opencode",
            args=["acp"],
            trusted=True,
            tool_parse_mode="update_detail",
        ),
        "qwen_code": ACPAgentConfig(
            enabled=True,
            command="qwen",
            args=["--acp"],
            trusted=True,
            tool_parse_mode="call_detail",
        ),
        "claude_code": ACPAgentConfig(
            enabled=True,
            command="npx",
            args=["-y", "@zed-industries/claude-agent-acp"],
            trusted=True,
            tool_parse_mode="update_detail",
        ),
        "codex": ACPAgentConfig(
            enabled=True,
            command="npx",
            args=["-y", "@zed-industries/codex-acp"],
            trusted=True,
            tool_parse_mode="call_detail",
        ),
        # "gemini_cli": ACPAgentConfig(
        #     enabled=True,
        #     command="npx",
        #     args=["-y", "@google/gemini-cli@latest", "--experimental-acp"],
        #     trusted=True,
        # ),
    }


class ACPConfig(BaseModel):
    """Minimal ACP config used by delegate_external_agent."""

    agents: Dict[str, ACPAgentConfig] = Field(default_factory=_default_agents)

    @model_validator(mode="after")
    def _merge_default_agents(self):
        for name, agent_cfg in _default_agents().items():
            if name not in self.agents:
                self.agents[name] = agent_cfg
        return self


class ACPErrors(Exception):
    def __init__(self, message: str, *, agent: Optional[str] = None):
        super().__init__(message)
        self.agent = agent


class ACPConfigurationError(ACPErrors):
    pass


class ACPTransportError(ACPErrors):
    pass


class ACPProtocolError(ACPErrors):
    pass


class ACPSessionError(ACPErrors):
    pass


@dataclass
class SuspendedPermission:
    payload: dict[str, Any]
    options: list[dict[str, Any]]
    agent: str
    tool_name: str
    tool_kind: str
    target: str | None = None
    action: str | None = None
    summary: str | None = None
    command: str | None = None
    paths: list[str] = field(default_factory=list)
    requires_user_confirmation: bool = True
