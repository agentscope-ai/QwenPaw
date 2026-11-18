# -*- coding: utf-8 -*-
"""Slash commands controlling the data-analysis bridge.

Handlers follow the SlashCommandRegistry contract:
``async (ctx: HookContext, args: str) -> Msg | None``.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from agentscope.message import Msg, TextBlock

from .engine_client import EngineClient, EngineClientError, EngineResponseError
from .session_store import BridgeSessionStore

logger = logging.getLogger(__name__)

_DATA_HELP = (
    "用法：/data on 开启数据分析模式（对话将由分析引擎处理）；" + "/data off 关闭；/data status 查看状态。"
)


def _reply(text: str) -> Msg:
    return Msg(
        name="system",
        role="system",
        content=[TextBlock(type="text", text=text)],
    )


def _session_key(ctx: Any) -> str:
    return getattr(ctx, "session_id", "") or ""


def make_data_command(
    store: BridgeSessionStore,
) -> Callable[[Any, str], Any]:
    async def data_command(ctx: Any, args: str) -> Optional[Msg]:
        key = _session_key(ctx)
        if not key:
            return _reply("无法识别当前会话，命令未生效。")
        action = (args or "").strip().lower()
        if action in ("on", "开启"):
            store.update(key, active=True)
            return _reply(
                "✅ 数据分析模式已开启：接下来的消息将交给分析引擎处理。\n"
                "可用 /datasource 选择数据源，/data off 退出。",
            )
        if action in ("off", "关闭"):
            store.update(
                key,
                active=False,
                pending_clarification=None,
                pending_datasource_choice=None,
            )
            return _reply("已退出数据分析模式，恢复普通对话。")
        if action in ("status", "状态", ""):
            state = store.get(key)
            if not state.active:
                return _reply(f"数据分析模式：未开启。{_DATA_HELP}")
            datasource = state.datasource_id or "未选择（使用全部可用上下文）"
            return _reply(
                "数据分析模式：已开启\n"
                f"引擎会话：{state.engine_session_id or '（首次提问时创建）'}\n"
                f"数据源：{datasource}",
            )
        return _reply(_DATA_HELP)

    return data_command


def make_datasource_command(
    store: BridgeSessionStore,
    client: EngineClient,
) -> Callable[[Any, str], Any]:
    async def datasource_command(ctx: Any, args: str) -> Optional[Msg]:
        _ = args
        key = _session_key(ctx)
        if not key:
            return _reply("无法识别当前会话，命令未生效。")
        state = store.get(key)
        if not state.active:
            return _reply("请先执行 /data on 开启数据分析模式。")
        try:
            items = await client.list_datasources()
        except EngineClientError as exc:
            if isinstance(exc, EngineResponseError) and not (
                500 <= exc.status_code < 600
            ):
                message = "无法获取数据源列表，请稍后重试。"
            else:
                message = "⚠️ 分析引擎当前不可用，无法获取数据源列表。"
            return _reply(message)
        options = [
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or item.get("id") or ""),
            }
            for item in items
            if item.get("id")
        ]
        if not options:
            return _reply("当前没有可用的数据源，请先在控制台接入数据。")
        store.update(key, pending_datasource_choice=options)
        lines = ["请选择数据源（回复编号）："]
        for index, option in enumerate(options, start=1):
            lines.append(f"{index}. {option['name']}")
        return _reply("\n".join(lines))

    return datasource_command
