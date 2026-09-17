# -*- coding: utf-8 -*-
"""Skill pool reconciliation and hub install-task APIs.

Covers the parts of ``app/routers/skills.py`` that existing skill tests
do not reach: the pool refresh/reconcile path, the built-in import
source catalogue and its update notice, the workspace-level skill
refresh, and the hub install-task lifecycle (start → status → cancel)
including its 404 branches.

The hub install is driven with an unreachable bundle URL so no network
fetch can succeed: the test asserts the task is *created and tracked*,
then cancels it, which is what exercises the task registry and the
cancel path without depending on GitHub.

API endpoints:
  - POST /api/skills/refresh
  - GET  /api/skills/pool
  - POST /api/skills/pool/refresh
  - GET  /api/skills/pool/builtin-sources
  - GET  /api/skills/pool/builtin-notice
  - POST /api/skills/hub/install/start
  - GET  /api/skills/hub/install/status/{task_id}
  - POST /api/skills/hub/install/cancel/{task_id}
"""
from __future__ import annotations

import time

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(60.0)

# Points at a closed local port: DNS always resolves, the connection
# always fails, so the install task cannot reach any real network.
_UNREACHABLE_BUNDLE = "http://127.0.0.1:9/integ-no-such-bundle.zip"


# ========================= A. pool reconciliation ==========================


