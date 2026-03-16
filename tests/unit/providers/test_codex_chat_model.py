# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace

import pytest

import copaw.providers.codex_chat_model as codex_chat_model_module
from copaw.providers.codex_chat_model import CodexResponsesChatModel

pytestmark = pytest.mark.anyio


def _make_model() -> CodexResponsesChatModel:
    return CodexResponsesChatModel(
        model_name="gpt-5.3-codex",
        access_token="token",
        account_id="acct",
        stream=True,
    )


def test_build_payload_flattens_function_tools_for_codex() -> None:
    model = _make_model()

    payload = model._build_payload(
        messages=[
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                            },
                        },
                        "required": ["path"],
                    },
                    "strict": False,
                },
            },
        ],
        tool_choice=None,
    )

    assert payload["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                    },
                },
                "required": ["path"],
            },
            "strict": False,
        },
    ]


def test_build_payload_formats_specific_tool_choice_for_codex() -> None:
    model = _make_model()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
    ]

    payload = model._build_payload(
        messages=[
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        ],
        tools=tools,
        tool_choice="read_file",
    )

    assert payload["tool_choice"] == {
        "type": "function",
        "name": "read_file",
    }


def test_build_payload_encodes_assistant_history_as_output_text() -> None:
    model = _make_model()

    payload = model._build_payload(
        messages=[
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Hey! 👋"}],
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": "你是什么模型"}],
            },
        ],
        tools=None,
        tool_choice=None,
    )

    assert payload["input"] == [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "hi"}],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Hey! 👋"}],
        },
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "你是什么模型"}],
        },
    ]


async def test_refresh_auth_persists_updated_tokens(monkeypatch) -> None:
    persisted: list[tuple[str, str]] = []
    provider = SimpleNamespace(
        auth=SimpleNamespace(access_token="token", account_id="acct"),
        persist=lambda: persisted.append(
            (provider.auth.access_token, provider.auth.account_id),
        ),
    )
    model = CodexResponsesChatModel(
        model_name="gpt-5.3-codex",
        access_token="token",
        account_id="acct",
        stream=True,
        provider=provider,
    )

    async def fake_refresh(current, save_callback):
        current.auth.access_token = "token-2"
        current.auth.account_id = "acct-2"
        save_callback(current)
        return current.auth

    monkeypatch.setattr(
        codex_chat_model_module,
        "refresh_provider_auth",
        fake_refresh,
    )

    await model._refresh_auth_if_needed()
    await model.aclose()

    assert model.access_token == "token-2"
    assert model.account_id == "acct-2"
    assert persisted == [("token-2", "acct-2")]


async def test_aclose_closes_http_client() -> None:
    model = _make_model()

    await model.aclose()

    assert model.http.is_closed is True
