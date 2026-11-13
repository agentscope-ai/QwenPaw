# -*- coding: utf-8 -*-
"""Targeted route mock for the sidebar session-list date grouping.

The backend cannot backfill ``created_at`` / ``updated_at`` (patch forces
"now"), so date-group buckets (Today / Within 7 days / Within 30 days /
Earlier / Pinned) can only be exercised by intercepting the sidebar list
request ``GET /api/chats?archived=false`` and returning sessions with
crafted timestamps.

Only the exact list GET is intercepted; every other ``/api/chats``
request (POST create, per-chat GET/DELETE, messages, ...) falls through
to the real backend via ``route.fallback()``.

Shape mirrors ``console/src/api/types/chat.ts`` (``ChatSpec[]``, plain
array, snake_case fields). Grouping uses ``updated_at ?? created_at``
per ``console/src/utils/sessionGrouping.ts``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from playwright.sync_api import Page

# Session names asserted by SIDEBAR-001.
TODAY_NAME = "E2E Group Today"
WEEK_NAME = "E2E Group Week"
MONTH_NAME = "E2E Group Month"
OLDER_NAME = "E2E Group Older"
PINNED_NAME = "E2E Group Pinned"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_sessions() -> list:
    now = datetime.now(timezone.utc)
    entries = [
        # (id, name, age, pinned)
        ("e2e-group-today", TODAY_NAME, timedelta(hours=1), False),
        ("e2e-group-week", WEEK_NAME, timedelta(days=3), False),
        ("e2e-group-month", MONTH_NAME, timedelta(days=10), False),
        ("e2e-group-older", OLDER_NAME, timedelta(days=60), False),
        ("e2e-group-pinned", PINNED_NAME, timedelta(days=2), True),
    ]
    sessions = []
    for sid, name, age, pinned in entries:
        ts = _iso(now - age)
        sessions.append(
            {
                "id": sid,
                "session_id": f"console:{sid}",
                "user_id": "admin",
                "channel": "console",
                "name": name,
                "created_at": ts,
                "updated_at": ts,
                "meta": {},
                "status": "idle",
                "pinned": pinned,
                "archived_at": None,
                "archived": False,
            }
        )
    return sessions


def register(page: Page) -> None:
    """Intercept the sidebar session-list GET for one page.

    The sidebar polls every ~3s; the mock stays registered and serves
    identical data on every poll so groups never flap mid-test.

    Upstream #6504+ re-architected the sidebar into user groups (fetched
    from /api/chats/groups) containing date buckets, so the groups
    endpoint is mocked too: a single default group that all crafted
    sessions resolve into.
    """
    sessions = _build_sessions()

    groups = [
        {
            "id": "default",
            "name": "Uncategorized",
            "order": 0,
            "kind": "default",
            "source": None,
            "pinned": False,
        },
    ]

    def _handle(route):
        request = route.request
        path = request.url.split("?")[0].rstrip("/")
        if request.method == "GET" and path.endswith("/api/chats"):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(sessions),
            )
        elif request.method == "GET" and path.endswith("/api/chats/groups"):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(groups),
            )
        else:
            route.fallback()

    page.route("**/api/chats*", _handle)
