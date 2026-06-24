# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
from pathlib import Path

from qwenpaw.runtime.commands.control.base import (
    BaseControlCommandHandler,
    ControlContext,
)

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


class A2AListCommandHandler(BaseControlCommandHandler):
    """Control command ``/a2a``.

    * ``/a2a`` (no args) — list registered remote A2A agents.
    * ``/a2a <agent_name> <message>`` — normally intercepted by the
      query-rewrite hook in ``hooks.py`` *before* reaching this handler.
      If the hook cannot rewrite (unknown alias, missing config, etc.),
      this handler returns a user-friendly error.
    """

    command_name = "/a2a"

    async def handle(self, context: ControlContext) -> str:
        workspace_dir = context.workspace.workspace_dir
        agents_cfg = _load_a2a_agents(workspace_dir)
        raw_args = context.args.get("_raw_args", "").strip()

        if raw_args:
            return self._handle_direct_call_fallback(agents_cfg, raw_args)

        return await self._handle_list(agents_cfg)

    async def _handle_list(self, agents_cfg: dict[str, dict]) -> str:
        from modules.a2a.client_manager import get_a2a_manager

        if not agents_cfg:
            return (
                "暂无已注册的远程 A2A Agent。\n\n"
                "使用 POST /a2a/agents 注册新的 Agent，"
                "或在 A2A 管理页面添加。"
            )

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
        lines.append(
            "\n---\n"
            "*Use `/a2a <alias> <message>` to"
            " send a message to a remote Agent.*",
        )

        return "\n".join(lines)

    @staticmethod
    def _handle_direct_call_fallback(
        agents_cfg: dict[str, dict],
        raw_args: str,
    ) -> str:
        """Fallback when the query-rewrite hook did not intercept.

        This only runs if the hook could not rewrite the query (e.g. the
        alias is invalid).  Return a helpful error message.
        """
        parts = raw_args.split(None, 1)
        if len(parts) < 2:
            return (
                "用法：`/a2a <agent_name> <message>`\n\n"
                "使用 `/a2a` 查看可用的 agent 列表。"
            )

        agent_name = parts[0].strip()

        if agent_name not in agents_cfg:
            available = ", ".join(agents_cfg.keys()) if agents_cfg else "无"
            return (
                f"未找到别名为 '{agent_name}' 的已注册 A2A Agent。\n\n"
                f"可用别名：{available}"
            )

        return f"正在将请求转发给 Agent '{agent_name}' 处理，" f"请稍候..."
