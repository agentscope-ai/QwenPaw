# -*- coding: utf-8 -*-
"""内置 Token 工具不得读取部署全局数据。"""

from __future__ import annotations

from uuid import uuid4
import importlib

import pytest

from qwenpaw.token_usage.manager import TokenUsageSummary

tool_module = importlib.import_module("qwenpaw.agents.tools.get_token_usage")


@pytest.mark.asyncio
async def test_multi_user_tool_queries_current_user_only(monkeypatch) -> None:
    user_id = uuid4()
    captured = {}

    class Service:
        async def get_summary(self, **kwargs):
            captured.update(kwargs)
            return TokenUsageSummary(total_prompt_tokens=7, total_calls=1)

    monkeypatch.setattr(tool_module, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(tool_module, "get_current_user_id", lambda: str(user_id))
    monkeypatch.setattr(tool_module, "_usage_scope_service", lambda: Service())

    await tool_module.get_token_usage(days=7)

    assert captured["scope"] == "personal"
    assert captured["actor"].user_id == user_id
