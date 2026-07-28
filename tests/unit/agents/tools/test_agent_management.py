# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Tests for agent discovery and inter-agent chat helpers."""

from __future__ import annotations

import json

import httpx
from agentscope.tool import FunctionTool
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


async def test_agent_management_tools_can_be_registered_in_toolkit():
    toolkit = Toolkit(
        tools=[
            FunctionTool(agent_management.list_agents),
            FunctionTool(agent_management.chat_with_agent),
        ],
    )

    schemas = await toolkit.get_tool_schemas()
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
    assert '"id": "bot_a"' in response.content[0].text


async def test_check_agent_task_formats_finished_background_result(
    monkeypatch,
):
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

    response = await agent_management.check_agent_task("task-1")

    text = response.content[0].text
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
    assert "reply from peer" in response.content[0].text


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
    monkeypatch.setattr(
        agent_management,
        "resolve_calling_agent_id",
        lambda _from_agent=None: "bot_a",
    )

    response = await agent_management.chat_with_agent(
        to_agent='  "bot_b"  ',
        text="Need help",
    )

    assert captured["to_agent"] == "bot_b"
    assert captured["session_id"].startswith("bot_a:to:bot_b:")
    assert captured["text"].startswith("[Agent bot_a requesting] ")
    assert "reply from peer" in response.content[0].text


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

    assert response.content[0].text == "Agent [missing_bot] not exists"


