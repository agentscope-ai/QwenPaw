# -*- coding: utf-8 -*-
"""QWENPAW_SESSION_ID 注入单测（#8156 / 同 Agent 多会话串根治）.

验证 ``execute_shell_command`` 的会话 ID 注入块：当前会话（framework
contextvar ``get_current_session_id``，由 request_setup hook 每请求设置）
被注入 shell 子进程 env 的 ``QWENPAW_SESSION_ID``——

- matrix 场景 → ``matrix:<room_id>``
- console 场景 → console session id
- 无会话（None/空）→ 不注入（外部工具降级到显式/env 指定）

被测逻辑与 ``shell.py`` ``execute_shell_command`` 中的注入块逐行一致；
抽成单元函数以便隔离测试（不拉起完整 shell 子进程/agent 上下文）。
"""
from __future__ import annotations

import pytest


def _inject_session_env() -> dict:
    """复制 ``shell.py`` ``execute_shell_command`` 的 QWENPAW_SESSION_ID 注入块。"""
    env: dict[str, str] = {}
    try:
        from qwenpaw.app.agent_context import get_current_session_id

        _sid = get_current_session_id()
        if _sid:
            env["QWENPAW_SESSION_ID"] = str(_sid)
    except Exception:  # noqa: BLE001 - 注入失败不阻塞（与实现一致）
        pass
    return env


@pytest.fixture(autouse=True)
def _reset_session():
    from qwenpaw.app.agent_context import set_current_session_id

    set_current_session_id(None)
    yield
    set_current_session_id(None)


def test_injects_matrix_room_session():
    from qwenpaw.app.agent_context import set_current_session_id

    set_current_session_id("matrix:!abc123:matrix.example")
    assert (
        _inject_session_env().get("QWENPAW_SESSION_ID")
        == "matrix:!abc123:matrix.example"
    )


def test_injects_console_session():
    from qwenpaw.app.agent_context import set_current_session_id

    set_current_session_id("1789368185062-b1556de")
    assert (
        _inject_session_env().get("QWENPAW_SESSION_ID")
        == "1789368185062-b1556de"
    )


def test_omits_when_no_session():
    assert "QWENPAW_SESSION_ID" not in _inject_session_env()
