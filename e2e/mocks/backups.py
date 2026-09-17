# -*- coding: utf-8 -*-
"""Mock API responses for backups endpoints."""
from __future__ import annotations

import json
from playwright.sync_api import Page

_MOCK_BACKUPS = [
    {
        "id": "backup-1",
        "name": "Initial Backup",
        "description": "First backup",
        "created_at": "2025-01-01T00:00:00Z",
        "scope": {
            "include_agents": True,
            "include_global_config": True,
            "include_secrets": False,
            "include_skill_pool": True,
        },
        "agent_count": 2,
    },
]


def register(page: Page):
    """Register backups API route mocks."""

    def _handle_list(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_BACKUPS),
        )

    def _handle_get(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({**_MOCK_BACKUPS[0], "workspace_stats": {}}),
        )

    def _handle_create(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_BACKUPS[0]),
        )

    def _handle_restore(route):
        route.fulfill(status=200, content_type="application/json", body="null")

    def _handle_delete(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"deleted": ["backup-1"], "failed": []}),
        )

    def _handle_export(route):
        route.fulfill(status=200, content_type="application/zip", body="")

    def _handle_import(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_BACKUPS[0]),
        )

    # Order: more specific routes first
    page.route("**/api/backups/*/export**", _handle_export)
    page.route("**/api/backups/*/restore**", _handle_restore)
    page.route("**/api/backups/import**", _handle_import)
    page.route("**/api/backups/delete**", _handle_delete)
    page.route("**/api/backups/stream**", _handle_create)
    page.route("**/api/backups/*", _handle_get)
    page.route("**/api/backups", _handle_list)
