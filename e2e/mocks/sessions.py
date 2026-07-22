# -*- coding: utf-8 -*-
"""Mock API responses for sessions (chats) endpoints."""
from __future__ import annotations

import json
from playwright.sync_api import Page

_MOCK_SESSIONS = [
    {
        "id": "session-1",
        "session_id": "session-1",
        "user_id": "admin",
        "channel": "console",
        "name": "Test Session 1",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "pinned": False,
    },
    {
        "id": "session-2",
        "session_id": "session-2",
        "user_id": "admin",
        "channel": "dingtalk",
        "name": "Test Session 2",
        "created_at": "2025-01-02T00:00:00Z",
        "updated_at": "2025-01-02T00:00:00Z",
        "pinned": False,
    },
]


def register(page: Page):
    """Register sessions API route mocks."""

    def _handle_list(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_SESSIONS),
        )

    def _handle_get(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"messages": [], "status": "idle"}),
        )

    def _handle_delete(route):
        session_id = route.request.url.split("/chats/")[-1].split("?")[0]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True, "chat_id": session_id}),
        )

    def _handle_update(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_SESSIONS[0]),
        )

    def _handle_batch_delete(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True, "deleted_count": 1}),
        )

    page.route("**/api/chats/batch-delete**", _handle_batch_delete)
    page.route(
        "**/api/chats/*",
        _handle_get,
    )  # GET / DELETE / PUT specific session
    page.route("**/api/chats", _handle_list)  # GET all / POST new
