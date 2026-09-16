# -*- coding: utf-8 -*-
"""Chat archive and unarchive lifecycle.

Covers the archive endpoints of ``app/chats/api.py`` and
``app/chats/manager.py``, which existing chat tests do not touch: the
single-chat archive/unarchive pair, their idempotence, the batch
variants, and the 404 branches for unknown ids.

Archive state is asserted by reading the chat back rather than trusting
the POST response, and every chat this module creates is deleted in
``finally``, so the shared chat list is left as it was.

API endpoints:
  - POST   /api/chats
  - GET    /api/chats/{chat_id}
  - POST   /api/chats/{chat_id}/archive
  - POST   /api/chats/{chat_id}/unarchive
  - POST   /api/chats/actions/batch-archive
  - POST   /api/chats/actions/batch-unarchive
  - DELETE /api/chats/{chat_id}
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)

_ABSENT_CHAT = "integ-absent-chat-7731"


def _create_chat(app_server, *, user_id: str, name: str) -> str:
    resp = app_server.api_request(
        "POST",
        "/api/chats",
        json={
            "name": name,
            "session_id": f"console:{user_id}",
            "user_id": user_id,
            "channel": "console",
            "meta": {},
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _chat_entry(app_server, chat_id: str) -> dict:
    resp = app_server.api_request(
        "GET",
        "/api/chats",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body if isinstance(body, list) else body.get("chats") or []
    for item in items:
        if item.get("id") == chat_id:
            return item
    raise AssertionError(f"chat {chat_id} not in listing")


def _delete_chat(app_server, chat_id: str) -> None:
    try:
        app_server.api_request(
            "DELETE",
            f"/api/chats/{chat_id}",
            timeout=_HTTP_TIMEOUT,
        )
    except Exception:  # noqa: BLE001 - cleanup must not mask failures
        pass


# ========================= A. single chat archive ==========================


@pytest.mark.integration
@pytest.mark.p1
def test_archive_then_unarchive_roundtrip(app_server):
    """Archiving flips the flag and unarchiving restores it.

    Test purpose:
      - Cover archive_chat / unarchive_chat and ChatManager's persistence
        of the archived flag, verified by reading the chat listing rather
        than by the POST response alone.

    Test flow:
      1. Create a chat and confirm it starts unarchived.
      2. POST archive and assert the listing shows it archived.
      3. POST unarchive and assert the flag clears.
    """
    chat_id = _create_chat(
        app_server,
        user_id="integ-chat-archive",
        name="archive roundtrip",
    )
    try:
        assert _chat_entry(app_server, chat_id).get("archived") in (
            False,
            None,
        )

        archived = app_server.api_request(
            "POST",
            f"/api/chats/{chat_id}/archive",
            timeout=_HTTP_TIMEOUT,
        )
        assert archived.status_code == 200, archived.text
        assert _chat_entry(app_server, chat_id).get("archived") is True

        restored = app_server.api_request(
            "POST",
            f"/api/chats/{chat_id}/unarchive",
            timeout=_HTTP_TIMEOUT,
        )
        assert restored.status_code == 200, restored.text
        assert _chat_entry(app_server, chat_id).get("archived") in (
            False,
            None,
        )
    finally:
        _delete_chat(app_server, chat_id)


@pytest.mark.integration
@pytest.mark.p2
def test_archive_is_idempotent(app_server):
    """Archiving an already-archived chat succeeds unchanged.

    Test purpose:
      - Cover the documented idempotence of archive_chat: a repeated
        call must not error and must leave the chat archived.
    """
    chat_id = _create_chat(
        app_server,
        user_id="integ-chat-archive-idem",
        name="archive idempotent",
    )
    try:
        for _ in range(2):
            resp = app_server.api_request(
                "POST",
                f"/api/chats/{chat_id}/archive",
                timeout=_HTTP_TIMEOUT,
            )
            assert resp.status_code == 200, resp.text
        assert _chat_entry(app_server, chat_id).get("archived") is True
    finally:
        _delete_chat(app_server, chat_id)


@pytest.mark.integration
@pytest.mark.p2
def test_archive_unknown_chat_returns_404(app_server):
    """Archiving a chat that does not exist is a 404.

    Test purpose:
      - Cover the not-found branch of archive_chat, distinct from the
        409 raised for a running chat.
    """
    resp = app_server.api_request(
        "POST",
        f"/api/chats/{_ABSENT_CHAT}/archive",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_unarchive_unknown_chat_returns_404(app_server):
    """Unarchiving a chat that does not exist is a 404.

    Test purpose:
      - Cover unarchive_chat's own lookup, a separate handler from
        archive.
    """
    resp = app_server.api_request(
        "POST",
        f"/api/chats/{_ABSENT_CHAT}/unarchive",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


# ============================== B. batch actions ===========================


@pytest.mark.integration
@pytest.mark.p1
def test_batch_archive_and_unarchive(app_server):
    """Batch archive affects every listed chat, and unarchive reverses it.

    Test purpose:
      - Cover batch_archive / batch_unarchive across more than one chat,
        asserting each chat's flag rather than only the summary counts.

    Test flow:
      1. Create two chats.
      2. Batch-archive both and assert both are archived.
      3. Batch-unarchive both and assert both are restored.
    """
    first = _create_chat(
        app_server,
        user_id="integ-chat-batch-a",
        name="batch archive a",
    )
    second = _create_chat(
        app_server,
        user_id="integ-chat-batch-b",
        name="batch archive b",
    )
    try:
        archived = app_server.api_request(
            "POST",
            "/api/chats/actions/batch-archive",
            json={"chat_ids": [first, second]},
            timeout=_HTTP_TIMEOUT,
        )
        assert archived.status_code == 200, archived.text
        for cid in (first, second):
            assert _chat_entry(app_server, cid).get("archived") is True, cid

        restored = app_server.api_request(
            "POST",
            "/api/chats/actions/batch-unarchive",
            json={"chat_ids": [first, second]},
            timeout=_HTTP_TIMEOUT,
        )
        assert restored.status_code == 200, restored.text
        for cid in (first, second):
            assert _chat_entry(app_server, cid).get("archived") in (
                False,
                None,
            ), cid
    finally:
        _delete_chat(app_server, first)
        _delete_chat(app_server, second)


@pytest.mark.integration
@pytest.mark.p2
def test_batch_archive_tolerates_unknown_ids(app_server):
    """An unknown id in a batch does not block the known ones.

    Test purpose:
      - Cover the per-item handling in batch_archive: one bad id must
        not abort the whole request, so the real chat still ends up
        archived.
    """
    chat_id = _create_chat(
        app_server,
        user_id="integ-chat-batch-mixed",
        name="batch archive mixed",
    )
    try:
        resp = app_server.api_request(
            "POST",
            "/api/chats/actions/batch-archive",
            json={"chat_ids": [chat_id, _ABSENT_CHAT]},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, resp.text
        assert _chat_entry(app_server, chat_id).get("archived") is True
    finally:
        _delete_chat(app_server, chat_id)


@pytest.mark.integration
@pytest.mark.p2
def test_batch_archive_empty_list_is_accepted(app_server):
    """An empty batch is a no-op rather than an error.

    Test purpose:
      - Cover the empty-input path of batch_archive, which the console
        can send when nothing is selected.
    """
    resp = app_server.api_request(
        "POST",
        "/api/chats/actions/batch-archive",
        json={"chat_ids": []},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
