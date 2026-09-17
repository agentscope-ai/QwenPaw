# -*- coding: utf-8 -*-
"""Mock API responses for environments endpoints."""
from __future__ import annotations

import json
from playwright.sync_api import Page

_MOCK_ENVS = [
    {"key": "OPENAI_API_KEY", "value": "sk-***"},
    {"key": "APP_ENV", "value": "development"},
]


def register(page: Page):
    """Register environments API route mocks."""

    def _handle_list(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_ENVS),
        )

    def _handle_save(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_ENVS),
        )

    def _handle_delete(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_ENVS),
        )

    page.route("**/api/envs/*", _handle_delete)
    page.route("**/api/envs", _handle_list)
