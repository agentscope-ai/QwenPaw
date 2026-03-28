# -*- coding: utf-8 -*-
"""Unit tests for DingTalk AI table tools."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from copaw.agents.tools import dingtalk_tools
from copaw.app import agent_context
from copaw.config import config as config_module
from copaw.config.config import _default_builtin_tools


def _tool_text(response) -> str:
    block = response.content[0]
    if isinstance(block, dict):
        return block["text"]
    return block.text


def _agent_config(client_id: str = "client-id", client_secret: str = "secret"):
    return SimpleNamespace(
        channels=SimpleNamespace(
            dingtalk=SimpleNamespace(
                client_id=client_id,
                client_secret=client_secret,
            ),
        ),
    )


def test_builtin_tool_defaults_include_dingtalk_ai_table_tools():
    builtin_tools = _default_builtin_tools()

    expected = {
        "dingtalk_ai_table_list_sheets",
        "dingtalk_ai_table_get_sheet",
        "dingtalk_ai_table_create_sheet",
        "dingtalk_ai_table_get_record",
        "dingtalk_ai_table_list_records",
        "dingtalk_ai_table_insert_records",
        "dingtalk_ai_table_update_records",
        "dingtalk_ai_table_delete_records",
    }

    assert expected.issubset(builtin_tools)


def test_list_sheets_calls_official_endpoint(monkeypatch):
    calls = []

    async def _fake_request(method, path, *, params=None, json_body=None):
        calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json_body": json_body,
            },
        )
        return {"value": [{"id": "sheet-1", "name": "任务"}]}

    monkeypatch.setattr(
        dingtalk_tools,
        "_request_dingtalk_json",
        _fake_request,
    )

    response = asyncio.run(
        dingtalk_tools.dingtalk_ai_table_list_sheets(
            "qnYxxx",
            "union_id",
        ),
    )

    assert json.loads(_tool_text(response)) == {
        "value": [{"id": "sheet-1", "name": "任务"}],
    }
    assert calls == [
        {
            "method": "GET",
            "path": "/v1.0/notable/bases/qnYxxx/sheets",
            "params": {"operatorId": "union_id"},
            "json_body": None,
        },
    ]


def test_get_sheet_encodes_sheet_name(monkeypatch):
    calls = []

    async def _fake_request(method, path, *, params=None, json_body=None):
        calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json_body": json_body,
            },
        )
        return {"id": "sheet-1", "name": "数据表 1"}

    monkeypatch.setattr(
        dingtalk_tools,
        "_request_dingtalk_json",
        _fake_request,
    )

    response = asyncio.run(
        dingtalk_tools.dingtalk_ai_table_get_sheet(
            "qnYxxx",
            "数据表 1",
            "union_id",
        ),
    )

    assert json.loads(_tool_text(response)) == {
        "id": "sheet-1",
        "name": "数据表 1",
    }
    assert (
        calls[0]["path"]
        == "/v1.0/notable/bases/qnYxxx/sheets/%E6%95%B0%E6%8D%AE%E8%A1%A8%201"
    )


def test_list_records_uses_empty_body_when_omitted(monkeypatch):
    calls = []

    async def _fake_request(method, path, *, params=None, json_body=None):
        calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json_body": json_body,
            },
        )
        return {"hasMore": False, "records": []}

    monkeypatch.setattr(
        dingtalk_tools,
        "_request_dingtalk_json",
        _fake_request,
    )

    response = asyncio.run(
        dingtalk_tools.dingtalk_ai_table_list_records(
            "qnYxxx",
            "任务表",
            "union_id",
        ),
    )

    assert json.loads(_tool_text(response)) == {
        "hasMore": False,
        "records": [],
    }
    assert calls == [
        {
            "method": "POST",
            "path": (
                "/v1.0/notable/bases/qnYxxx/sheets/"
                "%E4%BB%BB%E5%8A%A1%E8%A1%A8/records/list"
            ),
            "params": {"operatorId": "union_id"},
            "json_body": None,
        },
    ]


def test_insert_records_parses_body_json(monkeypatch):
    calls = []

    async def _fake_request(method, path, *, params=None, json_body=None):
        calls.append(
            {
                "method": method,
                "path": path,
                "params": params,
                "json_body": json_body,
            },
        )
        return {"value": [{"id": "recxxx"}]}

    monkeypatch.setattr(
        dingtalk_tools,
        "_request_dingtalk_json",
        _fake_request,
    )

    response = asyncio.run(
        dingtalk_tools.dingtalk_ai_table_insert_records(
            "qnYxxx",
            "任务表",
            "union_id",
            '{"records":[{"fields":{"标题":"文本"}}]}',
        ),
    )

    assert json.loads(_tool_text(response)) == {"value": [{"id": "recxxx"}]}
    assert calls == [
        {
            "method": "POST",
            "path": (
                "/v1.0/notable/bases/qnYxxx/sheets/"
                "%E4%BB%BB%E5%8A%A1%E8%A1%A8/records"
            ),
            "params": {"operatorId": "union_id"},
            "json_body": {"records": [{"fields": {"标题": "文本"}}]},
        },
    ]


def test_missing_dingtalk_credentials_returns_tool_error(monkeypatch):
    monkeypatch.setattr(
        agent_context,
        "get_current_agent_id",
        lambda: "default",
    )
    monkeypatch.setattr(
        config_module,
        "load_agent_config",
        lambda agent_id: _agent_config("", ""),
    )

    response = asyncio.run(
        dingtalk_tools.dingtalk_ai_table_list_sheets(
            "qnYxxx",
            "union_id",
        ),
    )

    assert "client_id/client_secret" in _tool_text(response)


def test_invalid_body_json_returns_tool_error():
    response = asyncio.run(
        dingtalk_tools.dingtalk_ai_table_create_sheet(
            "qnYxxx",
            "union_id",
            "{bad json",
        ),
    )

    assert "valid JSON" in _tool_text(response)
