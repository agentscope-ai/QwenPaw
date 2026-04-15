# -*- coding: utf-8 -*-
"""Shared agent template definitions and builders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config.config import (
    AgentProfileConfig,
    ChannelConfig,
    HeartbeatConfig,
    MCPConfig,
    ToolsConfig,
    build_local_agent_tools_config,
    build_qa_agent_tools_config,
)
from ..constant import BUILTIN_QA_AGENT_NAME, BUILTIN_QA_AGENT_SKILL_NAMES

DEFAULT_AGENT_TEMPLATE = "default"
LOCAL_AGENT_TEMPLATE = "local"
QA_AGENT_TEMPLATE = "qa"
SUPPORTED_AGENT_TEMPLATES = (
    DEFAULT_AGENT_TEMPLATE,
    LOCAL_AGENT_TEMPLATE,
    QA_AGENT_TEMPLATE,
)

LOCAL_TEMPLATE_SKILL_NAMES = ("make_plan",)
QA_TEMPLATE_DESCRIPTION = (
    "Builtin Q&A helper for QwenPaw setup, local config under "
    "QWENPAW_WORKING_DIR, and documentation. Prefer reading files "
    "before answering; use absolute paths for code outside this "
    "workspace."
)


@dataclass(frozen=True)
class AgentTemplateBuildResult:
    """Materialized result for creating an agent from a builtin template."""

    agent_config: AgentProfileConfig
    initial_skill_names: tuple[str, ...]
    md_template_id: str | None


def list_supported_agent_templates() -> tuple[str, ...]:
    """Return builtin agent template IDs supported by the application."""
    return SUPPORTED_AGENT_TEMPLATES


def get_workspace_md_template_id(template_id: str | None) -> str | None:
    """Map an agent template id to the workspace markdown template id."""
    if template_id in {LOCAL_AGENT_TEMPLATE, QA_AGENT_TEMPLATE}:
        return template_id
    return None


def build_agent_template(
    template_id: str,
    *,
    agent_id: str,
    workspace_dir: Path,
    fallback_language: str,
    name: str | None = None,
    description: str | None = None,
    language: str | None = None,
) -> AgentTemplateBuildResult:
    """Build a builtin template into a concrete agent configuration."""
    resolved_language = language or fallback_language or "zh"

    if template_id == DEFAULT_AGENT_TEMPLATE:
        if name is None:
            raise ValueError("Default template requires a name")
        agent_config = AgentProfileConfig(
            id=agent_id,
            name=name,
            description=description or "",
            workspace_dir=str(workspace_dir),
            template_id=template_id,
            language=resolved_language,
            channels=ChannelConfig(),
            mcp=MCPConfig(),
            heartbeat=HeartbeatConfig(),
            tools=ToolsConfig(),
        )
        return AgentTemplateBuildResult(
            agent_config=agent_config,
            initial_skill_names=(),
            md_template_id=get_workspace_md_template_id(template_id),
        )

    if template_id == LOCAL_AGENT_TEMPLATE:
        agent_config = AgentProfileConfig(
            id=agent_id,
            name=name or "Local Agent",
            description=(
                description or "An agent running on local deployed models."
            ),
            workspace_dir=str(workspace_dir),
            template_id=template_id,
            language=resolved_language,
            channels=ChannelConfig(),
            mcp=MCPConfig(),
            heartbeat=HeartbeatConfig(),
            tools=build_local_agent_tools_config(),
        )
        return AgentTemplateBuildResult(
            agent_config=agent_config,
            initial_skill_names=LOCAL_TEMPLATE_SKILL_NAMES,
            md_template_id=get_workspace_md_template_id(template_id),
        )

    if template_id == QA_AGENT_TEMPLATE:
        agent_config = AgentProfileConfig(
            id=agent_id,
            name=name or BUILTIN_QA_AGENT_NAME,
            description=description or QA_TEMPLATE_DESCRIPTION,
            workspace_dir=str(workspace_dir),
            template_id=template_id,
            language=resolved_language,
            channels=ChannelConfig(),
            mcp=MCPConfig(),
            heartbeat=HeartbeatConfig(),
            tools=build_qa_agent_tools_config(),
        )
        return AgentTemplateBuildResult(
            agent_config=agent_config,
            initial_skill_names=tuple(BUILTIN_QA_AGENT_SKILL_NAMES),
            md_template_id=get_workspace_md_template_id(template_id),
        )

    raise ValueError(
        f"Unsupported template: {template_id!r}. "
        f"Expected one of {SUPPORTED_AGENT_TEMPLATES}.",
    )