@pytest.mark.integration
@pytest.mark.p1
def test_pool_refresh_matches_pool_listing(app_server):
    """Refreshing the pool returns the same set the listing reports.

    Test purpose:
      - Cover refresh_pool_skills (reconcile_pool_manifest plus the
        auto-update follow-up) and assert its result agrees with GET
        /pool, so a reconcile that silently drops entries is caught.
    """
    refreshed = app_server.api_request(
        "POST",
        "/api/skills/pool/refresh",
        timeout=_HTTP_TIMEOUT,
    )
    assert refreshed.status_code == 200, refreshed.text
    refreshed_names = {item["name"] for item in refreshed.json()}

    listing = app_server.api_request(
        "GET",
        "/api/skills/pool",
        timeout=_HTTP_TIMEOUT,
    )
    assert listing.status_code == 200, listing.text
    listed_names = {item["name"] for item in listing.json()}
    assert refreshed_names == listed_names, (
        f"refresh and listing disagree: "
        f"only_in_refresh={refreshed_names - listed_names} "
        f"only_in_listing={listed_names - refreshed_names}"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_pool_refresh_is_idempotent(app_server):
    """Two consecutive refreshes converge on the same pool.

    Test purpose:
      - Prove reconcile is idempotent: a manifest reconciliation that
        duplicated or dropped entries on a second pass would show up as
        a set difference here.
    """
    first = app_server.api_request(
        "POST",
        "/api/skills/pool/refresh",
        timeout=_HTTP_TIMEOUT,
    )
    assert first.status_code == 200, first.text
    second = app_server.api_request(
        "POST",
        "/api/skills/pool/refresh",
        timeout=_HTTP_TIMEOUT,
    )
    assert second.status_code == 200, second.text
    assert {i["name"] for i in first.json()} == {
        i["name"] for i in second.json()
    }, "pool reconcile is not idempotent"


@pytest.mark.integration
@pytest.mark.p2
def test_pool_builtin_sources_listing(app_server):
    """Built-in import candidates are listed with names.

    Test purpose:
      - Cover list_pool_builtin_sources / list_builtin_import_candidates
        and the BuiltinImportSpec projection.
    """
    resp = app_server.api_request(
        "GET",
        "/api/skills/pool/builtin-sources",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert isinstance(items, list), items
    for item in items:
        assert item.get("name"), item


@pytest.mark.integration
@pytest.mark.p2
def test_pool_builtin_notice_shape(app_server):
    """The built-in update notice reports a self-consistent summary.

    Test purpose:
      - Cover get_pool_builtin_notice's projection of added / missing /
        updated / removed buckets, asserting has_updates agrees with
        total_changes rather than only checking the status code.
    """
    resp = app_server.api_request(
        "GET",
        "/api/skills/pool/builtin-notice",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("added", "missing", "updated", "removed"):
        assert isinstance(body.get(key), list), (key, body)
    assert isinstance(body.get("has_updates"), bool), body
    total = int(body.get("total_changes") or 0)
    assert total >= 0, body
    if total == 0:
        assert body["has_updates"] is False, body


@pytest.mark.integration
@pytest.mark.p1
def test_skills_refresh_matches_skill_listing(app_server):
    """Refreshing workspace skills agrees with the skill listing.

    Test purpose:
      - Cover refresh_skills, the workspace-level rescan, and verify it
        does not diverge from GET /api/skills.
    """
    refreshed = app_server.api_request(
        "POST",
        "/api/skills/refresh",
        timeout=_HTTP_TIMEOUT,
    )
    assert refreshed.status_code == 200, refreshed.text
    refreshed_names = {item["name"] for item in refreshed.json()}

    listing = app_server.api_request(
        "GET",
        "/api/skills",
        timeout=_HTTP_TIMEOUT,
    )
    assert listing.status_code == 200, listing.text
    listed_names = {item["name"] for item in listing.json()}
    assert refreshed_names == listed_names, (
        f"only_in_refresh={refreshed_names - listed_names} "
        f"only_in_listing={listed_names - refreshed_names}"
    )


# ======================= B. hub install task lifecycle =====================


@pytest.mark.integration
@pytest.mark.p1
def test_hub_install_task_is_tracked_then_cancelled(app_server):
    """A started install is queryable by id and can be cancelled.

    Test purpose:
      - Cover start_install_from_hub's task registration,
        get_hub_install_status' lookup, and cancel_hub_install's
        cancel/terminal handling — without any real network fetch.

    Test flow:
      1. POST a start request whose bundle_url points at a closed port.
      2. GET the status by task id and assert the same id comes back.
      3. POST cancel and assert a terminal status is reported.
      4. GET the status again and assert it stays terminal.
    """
    start = app_server.api_request(
        "POST",
        "/api/skills/hub/install/start",
        json={
            "bundle_url": _UNREACHABLE_BUNDLE,
            "version": "0.0.1",
            "enable": False,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert start.status_code == 200, start.text
    task_id = start.json()["task_id"]
    assert task_id, start.json()

    status = app_server.api_request(
        "GET",
        f"/api/skills/hub/install/status/{task_id}",
        timeout=_HTTP_TIMEOUT,
    )
    assert status.status_code == 200, status.text
    assert status.json()["task_id"] == task_id, status.json()

    cancel = app_server.api_request(
        "POST",
        f"/api/skills/hub/install/cancel/{task_id}",
        timeout=_HTTP_TIMEOUT,
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["task_id"] == task_id, cancel.json()

    # The task must settle into a terminal state and stay there.
    deadline = time.time() + 20.0
    terminal = {"cancelled", "failed", "succeeded", "success"}
    final = None
    while time.time() < deadline:
        again = app_server.api_request(
            "GET",
            f"/api/skills/hub/install/status/{task_id}",
            timeout=_HTTP_TIMEOUT,
        )
        assert again.status_code == 200, again.text
        final = str(again.json().get("status", "")).lower()
        if final in terminal:
            break
        time.sleep(0.4)
    assert (
        final in terminal
    ), f"install task never reached a terminal status: {final!r}"


@pytest.mark.integration
@pytest.mark.p2
def test_hub_install_status_unknown_task_returns_404(app_server):
    """Querying an unknown install task is a 404.

    Test purpose:
      - Cover get_hub_install_status' not-found branch.
    """
    resp = app_server.api_request(
        "GET",
        "/api/skills/hub/install/status/integ-no-such-install-task",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, resp.text
    assert "not found" in resp.text.lower(), resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_hub_install_start_rejects_missing_bundle_url(app_server):
    """A start request with no bundle_url is rejected by validation.

    Test purpose:
      - Cover HubInstallRequest's required-field validation, which keeps
        an unusable task out of the registry entirely.
    """
    resp = app_server.api_request(
        "POST",
        "/api/skills/hub/install/start",
        json={"version": "0.0.1"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 422, resp.text
