# -*- coding: utf-8 -*-
"""Slash command catalog for the web chat sender."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from ..agent_context import get_agent_for_request
from ...agents.skill_runtime import discover_enabled_skills

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slash", tags=["slash"])

SlashItemType = Literal["command", "skill", "mcp_client", "mcp_tool"]


class SlashCatalogItem(BaseModel):
    """One selectable slash item."""

    id: str = Field(..., description="Stable item id")
    type: SlashItemType = Field(..., description="Item category")
    label: str = Field(..., description="Display label")
    command: str = Field(..., description="Slash command")
    insertText: str = Field(..., description="Text inserted into sender")
    description: str = Field(default="", description="Short description")
    icon: str = Field(default="", description="Emoji or short icon")
    group: str = Field(default="", description="Display group")
    enabled: bool = Field(default=True, description="Whether item is usable")


def _command_items(plan_enabled: bool) -> list[SlashCatalogItem]:
    items = [
        SlashCatalogItem(
            id="command:clear",
            type="command",
            label="/clear",
            command="/clear",
            insertText="/clear",
            description="Clear current chat history",
            icon="⌫",
            group="Commands",
        ),
        SlashCatalogItem(
            id="command:compact",
            type="command",
            label="/compact",
            command="/compact",
            insertText="/compact",
            description="Compact conversation context",
            icon="▤",
            group="Commands",
        ),
        SlashCatalogItem(
            id="command:mission",
            type="command",
            label="/mission",
            command="/mission",
            insertText="/mission ",
            description="Start mission workflow",
            icon="◎",
            group="Commands",
        ),
        SlashCatalogItem(
            id="command:skills",
            type="command",
            label="/skills",
            command="/skills",
            insertText="/skills ",
            description="List or invoke enabled skills",
            icon="✦",
            group="Commands",
        ),
        SlashCatalogItem(
            id="command:dream",
            type="command",
            label="/dream",
            command="/dream",
            insertText="/dream ",
            description="Run one private-memory optimization pass",
            icon="☾",
            group="Memory",
        ),
        SlashCatalogItem(
            id="command:memorize",
            type="command",
            label="/memorize",
            command="/memorize",
            insertText="/memorize ",
            description="Memorize recent assistant replies",
            icon="◆",
            group="Memory",
        ),
        SlashCatalogItem(
            id="command:reme_status",
            type="command",
            label="/reme_status",
            command="/reme_status",
            insertText="/reme_status",
            description="Inspect the active ReMe memory runtime",
            icon="ⓘ",
            group="Memory",
        ),
    ]
    if plan_enabled:
        items.append(
            SlashCatalogItem(
                id="command:plan",
                type="command",
                label="/plan",
                command="/plan",
                insertText="/plan ",
                description="Create a plan before execution",
                icon="□",
                group="Commands",
            ),
        )
    return items


@router.get("/catalog", response_model=list[SlashCatalogItem])
async def slash_catalog(request: Request) -> list[SlashCatalogItem]:
    """Return slash-selectable commands, skills, and MCP entries."""
    workspace = await get_agent_for_request(request)
    agent_config = workspace.config
    plan_enabled = bool(getattr(getattr(agent_config, "plan", None), "enabled", False))
    skill_items: list[SlashCatalogItem] = []
    mcp_items: list[SlashCatalogItem] = []

    for skill in discover_enabled_skills(workspace.workspace_dir, "console"):
        skill_items.append(
            SlashCatalogItem(
                id=f"skill:{skill.name}",
                type="skill",
                label=skill.name,
                command=f"/{skill.name}",
                insertText=f"/{skill.name} ",
                description=skill.description,
                icon="✦",
                group="Skills",
            ),
        )

    from ..mcp.config_service import MCPConfigService

    mcp_service = MCPConfigService(workspace)
    for card in await mcp_service.list_cards():
        client_key = card.name
        if not card.enabled:
            continue
        client_name = str(card.config.get("display_name") or client_key)
        mcp_items.append(
            SlashCatalogItem(
                id=f"mcp-client:{client_key}",
                type="mcp_client",
                label=client_name,
                command=f"/mcp {client_key}",
                insertText=f"/mcp {client_key} ",
                description=str(card.config.get("description") or ""),
                icon="◇",
                group="MCP",
            ),
        )
        manager = getattr(workspace, "driver_manager", None)
        if manager is None:
            continue
        try:
            tools = await manager.list_driver_capabilities(
                client_key,
                kind="tool",
                request_context={},
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.debug(
                "Failed to list MCP tools for slash catalog: %s %s",
                client_key,
                exc,
            )
            continue
        for tool in tools:
            tool_name = getattr(tool, "name", "") or ""
            if not tool_name:
                continue
            mcp_items.append(
                SlashCatalogItem(
                    id=f"mcp-tool:{client_key}.{tool_name}",
                    type="mcp_tool",
                    label=f"{client_key}.{tool_name}",
                    command=f"/mcp {client_key}.{tool_name}",
                    insertText=f"/mcp {client_key}.{tool_name} ",
                    description=getattr(tool, "description", "") or "",
                    icon="◇",
                    group="MCP",
                ),
            )

    return [
        *_command_items(plan_enabled),
        *skill_items,
        *mcp_items,
    ]
