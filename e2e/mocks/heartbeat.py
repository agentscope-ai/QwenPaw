# -*- coding: utf-8 -*-
"""Mock API responses for heartbeat endpoints."""
from __future__ import annotations

import json
from playwright.sync_api import Page

_MOCK_HEARTBEAT = {
    "enabled": True,
    "every": 3600,
    "target": "main",
    "activeHours": None,
}


def register(page: Page):
    """Register heartbeat API route mocks."""

    def _handle_get(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_HEARTBEAT),
        )

    def _handle_update(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_HEARTBEAT),
        )

    def _handle_run(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"started": True}),
        )

    page.route("**/api/config/heartbeat/run**", _handle_run)
    page.route("**/api/config/heartbeat", _handle_get)
