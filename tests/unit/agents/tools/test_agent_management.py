# -*- coding: utf-8 -*-
"""Tests for agent discovery and inter-agent chat helpers."""

from __future__ import annotations

import httpx
from agentscope.tool import Toolkit

from qwenpaw.agents.tools import agent_management


class _FakeResponse:
    def __init__(self, json_data=None, lines=None, status_code=200):
        self._json_data = json_data or {}
        self._lines = lines or []
        self.status_code = status_code
        self.request = httpx.Request("GET", "http://test/api")

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "request failed",
                request=self.request,
                response=httpx.Response(
                    self.status_code,
                    request=self.request,
                ),
            )

    def iter_lines(self):
        yield from self._lines


class _FakeStreamContext:
    def __init__(self, response):
        self._response = response

    def __enter__(self):
        return self._response

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeClient:
    def __init__(
        self,
        get_response=None,
        post_response=None,
        stream_response=None,
    ):
        self.get_response = get_response or _FakeResponse()
        self.post_response = post_response or _FakeResponse()
        self.stream_response = stream_response or _FakeResponse(lines=[])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, *_args, **_kwargs):
        return self.get_response

    def post(self, *_args, **_kwargs):
        return self.post_response

    def stream(self, *_args, **_kwargs):
        return _FakeStreamContext(self.stream_response)


def test_build_agent_chat_request_adds_identity_prefix():
    (
        session_id,
        payload,
        prefix_added,
    ) = agent_management.build_agent_chat_request(
        "bot_b",
        "Need a summary",
        from_agent="bot_a",
    )

    assert session_id.startswith("bot_a:to:bot_b:")
    assert prefix_added is True
    assert payload["session_id"] == session_id
    assert payload["input"][0]["content"][0]["text"].startswith(
        "[Agent bot_a requesting] ",
    )


def test_build_agent_chat_request_discovers_calling_agent(monkeypatch):
    monkeypatch.setattr(
        agent_management,
        "resolve_calling_agent_id",
        lambda _from_agent=None: "auto_bot",
    )

    (
        session_id,
        payload,
        prefix_added,
    ) = agent_management.build_agent_chat_request(
        "bot_b",
        "Need a summary",
        from_agent=None,
    )

    assert session_id.startswith("auto_bot:to:bot_b:")
    assert payload["input"][0]["content"][0]["text"].startswith(
        "[Agent auto_bot requesting] ",
    )
    assert prefix_added is True


def test_build_agent_chat_request_reuses_session_id_when_provided():
    (
        session_id,
        payload,
        prefix_added,
    ) = agent_management.build_agent_chat_request(
        "bot_b",
        "Need a summary",
        session_id="existing-session",
        from_agent="bot_a",
    )

    assert session_id == "existing-session"
    assert payload["session_id"] == "existing-session"
    assert prefix_added is True


def test_list_agents_data_uses_shared_client(monkeypatch):
    fake_client = _FakeClient(
        get_response=_FakeResponse(
            json_data={
                "agents": [
                    {"id": "default", "name": "Default", "enabled": True},
                ],
            },
        ),
    )
    monkeypatch.setattr(
        agent_management,
        "create_agent_api_client",
        lambda _base_url: fake_client,
    )

    result = agent_management.list_agents_data("http://127.0.0.1:8088")

    assert result["agents"][0]["id"] == "default"


def test_extract_agent_ids_normalizes_values():
    result = agent_management.extract_agent_ids(
        {
            "agents": [
                {"id": "bot_a"},
                {"id": "bot_b"},
                {"id": None},
                "invalid",
            ],
        },
    )

    assert result == {"bot_a", "bot_b"}


def test_resolve_agent_api_base_url_uses_last_api(monkeypatch):
    monkeypatch.setattr(
        agent_management,
        "read_last_api",
        lambda: ("192.168.1.8", 18088),
    )

    result = agent_management.resolve_agent_api_base_url()

    assert result == "http://192.168.1.8:18088"


def test_resolve_agent_api_base_url_falls_back_to_default(monkeypatch):
    monkeypatch.setattr(agent_management, "read_last_api", lambda: None)

    result = agent_management.resolve_agent_api_base_url()

    assert result == agent_management.DEFAULT_AGENT_API_BASE_URL