async def test_spawn_subagent_inherits_root_channel_context(monkeypatch):
    captured = {}

    def fake_collect(_base_url, request_payload, to_agent, _timeout):
        captured["payload"] = request_payload
        captured["agent_id"] = to_agent
        return {
            "output": [
                {"content": [{"type": "text", "text": "done"}]},
            ],
        }

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    from qwenpaw.app import agent_context

    monkeypatch.setattr(
        agent_management,
        "collect_final_agent_chat_response",
        fake_collect,
    )
    monkeypatch.setattr(agent_management.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(agent_context, "get_current_agent_id", lambda: "bot-a")
    monkeypatch.setattr(
        agent_context,
        "get_current_approval_route",
        lambda: {
            "root_session_id": "root-session",
            "root_agent_id": "bot-a",
            "user_id": "u1",
            "channel": "qq",
            "channel_meta": {"group_openid": "g1", "opaque": object()},
        },
    )

    response = await agent_management.spawn_subagent("do work")

    context = captured["payload"]["request_context"]
    assert captured["agent_id"] == "bot-a"
    assert "user_id" not in captured["payload"]
    assert "channel" not in captured["payload"]
    assert context["root_session_id"] == "root-session"
    assert context["root_agent_id"] == "bot-a"
    assert context["channel"] == "qq"
    assert context["user_id"] == "u1"
    assert context["channel_meta"] == {"group_openid": "g1"}
    assert context["_spawn_subagent"] is True
    assert "done" in response.content[0].text


def test_normalize_str_list_accepts_json_array_string():
    assert agent_management._normalize_str_list(
        '["read_file", "write_file"]',
        "allowed_tools",
    ) == ["read_file", "write_file"]
    assert agent_management._normalize_str_list(None, "skills") is None
    assert agent_management._normalize_str_list([], "skills") == []


def test_normalize_str_list_rejects_plain_string():
    try:
        agent_management._normalize_str_list("read_file", "allowed_tools")
    except ValueError as exc:
        assert "allowed_tools" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-JSON string")


def test_normalize_batch_accepts_json_array_string():
    raw = json.dumps(
        [
            {"task": "do A", "fork": False},
            {"task": "do B", "fork": True},
        ],
    )
    out = agent_management._normalize_batch(raw)
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[0]["task"] == "do A"
    assert out[1]["fork"] is True


def test_coerce_bool_string_false_is_false():
    assert agent_management._coerce_bool("false") is False
    assert agent_management._coerce_bool("true") is True
    assert agent_management._coerce_bool(False) is False
    assert agent_management._coerce_bool(None, default=True) is True
    assert agent_management._coerce_bool(0) is False
    assert agent_management._coerce_bool(1) is True
    # Python bool("false") is True — must not use that.
    assert bool("false") is True


def test_coerce_bool_rejects_ambiguous_values():
    for bad in ("null", "None", "nope", "fals", "maybe", "", "2", 2, 0.5):
        try:
            agent_management._coerce_bool(bad, field_name="fork")
        except ValueError as exc:
            assert "fork" in str(exc)
        else:
            raise AssertionError(f"expected ValueError for {bad!r}")


def test_coerce_timeout_accepts_numeric_and_rejects_non_positive():
    assert agent_management._coerce_timeout("600") == 600
    assert agent_management._coerce_timeout(30.9) == 30
    assert agent_management._coerce_timeout(1) == 1
    # Truncation of (0, 1) must not silently become timeout=0.
    for bad in (
        0,
        -1,
        "0",
        "-1",
        0.5,
        0.9,
        "0.5",
        "1e-9",
        "abc",
        True,
        False,
        "",
    ):
        try:
            agent_management._coerce_timeout(bad, field_name="timeout")
        except ValueError as exc:
            assert "timeout" in str(exc)
        else:
            raise AssertionError(f"expected ValueError for {bad!r}")


def test_spawn_subagent_schema_accepts_batch_string():
    """Tool JSON schema must allow string so AgentScope validation passes."""
    import jsonschema

    tool = FunctionTool(agent_management.spawn_subagent)
    schema = tool.input_schema
    # Stringified batch (the live LLM failure mode) must validate.
    jsonschema.validate(
        {
            "task": "",
            "batch": (
                '[{"task": "Create A", "fork": false},'
                ' {"task": "Create B"}]'
            ),
        },
        schema,
    )
    # Native list still validates.
    jsonschema.validate(
        {
            "task": "",
            "batch": [{"task": "Create A"}, {"task": "Create B"}],
        },
        schema,
    )
    # Top-level fork/background string forms (LLM mis-serialization).
    jsonschema.validate(
        {"task": "do work", "fork": "false", "background": "true"},
        schema,
    )
    jsonschema.validate(
        {"task": "do work", "fork": False, "background": True},
        schema,
    )
    # Integer 0/1 aligns with _coerce_bool (common LLM numeric bools).
    jsonschema.validate(
        {"task": "do work", "fork": 0, "background": 1},
        schema,
    )
    # Top-level timeout string (LLM mis-serialization).
    jsonschema.validate(
        {"task": "do work", "timeout": "600"},
        schema,
    )
    jsonschema.validate(
        {
            "task": "",
            "batch": [{"task": "ok"}],
            "timeout": "600",
        },
        schema,
    )


async def test_spawn_subagent_batch_json_string_dispatches(monkeypatch):
    submitted: list[dict] = []

    def fake_submit(
        _base,
        payload,
        agent_id,
        _timeout,
        task_timeout=None,  # pylint: disable=unused-argument
    ):
        submitted.append({"agent_id": agent_id, "payload": payload})
        return {"task_id": f"t-{len(submitted)}"}

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    from qwenpaw.app import agent_context

    monkeypatch.setattr(
        agent_management,
        "submit_agent_chat_task",
        fake_submit,
    )
    monkeypatch.setattr(agent_management.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(agent_context, "get_current_agent_id", lambda: "bot-a")
    monkeypatch.setattr(
        agent_context,
        "get_current_approval_route",
        lambda: None,
    )
    monkeypatch.setattr(agent_context, "get_current_session_id", lambda: "s1")
    monkeypatch.setattr(agent_context, "get_current_user_id", lambda: "u1")
    monkeypatch.setattr(
        agent_context,
        "get_current_channel",
        lambda: "console",
    )
    monkeypatch.setattr(
        agent_context,
        "get_current_root_session_id",
        lambda: "s1",
    )

    batch_json = json.dumps(
        [
            {"task": "create file a", "fork": False},
            {"task": "create file b", "fork": "false"},
        ],
    )
    response = await agent_management.spawn_subagent(
        task="",
        batch=batch_json,
    )
    text = response.content[0].text
    assert "[1/2]" in text
    assert "[2/2]" in text
    assert len(submitted) == 2
    assert submitted[0]["agent_id"] == "bot-a"
    # fork="false" must not take the fork path (no fork_project_dir).
    for item in submitted:
        rc = item["payload"]["request_context"]
        assert "fork_project_dir" not in rc


async def test_spawn_subagent_batch_list_still_works(monkeypatch):
    submitted: list[dict] = []

    def fake_submit(
        _base,
        payload,
        _agent_id,
        _timeout,
        task_timeout=None,  # pylint: disable=unused-argument
    ):
        submitted.append(payload)
        return {"task_id": f"t-{len(submitted)}"}

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    from qwenpaw.app import agent_context

    monkeypatch.setattr(
        agent_management,
        "submit_agent_chat_task",
        fake_submit,
    )
    monkeypatch.setattr(agent_management.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(agent_context, "get_current_agent_id", lambda: "bot-a")
    monkeypatch.setattr(
        agent_context,
        "get_current_approval_route",
        lambda: None,
    )
    monkeypatch.setattr(agent_context, "get_current_session_id", lambda: "s1")
    monkeypatch.setattr(agent_context, "get_current_user_id", lambda: "u1")
    monkeypatch.setattr(
        agent_context,
        "get_current_channel",
        lambda: "console",
    )
    monkeypatch.setattr(
        agent_context,
        "get_current_root_session_id",
        lambda: "s1",
    )

    response = await agent_management.spawn_subagent(
        task="",
        batch=[
            {"task": "one", "allowed_tools": '["read_file"]'},
            {"task": "two"},
        ],
    )
    assert "[1/2]" in response.content[0].text
    assert len(submitted) == 2
    rc0 = submitted[0]["request_context"]
    assert rc0.get("subagent_allowed_tools") == ["read_file"]


async def test_spawn_subagent_batch_invalid_string_returns_error():
    response = await agent_management.spawn_subagent(
        task="",
        batch="not-json-array",
    )
    assert "ERROR" in response.content[0].text
    assert "batch" in response.content[0].text.lower()


async def test_spawn_subagent_batch_ignores_top_level_ignored_fields(
    monkeypatch,
):
    """Batch mode ignores invalid top-level fork/tools/skills/timeout."""
    submitted: list[dict] = []

    def fake_submit(
        _base,
        payload,
        _agent_id,
        _timeout,
        task_timeout=None,  # pylint: disable=unused-argument
    ):
        submitted.append(payload)
        return {"task_id": f"t-{len(submitted)}"}

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    from qwenpaw.app import agent_context

    monkeypatch.setattr(
        agent_management,
        "submit_agent_chat_task",
        fake_submit,
    )
    monkeypatch.setattr(agent_management.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(agent_context, "get_current_agent_id", lambda: "bot-a")
    monkeypatch.setattr(
        agent_context,
        "get_current_approval_route",
        lambda: None,
    )
    monkeypatch.setattr(agent_context, "get_current_session_id", lambda: "s1")
    monkeypatch.setattr(agent_context, "get_current_user_id", lambda: "u1")
    monkeypatch.setattr(
        agent_context,
        "get_current_channel",
        lambda: "console",
    )
    monkeypatch.setattr(
        agent_context,
        "get_current_root_session_id",
        lambda: "s1",
    )

    response = await agent_management.spawn_subagent(
        task="",
        batch=[{"task": "ok"}],
        fork="null",
        background="maybe",
        allowed_tools="null",
        skills="null",
        timeout="600",
    )
    text = response.content[0].text
    assert "ERROR" not in text
    assert "[1/1]" in text
    assert len(submitted) == 1

    # Plain non-JSON string for tools must also be ignored at top level.
    submitted.clear()
    response2 = await agent_management.spawn_subagent(
        task="",
        batch=[{"task": "ok2"}],
        allowed_tools="read_file",
        skills="read_file",
    )
    assert "ERROR" not in response2.content[0].text
    assert len(submitted) == 1


async def test_spawn_subagent_batch_ambiguous_fork_errors_before_dispatch(
    monkeypatch,
):
    """Illegal batch fork must ERROR with zero submits / fork spawns."""
    submitted: list[dict] = []
    forked: list[str] = []

    def fake_submit(
        _base,
        payload,
        _agent_id,
        _timeout,
        task_timeout=None,  # pylint: disable=unused-argument
    ):
        submitted.append(payload)
        return {"task_id": f"t-{len(submitted)}"}

    async def fake_forked(**kwargs):
        forked.append(kwargs.get("task", ""))
        return agent_management._tool_text_response("forked")

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    from qwenpaw.app import agent_context

    monkeypatch.setattr(
        agent_management,
        "submit_agent_chat_task",
        fake_submit,
    )
    monkeypatch.setattr(
        agent_management,
        "_spawn_forked_subagent",
        fake_forked,
    )
    monkeypatch.setattr(agent_management.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(agent_context, "get_current_agent_id", lambda: "bot-a")
    monkeypatch.setattr(
        agent_context,
        "get_current_approval_route",
        lambda: None,
    )
    monkeypatch.setattr(agent_context, "get_current_session_id", lambda: "s1")
    monkeypatch.setattr(agent_context, "get_current_user_id", lambda: "u1")
    monkeypatch.setattr(
        agent_context,
        "get_current_channel",
        lambda: "console",
    )
    monkeypatch.setattr(
        agent_context,
        "get_current_root_session_id",
        lambda: "s1",
    )

    response = await agent_management.spawn_subagent(
        task="",
        batch=[{"task": "t", "fork": "null"}],
    )
    text = response.content[0].text
    assert text.startswith("ERROR:")
    assert "fork" in text.lower()
    assert not submitted
    assert not forked

    # Mixed batch: one good item must not partially dispatch.
    response2 = await agent_management.spawn_subagent(
        task="",
        batch=[
            {"task": "ok-task", "fork": False},
            {"task": "bad-task", "fork": "null"},
        ],
    )
    text2 = response2.content[0].text
    assert text2.startswith("ERROR:")
    assert "batch[1].fork" in text2
    assert not submitted
    assert not forked


async def test_spawn_subagent_top_level_string_bools(monkeypatch):
    """Top-level fork/background strings: schema-safe + no false fork."""
    collected: list[dict] = []
    forked: list[str] = []

    def fake_collect(_base, payload, _agent_id, _timeout):
        collected.append(payload)
        return {
            "output": [
                {"content": [{"type": "text", "text": "done"}]},
            ],
        }

    async def fake_forked(**kwargs):
        forked.append(kwargs.get("task", ""))
        return agent_management._tool_text_response("forked")

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    from qwenpaw.app import agent_context

    monkeypatch.setattr(
        agent_management,
        "collect_final_agent_chat_response",
        fake_collect,
    )
    monkeypatch.setattr(
        agent_management,
        "_spawn_forked_subagent",
        fake_forked,
    )
    monkeypatch.setattr(agent_management.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(agent_context, "get_current_agent_id", lambda: "bot-a")
    monkeypatch.setattr(
        agent_context,
        "get_current_approval_route",
        lambda: None,
    )
    monkeypatch.setattr(agent_context, "get_current_session_id", lambda: "s1")
    monkeypatch.setattr(agent_context, "get_current_user_id", lambda: "u1")
    monkeypatch.setattr(
        agent_context,
        "get_current_channel",
        lambda: "console",
    )
    monkeypatch.setattr(
        agent_context,
        "get_current_root_session_id",
        lambda: "s1",
    )

    # fork="false" must NOT take the fork path.
    response = await agent_management.spawn_subagent(
        task="do work",
        fork="false",
        background="false",
    )
    assert "ERROR" not in response.content[0].text
    assert "done" in response.content[0].text
    assert not forked
    assert len(collected) == 1
    assert "fork_project_dir" not in collected[0]["request_context"]

    collected.clear()
    bad = await agent_management.spawn_subagent(
        task="do work",
        fork="null",
    )
    assert bad.content[0].text.startswith("ERROR:")
    assert "fork" in bad.content[0].text.lower()
    assert not collected
    assert not forked

    bad_bg = await agent_management.spawn_subagent(
        task="do work",
        background="maybe",
    )
    assert bad_bg.content[0].text.startswith("ERROR:")
    assert "background" in bad_bg.content[0].text.lower()
    assert not collected

    # String timeout is accepted on the single-spawn path.
    collected.clear()
    ok_timeout = await agent_management.spawn_subagent(
        task="do work",
        timeout="600",
    )
    assert "ERROR" not in ok_timeout.content[0].text
    assert len(collected) == 1

    collected.clear()
    bad_timeout = await agent_management.spawn_subagent(
        task="do work",
        timeout="abc",
    )
    assert bad_timeout.content[0].text.startswith("ERROR:")
    assert "timeout" in bad_timeout.content[0].text.lower()
    assert not collected


async def test_spawn_subagent_batch_item_timeout_errors_before_dispatch(
    monkeypatch,
):
    """Illegal batch item timeout must ERROR with zero submits."""
    submitted: list[dict] = []
    forked: list[str] = []

    def fake_submit(
        _base,
        payload,
        _agent_id,
        _timeout,
        task_timeout=None,  # pylint: disable=unused-argument
    ):
        submitted.append(payload)
        return {"task_id": f"t-{len(submitted)}"}

    async def fake_forked(**kwargs):
        forked.append(kwargs.get("task", ""))
        return agent_management._tool_text_response("forked")

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    from qwenpaw.app import agent_context

    monkeypatch.setattr(
        agent_management,
        "submit_agent_chat_task",
        fake_submit,
    )
    monkeypatch.setattr(
        agent_management,
        "_spawn_forked_subagent",
        fake_forked,
    )
    monkeypatch.setattr(agent_management.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(agent_context, "get_current_agent_id", lambda: "bot-a")
    monkeypatch.setattr(
        agent_context,
        "get_current_approval_route",
        lambda: None,
    )
    monkeypatch.setattr(agent_context, "get_current_session_id", lambda: "s1")
    monkeypatch.setattr(agent_context, "get_current_user_id", lambda: "u1")
    monkeypatch.setattr(
        agent_context,
        "get_current_channel",
        lambda: "console",
    )
    monkeypatch.setattr(
        agent_context,
        "get_current_root_session_id",
        lambda: "s1",
    )

    response = await agent_management.spawn_subagent(
        task="",
        batch=[
            {"task": "a"},
            {"task": "b", "timeout": "abc"},
        ],
    )
    text = response.content[0].text
    assert text.startswith("ERROR:")
    assert "batch[1].timeout" in text
    assert not submitted
    assert not forked

    # Sub-second values truncate to 0 and must not dispatch.
    response2 = await agent_management.spawn_subagent(
        task="",
        batch=[{"task": "a", "timeout": 0.5}],
    )
    text2 = response2.content[0].text
    assert text2.startswith("ERROR:")
    assert "timeout" in text2.lower()
    assert not submitted
    assert not forked

    response3 = await agent_management.spawn_subagent(
        task="",
        batch=json.dumps([{"task": "a", "timeout": "0.5"}]),
    )
    text3 = response3.content[0].text
    assert text3.startswith("ERROR:")
    assert "timeout" in text3.lower()
    assert not submitted
    assert not forked
