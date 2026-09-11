# -*- coding: utf-8 -*-
"""Unit tests for the mail access control API router."""

# pylint: disable=redefined-outer-name,unused-argument
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from qwenpaw.app.mail.mail_access_control import MailAccessControlStore
from qwenpaw.app.routers.mail_access_control import (
    MailACLActionBody,
    MailACLEntry,
    MailACLRemarkBody,
    add_to_blacklist,
    add_to_whitelist,
    approve_pending,
    deny_pending,
    dismiss_pending,
    remove_from_blacklist,
    remove_from_whitelist,
    update_remark,
)

AGENT = "agent-1"


@pytest.fixture
def store(tmp_path):
    """A real store; the router resolves it only for the known agent."""
    acl_store = MailAccessControlStore(
        tmp_path / "mail_access_control.json",
    )

    def _fake_get_store(agent_id):
        return acl_store if agent_id == AGENT else None

    with patch(
        "qwenpaw.app.routers.mail_access_control._get_store_for_agent",
        new=_fake_get_store,
    ):
        yield acl_store


def _entries(*addresses, agent_id: str = AGENT) -> MailACLActionBody:
    return MailACLActionBody(
        entries=[
            MailACLEntry(agent_id=agent_id, address=addr) for addr in addresses
        ],
    )


# ── Pending approve / deny / dismiss ────────────────────────────────


def test_approve_moves_pending_to_whitelist(store):
    store.add_pending(AGENT, "new@example.com", subject="hi")
    result = asyncio.run(
        approve_pending(_entries("new@example.com"), request=None),
    )
    assert result == {"status": "ok", "count": 1}
    acl = store.get_acl(AGENT)
    assert acl["pending"] == []
    assert "new@example.com" in acl["whitelist"]


def test_approve_is_idempotent(store):
    store.add_pending(AGENT, "new@example.com")
    body = _entries("new@example.com")
    first = asyncio.run(approve_pending(body, request=None))
    second = asyncio.run(approve_pending(body, request=None))
    assert first["status"] == second["status"] == "ok"
    acl = store.get_acl(AGENT)
    assert "new@example.com" in acl["whitelist"]
    assert acl["pending"] == []


def test_approve_hides_pending_and_schedules_all_uids_once(store):
    store.add_pending(
        AGENT,
        "new@example.com",
        subject="first",
        uid=101,
    )
    store.add_pending(
        AGENT,
        "new@example.com",
        subject="second",
        uid=102,
    )

    class _Monitor:
        def __init__(self):
            self.schedules = 0

        def schedule_approved_replay(self):
            self.schedules += 1
            return True

    monitor = _Monitor()
    workspace = SimpleNamespace(mail_monitor=monitor)

    class _Manager:
        async def get_agent(self, _agent_id):
            return workspace

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=_Manager()),
        ),
    )

    async def _run():
        with patch(
            "qwenpaw.app.inbox_store.mark_read_by_acl_sender",
            new=lambda _agent_id, _address: asyncio.sleep(0, result=0),
        ):
            first = await approve_pending(
                _entries("new@example.com"),
                request=request,
            )
            # Simulate the stale UI issuing the same action before its next
            # refresh.  There is no pending snapshot left to schedule again.
            second = await approve_pending(
                _entries("new@example.com"),
                request=request,
            )
            return first, second

    first, second = asyncio.run(_run())
    assert first == {"status": "ok", "count": 1}
    assert second == {"status": "ok", "count": 1}
    assert monitor.schedules == 1
    assert store.get_acl(AGENT)["pending"] == []
    replay = store.get_approved_replay(AGENT)
    assert [message["uid"] for message in replay[0]["messages"]] == [101, 102]


def test_failed_approval_replay_remains_durable(store):
    store.add_pending(AGENT, "new@example.com", subject="first", uid=101)

    class _Manager:
        async def get_agent(self, _agent_id):
            # No running monitor (for example an agent currently unavailable)
            # must not put the approved row back in the visible pending list.
            return SimpleNamespace(mail_monitor=None)

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=_Manager()),
        ),
    )

    async def _run():
        with patch(
            "qwenpaw.app.inbox_store.mark_read_by_acl_sender",
            new=lambda _agent_id, _address: asyncio.sleep(0, result=0),
        ):
            result = await approve_pending(
                _entries("new@example.com"),
                request=request,
            )
            return result

    assert asyncio.run(_run()) == {"status": "ok", "count": 1}
    acl = store.get_acl(AGENT)
    assert "new@example.com" in acl["whitelist"]
    assert acl["pending"] == []
    assert [
        message["uid"]
        for message in store.get_approved_replay(AGENT)[0]["messages"]
    ] == [101]


def test_approve_unknown_agent_is_skipped(store):
    result = asyncio.run(
        approve_pending(
            _entries("new@example.com", agent_id="no-such-agent"),
            request=None,
        ),
    )
    assert result == {"status": "ok", "count": 0}


