# -*- coding: utf-8 -*-
"""Targeted route mocks for the Plugin Market compatibility feature.

Unlike the ``register_all`` smoke mocks, these are meant to be layered on
top of a *real* backend inside integration tests: only the market catalog,
version probe and install endpoints are intercepted, because the market
catalog is fetched from the network (platform.agentscope.io proxy) and is
not seedable locally.

Response shapes mirror ``console/src/api/modules/pluginMarket.ts``
(``MarketPluginListResponse`` / ``MarketPluginEntry``) and
``useMarketPlugins.ts`` (``/api/version`` -> ``{"version": ...}``).
"""
from __future__ import annotations

import json

from playwright.sync_api import Page

# Names are matched by the tests — keep them unique enough to locate rows.
COMPATIBLE_PLUGIN_NAME = "E2E Compat Plugin"
INCOMPATIBLE_PLUGIN_NAME = "E2E Legacy Plugin"

# Backend version reported to the frontend; deriveCompatLabel() turns it
# into the "2.x" label used for the includes() check.
MOCK_QWENPAW_VERSION = "2.0.0"

_MARKET_PLUGINS = [
    {
        "id": "e2e-compat-plugin",
        "display_name": COMPATIBLE_PLUGIN_NAME,
        "developer": "e2e",
        "owner": "e2e",
        "version": "1.0.0",
        "logo_url": None,
        "downloads": 42,
        "view_count": 100,
        "details_url": None,
        "locales": {
            "en": {"description": "Compatible test plugin", "category": "tools"},
            "zh": {"description": "兼容性测试插件", "category": "tools"},
        },
        "qwenpaw_compat_labels": ["2.x"],
        "is_featured": False,
    },
    {
        "id": "e2e-legacy-plugin",
        "display_name": INCOMPATIBLE_PLUGIN_NAME,
        "developer": "e2e",
        "owner": "e2e",
        "version": "0.9.0",
        "logo_url": None,
        "downloads": 7,
        "view_count": 10,
        "details_url": None,
        "locales": {
            "en": {"description": "Incompatible test plugin", "category": "tools"},
            "zh": {"description": "不兼容测试插件", "category": "tools"},
        },
        "qwenpaw_compat_labels": ["1.x"],
        "is_featured": False,
    },
]


def register(page: Page) -> None:
    """Intercept market search / version / install for one page."""

    def _handle_search(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "success": True,
                    "message": "",
                    "data": {
                        "total": len(_MARKET_PLUGINS),
                        "plugins": _MARKET_PLUGINS,
                    },
                }
            ),
        )

    def _handle_version(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({"version": MOCK_QWENPAW_VERSION}),
        )

    def _handle_install(route):
        # Never let a mocked install reach the real CDN / plugin loader.
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "id": "e2e-legacy-plugin",
                    "name": INCOMPATIBLE_PLUGIN_NAME,
                    "version": "0.9.0",
                    "description": "mocked install",
                    "loaded": True,
                    "message": "",
                }
            ),
        )

    page.route("**/api/plugins/market/search*", _handle_search)
    page.route("**/api/version", _handle_version)
    page.route("**/api/plugins/install", _handle_install)
