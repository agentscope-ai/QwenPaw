# -*- coding: utf-8 -*-
"""Chat slash-command shortcut menu configuration.

Endpoints
---------
GET  /available  全量可用魔法命令（后端定义单一真相源）
GET  /           当前用户勾选的命令列表
PUT  /           更新勾选列表（写入 agent.json）
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Body, Request
from pydantic import BaseModel, Field

from ...config.config import save_agent_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat-commands", tags=["chat-commands"])


# ============================================================
# 模型
# ============================================================


class AvailableCommand(BaseModel):
    command: str  # 内部标识符，如 "clear" / "daemon_status"
    display: str  # 用户看到的文本，如 "/clear" / "/status"
    category: str  # context/history/model/session/control/daemon
    has_args: bool = False  # type: ignore


class ChatCommandsResponse(BaseModel):
    commands: list[str] = Field(default_factory=list)


class ChatCommandsUpdate(BaseModel):
    commands: list[str] = Field(default_factory=list, max_length=30)


# ============================================================
# 全量命令清单（后端单一真相源）
# ============================================================
# display 字段的值必须能被后端三个命令分发路径识别：
#   - command_handler.py  → SYSTEM_COMMANDS
#   - control_commands/   → 注册表
#   - daemon_commands.py  → DAEMON_SHORT_ALIASES / parse_daemon_query
# 前端构造 CommandSuggestion.value 时直接去掉前缀 / 即可。

_AVAILABLE_COMMANDS: list[AvailableCommand] = [
    # ---- 上下文 ----
    AvailableCommand(
        command="compact",
        display="/compact",
        category="context",
        has_args=False,
    ),
    AvailableCommand(
        command="clear",
        display="/clear",
        category="context",
        has_args=False,
    ),
    AvailableCommand(
        command="new",
        display="/new",
        category="context",
        has_args=False,
    ),
    # ---- 历史 ----
    AvailableCommand(
        command="history",
        display="/history",
        category="history",
        has_args=False,
    ),
    AvailableCommand(
        command="message",
        display="/message <n>",
        category="history",
        has_args=True,
    ),
    AvailableCommand(
        command="compact_str",
        display="/compact_str",
        category="history",
        has_args=False,
    ),
    AvailableCommand(
        command="summarize_status",
        display="/summarize_status",
        category="history",
        has_args=False,
    ),
    AvailableCommand(
        command="dump_history",
        display="/dump_history",
        category="history",
        has_args=False,
    ),
    AvailableCommand(
        command="load_history",
        display="/load_history",
        category="history",
        has_args=False,
    ),
    # ---- 模型 ----
    AvailableCommand(
        command="model",
        display="/model",
        category="model",
        has_args=True,
    ),
    # ---- 会话 ----
    AvailableCommand(
        command="mission",
        display="/mission",
        category="session",
        has_args=True,
    ),
    AvailableCommand(
        command="plan",
        display="/plan",
        category="session",
        has_args=True,
    ),
    AvailableCommand(
        command="proactive",
        display="/proactive",
        category="session",
        has_args=True,
    ),
    AvailableCommand(
        command="skills",
        display="/skills",
        category="session",
        has_args=False,
    ),
    # ---- 控制 ----
    AvailableCommand(
        command="stop",
        display="/stop",
        category="control",
        has_args=False,
    ),
    # ---- 守护（短别名，与 DAEMON_SHORT_ALIASES / parse_daemon_query 匹配）----
    AvailableCommand(
        command="daemon_status",
        display="/status",
        category="daemon",
        has_args=False,
    ),
    AvailableCommand(
        command="daemon_restart",
        display="/restart",
        category="daemon",
        has_args=False,
    ),
    AvailableCommand(
        command="daemon_reload_config",
        display="/reload-config",
        category="daemon",
        has_args=False,
    ),
    AvailableCommand(
        command="daemon_reload_config_alt",
        display="/reload_config",
        category="daemon",
        has_args=False,
    ),
    AvailableCommand(
        command="daemon_version",
        display="/version",
        category="daemon",
        has_args=False,
    ),
    AvailableCommand(
        command="daemon_logs",
        display="/logs",
        category="daemon",
        has_args=True,
    ),
]


# ============================================================
# 辅助
# ============================================================


async def _get_workspace(request: Request):
    from ..agent_context import get_agent_for_request

    return await get_agent_for_request(request)


# ============================================================
# 端点
# ============================================================


@router.get(
    "/available",
    response_model=list[AvailableCommand],
    summary="获取全量可用魔法命令",
)
async def get_available_commands() -> list[AvailableCommand]:
    """返回全量可用命令（含分类、参数标识）。

    前端用此数据生成设置面板的勾选列表。
    i18n 描述由前端根据 ``command`` 字段自推导 key：
        t(`chat.commands.${cmd.command}.description`)
    """
    return _AVAILABLE_COMMANDS


@router.get(
    "",
    response_model=ChatCommandsResponse,
    summary="获取当前快捷菜单命令配置",
)
async def get_chat_commands(request: Request) -> ChatCommandsResponse:
    """返回 agent.json 中 running.chat_commands 的当前值。

    若字段缺失（旧版 agent.json），利用 Pydantic default_factory 返回默认值。
    """
    workspace = await _get_workspace(request)
    commands = workspace.config.running.chat_commands
    return ChatCommandsResponse(commands=list(commands))


@router.put(
    "",
    response_model=ChatCommandsResponse,
    summary="更新快捷菜单命令配置",
)
async def put_chat_commands(
    request: Request,
    body: ChatCommandsUpdate = Body(...),
) -> ChatCommandsResponse:
    """更新用户在快捷菜单中显示的命令列表。

    白名单过滤 + 去重，防止脏数据写入 agent.json。
    """
    valid_names = {cmd.command for cmd in _AVAILABLE_COMMANDS}

    # 白名单过滤 + 保序去重
    seen: set[str] = set()
    filtered: list[str] = []
    for c in body.commands:
        if c in valid_names and c not in seen:
            filtered.append(c)
            seen.add(c)

    workspace = await _get_workspace(request)
    workspace.config.running.chat_commands = filtered
    save_agent_config(workspace.agent_id, workspace.config)

    return ChatCommandsResponse(commands=filtered)
