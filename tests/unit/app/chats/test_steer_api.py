# -*- coding: utf-8 -*-
"""Steer API ownership and terminal retry contracts."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from qwenpaw.app.chats import api
from qwenpaw.app.chats.transcript import TranscriptStore


@pytest.mark.asyncio
async def test_retry_after_run_end_returns_receipt_not_new_delivery(tmp_path):
    store = TranscriptStore(tmp_path / "s.db")
    store.start_turn(
        session_id="s",
        user_id="u",
        channel="console",
        turn_id="t",
    )
    receipt = store.accept_steer(
        session_id="s",
        turn_id="t",
        client_message_id="c",
        content=[{"type": "text", "text": "fix"}],
    )
    store.fail_steers(session_id="s", turn_id="t", reason="stopped")
    chat = SimpleNamespace(
        session_id="s",
        user_id="u",
        channel="console",
        meta={},
    )

    async def get_chat(_):
        return chat

    workspace = SimpleNamespace(transcript_store=store, steer_runs={})
    mgr = SimpleNamespace(get_chat=get_chat)
    result = await api.post_chat_steer(
        "chat",
        api.ChatSteerRequest(
            turn_id="t",
            client_message_id="c",
            content=[{"type": "text", "text": "fix"}],
        ),
        mgr,
        workspace,
    )
    assert result["user_message_id"] == receipt["user_message_id"]
    assert result["status"] == "failed"
    with pytest.raises(HTTPException) as exc:
        await api.post_chat_steer(
            "chat",
            api.ChatSteerRequest(
                turn_id="t",
                client_message_id="new",
                content=[{"type": "text", "text": "other"}],
            ),
            mgr,
            workspace,
        )
    assert exc.value.status_code == 409
    store.close()
