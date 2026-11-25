# -*- coding: utf-8 -*-
"""Failure finalization must preserve live ownership and durable receipts."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.app.chats.transcript_catalog import TranscriptCatalog
from qwenpaw.app.workspace import workspace as workspace_module
from qwenpaw.runtime.steer import current_steer
from qwenpaw.schemas import AgentRequest, AgentResponse, Message, RunStatus


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["close", "commit"])
async def test_workspace_failure_keeps_terminal_and_releases_ownership(
    tmp_path,
    monkeypatch,
    failure,
):
    store = TranscriptCatalog(tmp_path)
    request = AgentRequest(
        session_id="session",
        user_id="user",
        channel="console",
        request_context={"turn_id": "test"},
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hello"},
                ],
            },
        ],
    )
    identity = dict(session_id="session", user_id="user", channel="console")
    closed = 0

    class Stream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            return AgentResponse(status=RunStatus.Completed)

        async def aclose(self):
            nonlocal closed
            closed += 1
            if failure == "close":
                raise RuntimeError("close failed")

    class Runtime(workspace_module.Runtime):
        def __init__(self, **kwargs):
            pass

        def run(self, incoming):
            return Stream()

    monkeypatch.setattr(workspace_module, "Runtime", Runtime)
    monkeypatch.setattr(
        workspace_module,
        "load_agent_config_async",
        AsyncMock(return_value=SimpleNamespace(backend="qwenpaw")),
    )
    original = TranscriptStore.commit_turn

    def commit(self, **kwargs):
        if failure == "commit":
            raise sqlite3.OperationalError("commit failed")
        return original(self, **kwargs)

    monkeypatch.setattr(TranscriptStore, "commit_turn", commit)
    original_fail = store.fail_turn

    def fail_turn(**kwargs):
        # A concurrent history reader must not recover the owned turn.
        page = store.get_page(**identity)
        assert (
            page.messages[0].metadata["qwenpaw_turn_state"]["status"]
            == "running"
        )
        return original_fail(**kwargs)

    monkeypatch.setattr(store, "fail_turn", fail_turn)
    workspace = SimpleNamespace(
        agent_id="test",
        workspace_dir=tmp_path,
        transcript_store=store,
        session=None,
        _app_services=None,
        steer_runs={},
        finalize_turn_usage=AsyncMock(),
    )
    stream = workspace_module.Workspace._stream_query(workspace, request)
    try:
        if failure in ("close", "steer_close"):
            # Cancellation before a terminal response is observed.
            async def first_item(self):
                return AgentResponse(status=RunStatus.InProgress)

            monkeypatch.setattr(Stream, "__anext__", first_item)
            await anext(stream)
            with pytest.raises(RuntimeError, match="close failed"):
                await stream.aclose()
        else:
            with pytest.raises(
                sqlite3.OperationalError,
                match="commit failed",
            ):
                await anext(stream)
        store.get_page(**identity)
        path = (
            tmp_path
            / "transcripts"
            / (store.storage_id_for(**identity) + ".db")
        )
        with sqlite3.connect(path) as db:
            status = db.execute(
                "SELECT status FROM transcript_turns",
            ).fetchone()[0]
        assert status == "failed"
        assert closed == 1
        assert workspace.steer_runs == {}
        assert current_steer.get() is None
        assert not store._handles
    finally:
        await stream.aclose()
        store.close()


def test_failure_settlement_rolls_back_and_preserves_applied_attachment(
    tmp_path,
    monkeypatch,
):
    store = TranscriptStore(tmp_path / "chat.db")
    identity = dict(session_id="s", user_id="u", channel="console")
    store.start_turn(**identity, turn_id="t")
    content = [{"type": "file", "file_url": "/uploads/input.txt"}]
    receipts = [
        store.accept_steer(
            session_id="s",
            turn_id="t",
            client_message_id=key,
            content=content,
        )
        for key in ("applied", "pending")
    ]
    message = Message(
        id=receipts[0]["user_message_id"],
        role="user",
        content=content,
        metadata={"input_kind": "steer", "client_message_id": "applied"},
    ).completed()
    store.apply_steers(
        session_id="s",
        turn_id="t",
        messages=[(message, 0)],
        step_index=1,
    )
    original = store.finish_turn

    def broken(**kwargs):
        raise sqlite3.OperationalError("finalization failed")

    monkeypatch.setattr(store, "finish_turn", broken)
    try:
        with pytest.raises(sqlite3.OperationalError):
            store.fail_turn(session_id="s", turn_id="t", error={})
        assert [
            r["status"]
            for r in store.list_steers(
                session_id="s",
                turn_id="t",
            )
        ] == ["applied", "accepted"]
        monkeypatch.setattr(store, "finish_turn", original)
        assert store.fail_turn(session_id="s", turn_id="t", error={})
        store.rebuild_projections()
        assert [
            r["status"]
            for r in store.list_steers(
                session_id="s",
                turn_id="t",
            )
        ] == ["applied", "failed"]
        page = store.get_page(**identity)
        assert page.messages[0].content == message.content
        assert (
            page.messages[0].metadata["qwenpaw_turn_state"]["status"]
            == "failed"
        )
    finally:
        store.close()
