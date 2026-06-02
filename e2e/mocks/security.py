# -*- coding: utf-8 -*-
"""Mock API responses for security endpoints."""
from __future__ import annotations

import json
from playwright.sync_api import Page

_MOCK_TOOL_GUARD = {
    "enabled": True,
    "guarded_tools": None,
    "denied_tools": [],
    "custom_rules": [],
    "disabled_rules": [],
    "auto_denied_rules": [],
    "shell_evasion_checks": {"enabled": False, "blocked_commands": []},
}

_MOCK_FILE_GUARD = {
    "enabled": False,
    "paths": [],
}

_MOCK_SKILL_SCANNER = {
    "mode": "off",
    "timeout": 30,
    "whitelist": [],
}

_MOCK_ALLOW_NO_AUTH_HOSTS = {
    "hosts": [],
}


def register(page: Page):
    """Register security API route mocks."""

    def _handle_tool_guard(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_TOOL_GUARD),
        )

    def _handle_tool_guard_builtin(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([]),
        )

    def _handle_file_guard(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_FILE_GUARD),
        )

    def _handle_skill_scanner(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_SKILL_SCANNER),
        )

    def _handle_skill_scanner_history(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps([]),
        )

    def _handle_skill_scanner_whitelist(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"whitelisted": True, "skill_name": "test"}),
        )

    def _handle_allow_no_auth_hosts(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(_MOCK_ALLOW_NO_AUTH_HOSTS),
        )

    page.route(
        "**/api/config/security/tool-guard/builtin-rules**",
        _handle_tool_guard_builtin,
    )
    page.route("**/api/config/security/tool-guard", _handle_tool_guard)
    page.route("**/api/config/security/file-guard", _handle_file_guard)
    page.route(
        "**/api/config/security/skill-scanner/blocked-history**",
        _handle_skill_scanner_history,
    )
    page.route(
        "**/api/config/security/skill-scanner/whitelist**",
        _handle_skill_scanner_whitelist,
    )
    page.route("**/api/config/security/skill-scanner", _handle_skill_scanner)
    page.route(
        "**/api/config/security/allow-no-auth-hosts",
        _handle_allow_no_auth_hosts,
    )
