# -*- coding: utf-8 -*-
"""Mock API responses for agents endpoints."""
from __future__ import annotations

import json
from playwright.sync_api import Page

_MOCK_AGENTS = [
    {
        "id": "default",
        "name": "Default Agent",
        "description": "The default agent",
        "workspace_dir": "/workspace/default",
        "enabled": True,
        "active_model": "gpt-4",
    },
    {
        "id": "test-agent",
        "name": "Test Agent",
        "description": "A test agent for smoke tests",
        "workspace_dir": "/workspace/test",
        "enabled": True,
        "active_model": "gpt-4",
    },
]


def register(page: Page):
    """Register agents API route mocks."""

    def _handle_list(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"agents": _MOCK_AGENTS}),
        )

    def _handle_get(route):
        agent_id = route.request.url.split("/agents/")[-1].split("?")[0]
        agent = next((a for a in _MOCK_AGENTS if a["id"] == agent_id), None)
        if agent:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(agent),
            )
        else:
            route.fulfill(
                status=404,
                content_type="application/json",
                body=json.dumps({"detail": "Agent not found"}),
            )

    def _handle_create(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"id": "new-agent", "workspace_dir": "/workspace/new-agent"},
            ),
        )

    def _handle_update(route):
        agent_id = route.request.url.split("/agents/")[-1].split("?")[0]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({**_MOCK_AGENTS[0], "id": agent_id}),
        )

    def _handle_delete(route):
        agent_id = route.request.url.split("/agents/")[-1].split("?")[0]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"success": True, "agent_id": agent_id}),
        )

    def _handle_reorder(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"success": True, "agent_ids": ["default", "test-agent"]},
            ),
        )

    def _handle_toggle(route):
        agent_id = route.request.url.split("/agents/")[1].split("/")[0]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"success": True, "agent_id": agent_id, "enabled": True},
            ),
        )

    page.route("**/api/agents/order**", _handle_reorder)
    page.route("**/api/agents/*/toggle**", _handle_toggle)
    page.route(
        "**/api/agents/*",
        _handle_get,
    )  # GET / DELETE / PUT specific agent
    page.route("**/api/agents", _handle_list)  # GET all / POST new
