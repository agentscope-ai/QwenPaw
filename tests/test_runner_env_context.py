# -*- coding: utf-8 -*-
import re

from copaw.app.runner.utils import build_env_context


def test_build_env_context_includes_local_time_timezone_rules() -> None:
    context = build_env_context(
        session_id="s1",
        user_id="u1",
        channel="console",
        working_dir="/tmp/copaw",
        add_hint=False,
    )

    assert re.search(
        r"- 当前本地时间: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}",
        context,
    )
    assert "- 当前本地时区:" in context
    assert re.search(r"UTC(?:[+-]\d{2}:\d{2})?", context)
    assert "日期解释规则" in context


def test_build_env_context_keeps_original_fields_and_hint() -> None:
    context = build_env_context(
        session_id="session-x",
        user_id="user-y",
        channel="qq",
        working_dir="/tmp/workspace",
        add_hint=True,
    )

    assert "- 当前的session_id: session-x" in context
    assert "- 当前的user_id: user-y" in context
    assert "- 当前的channel: qq" in context
    assert "- 工作目录: /tmp/workspace" in context
    assert "完成任务时，优先考虑使用 skills" in context
