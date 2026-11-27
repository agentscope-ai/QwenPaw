# -*- coding: utf-8 -*-
"""Steer ownership, atomic application and replay contracts."""

import pytest

from qwenpaw.app.chats.transcript import TranscriptStore
from qwenpaw.schemas import Message, TextContent


def test_steer_receipt_survives_reopen_and_replays_once(tmp_path):
    path = tmp_path / "chat.db"
    store = TranscriptStore(path)
    store.start_turn(
        session_id="s",
        user_id="u",
        channel="console",
        turn_id="t",
    )
    store.upsert_message(
        session_id="s",
        turn_id="t",
        ordinal=0,
        message=Message(
            id="initial",
            role="user",
            content=[TextContent(text="ordinary input")],
        ).completed(),
    )
    receipt = store.accept_steer(
        session_id="s",
        turn_id="t",
        client_message_id="c",
        content=[{"type": "text", "text": "fix"}],
    )
    assert receipt["status"] == "accepted"
    assert (
        store.accept_steer(
            session_id="s",
            turn_id="t",
            client_message_id="c",
            content=[{"type": "text", "text": "fix"}],
        )
        == receipt
    )
    with pytest.raises(ValueError, match="conflict"):
        store.accept_steer(
            session_id="s",
            turn_id="t",
            client_message_id="c",
            content=[{"type": "text", "text": "other"}],
        )
    msg = Message(
        id=receipt["user_message_id"],
        role="user",
        content=[TextContent(text="fix")],
        sequence_number=7,
        metadata={"input_kind": "steer", "client_message_id": "c"},
    ).completed()
    store.apply_steers(
        session_id="s",
        turn_id="t",
        messages=[(msg, 2)],
        step_index=1,
    )
    store.close()
    store = TranscriptStore(path)
    store.rebuild_projections()
    receipts = store.list_steers(session_id="s", turn_id="t")
    assert [(r["status"], r["revision"]) for r in receipts] == [("applied", 2)]
    assert (
        store.read_replay_page(
            session_id="s",
            turn_id="t",
            through=6,
            after=-1,
        )
        == []
    )
    page = store.read_replay_page(
        session_id="s",
        turn_id="t",
        through=7,
        after=-1,
    )
    recovered = store.list_steers(
        session_id="s",
        latest=True,
        include_messages=True,
    )[0]["message"]
    assert recovered["id"] == msg.id
    assert recovered["content"][0]["text"] == "fix"
    history = store.get_page(
        session_id="s",
        user_id="u",
        channel="console",
    ).messages
    assert history[0].metadata["qwenpaw_turn_state"] == {
        "status": "running",
    }
    assert store.history_steers(
        session_id="s",
        messages=history[:1],
    ) == {"t": []}
    assert (
        store.history_steers(
            session_id="s",
            messages=history[1:],
        )["t"][
            0
        ]["client_message_id"]
        == "c"
    )
    assert len(page) == 1
    assert '"fix"' in page[0][1]
    store.upsert_message(
        session_id="s",
        turn_id="t",
        ordinal=3,
        message=Message(
            id="tail",
            role="assistant",
            sequence_number=8,
            content=[TextContent(text="partial reply")],
        ).completed(),
    )
    for status in ("running", "cancelled"):
        if status == "cancelled":
            store.finish_turn(
                session_id="s",
                turn_id="t",
                status=status,
            )
        tail = store.get_page(
            session_id="s",
            user_id="u",
            channel="console",
            max_content_blocks=1,
        )
        assert tail.has_more
        expected_id = msg.id if status == "running" else "tail"
        assert [m.id for m in tail.messages] == [expected_id]
        expected = "canceled" if status == "cancelled" else "running"
        assert (
            tail.messages[0].metadata["qwenpaw_turn_state"]["status"]
            == expected
        )
    store.close()


