# -*- coding: utf-8 -*-
"""Integration tests for /api/access-control/* (Sprint 4.2).

Target router: src/qwenpaw/app/routers/access_control.py (13 routes)
Backing store: src/qwenpaw/app/channels/access_control.py
               (AccessControlStore, per-workspace JSON file)

Coverage strategy (happy path first):
  - whitelist / blacklist add + remove roundtrips (GET reflects writes)
  - pending approve / deny / dismiss lifecycle: since only the channel
    gate can create a pending entry via HTTP, we seed the store file
    directly (like helpers.seed_inbox_events) and then drive the HTTP
    approval endpoints.
  - remark / username updates
  - 404 / 422 contract branches

Store file lives at:
  <working_dir>/workspaces/default/access_control.json

Important store quirks discovered while writing these tests:
  - ``get_all_acls`` and ``get_acl`` call ``_reload_if_stale`` (mtime
    check) so a seeded file is picked up. ``get_all_pending`` does NOT
    reload, so after seeding we must hit ``GET /api/access-control``
    (all) or ``GET /{channel}`` first to sync the in-memory store before
    calling mutation endpoints (approve/deny/dismiss read in-memory data).
  - add/remove are idempotent; the store never 409s on duplicates.

No LLM / external deps required.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(15.0)

_CH = "dingtalk"  # arbitrary channel key; ACL store is channel-namespaced


# ================================================================== #
# helpers
# ================================================================== #


def _acl_store_path(app_server) -> Path:
    """Path to the default agent's access_control.json."""
    return (
        app_server.working_dir
        / "workspaces"
        / "default"
        / "access_control.json"
    )


