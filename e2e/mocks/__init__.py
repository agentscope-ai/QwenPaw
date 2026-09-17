# -*- coding: utf-8 -*-
"""
Mock API modules for UI smoke tests.

Each module registers page.route() handlers for its API endpoints.
Call register_all(page) to set up all mocks at once.
"""
from __future__ import annotations

import json
from typing import List

from playwright.sync_api import Page


def _json_response(data, status=200):
    """Create a fulfillment handler that returns JSON."""
    return lambda route: route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps(data),
    )


def register_all(page: Page):
    """Register all API route mocks for UI smoke tests.

    Playwright matches routes in reverse registration order (last registered = first matched),
    so we register the catch-all FIRST and specific routes AFTER to ensure specific routes
    take priority.
    """
    from mocks import auth, agents, channels, sessions, cron_jobs, heartbeat
    from mocks import models, security, environments, backups

    # Catch-all: return empty JSON for any unmatched /api/ routes.
    # Registered first so specific routes (registered after) take priority.
    page.route(
        "**/api/**",
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({}),
        ),
    )

    # Specific route mocks — registered after catch-all so they match first
    for module in [
        auth,
        agents,
        channels,
        sessions,
        cron_jobs,
        heartbeat,
        models,
        security,
        environments,
        backups,
    ]:
        module.register(page)


# Re-export helper for individual mock modules
__all__ = ["register_all", "_json_response"]