def test_collect_final_agent_chat_response_keeps_last_sse_payload(monkeypatch):
    fake_lines = [
        'data: {"output": [{"content": [{"type": "text", "text": "first"}]}]}',
        (
            'data: {"output": [{"content": '
            '[{"type": "text", "text": "second"}]}]}'
        ),
    ]
    fake_client = _FakeClient(stream_response=_FakeResponse(lines=fake_lines))
    monkeypatch.setattr(
        agent_management,
        "create_agent_api_client",
        lambda _base_url: fake_client,
    )

    result = agent_management.collect_final_agent_chat_response(
        "http://127.0.0.1:8088",
        {"session_id": "sid", "input": []},
        "bot_b",
        30,
    )

    assert result is not None
    assert agent_management.extract_agent_text_content(result) == "second"


def test_agent_management_tools_can_be_registered_in_toolkit():
    toolkit = Toolkit()

    toolkit.register_tool_function(agent_management.list_agents)
    toolkit.register_tool_function(agent_management.chat_with_agent)

    schemas = toolkit.get_json_schemas()
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert "list_agents" in schema_names
    assert "chat_with_agent" in schema_names


async def test_list_agents_uses_to_thread(monkeypatch):
    monkeypatch.setattr(
        agent_management,
        "list_agents_data",
        lambda _base_url: {"agents": [{"id": "bot_a"}]},
    )

    calls = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(agent_management.asyncio, "to_thread", fake_to_thread)

    response = await agent_management.list_agents()

    assert calls
    assert calls[0][0] is agent_management.list_agents_data
    assert '"id": "bot_a"' in response.content[0].get("text", "")


async def test_chat_with_agent_formats_finished_background_result(monkeypatch):
    monkeypatch.setattr(
        agent_management,
        "get_agent_chat_task_status",
        lambda *_args, **_kwargs: {
            "status": "finished",
            "result": {
                "status": "completed",
                "session_id": "sid-1",
                "output": [
                    {
                        "content": [
                            {"type": "text", "text": "Background reply"},
                        ],
                    },
                ],
            },
        },
    )

    response = await agent_management.chat_with_agent(
        from_agent="bot_a",
        to_agent="bot_b",
        text="hello",
        background=True,
        task_id="task-1",
    )

    text = response.content[0].get("text", "")
    assert "[TASK_ID: task-1]" in text
    assert "Background reply" in text


async def test_chat_with_agent_uses_to_thread_for_final_mode(monkeypatch):
    monkeypatch.setattr(
        agent_management,
        "collect_final_agent_chat_response",
        lambda *_args, **_kwargs: {
            "output": [
                {
                    "content": [
                        {"type": "text", "text": "reply from peer"},
                    ],
                },
            ],
        },
    )

    calls = []

    async def fake_to_thread(func, *args, **kwargs):
        calls.append((func, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(agent_management.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(
        agent_management,
        "resolve_calling_agent_id",
        lambda _from_agent=None: "auto_bot",
    )
    monkeypatch.setattr(
        agent_management,
        "agent_exists",
        lambda _to_agent, _base_url=None: True,
    )

    response = await agent_management.chat_with_agent(
        to_agent="bot_b",
        text="Need help",
    )

    assert calls
    assert calls[-1][0] is agent_management.collect_final_agent_chat_response
    assert "reply from peer" in response.content[0].get("text", "")


async def test_chat_with_agent_normalizes_agent_ids(monkeypatch):
    captured = {}

    def fake_collect_final(_base_url, request_payload, to_agent, _timeout):
        captured["to_agent"] = to_agent
        captured["session_id"] = request_payload["session_id"]
        captured["text"] = request_payload["input"][0]["content"][0]["text"]
        return {
            "output": [
                {
                    "content": [
                        {"type": "text", "text": "reply from peer"},
                    ],
                },
            ],
        }

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(
        agent_management,
        "collect_final_agent_chat_response",
        fake_collect_final,
    )
    monkeypatch.setattr(agent_management.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(
        agent_management,
        "agent_exists",
        lambda _to_agent, _base_url=None: True,
    )

    response = await agent_management.chat_with_agent(
        to_agent='  "bot_b"  ',
        text="Need help",
        from_agent="  'bot_a'  ",
    )

    assert captured["to_agent"] == "bot_b"
    assert captured["session_id"].startswith("bot_a:to:bot_b:")
    assert captured["text"].startswith("[Agent bot_a requesting] ")
    assert "reply from peer" in response.content[0].get("text", "")


async def test_chat_with_agent_returns_clear_error_when_agent_missing(
    monkeypatch,
):
    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(agent_management.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(
        agent_management,
        "agent_exists",
        lambda _to_agent, _base_url=None: False,
    )

    response = await agent_management.chat_with_agent(
        to_agent='  "missing_bot"  ',
        text="Need help",
    )

    assert (
        response.content[0].get("text", "") == "Agent [missing_bot] not exists"
    )
