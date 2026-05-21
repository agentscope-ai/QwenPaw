# -*- coding: utf-8 -*-
"""Mock API responses for models/providers endpoints."""
from __future__ import annotations

import json
from playwright.sync_api import Page

_MOCK_PROVIDERS = [
    {
        "id": "openai",
        "name": "OpenAI",
        "builtin": True,
        "enabled": True,
        "models": [
            {
                "id": "gpt-4",
                "name": "GPT-4",
                "enabled": True,
                "is_free": False,
            },
            {
                "id": "gpt-3.5-turbo",
                "name": "GPT-3.5 Turbo",
                "enabled": True,
                "is_free": False,
            },
        ],
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "builtin": True,
        "enabled": True,
        "models": [
            {
                "id": "claude-3-opus",
                "name": "Claude 3 Opus",
                "enabled": True,
                "is_free": False,
            },
        ],
    },
]

_MOCK_ACTIVE_MODELS = {
    "active_llm": {"provider_id": "openai", "model": "gpt-4"},
}


def register(page: Page):
    """Register models API route mocks."""

    def _handle_list_providers(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_PROVIDERS),
        )

    def _handle_active_models(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_ACTIVE_MODELS),
        )

    def _handle_set_active(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_ACTIVE_MODELS),
        )

    def _handle_config(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_PROVIDERS[0]),
        )

    def _handle_test(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"success": True, "message": "Connection successful"},
            ),
        )

    def _handle_discover(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "success": True,
                    "message": "Discovery complete",
                    "models": [],
                    "added_count": 0,
                },
            ),
        )

    def _handle_custom_providers(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_PROVIDERS),
        )

    def _handle_add_model(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_PROVIDERS[0]),
        )

    def _handle_remove_model(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_PROVIDERS[0]),
        )

    def _handle_openrouter(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"series": []}),
        )

    # Order matters: more specific routes first
    page.route("**/api/models/openrouter/**", _handle_openrouter)
    page.route("**/api/models/custom-providers**", _handle_custom_providers)
    page.route("**/api/models/active**", _handle_active_models)
    page.route("**/api/models/*/models/*/test**", _handle_test)
    page.route("**/api/models/*/test**", _handle_test)
    page.route("**/api/models/*/discover**", _handle_discover)
    page.route("**/api/models/*/models/*", _handle_remove_model)
    page.route("**/api/models/*/models", _handle_add_model)
    page.route("**/api/models/*/config", _handle_config)
    page.route("**/api/models", _handle_list_providers)
