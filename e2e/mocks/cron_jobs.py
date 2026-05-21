# -*- coding: utf-8 -*-
"""Mock API responses for cron jobs endpoints."""
from __future__ import annotations

import json
from playwright.sync_api import Page

_MOCK_CRON_JOBS = [
    {
        "id": "cron-1",
        "name": "Daily Report",
        "enabled": True,
        "schedule": {
            "type": "cron",
            "cron": "0 9 * * *",
            "timezone": "Asia/Shanghai",
        },
        "task_type": "text",
        "text": "Generate daily report",
        "dispatch": {
            "channel": "console",
            "target": {"user_id": "admin", "session_id": "default"},
        },
        "runtime": {"max_concurrency": 1, "timeout_seconds": 300},
    },
]


def register(page: Page):
    """Register cron jobs API route mocks."""

    def _handle_list(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_CRON_JOBS),
        )

    def _handle_get(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    **_MOCK_CRON_JOBS[0],
                    "state": "idle",
                    "next_run_time": "2025-01-01T09:00:00Z",
                },
            ),
        )

    def _handle_create(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_CRON_JOBS[0]),
        )

    def _handle_update(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_CRON_JOBS[0]),
        )

    def _handle_delete(route):
        route.fulfill(status=200, content_type="application/json", body="null")

    def _handle_action(route):
        route.fulfill(status=200, content_type="application/json", body="null")

    def _handle_dispatch_targets(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"channels": ["console"], "items": []}),
        )

    page.route("**/api/cron/dispatch-targets**", _handle_dispatch_targets)
    page.route("**/api/cron/jobs/*/pause**", _handle_action)
    page.route("**/api/cron/jobs/*/resume**", _handle_action)
    page.route("**/api/cron/jobs/*/run**", _handle_action)
    page.route("**/api/cron/jobs/*/state**", _handle_action)
    page.route("**/api/cron/jobs/*/history**", _handle_action)
    page.route("**/api/cron/jobs/*", _handle_get)
    page.route("**/api/cron/jobs", _handle_list)