def test_deny_moves_pending_to_blacklist(store):
    store.add_pending(AGENT, "spam@example.com")
    result = asyncio.run(deny_pending(_entries("spam@example.com")))
    assert result == {"status": "ok", "count": 1}
    acl = store.get_acl(AGENT)
    assert acl["pending"] == []
    assert "spam@example.com" in acl["blacklist"]


def test_dismiss_removes_pending_without_listing(store):
    store.add_pending(AGENT, "new@example.com")
    result = asyncio.run(dismiss_pending(_entries("new@example.com")))
    assert result == {"status": "ok", "count": 1}
    acl = store.get_acl(AGENT)
    assert acl["pending"] == []
    assert acl["whitelist"] == {}
    assert acl["blacklist"] == {}


# ── Whitelist / blacklist add & remove ──────────────────────────────


def test_whitelist_add_and_remove(store):
    result = asyncio.run(
        add_to_whitelist(_entries("alice@example.com", "*@good.com")),
    )
    assert result == {"status": "ok", "count": 2}
    acl = store.get_acl(AGENT)
    assert "alice@example.com" in acl["whitelist"]
    assert "*@good.com" in acl["whitelist"]

    result = asyncio.run(
        remove_from_whitelist(_entries("alice@example.com")),
    )
    assert result == {"status": "ok", "count": 1}
    assert "alice@example.com" not in store.get_acl(AGENT)["whitelist"]


def test_same_workspace_batch_writes_once(store):
    body = _entries("alice@example.com", "bob@example.com")
    # pylint: disable-next=protected-access
    with patch.object(store, "_save", wraps=store._save) as save:
        result = asyncio.run(add_to_whitelist(body))
    assert result == {"status": "ok", "count": 2}
    assert save.call_count == 1


def test_sync_acl_io_does_not_block_event_loop(store):
    def _slow_get_store(_agent_id):
        time.sleep(0.1)
        return store

    async def _run():
        ticks = 0
        with patch(
            "qwenpaw.app.routers.mail_access_control._get_store_for_agent",
            new=_slow_get_store,
        ):
            operation = asyncio.create_task(
                add_to_whitelist(_entries("alice@example.com")),
            )
            while not operation.done():
                ticks += 1
                await asyncio.sleep(0.005)
            await operation
        return ticks

    assert asyncio.run(_run()) >= 2


def test_blacklist_add_and_remove(store):
    result = asyncio.run(add_to_blacklist(_entries("*@bad.com")))
    assert result == {"status": "ok", "count": 1}
    assert "*@bad.com" in store.get_acl(AGENT)["blacklist"]

    result = asyncio.run(remove_from_blacklist(_entries("*@bad.com")))
    assert result == {"status": "ok", "count": 1}
    assert "*@bad.com" not in store.get_acl(AGENT)["blacklist"]


# ── Address validation (400) ────────────────────────────────────────


def test_whitelist_add_rejects_malformed_address(store):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(add_to_whitelist(_entries("not-an-email")))
    assert exc_info.value.status_code == 400
    assert store.get_acl(AGENT)["whitelist"] == {}


def test_blacklist_add_rejects_invalid_wildcard(store):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(add_to_blacklist(_entries("*@*")))
    assert exc_info.value.status_code == 400
    assert store.get_acl(AGENT)["blacklist"] == {}


def test_approve_rejects_malformed_address(store):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            approve_pending(_entries("bad address"), request=None),
        )
    assert exc_info.value.status_code == 400


def test_deny_rejects_malformed_address(store):
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(deny_pending(_entries("no-at-sign.com")))
    assert exc_info.value.status_code == 400


def test_batch_validated_before_any_write(store):
    """One bad entry must reject the whole batch before any store write."""
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            add_to_whitelist(_entries("alice@example.com", "broken")),
        )
    assert exc_info.value.status_code == 400
    assert store.get_acl(AGENT)["whitelist"] == {}


# ── Remark endpoints (404) ──────────────────────────────────────────


def test_update_remark_unknown_agent_404(store):
    body = MailACLRemarkBody(
        agent_id="no-such-agent",
        address="alice@example.com",
        remark="x",
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_remark(body))
    assert exc_info.value.status_code == 404


def test_update_remark_unlisted_address_404(store):
    body = MailACLRemarkBody(
        agent_id=AGENT,
        address="ghost@example.com",
        remark="x",
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_remark(body))
    assert exc_info.value.status_code == 404


def test_update_remark_success(store):
    store.add_to_whitelist(AGENT, "alice@example.com")
    body = MailACLRemarkBody(
        agent_id=AGENT,
        address="alice@example.com",
        remark="bestie",
    )
    result = asyncio.run(update_remark(body))
    assert result == {"status": "ok"}
    acl = store.get_acl(AGENT)
    assert acl["whitelist"]["alice@example.com"]["remark"] == "bestie"
