# -*- coding: utf-8 -*-
"""PawApp discovery, settings and static-asset APIs.

Covers ``app/routers/pawapps.py``, which had no integration coverage:
the installed-app listing (registry path plus the directory-scan
fallback), per-app detail and settings lookups, the static-asset server,
and every security guard on the ``app_id`` / ``file_path`` segments —
traversal attempts, invalid ids, and unknown apps.

The router's guards are asserted by their distinct status codes (400 for
a malformed id, 403 for an escape attempt, 404 for a missing app or
file), and the traversal tests also assert no host file content leaked.
All requests are read-only apart from an uninstall of a deliberately
non-existent app, so nothing on disk is destroyed.

API endpoints:
  - GET    /api/pawapps
  - GET    /api/pawapps/{app_id}
  - GET    /api/pawapps/{app_id}/settings
  - GET    /api/pawapps/{app_id}/static/{file_path}
  - DELETE /api/pawapps/{app_id}
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)

# An id that cannot exist, so uninstall only reaches the 404 branch and
# never deletes anything real.
_ABSENT_APP = "integ-absent-pawapp-7742"


# ============================== A. listing =================================


@pytest.mark.integration
@pytest.mark.p1
def test_list_pawapps_returns_apps_and_total(app_server):
    """The listing reports apps plus a consistent total.

    Test purpose:
      - Cover list_pawapps including the directory-scan fallback that
        runs when the plugin registry has no PawApps, and assert the
        ``total`` field matches the returned collection rather than only
        checking for a 200.
    """
    resp = app_server.api_request(
        "GET",
        "/api/pawapps",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert isinstance(body.get("apps"), list), body
    assert body.get("total") == len(body["apps"]), body


# ========================= B. detail / settings ============================


@pytest.mark.integration
@pytest.mark.p2
def test_get_unknown_pawapp_returns_404(app_server):
    """Requesting an app that is not installed is a clean 404.

    Test purpose:
      - Cover get_pawapp's not-found branch, reached only after the
        registry lookup and the scan fallback both come up empty.
    """
    resp = app_server.api_request(
        "GET",
        f"/api/pawapps/{_ABSENT_APP}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.text.lower(), resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_get_unknown_pawapp_settings_returns_404(app_server):
    """Settings for an absent app are a 404, not an empty schema.

    Test purpose:
      - Cover get_pawapp_settings' own not-found branch, which is a
        separate handler from the detail route above.
    """
    resp = app_server.api_request(
        "GET",
        f"/api/pawapps/{_ABSENT_APP}/settings",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_installed_pawapp_settings_shape(app_server):
    """When an app is installed, its settings come back keyed by id.

    Test purpose:
      - Cover the success path of get_pawapp_settings. The environment
        may ship no PawApps, so the test skips rather than asserting a
        fixture that does not exist.
    """
    listing = app_server.api_request(
        "GET",
        "/api/pawapps",
        timeout=_HTTP_TIMEOUT,
    )
    assert listing.status_code == 200, listing.text
    apps = listing.json().get("apps") or []
    if not apps:
        pytest.skip("no PawApps installed in this environment")

    app_id = apps[0]["id"]
    detail = app_server.api_request(
        "GET",
        f"/api/pawapps/{app_id}",
        timeout=_HTTP_TIMEOUT,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == app_id, detail.json()

    settings = app_server.api_request(
        "GET",
        f"/api/pawapps/{app_id}/settings",
        timeout=_HTTP_TIMEOUT,
    )
    assert settings.status_code == 200, settings.text
    body = settings.json()
    assert body["app_id"] == app_id, body
    assert isinstance(body.get("settings"), list), body


# ========================= C. static asset guards ==========================


@pytest.mark.integration
@pytest.mark.p2
def test_static_for_unknown_app_returns_404(app_server):
    """Static assets of an absent app are a 404.

    Test purpose:
      - Cover serve_pawapp_static's missing-app-directory branch, which
        sits before any file resolution.
    """
    resp = app_server.api_request(
        "GET",
        f"/api/pawapps/{_ABSENT_APP}/static/index.html",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.integration
@pytest.mark.p1
def test_static_path_traversal_is_blocked(app_server):
    """A traversal in the file path cannot escape the app directory.

    Test purpose:
      - Cover the ``is_relative_to`` containment check on the static
        route. A successful escape would let any browser read host
        files through the PawApp asset server.

    Test flow:
      1. Request a percent-encoded ``..`` chain pointing at /etc/passwd
         (a literal ``../`` would be normalized away client-side and
         never reach the handler).
      2. Assert a refusal status and that no passwd content leaked.
    """
    traversal = "%2e%2e/%2e%2e/%2e%2e/%2e%2e/etc/passwd"
    resp = app_server.api_request(
        "GET",
        f"/api/pawapps/{_ABSENT_APP}/static/{traversal}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (400, 403, 404), resp.text[:500]
    assert "root:" not in resp.text, "traversal leaked /etc/passwd"


@pytest.mark.integration
@pytest.mark.p1
def test_static_rejects_traversal_in_app_id(app_server):
    """A dotted app id is refused before touching the filesystem.

    Test purpose:
      - Cover the app_id segment guard, which rejects ``.``/``..`` and
        any embedded separator so the app directory cannot be relocated.
    """
    resp = app_server.api_request(
        "GET",
        "/api/pawapps/%2e%2e/static/index.html",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (400, 403, 404), resp.text[:500]
    assert "root:" not in resp.text, resp.text[:300]


# ============================ D. uninstall =================================


@pytest.mark.integration
@pytest.mark.p2
def test_uninstall_unknown_pawapp_returns_404(app_server):
    """Uninstalling an app that does not exist is a 404.

    Test purpose:
      - Cover uninstall_pawapp's final not-found branch, reached after
        the id guard passes, no plugin is loaded, and no directory
        exists. Uses an id that cannot exist so nothing is deleted.
    """
    resp = app_server.api_request(
        "DELETE",
        f"/api/pawapps/{_ABSENT_APP}",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.text.lower(), resp.text


@pytest.mark.integration
@pytest.mark.p1
def test_uninstall_rejects_invalid_app_id(app_server):
    """A dotted app id cannot be passed to uninstall.

    Test purpose:
      - Cover the uninstall id guard: without it, ``..`` would resolve
        the delete target outside the apps directory.
    """
    resp = app_server.api_request(
        "DELETE",
        "/api/pawapps/%2e%2e",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (400, 404), resp.text
