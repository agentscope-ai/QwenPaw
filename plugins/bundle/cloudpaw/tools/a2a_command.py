# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from qwenpaw.app.runner.control_commands.base import (
    BaseControlCommandHandler,
    ControlContext,
)

logger = logging.getLogger(__name__)

A2A_STREAM_MARKER = "__A2A_STREAM_START__"

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
    command_name = "/a2a"

    async def handle(self, context: ControlContext) -> str:
        workspace_dir = context.workspace.workspace_dir
        agents_cfg = _load_a2a_agents(workspace_dir)
        raw_args = context.args.get("_raw_args", "").strip()

        if raw_args:
            return await self._handle_direct_call(agents_cfg, raw_args)

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
            "\n---\n使用 `/a2a <agent_name> <message>` 直接向远程 Agent 发送消息，例如：",
        )
        for alias in agents_cfg:
            lines.append(f"  `/a2a {alias} 如何部署 ECS？`")

        return "\n".join(lines)

    async def _handle_direct_call(
        self,
        agents_cfg: dict[str, dict],
        raw_args: str,
    ) -> str:
        from .a2a_call import a2a_call
        from modules.a2a.call_stream import start_stream

        parts = raw_args.split(None, 1)
        if len(parts) < 2:
            return (
                "用法：`/a2a <agent_name> <message>`"
                "\n\n使用 `/a2a` 查看可用的 agent 列表。"
            )

        agent_name, message = parts[0].strip(), parts[1].strip()
        if not message:
            return "用法：`/a2a <agent_name> <message>`" "\n\n消息内容不能为空。"

        if agent_name not in agents_cfg:
            available = ", ".join(agents_cfg.keys()) if agents_cfg else "无"
            return f"未找到别名为 '{agent_name}' 的已注册 A2A Agent。\n\n可用别名：{available}"

        # Create the stream queue BEFORE returning the marker so the SSE
        # endpoint can find it immediately when the frontend subscribes.
        start_stream()
        logger.info("A2A stream queue created for direct call to %s", agent_name)

        asyncio.create_task(
            self._run_a2a_call_in_background(a2a_call, message, agent_name)
        )

        return A2A_STREAM_MARKER

    @staticmethod
    async def _run_a2a_call_in_background(
        a2a_call_fn, message: str, agent_name: str
    ) -> None:
        """Run the actual A2A call in the background.

        ``a2a_call`` internally manages ``start_stream()`` /
        ``finish_stream()`` and pushes incremental progress to the
        queue.  We only swallow the final ToolResponse — the frontend
        receives all progress via the SSE endpoint.
        """
        try:
            await a2a_call_fn(message=message, agent_alias=agent_name)
        except Exception as e:
            logger.error("A2A direct call failed for %s: %s", agent_name, e)
            last_error = str(e)

        if last_error and not accumulated_text:
            return f"[远程 Agent '{agent_name}' 调用失败]" f" 错误：{last_error}"
        if last_error:
            return f"{accumulated_text}" f"\n\n[调用完成，但有错误: {last_error}]"
        return accumulated_text or f"[远程 Agent '{agent_name}' 返回空响应]"
