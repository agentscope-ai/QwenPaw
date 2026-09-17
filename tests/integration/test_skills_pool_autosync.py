# -*- coding: utf-8 -*-
"""Integration tests for skill-pool auto-sync deepening (Sprint 4.4).

Deepens coverage of ``SkillPoolService`` / the pool router beyond the
CRUD paths already in ``test_skills_pool.py``. Focus: the v2.0 auto-sync
surface that was previously 0-covered:

  - PUT  /api/skills/pool/{skill_name}/auto-update   (toggle + 404)
  - GET  /api/skills/pool/builtin-notice
  - GET  /api/skills/pool/builtin-sources
  - POST /api/skills/pool/refresh
  - POST /api/skills/hub/install/cancel/{task_id}    (404 branch)
  - GET  /api/skills/workspaces

All pool endpoints use the global ``SkillPoolService()`` singleton, so we
hit the global ``/api/skills/*`` paths directly (agent-scoped routing for
pool URLs is covered elsewhere). Happy path first; each mutation is
verified via a follow-up GET (side-effect assertion). No LLM / network
deps (hub search excluded — needs a real hub).
"""
from __future__ import annotations

from typing import Any

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(15.0)
_POOL_BASE = "/api/skills/pool"


# ------------------------------------------------------------------ #
# helpers (mirror test_skills_pool.py house style)
# ------------------------------------------------------------------ #


def _skill_md(name: str, description: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        "# Pool Auto-sync Skill\n"
        "Created by pool auto-sync integration tests.\n"
    )