def _seed_pending(app_server, channel, user_id, *, username="", remark=""):
    """Seed a pending entry directly into the store file.

    Only the channel gate creates pending entries in production, so tests
    inject them at the file layer. Caller must then hit a reload-aware
    read endpoint (GET all / GET {channel}) before driving mutations.
    """
    path = _acl_store_path(app_server)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = {}
    channel_acl = data.setdefault(
        channel,
        {"whitelist": {}, "blacklist": {}, "pending": []},
    )
    channel_acl.setdefault("pending", []).append(
        {
            "user_id": user_id,
            "channel": channel,
            "timestamp": time.time(),
            "first_message": "seeded pending message",
            "remark": remark,
            "username": username,
        },
    )
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _sync_store_memory(app_server):
    """Force the store to reload the file into memory (mtime-based).

    GET /api/access-control calls get_all_acls -> _reload_if_stale.
    """
    resp = app_server.api_request(
        "GET",
        "/api/access-control",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    return resp.json()


def _get_channel_acl(app_server, channel):
    resp = app_server.api_request(
        "GET",
        f"/api/access-control/{channel}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    return resp.json()


def _whitelist_add(app_server, channel, user_id, *, remark="", username=""):
    return app_server.api_request(
        "POST",
        "/api/access-control/whitelist/add",
        json={
            "entries": [
                {
                    "channel": channel,
                    "user_id": user_id,
                    "remark": remark,
                    "username": username,
                },
            ],
        },
        timeout=_HTTP_TIMEOUT,
    )


# ================================================================== #
# A class — whitelist / blacklist happy path (5 tests)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_whitelist_add_then_get_channel_roundtrip(app_server) -> None:
    """POST whitelist/add → GET /{channel} reflects the user + fields.

    API endpoints:
    - POST /api/access-control/whitelist/add
    - GET  /api/access-control/{channel}
    """
    user_id = "integ_ac_wl_01"
    resp = _whitelist_add(
        app_server,
        _CH,
        user_id,
        remark="vip",
        username="Alice",
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert resp.json() == {"status": "ok", "count": 1}

    acl = _get_channel_acl(app_server, _CH)
    assert user_id in acl["whitelist"], acl
    assert acl["whitelist"][user_id]["remark"] == "vip", acl
    assert acl["whitelist"][user_id]["username"] == "Alice", acl


@pytest.mark.integration
@pytest.mark.p1
def test_whitelist_remove_roundtrip(app_server) -> None:
    """add → remove → GET confirms the user is gone from whitelist.

    API endpoints:
    - POST /api/access-control/whitelist/add
    - POST /api/access-control/whitelist/remove
    - GET  /api/access-control/{channel}
    """
    user_id = "integ_ac_wl_rm_01"
    _whitelist_add(app_server, _CH, user_id, remark="temp")
    assert user_id in _get_channel_acl(app_server, _CH)["whitelist"]

    resp = app_server.api_request(
        "POST",
        "/api/access-control/whitelist/remove",
        json={"entries": [{"channel": _CH, "user_id": user_id}]},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert user_id not in _get_channel_acl(app_server, _CH)["whitelist"]


@pytest.mark.integration
@pytest.mark.p1
def test_blacklist_add_then_get_roundtrip(app_server) -> None:
    """POST blacklist/add → GET /{channel} reflects the user.

    API endpoints:
    - POST /api/access-control/blacklist/add
    - GET  /api/access-control/{channel}
    """
    user_id = "integ_ac_bl_01"
    resp = app_server.api_request(
        "POST",
        "/api/access-control/blacklist/add",
        json={
            "entries": [
                {
                    "channel": _CH,
                    "user_id": user_id,
                    "remark": "spammer",
                    "username": "Bob",
                },
            ],
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()

    acl = _get_channel_acl(app_server, _CH)
    assert user_id in acl["blacklist"], acl
    assert acl["blacklist"][user_id]["remark"] == "spammer", acl


@pytest.mark.integration
@pytest.mark.p1
def test_blacklist_remove_roundtrip(app_server) -> None:
    """add → remove → GET confirms the user is gone from blacklist.

    API endpoints:
    - POST /api/access-control/blacklist/add
    - POST /api/access-control/blacklist/remove
    - GET  /api/access-control/{channel}
    """
    user_id = "integ_ac_bl_rm_01"
    app_server.api_request(
        "POST",
        "/api/access-control/blacklist/add",
        json={"entries": [{"channel": _CH, "user_id": user_id}]},
        timeout=_HTTP_TIMEOUT,
    )
    assert user_id in _get_channel_acl(app_server, _CH)["blacklist"]

    resp = app_server.api_request(
        "POST",
        "/api/access-control/blacklist/remove",
        json={"entries": [{"channel": _CH, "user_id": user_id}]},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert user_id not in _get_channel_acl(app_server, _CH)["blacklist"]


@pytest.mark.integration
@pytest.mark.p1
def test_get_all_acls_reflects_multiple_channels(app_server) -> None:
    """Add users to two channels → GET all shows both channels.

    API endpoints:
    - POST /api/access-control/whitelist/add
    - GET  /api/access-control
    """
    _whitelist_add(app_server, "telegram", "integ_ac_multi_tg")
    _whitelist_add(app_server, "discord", "integ_ac_multi_dc")

    all_acls = _sync_store_memory(app_server)
    assert "telegram" in all_acls, all_acls
    assert "discord" in all_acls, all_acls
    assert "integ_ac_multi_tg" in all_acls["telegram"]["whitelist"]
    assert "integ_ac_multi_dc" in all_acls["discord"]["whitelist"]


# ================================================================== #
# B class — pending lifecycle via seed (3 tests)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_seed_pending_then_approve_moves_to_whitelist(app_server) -> None:
    """Seed pending → approve → user is whitelisted (username carried).

    Test flow:
    1. Seed a pending entry into access_control.json.
    2. GET /api/access-control to sync the in-memory store.
    3. POST /pending/approve.
    4. GET /{channel} → user in whitelist, pending empty, username kept.

    API endpoints:
    - GET  /api/access-control
    - POST /api/access-control/pending/approve
    - GET  /api/access-control/{channel}
    """
    user_id = "integ_ac_pending_approve"
    _seed_pending(app_server, _CH, user_id, username="PendingAlice")
    _sync_store_memory(app_server)

    resp = app_server.api_request(
        "POST",
        "/api/access-control/pending/approve",
        json={"entries": [{"channel": _CH, "user_id": user_id}]},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert resp.json()["count"] == 1

    acl = _get_channel_acl(app_server, _CH)
    assert user_id in acl["whitelist"], acl
    # Username is always carried over from the pending entry.
    assert acl["whitelist"][user_id]["username"] == "PendingAlice", acl
    # Pending list no longer contains the user.
    assert all(p["user_id"] != user_id for p in acl["pending"]), acl


@pytest.mark.integration
@pytest.mark.p1
def test_seed_pending_then_deny_moves_to_blacklist(app_server) -> None:
    """Seed pending → deny → user is blacklisted.

    API endpoints:
    - GET  /api/access-control
    - POST /api/access-control/pending/deny
    - GET  /api/access-control/{channel}
    """
    user_id = "integ_ac_pending_deny"
    _seed_pending(app_server, _CH, user_id, username="PendingBob")
    _sync_store_memory(app_server)

    resp = app_server.api_request(
        "POST",
        "/api/access-control/pending/deny",
        json={"entries": [{"channel": _CH, "user_id": user_id}]},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()

    acl = _get_channel_acl(app_server, _CH)
    assert user_id in acl["blacklist"], acl
    assert all(p["user_id"] != user_id for p in acl["pending"]), acl


@pytest.mark.integration
@pytest.mark.p1
def test_seed_pending_then_dismiss_removes(app_server) -> None:
    """Seed pending → dismiss → user gone from pending and both lists.

    API endpoints:
    - GET  /api/access-control
    - POST /api/access-control/pending/dismiss
    - GET  /api/access-control/{channel}
    """
    user_id = "integ_ac_pending_dismiss"
    _seed_pending(app_server, _CH, user_id)
    _sync_store_memory(app_server)

    resp = app_server.api_request(
        "POST",
        "/api/access-control/pending/dismiss",
        json={"entries": [{"channel": _CH, "user_id": user_id}]},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()

    acl = _get_channel_acl(app_server, _CH)
    assert all(p["user_id"] != user_id for p in acl["pending"]), acl
    assert user_id not in acl["whitelist"], acl
    assert user_id not in acl["blacklist"], acl


# ================================================================== #
# C class — remark / username updates (2 tests)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_update_remark_on_whitelisted_user(app_server) -> None:
    """add → update remark → GET reflects the new remark.

    API endpoints:
    - POST /api/access-control/whitelist/add
    - POST /api/access-control/remark
    - GET  /api/access-control/{channel}
    """
    user_id = "integ_ac_remark_01"
    _whitelist_add(app_server, _CH, user_id, remark="old")

    resp = app_server.api_request(
        "POST",
        "/api/access-control/remark",
        json={"channel": _CH, "user_id": user_id, "remark": "new-remark"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()

    acl = _get_channel_acl(app_server, _CH)
    assert acl["whitelist"][user_id]["remark"] == "new-remark", acl


@pytest.mark.integration
@pytest.mark.p2
def test_update_username_on_whitelisted_user(app_server) -> None:
    """add → update username → GET reflects the new username.

    API endpoints:
    - POST /api/access-control/whitelist/add
    - POST /api/access-control/username
    - GET  /api/access-control/{channel}
    """
    user_id = "integ_ac_username_01"
    _whitelist_add(app_server, _CH, user_id, username="OldName")

    resp = app_server.api_request(
        "POST",
        "/api/access-control/username",
        json={"channel": _CH, "user_id": user_id, "username": "NewName"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()

    acl = _get_channel_acl(app_server, _CH)
    assert acl["whitelist"][user_id]["username"] == "NewName", acl


# ================================================================== #
# D class — contract / error branches (3 tests)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p2
def test_update_remark_unknown_user_returns_404(app_server) -> None:
    """POST /remark for a user not in any list → 404.

    API endpoints:
    - POST /api/access-control/remark
    """
    resp = app_server.api_request(
        "POST",
        "/api/access-control/remark",
        json={
            "channel": _CH,
            "user_id": "integ_ac_nonexistent_user",
            "remark": "x",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json()["detail"] == "User not found in any list"


@pytest.mark.integration
@pytest.mark.p2
def test_update_pending_remark_unknown_returns_404(app_server) -> None:
    """POST /pending/remark for a non-existent pending entry → 404.

    API endpoints:
    - POST /api/access-control/pending/remark
    """
    resp = app_server.api_request(
        "POST",
        "/api/access-control/pending/remark",
        json={
            "channel": _CH,
            "user_id": "integ_ac_no_pending",
            "remark": "x",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert resp.json()["detail"] == "Pending entry not found"


@pytest.mark.integration
@pytest.mark.p2
def test_whitelist_add_missing_entries_key_returns_422(app_server) -> None:
    """POST whitelist/add with a body missing 'entries' → 422.

    API endpoints:
    - POST /api/access-control/whitelist/add
    """
    resp = app_server.api_request(
        "POST",
        "/api/access-control/whitelist/add",
        json={},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, app_server.logs_tail()
