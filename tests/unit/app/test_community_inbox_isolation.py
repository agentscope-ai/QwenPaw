# -*- coding: utf-8 -*-
"""Community corruption must not take the independent local Inbox down."""

import json

import pytest

from qwenpaw.app import community_store, inbox_store
from qwenpaw.app.routers import console

pytestmark = [pytest.mark.unit, pytest.mark.p0]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "contents",
    [
        "broken json",
        json.dumps(
            {
                "events": {"bad": "not an event"},
                "connection": {"account_id": "alice"},
            },
        ),
        json.dumps(
            {
                "events": {"bad": {"id": "bad", "created_at": "invalid time"}},
                "connection": {"account_id": "alice"},
            },
        ),
    ],
)
async def test_corrupt_community_history_keeps_local_events(
    tmp_path,
    monkeypatch,
    contents,
):
    path = tmp_path / "community.json"
    path.write_text(contents)
    monkeypatch.setattr(community_store, "_STATE_PATH", path)

    async def local_events(**_kwargs):
        return [{"id": "local-event", "created_at": 10, "read": False}], 1, 1

    monkeypatch.setattr(inbox_store, "query_events", local_events)
    result = await console.get_inbox_events(
        limit=50,
        offset=0,
        source_type=None,
        source_types=None,
        status=None,
        agent_id=None,
        unread_only=False,
        exclude_acl_pending=False,
    )
    assert [event["id"] for event in result["events"]] == ["local-event"]
    assert result["unread_count"] == 1
    assert result["source_errors"] == {
        "community": "community_history_unavailable",
    }
    assert path.read_text() == contents
    assert "community_scope" not in result


@pytest.mark.asyncio
async def test_local_read_does_not_load_community_state(monkeypatch):
    async def mark_local(ids):
        assert ids == ["local-event"]
        return 1

    async def mark_community(_ids=None):
        pytest.fail(
            "An independent local message must not read community state",
        )

    monkeypatch.setattr(inbox_store, "mark_read", mark_local)
    monkeypatch.setattr(community_store, "mark_read", mark_community)
    result = await console.post_mark_inbox_read(
        console.MarkInboxReadRequest(event_ids=["local-event"]),
    )
    assert result == {"updated": 1}


@pytest.mark.asyncio
async def test_mark_all_keeps_local_success_when_community_is_corrupt(
    monkeypatch,
):
    async def local_read():
        return 2

    async def corrupt_read():
        raise ValueError("sensitive corrupt contents")

    monkeypatch.setattr(inbox_store, "mark_all_read", local_read)
    monkeypatch.setattr(community_store, "mark_read", corrupt_read)
    result = await console.post_mark_inbox_read(
        console.MarkInboxReadRequest(all=True),
    )
    assert result["updated"] == 2
    assert result["source_errors"] == {
        "community": "community_history_unavailable",
    }


@pytest.mark.asyncio
async def test_community_only_read_reports_failure_without_secret(monkeypatch):
    async def corrupt_read(_ids=None):
        raise ValueError("sensitive corrupt contents")

    monkeypatch.setattr(community_store, "mark_read", corrupt_read)
    with pytest.raises(console.HTTPException) as error:
        await console.post_mark_inbox_read(
            console.MarkInboxReadRequest(event_ids=["community:id"]),
        )
    assert error.value.status_code == 503
    assert error.value.detail == "community_history_unavailable"
