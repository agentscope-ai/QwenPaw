# -*- coding: utf-8 -*-
"""A2A mode — ``AgentMode`` for A2A agent communication.

Exposes ``/a2a`` slash command via ``SlashCommandRegistry``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from agentscope.message import Msg, TextBlock

from qwenpaw.modes.base import AgentMode
from qwenpaw.runtime.slash_command_registry import CommandSpec

if TYPE_CHECKING:
    from qwenpaw.runtime.hooks import HookContext

logger = logging.getLogger("qwenpaw").getChild(
    __name__.replace("plugin_cloudpaw.", ""),
)

_A2A_CONFIG_FILENAME = "a2a_config.json"


def _load_a2a_agents(workspace_dir: Path) -> dict[str, dict]:
    """Load per-agent A2A config from workspace."""
    path = workspace_dir / _A2A_CONFIG_FILENAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("agents", {})
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return {}


def _info_msg(text: str) -> Msg:
    """Wrap text into a system Msg for display."""
    return Msg(
        name="system",
        content=[TextBlock(type="text", text=text)],
        role="system",
    )


def _rewrite_user_msg(ctx: "HookContext", text: str) -> None:
    """Replace the last user message with *text*."""
    msgs = getattr(ctx, "input_msgs", None)
    if not msgs:
        return
    last = msgs[-1]
    if not isinstance(last, Msg):
        return
    last.content = [TextBlock(type="text", text=text)]


class A2AMode(AgentMode):
    """Bundle for A2A mode behaviour."""

    name = "a2a"

    def commands(self) -> list[CommandSpec]:
        """Register ``/a2a`` as a standard command."""
        return [
            CommandSpec(
                name="a2a",
                handler=self._a2a_handler,
                category="plugin",
                help_text="List or call remote A2A agents",
                metadata={"plugin": "cloudpaw"},
            ),
        ]

    async def _a2a_handler(
        self,
        ctx: "HookContext",
        args: str,
    ) -> Optional[Msg]:
        """Handle ``/a2a [args]``.

        * ``/a2a`` (no args) — list registered A2A agents
        * ``/a2a list`` — list registered A2A agents
        * ``/a2a <alias> <message>`` — rewrite for a2a_call
        """
        workspace_dir = getattr(ctx, "workspace_dir", None)
        if not workspace_dir:
            return _info_msg("Error: workspace_dir not available")

        agents_cfg = _load_a2a_agents(Path(workspace_dir))

        # No args or "list": list agents
        if not args or not args.strip() or args.strip().lower() == "list":
            return await self._handle_list(agents_cfg)

        # Parse args: <alias> <message>
        parts = args.strip().split(None, 1)
        if len(parts) < 2:
            return _info_msg(
                "用法：`/a2a <agent_name> <message>`\n\n"
                "使用 `/a2a` 或 `/a2a list` 查看可用的 agent 列表。",
            )

        agent_name, message = parts[0].strip(), parts[1].strip()

        # Check if agent exists
        if agent_name not in agents_cfg:
            available = ", ".join(agents_cfg.keys()) if agents_cfg else "无"
            return _info_msg(
                f"未找到别名为 '{agent_name}' 的已注册 A2A Agent。\n\n"
                f"可用别名：{available}",
            )

        # Rewrite message for agent to call a2a_call
        prompt = (
            f"请使用 a2a_call 工具调用远程 A2A Agent。\n"
            f'调用参数：agent_alias="{agent_name}"，'
            f'message="{message}"\n\n'
            f"请直接调用 a2a_call 工具完成此任务，不需要做其他额外操作。"
        )

        _rewrite_user_msg(ctx, prompt)
        logger.info("[CloudPaw] /a2a rewritten for agent processing")
        return None  # Let agent process the rewritten message

    async def _handle_list(self, agents_cfg: dict[str, dict]) -> Msg:
        """List registered A2A agents."""
        if not agents_cfg:
            return _info_msg(
                "暂无已注册的远程 A2A Agent。\n\n"
                "使用 POST /api/a2a/agents 注册新的 Agent，"
                "或在 A2A 管理页面添加。",
            )

        try:
            from modules.a2a.client_manager import get_a2a_manager
        except ImportError:
            # Fallback: just list aliases
            lines = ["**已注册的远程 A2A Agent：\n"]
            for alias in agents_cfg.keys():
                lines.append(f"- {alias}")
            footer = "\n---\n*Use `/a2a <alias> <message>` to send a message.*"
            lines.append(footer)
            return _info_msg("\n".join(lines))
        manager = get_a2a_manager()

        lines = ["**已注册的远程 A2A Agent：**\n"]
        for alias, reg in agents_cfg.items():
            card_info = await manager.get_card_info(reg["url"])
            status = (
                card_info.get("status", "disconnected")
                if card_info
                else "disconnected"
            )
            name = card_info.get("name", "") if card_info else ""
            desc = card_info.get("description", "") if card_info else ""
            status_icon = "🟢" if status == "connected" else "⚪"

            line = f"\n{status_icon} **{alias}**"
            if name:
                line += f" — {name}"
            if desc:
                line += f"\n   {desc[:80]}"
            if status != "connected":
                line += f"\n   状态: {status}"
            lines.append(line)

        footer = (
            "\n---\n"
            "*Use `/a2a <alias> <message>` to send a message "
            "to a remote Agent.*"
        )
        lines.append(footer)

        return _info_msg("\n".join(lines))


__all__ = ["A2AMode"]
