# -*- coding: utf-8 -*-
"""Plugin static-file serving guards.

Covers ``app/routers/plugins.py``'s ``/{plugin_id}/files/{file_path}``
route, which existing plugin tests do not touch: the unknown-plugin
lookup, the path-traversal containment check, and the missing-file
branch. These are the guards that keep the plugin asset server from
turning into an arbitrary-file reader for the browser.

The market-search proxy is deliberately not covered here: it forwards to
an external platform host, so a test would depend on outbound network.

API endpoints:
  - GET /api/plugins
  - GET /api/plugins/{plugin_id}/files/{file_path}
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)

_ABSENT_PLUGIN = "integ-absent-plugin-5583"


def _installed_plugin_ids(app_server) -> list[str]:
    resp = app_server.api_request(
        "GET",
        "/api/plugins",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body if isinstance(body, list) else body.get("plugins") or []
    return [item["id"] for item in items if item.get("id")]


@pytest.mark.integration
@pytest.mark.p2
def test_plugin_file_for_unknown_plugin_returns_404(app_server):
    """Serving a file from an unknown plugin is a 404.

    Test purpose:
      - Cover serve_plugin_ui_file's plugin-lookup branch (both the
        loader-record path and the on-disk fallback resolve to "not
        found" for an id that was never installed).
    """
    resp = app_server.api_request(
        "GET",
        f"/api/plugins/{_ABSENT_PLUGIN}/files/index.js",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.text.lower(), resp.text


@pytest.mark.integration
@pytest.mark.p1
def test_plugin_file_path_traversal_is_blocked(app_server):
    """A traversal in the file path cannot escape the plugin directory.

    Test purpose:
      - Cover the ``is_relative_to`` containment guard. A successful
        escape here would let any page read host files through the
        plugin asset route, so the test also asserts no passwd content
        came back.

    Test flow:
      1. Pick an installed plugin when one exists, else use an absent id
         (the traversal must be refused either way).
      2. Request a percent-encoded ``..`` chain pointing at /etc/passwd.
      3. Assert a refusal status and that no file content leaked.
    """
    ids = _installed_plugin_ids(app_server)
    plugin_id = ids[0] if ids else _ABSENT_PLUGIN
    traversal = "%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd"
    resp = app_server.api_request(
        "GET",
        f"/api/plugins/{plugin_id}/files/{traversal}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (400, 403, 404), resp.text[:500]
    assert "root:" not in resp.text, "traversal leaked /etc/passwd"


@pytest.mark.integration
@pytest.mark.p2
def test_plugin_file_missing_asset_returns_404(app_server):
    """A missing asset inside a real plugin is a 404, not a 500.

    Test purpose:
      - Cover the exists/is_file check that runs after the containment
        guard passes. Skips when no plugin is installed, since the
        branch is only reachable with a real plugin directory.
    """
    ids = _installed_plugin_ids(app_server)
    if not ids:
        pytest.skip("no plugins installed in this environment")
    resp = app_server.api_request(
        "GET",
        f"/api/plugins/{ids[0]}/files/integ-no-such-asset-4471.js",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text
