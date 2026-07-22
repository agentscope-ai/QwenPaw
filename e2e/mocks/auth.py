# -*- coding: utf-8 -*-
"""Mock API responses for auth endpoints."""
from __future__ import annotations

import json
from playwright.sync_api import Page


def register(page: Page):
    """Register auth API route mocks."""

    def _handle_auth_status(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"enabled": True, "has_users": True}),
        )

    def _handle_auth_login(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "token": "mock-jwt-token-for-smoke-test",
                    "username": "admin",
                },
            ),
        )

    def _handle_auth_register(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "token": "mock-jwt-token-for-smoke-test",
                    "username": "admin",
                },
            ),
        )

    page.route("**/api/auth/status", _handle_auth_status)
    page.route("**/api/auth/login", _handle_auth_login)
    page.route("**/api/auth/register", _handle_auth_register)
