# -*- coding: utf-8 -*-
"""Tests for DataPaw dialogue trace submission."""
from __future__ import annotations

import asyncio
import json

import pytest

from plugin_datapaw.core import trace_submitter
from plugin_datapaw.core.trace_submitter import (
    CM_BASE_URL_ENV,
    _build_trace_payload,
    submit_trace_from_session,
)


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class _RecordingAsyncClient:
    captured: list[dict] = []
    status_code = 200
    raise_on_post = False

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    async def __aenter__(self) -> "_RecordingAsyncClient":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def post(self, url, json=None, headers=None):  # noqa: A002
        type(self).captured.append(
            {"url": url, "json": json, "headers": headers},
        )
        if type(self).raise_on_post:
            raise RuntimeError("network down")
        return _FakeResponse(type(self).status_code)


class _FakeSession:
    def __init__(self, state: dict) -> None:
        self.state = state

    async def get_session_state_dict(self, *args, **kwargs) -> dict:
        return self.state


class _FakeRunner:
    def __init__(self, state: dict) -> None:
        self.session = _FakeSession(state)


@pytest.fixture
def recording_client(monkeypatch: pytest.MonkeyPatch):
    _RecordingAsyncClient.captured = []
    _RecordingAsyncClient.status_code = 200
    _RecordingAsyncClient.raise_on_post = False
    monkeypatch.setattr(
        trace_submitter.httpx,
        "AsyncClient",
        _RecordingAsyncClient,
    )
    return _RecordingAsyncClient


def _state_for(messages: list[dict]) -> dict:
    return {
        "agent": {
            "memory": {
                "content": [[message, []] for message in messages],
            },
        },
    }


def test_build_trace_payload_slices_current_dialogue_and_sorts() -> None:
    messages = [
        {
            "id": "u1",
            "timestamp": "2026-06-25 10:00:00.000",
            "role": "user",
            "content": [{"type": "text", "text": "old"}],
        },
        {
            "id": "a1",
            "timestamp": "2026-06-25 10:00:01.000",
            "role": "assistant",
            "content": [{"type": "text", "text": "old answer"}],
        },
        {
            "id": "a2",
            "timestamp": "2026-06-25 10:00:03.000",
            "role": "assistant",
            "content": [{"type": "text", "text": "answer"}],
        },
        {
            "id": "u2",
            "timestamp": "2026-06-25 10:00:02.000",
            "role": "user",
            "content": [{"type": "text", "text": "new"}],
        },
    ]

    payload = _build_trace_payload(
        session_id="s1",
        user_id="default",
        messages=messages,
        request_context={"datasource_id": "ds1"},
        trigger_msg_id="u2",
    )

    assert [message["id"] for message in payload["messages"]] == ["u2", "a2"]
    assert payload["metadata"] == json.dumps(
        {"datasource_id": "ds1"},
        ensure_ascii=False,
    )
    assert "agent_name" not in payload


def test_build_trace_payload_falls_back_to_last_user_split() -> None:
    messages = [
        {"id": "u1", "timestamp": "2026-06-25 10:00:00.000", "role": "user"},
        {
            "id": "a1",
            "timestamp": "2026-06-25 10:00:01.000",
            "role": "assistant",
        },
        {"id": "u2", "timestamp": "2026-06-25 10:00:02.000", "role": "user"},
        {
            "id": "a2",
            "timestamp": "2026-06-25 10:00:03.000",
            "role": "assistant",
        },
    ]

    payload = _build_trace_payload(
        session_id="s1",
        user_id="default",
        messages=messages,
    )

    assert [message["id"] for message in payload["messages"]] == ["u2", "a2"]


def test_submit_trace_skips_when_cm_base_url_unset(
    monkeypatch: pytest.MonkeyPatch,
    recording_client,
) -> None:
    monkeypatch.delenv(CM_BASE_URL_ENV, raising=False)
    runner = _FakeRunner(_state_for([]))

    ok = asyncio.run(
        submit_trace_from_session(
            runner=runner,
            session_id="s1",
            user_id="default",
            channel="console",
        ),
    )

    assert ok is False
    assert recording_client.captured == []


def test_submit_trace_posts_dialogue_payload(
    monkeypatch: pytest.MonkeyPatch,
    recording_client,
) -> None:
    monkeypatch.setenv(CM_BASE_URL_ENV, "http://cm.local/")
    runner = _FakeRunner(
        _state_for(
            [
                {
                    "id": "u1",
                    "timestamp": "2026-06-25 10:00:00.000",
                    "role": "user",
                },
                {
                    "id": "a1",
                    "timestamp": "2026-06-25 10:00:01.000",
                    "role": "assistant",
                },
                {
                    "id": "u2",
                    "timestamp": "2026-06-25 10:00:02.000",
                    "role": "user",
                },
                {
                    "id": "a2",
                    "timestamp": "2026-06-25 10:00:03.000",
                    "role": "assistant",
                    "content": "streaming answer",
                    "metadata": {"graph_id": "g1"},
                },
            ],
        ),
    )

    ok = asyncio.run(
        submit_trace_from_session(
            runner=runner,
            session_id="s1",
            user_id="default",
            channel="console",
            request_context={"datasource_id": "ds1"},
            trigger_msg_id="u2",
        ),
    )

    assert ok is True
    assert len(recording_client.captured) == 1
    sent = recording_client.captured[0]
    assert sent["url"] == "http://cm.local/api/v1/trace/submit_trace"
    assert sent["headers"]["X-Request-Id"]
    assert sent["json"]["session_id"] == "s1"
    assert sent["json"]["user_id"] == "default"
    assert "agent_name" not in sent["json"]
    assert sent["json"]["metadata"] == '{"datasource_id": "ds1"}'
    assert [msg["id"] for msg in sent["json"]["messages"]] == ["u2", "a2"]
    assert sent["json"]["messages"][1]["content"] == "streaming answer"
    assert sent["json"]["messages"][1]["metadata"] == {"graph_id": "g1"}


def test_submit_trace_swallows_http_status_errors(
    monkeypatch: pytest.MonkeyPatch,
    recording_client,
) -> None:
    monkeypatch.setenv(CM_BASE_URL_ENV, "http://cm.local")
    recording_client.status_code = 404
    runner = _FakeRunner(
        _state_for(
            [
                {
                    "id": "u1",
                    "timestamp": "2026-06-25 10:00:00.000",
                    "role": "user",
                },
            ],
        ),
    )

    ok = asyncio.run(
        submit_trace_from_session(
            runner=runner,
            session_id="s1",
            user_id="default",
            channel="console",
        ),
    )

    assert ok is False
    assert len(recording_client.captured) == 1


def test_submit_trace_swallows_network_errors(
    monkeypatch: pytest.MonkeyPatch,
    recording_client,
) -> None:
    monkeypatch.setenv(CM_BASE_URL_ENV, "http://cm.local")
    recording_client.raise_on_post = True
    runner = _FakeRunner(
        _state_for(
            [
                {
                    "id": "u1",
                    "timestamp": "2026-06-25 10:00:00.000",
                    "role": "user",
                },
            ],
        ),
    )

    ok = asyncio.run(
        submit_trace_from_session(
            runner=runner,
            session_id="s1",
            user_id="default",
            channel="console",
        ),
    )

    assert ok is False