def test_steer_apply_rolls_back_batch_on_invalid_message(tmp_path):
    store = TranscriptStore(tmp_path / "chat.db")
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
    msg = Message(
        id=receipt["user_message_id"],
        role="user",
        content=[TextContent(text="fix")],
    ).completed()
    bad = Message(id="unknown", role="user", content=[]).completed()
    with pytest.raises(ValueError):
        store.apply_steers(
            session_id="s",
            turn_id="t",
            messages=[(msg, 1), (bad, 2)],
            step_index=1,
        )
    assert (
        store.list_steers(session_id="s", turn_id="t")[0]["status"]
        == "accepted"
    )
    assert (
        store.read_replay_page(
            session_id="s",
            turn_id="t",
            through=99,
            after=-1,
        )
        == []
    )
    store.recover_running_turns()
    assert (
        store.list_steers(session_id="s", turn_id="t")[0]["status"] == "failed"
    )
    assert store.list_steers(session_id="s")[0]["reason"] == "invocation_lost"
    store.close()


@pytest.mark.parametrize(
    "with_marker, in_context",
    [(False, True), (True, False), (True, True)],
)
@pytest.mark.parametrize(
    "status, snapshot",
    [
        ("completed", "valid"),
        ("cancelled", "valid"),
        ("cancelled", "missing_marker"),
        ("cancelled", "open_tool"),
    ],
)
def test_fork_requires_applied_runtime_marker(
    tmp_path,
    with_marker,
    in_context,
    status,
    snapshot,
):
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
    msg = Message(
        id=receipt["user_message_id"],
        role="user",
        content=[TextContent(text="fix")],
        metadata={"input_kind": "steer", "steer_scope": "parent"},
    ).completed()
    store.apply_steers(
        session_id="s",
        turn_id="t",
        messages=[(msg, 1)],
        step_index=1,
    )
    state = {
        "agent": {
            "state": {
                "middle_context": {},
                "context": [msg.model_dump(mode="json")] if in_context else [],
            },
        },
    }
    if status == "cancelled":
        state["agent"]["state"]["context"].append(
            {
                "role": "user",
                "content": [{"type": "text", "text": "initial"}],
                "metadata": {
                    "qwenpaw_client_message_id": "t",
                    "qwenpaw_turn_state": {"status": "canceled"},
                },
            },
        )
    if snapshot == "missing_marker":
        state["agent"]["state"]["context"][-1]["metadata"].pop(
            "qwenpaw_turn_state",
        )
    elif snapshot == "open_tool":
        state["agent"]["state"]["context"].append(
            {
                "role": "assistant",
                "content": [{"type": "tool_call", "id": "open"}],
            },
        )
    if with_marker:
        state["agent"]["state"]["middle_context"]["qwenpaw_steer_boundary"] = {
            "turn_id": "t",
            "message_ids": [msg.id],
        }
    store.write_runtime_state(
        session_id="s",
        user_id="u",
        channel="console",
        state=state,
        turn_id="t",
    )
    assert not store.can_fork_turn(session_id="s", turn_id="t")
    store.finish_turn(session_id="s", turn_id="t", status=status)
    allowed = with_marker and in_context and snapshot == "valid"
    assert store.can_fork_turn(session_id="s", turn_id="t") is allowed
    child = TranscriptStore(tmp_path / "child.db")
    kwargs = dict(
        source_path=store.path,
        source_session_id="s",
        source_chat_id="chat",
        turn_id="t",
        target_session_id="child",
        target_user_id="u",
        target_channel="console",
    )
    if allowed:
        child.fork_completed_turn_from(**kwargs)
        assert child.list_steers(session_id="child") == []
        state = child.read_runtime_state(
            session_id="child",
            user_id="u",
            channel="console",
        )
        assert state.state["agent"]["state"]["context"][0]["id"] == msg.id
        copied = child._conn.execute(
            "SELECT envelope_json FROM transcript_messages",
        ).fetchone()[0]
        assert '"steer"' in copied
        assert "steer_scope" not in copied
    else:
        with pytest.raises(ValueError, match="consistent runtime"):
            child.fork_completed_turn_from(**kwargs)
    child.close()
    store.close()
