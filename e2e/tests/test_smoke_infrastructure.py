# -*- coding: utf-8 -*-
"""
UI smoke test: validates mock API infrastructure works correctly.

This test uses page.route() to mock all API responses, so it only
needs a frontend dev server — no backend or API keys required.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

from config.settings import config


def _goto(page: Page, url: str):
    """Navigate to URL with wait_until='commit' to avoid HMR WebSocket blocking."""
    page.goto(url, wait_until="commit")


@pytest.mark.ui_smoke
@pytest.mark.login_form
@pytest.mark.test_id("SMOKE-INFRA-001")
class TestMockInfrastructure:
    """Validate that mock API routes intercept requests correctly."""

    def test_mock_auth_status_intercepted(self, mock_api: Page):
        """Verify /api/auth/status route mock intercepts browser requests."""
        _goto(mock_api, config.server.base_url)

        result = mock_api.evaluate(
            """
            async () => {
                const resp = await fetch('/api/auth/status');
                return await resp.json();
            }
        """,
        )
        assert result["enabled"] is True
        assert result["has_users"] is True

    def test_mock_agents_list_intercepted(self, mock_api: Page):
        """Verify /api/agents route mock intercepts browser requests."""
        _goto(mock_api, config.server.base_url)

        result = mock_api.evaluate(
            """
            async () => {
                const resp = await fetch('/api/agents');
                return await resp.json();
            }
        """,
        )
        assert "agents" in result
        assert isinstance(result["agents"], list)

    def test_mock_catchall_intercepted(self, mock_api: Page):
        """Verify unmatched /api/ routes return empty JSON (catch-all)."""
        _goto(mock_api, config.server.base_url)

        result = mock_api.evaluate(
            """
            async () => {
                const resp = await fetch('/api/unknown-endpoint');
                return await resp.json();
            }
        """,
        )
        assert result == {}


@pytest.mark.ui_smoke
@pytest.mark.login_form
@pytest.mark.test_id("SMOKE-INFRA-002")
class TestLoginPageWithMocks:
    """Validate login page renders with mocked API."""

    def test_login_page_loads(self, mock_api: Page):
        """Navigate to app and verify page renders."""
        _goto(mock_api, config.server.base_url)

        title = mock_api.title()
        assert title is not None
        assert len(title) > 0