def _create_pool_skill(app_server, name: str) -> dict[str, Any]:
    resp = app_server.api_request(
        "POST",
        f"{_POOL_BASE}/create",
        json={
            "name": name,
            "content": _skill_md(name, "auto-sync test skill"),
            "enable": False,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    return resp.json()


def _delete_pool_skill_quietly(app_server, name: str) -> None:
    try:
        app_server.api_request(
            "DELETE",
            f"{_POOL_BASE}/{name}",
            timeout=_HTTP_TIMEOUT,
        )
    except Exception:
        pass


def _pool_entry(app_server, name: str) -> dict[str, Any] | None:
    resp = app_server.api_request("GET", _POOL_BASE, timeout=_HTTP_TIMEOUT)
    assert resp.status_code == 200, app_server.logs_tail()
    for item in resp.json():
        if item.get("name") == name:
            return item
    return None


# ================================================================== #
# A — auto-update toggle (happy path, P0/P1)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_auto_update_enable_then_disable_roundtrip(app_server) -> None:
    """PUT auto-update toggles the pool skill's auto_update flag.

    Test flow:
      1. Create a pool skill.
      2. PUT .../auto-update {enabled:True} -> 200 updated/enabled.
      3. GET /pool: the skill shows auto_update=True.
      4. PUT .../auto-update {enabled:False} -> 200.
      5. GET /pool: auto_update=False again.
      6. finally: delete the pool skill.

    API endpoints:
      - POST /api/skills/pool/create
      - PUT  /api/skills/pool/{skill_name}/auto-update
      - GET  /api/skills/pool
      - DELETE /api/skills/pool/{skill_name}
    """
    name = "integ-pool-au-roundtrip"
    try:
        _create_pool_skill(app_server, name)

        on = app_server.api_request(
            "PUT",
            f"{_POOL_BASE}/{name}/auto-update",
            json={"enabled": True, "targets": None},
            timeout=_HTTP_TIMEOUT,
        )
        assert on.status_code == 200, app_server.logs_tail()
        assert on.json()["updated"] is True
        assert on.json()["enabled"] is True
        entry = _pool_entry(app_server, name)
        assert entry is not None and entry["auto_update"] is True, entry

        off = app_server.api_request(
            "PUT",
            f"{_POOL_BASE}/{name}/auto-update",
            json={"enabled": False},
            timeout=_HTTP_TIMEOUT,
        )
        assert off.status_code == 200, app_server.logs_tail()
        assert off.json()["enabled"] is False
        entry = _pool_entry(app_server, name)
        assert entry is not None and entry["auto_update"] is False, entry
    finally:
        _delete_pool_skill_quietly(app_server, name)


@pytest.mark.integration
@pytest.mark.p1
def test_auto_update_persists_targets(app_server) -> None:
    """PUT auto-update with explicit targets persists them.

    Test flow:
      1. Create a pool skill.
      2. PUT .../auto-update {enabled:True, targets:[...]} -> 200,
         response echoes the targets.
      3. GET /pool: the slim list entry shows auto_update=True.
      4. GET /pool/{name}: the detail entry exposes the persisted
         auto_update_targets (the list view intentionally only carries
         lightweight fields; per-skill detail lives on the detail
         endpoint).
      5. finally: delete the pool skill.

    API endpoints:
      - PUT /api/skills/pool/{skill_name}/auto-update
      - GET /api/skills/pool
      - GET /api/skills/pool/{skill_name}
    """
    name = "integ-pool-au-targets"
    targets = ["default"]
    try:
        _create_pool_skill(app_server, name)
        resp = app_server.api_request(
            "PUT",
            f"{_POOL_BASE}/{name}/auto-update",
            json={"enabled": True, "targets": targets},
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        assert resp.json()["targets"] == targets
        entry = _pool_entry(app_server, name)
        assert entry is not None, "pool skill missing after auto-update"
        assert entry["auto_update"] is True
        detail = app_server.api_request(
            "GET",
            f"{_POOL_BASE}/{name}",
            timeout=_HTTP_TIMEOUT,
        )
        assert detail.status_code == 200, app_server.logs_tail()
        detail_body = detail.json()
        assert detail_body["auto_update_targets"] == targets, detail_body
    finally:
        _delete_pool_skill_quietly(app_server, name)


@pytest.mark.integration
@pytest.mark.p2
def test_auto_update_unknown_skill_returns_404(app_server) -> None:
    """PUT auto-update on a missing pool skill -> 404.

    API endpoints:
      - PUT /api/skills/pool/{skill_name}/auto-update
    """
    resp = app_server.api_request(
        "PUT",
        f"{_POOL_BASE}/integ-pool-au-nonexistent/auto-update",
        json={"enabled": True},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert "not found" in resp.json()["detail"].lower()


# ================================================================== #
# B — builtin notice / sources (happy path, P1)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_builtin_notice_returns_contract(app_server) -> None:
    """GET /pool/builtin-notice returns the documented contract.

    Test flow:
      1. GET /pool/builtin-notice -> 200.
      2. Assert fingerprint(str), has_updates(bool),
         total_changes(int>=0), and added/missing/updated/removed and
         actionable_skill_names are lists.

    API endpoints:
      - GET /api/skills/pool/builtin-notice
    """
    resp = app_server.api_request(
        "GET",
        f"{_POOL_BASE}/builtin-notice",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert isinstance(body["fingerprint"], str)
    assert isinstance(body["has_updates"], bool)
    assert isinstance(body["total_changes"], int)
    assert body["total_changes"] >= 0
    for field in ("added", "missing", "updated", "removed"):
        assert isinstance(body[field], list), body
    assert isinstance(body["actionable_skill_names"], list)


@pytest.mark.integration
@pytest.mark.p1
def test_builtin_sources_lists_candidates(app_server) -> None:
    """GET /pool/builtin-sources returns the builtin import candidates.

    Test flow:
      1. GET /pool/builtin-sources -> 200, a list.
      2. If non-empty, each item exposes name/status/available_languages/
         languages with the documented types.

    API endpoints:
      - GET /api/skills/pool/builtin-sources
    """
    resp = app_server.api_request(
        "GET",
        f"{_POOL_BASE}/builtin-sources",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    items = resp.json()
    assert isinstance(items, list)
    for item in items:
        assert isinstance(item["name"], str) and item["name"]
        assert isinstance(item["status"], str)
        assert isinstance(item["available_languages"], list)
        assert isinstance(item["languages"], dict)


@pytest.mark.integration
@pytest.mark.p1
def test_builtin_notice_reflects_import(app_server) -> None:
    """Importing a builtin shrinks the builtin-notice 'added' set.

    Test flow:
      1. GET /pool/builtin-sources; pick one candidate name.
      2. POST /pool/import-builtin {names:[that]} (best-effort).
      3. GET /pool/builtin-notice; the imported name no longer appears
         in 'added'.
      4. finally: delete the imported pool skill.

    API endpoints:
      - GET  /api/skills/pool/builtin-sources
      - POST /api/skills/pool/import-builtin
      - GET  /api/skills/pool/builtin-notice
    """
    sources = app_server.api_request(
        "GET",
        f"{_POOL_BASE}/builtin-sources",
        timeout=_HTTP_TIMEOUT,
    ).json()
    if not sources:
        pytest.skip("no packaged builtin skills available")
    target = sources[0]["name"]
    try:
        imp = app_server.api_request(
            "POST",
            f"{_POOL_BASE}/import-builtin",
            json={"names": [target]},
            timeout=_HTTP_TIMEOUT,
        )
        assert imp.status_code == 200, app_server.logs_tail()

        notice = app_server.api_request(
            "GET",
            f"{_POOL_BASE}/builtin-notice",
            timeout=_HTTP_TIMEOUT,
        ).json()
        added_names = {item["name"] for item in notice["added"]}
        assert target not in added_names, notice
    finally:
        _delete_pool_skill_quietly(app_server, target)


# ================================================================== #
# C — refresh (happy path, P1)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_refresh_returns_pool_list_with_created_skill(app_server) -> None:
    """POST /pool/refresh reconciles and returns the pool list.

    Test flow:
      1. Create a pool skill.
      2. POST /pool/refresh -> 200, a list containing the skill.
      3. finally: delete the pool skill.

    API endpoints:
      - POST /api/skills/pool/create
      - POST /api/skills/pool/refresh
    """
    name = "integ-pool-refresh-01"
    try:
        _create_pool_skill(app_server, name)
        resp = app_server.api_request(
            "POST",
            f"{_POOL_BASE}/refresh",
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        names = {item["name"] for item in resp.json()}
        assert name in names, names
    finally:
        _delete_pool_skill_quietly(app_server, name)


# ================================================================== #
# D — adjacent uncovered pool endpoints
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_list_workspace_skill_sources(app_server) -> None:
    """GET /skills/workspaces returns per-workspace skill summaries.

    Test flow:
      1. GET /api/skills/workspaces -> 200, a list.

    API endpoints:
      - GET /api/skills/workspaces
    """
    resp = app_server.api_request(
        "GET",
        "/api/skills/workspaces",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert isinstance(resp.json(), list)


@pytest.mark.integration
@pytest.mark.p2
def test_hub_install_cancel_unknown_task_returns_404(app_server) -> None:
    """POST /skills/hub/install/cancel/{task_id} unknown -> 404.

    API endpoints:
      - POST /api/skills/hub/install/cancel/{task_id}
    """
    resp = app_server.api_request(
        "POST",
        "/api/skills/hub/install/cancel/integ-no-such-task",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()
    assert "not found" in resp.json()["detail"].lower()
