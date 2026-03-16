# -*- coding: utf-8 -*-
# pylint: disable=protected-access
from __future__ import annotations

import pytest

import copaw.providers.codex_chat_model as codex_chat_model_module
from copaw.providers.codex_chat_model import CodexResponsesChatModel

pytestmark = pytest.mark.anyio


class _FakeAuth:
    def __init__(self, access_token: str, account_id: str) -> None:
        self.access_token = access_token
        self.account_id = account_id


class _FakeProvider:
    def __init__(
        self,
        persisted: list[tuple[str, str]],
        access_token: str = "token",
        account_id: str = "acct",
    ) -> None:
        self.auth = _FakeAuth(access_token=access_token, account_id=account_id)
        self._persisted = persisted

    def persist(self) -> None:
        self._persisted.append(
            (self.auth.access_token, self.auth.account_id),
        )


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
    provider = _FakeProvider(persisted)
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
