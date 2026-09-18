# -*- coding: utf-8 -*-
"""Chat reuse avoids I/O without leaking across tasks or identities."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.services.request_chat import bind_request_chat, get_request_chat
from qwenpaw.services.model_selection import (
    prepare_model_context,
    clear_current_model_context,
)
from qwenpaw.hooks.request_setup.contextvars_hook import _session_project_dirs
from qwenpaw.app.task_tracker import TaskTracker


def _chat(session_id="session"):
    return SimpleNamespace(
        id="chat",
        session_id=session_id,
        user_id="user",
        channel="console",
        meta={"runtime_context": {"project_dirs": [{"path": "/project"}]}},
    )


@pytest.mark.asyncio
async def test_snapshot_inherits_into_task_and_thread_but_not_caller():
    manager = object()
    chat = _chat()
    gate = asyncio.Event()
    tracker = TaskTracker()
    observed = []

    async def consume(_payload):
        await gate.wait()
        snapshot = await asyncio.to_thread(
            get_request_chat,
            manager,
            "session",
            "user",
            "console",
        )
        observed.append(snapshot)
        yield "data: done\n\n"

    with bind_request_chat(manager, chat):
        queue, started = await tracker.attach_or_start("chat", {}, consume)
    assert started
    assert get_request_chat(manager, "session", "user", "console") is None
    gate.set()
    events = [
        event async for event in tracker.stream_from_queue(queue, "chat")
    ]
    assert events == ["data: done\n\n"]
    assert observed == [chat]


def test_snapshot_checks_workspace_and_full_identity_and_restores_on_error():
    manager = object()
    with pytest.raises(ValueError):
        with bind_request_chat(manager, _chat()):
            assert (
                get_request_chat(object(), "session", "user", "console")
                is None
            )
            assert (
                get_request_chat(manager, "other", "user", "console") is None
            )
            assert (
                get_request_chat(manager, "session", "other", "console")
                is None
            )
            assert (
                get_request_chat(manager, "session", "user", "other") is None
            )
            raise ValueError("test")
    assert get_request_chat(manager, "session", "user", "console") is None


@pytest.mark.asyncio
async def test_model_and_project_hooks_reuse_entry_snapshot_without_reads(
    monkeypatch,
):
    manager = SimpleNamespace(
        find_chat=AsyncMock(),
        get_chat=AsyncMock(),
        get_chat_id_by_session=AsyncMock(),
    )
    workspace = SimpleNamespace(
        chat_manager=manager,
        config=SimpleNamespace(active_model=None),
    )
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: SimpleNamespace(get_active_model=lambda: None),
    )
    chat = _chat()
    with bind_request_chat(manager, chat):
        try:
            context = await prepare_model_context(
                workspace=workspace,
                session_id="session",
                user_id="user",
                channel="console",
                request_override=None,
            )
            dirs = await _session_project_dirs(
                SimpleNamespace(
                    workspace=workspace,
                    session_id="session",
                    request=SimpleNamespace(user_id="user", channel="console"),
                ),
            )
            assert context.chat_id == "chat"
            assert dirs == [{"path": "/project"}]
        finally:
            clear_current_model_context()
    manager.find_chat.assert_not_awaited()
    manager.get_chat.assert_not_awaited()
    manager.get_chat_id_by_session.assert_not_awaited()
