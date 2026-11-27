# -*- coding: utf-8 -*-
"""Tests for the fresh append-only conversation event store."""

from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.app.chats.event_store import (
    ContentDraft,
    ConversationEventStore,
    EventConflictError,
    EventDraft,
)


def test_event_replay_is_idempotent_and_conflicts_are_rejected(
    tmp_path: Path,
) -> None:
    store = ConversationEventStore(tmp_path / "session.db")
    try:
        event = EventDraft(
            event_type="turn.started",
            payload={"source": "console"},
            idempotency_key="turn:t1:started",
            turn_id="t1",
        )
        first = store.append(event)
        replayed = store.append(
            EventDraft(
                event_type=event.event_type,
                payload=event.payload,
                idempotency_key=event.idempotency_key,
                turn_id=event.turn_id,
            ),
        )
        assert replayed.seq == first.seq
        assert len(list(store.iter_events())) == 1

        with pytest.raises(EventConflictError):
            store.append(
                EventDraft(
                    event_type="turn.started",
                    payload={"source": "feishu"},
                    idempotency_key=event.idempotency_key,
                    turn_id="t1",
                ),
            )
        assert len(list(store.iter_events())) == 1
    finally:
        store.close()


def test_event_batch_and_content_objects_commit_atomically(
    tmp_path: Path,
) -> None:
    store = ConversationEventStore(tmp_path / "session.db")
    content = ContentDraft.from_text(codec="text-v1", payload="hello")
    try:
        records = store.append_batch(
            [
                EventDraft(
                    event_type="message.appended",
                    payload={"content_hash": content.content_hash},
                    idempotency_key="message:m1",
                    turn_id="t1",
                    message_id="m1",
                ),
                EventDraft(
                    event_type="turn.completed",
                    payload={"status": "completed"},
                    idempotency_key="turn:t1:completed",
                    turn_id="t1",
                ),
            ],
            objects=[content],
        )
        assert [record.seq for record in records] == [1, 2]
        assert store.read_object(content.content_hash) == (
            "text-v1",
            b"hello",
        )
    finally:
        store.close()


def test_failed_batch_rolls_back_new_objects_and_events(
    tmp_path: Path,
) -> None:
    store = ConversationEventStore(tmp_path / "session.db")
    content = ContentDraft.from_text(codec="text-v1", payload="rollback")
    try:
        with pytest.raises(ValueError):
            store.append_batch(
                [
                    EventDraft(
                        event_type="",
                        payload={},
                        idempotency_key="invalid",
                    ),
                ],
                objects=[content],
            )
        assert not list(store.iter_events())
        assert store.read_object(content.content_hash) is None
    finally:
        store.close()
