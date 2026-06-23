# -*- coding: utf-8 -*-
"""Integration tests for skill pool CRUD endpoints.

Pool endpoints (``/api/skills/pool/*``) use ``SkillPoolService()`` — a
global singleton that ignores the ``agentId`` path parameter when
reached via agent-scoped routing.  Tests here hit the global
``/api/skills/pool/*`` paths directly.

Agent-scoped routing coverage for pool URLs is in
``test_agent_scoped_routing.py``.
"""
from __future__ import annotations

import io
import zipfile
from typing import Any

import pytest

_HTTP_TIMEOUT = 15.0
_POOL_BASE = "/api/skills/pool"


# ------------------------------------------------------------------ #
# helpers
# ------------------------------------------------------------------ #


def _skill_md(name: str, description: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        "# Pool Integration Skill\n"
        "This skill is created by pool integration tests.\n"
    )


def _create_pool_skill(
    app_server,
    name: str,
    *,
    description: str = "pool test skill",
) -> dict[str, Any]:
    resp = app_server.api_request(
        "POST",
        f"{_POOL_BASE}/create",
        json={
            "name": name,
            "content": _skill_md(name, description),
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


def _list_pool_skill_names(app_server) -> set[str]:
    resp = app_server.api_request(
        "GET",
        _POOL_BASE,
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    return {item["name"] for item in resp.json()}


def _build_skill_zip(skills: dict[str, str]) -> bytes:
    """Build a zip containing one SKILL.md per skill name."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in skills.items():
            zf.writestr(f"{name}/SKILL.md", content)
    return buf.getvalue()


# ------------------------------------------------------------------ #
# lifecycle
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_skill_lifecycle(app_server) -> None:
    """Test purpose:
    - Verify the create → list → get-config → delete lifecycle for a
      pool skill. This is the primary happy-path CRUD coverage.

    Test flow:
    1. POST /pool/create with a new skill.
    2. GET /pool — assert the skill appears.
    3. GET /pool/{name}/config — assert empty config.
    4. DELETE /pool/{name} — assert ``deleted=True``.
    5. GET /pool — assert the skill is gone.

    API endpoints:
    - POST /api/skills/pool/create
    - GET  /api/skills/pool
    - GET  /api/skills/pool/{skill_name}/config
    - DELETE /api/skills/pool/{skill_name}
    """
    name = "integ-pool-lifecycle-01"
    try:
        result = _create_pool_skill(app_server, name)
        assert result.get("created") is True

        assert name in _list_pool_skill_names(app_server)

        config_resp = app_server.api_request(
            "GET",
            f"{_POOL_BASE}/{name}/config",
            timeout=_HTTP_TIMEOUT,
        )
        assert config_resp.status_code == 200, app_server.logs_tail()
        assert config_resp.json().get("config") == {}

        del_resp = app_server.api_request(
            "DELETE",
            f"{_POOL_BASE}/{name}",
            timeout=_HTTP_TIMEOUT,
        )
        assert del_resp.status_code == 200, app_server.logs_tail()
        assert del_resp.json().get("deleted") is True

        assert name not in _list_pool_skill_names(app_server)
    finally:
        _delete_pool_skill_quietly(app_server, name)


@pytest.mark.integration
@pytest.mark.p0
def test_pool_skill_duplicate_409(app_server) -> None:
    """Test purpose:
    - Verify POST /pool/create with an existing name returns 409 and
      includes a ``suggested_name``.

    Test flow:
    1. Create pool skill ``integ-pool-dup-01``.
    2. POST /pool/create with the same name.
    3. Assert 409 and detail.reason == ``conflict``.

    API endpoints:
    - POST /api/skills/pool/create
    """
    name = "integ-pool-dup-01"
    try:
        _create_pool_skill(app_server, name)

        dup_resp = app_server.api_request(
            "POST",
            f"{_POOL_BASE}/create",
            json={
                "name": name,
                "content": _skill_md(name, "duplicate"),
                "enable": False,
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert dup_resp.status_code == 409, app_server.logs_tail()
        detail = dup_resp.json().get("detail", {})
        assert detail.get("reason") == "conflict"
        assert "suggested_name" in detail
    finally:
        _delete_pool_skill_quietly(app_server, name)


# ------------------------------------------------------------------ #
# save
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_save_missing_404(app_server) -> None:
    """Test purpose:
    - Verify PUT /pool/save on a non-existent pool skill returns 404.

    Test flow:
    1. PUT /pool/save with a name that does not exist.
    2. Assert 404.

    API endpoints:
    - PUT /api/skills/pool/save
    """
    resp = app_server.api_request(
        "PUT",
        f"{_POOL_BASE}/save",
        json={
            "name": "integ-pool-nosuch-01",
            "content": _skill_md("nosuch", "missing"),
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


# ------------------------------------------------------------------ #
# delete
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_delete_missing_409(app_server) -> None:
    """Test purpose:
    - Verify DELETE /pool/{name} for a non-existent skill returns 409
      ``cannot be deleted``.

    Test flow:
    1. DELETE /pool/<nonexistent>.
    2. Assert 409.

    API endpoints:
    - DELETE /api/skills/pool/{skill_name}
    """
    resp = app_server.api_request(
        "DELETE",
        f"{_POOL_BASE}/integ-pool-gone-01",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 409, app_server.logs_tail()


# ------------------------------------------------------------------ #
# config
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_config_put_missing_404(app_server) -> None:
    """Test purpose:
    - Verify PUT /pool/{name}/config returns 404 when the skill does
      not exist.

    API endpoints:
    - PUT /api/skills/pool/{skill_name}/config
    """
    resp = app_server.api_request(
        "PUT",
        f"{_POOL_BASE}/integ-pool-cfg-miss-01/config",
        json={"config": {"key": "value"}},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p0
def test_pool_config_delete_missing_404(app_server) -> None:
    """Test purpose:
    - Verify DELETE /pool/{name}/config returns 404 when the skill
      does not exist.

    API endpoints:
    - DELETE /api/skills/pool/{skill_name}/config
    """
    resp = app_server.api_request(
        "DELETE",
        f"{_POOL_BASE}/integ-pool-cfg-del-miss-01/config",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p0
def test_pool_config_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify PUT → GET → DELETE config roundtrip on a pool skill.
      This is the happy-path coverage for the pool config endpoints.

    Test flow:
    1. Create pool skill.
    2. PUT config with ``{"llm_model": "qwen-max"}``.
    3. GET config — assert value matches.
    4. DELETE config — assert ``cleared=True``.
    5. GET config — assert empty.

    API endpoints:
    - PUT    /api/skills/pool/{skill_name}/config
    - GET    /api/skills/pool/{skill_name}/config
    - DELETE /api/skills/pool/{skill_name}/config
    """
    name = "integ-pool-cfg-rt-01"
    try:
        _create_pool_skill(app_server, name)

        put_resp = app_server.api_request(
            "PUT",
            f"{_POOL_BASE}/{name}/config",
            json={"config": {"llm_model": "qwen-max"}},
            timeout=_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("updated") is True

        get_resp = app_server.api_request(
            "GET",
            f"{_POOL_BASE}/{name}/config",
            timeout=_HTTP_TIMEOUT,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        assert get_resp.json()["config"]["llm_model"] == "qwen-max"

        del_resp = app_server.api_request(
            "DELETE",
            f"{_POOL_BASE}/{name}/config",
            timeout=_HTTP_TIMEOUT,
        )
        assert del_resp.status_code == 200, app_server.logs_tail()
        assert del_resp.json().get("cleared") is True

        empty_resp = app_server.api_request(
            "GET",
            f"{_POOL_BASE}/{name}/config",
            timeout=_HTTP_TIMEOUT,
        )
        assert empty_resp.status_code == 200, app_server.logs_tail()
        assert empty_resp.json()["config"] == {}
    finally:
        _delete_pool_skill_quietly(app_server, name)


# ------------------------------------------------------------------ #
# tags
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_tags_put_missing_404(app_server) -> None:
    """Test purpose:
    - Verify PUT /pool/{name}/tags returns 404 when the skill does
      not exist.

    API endpoints:
    - PUT /api/skills/pool/{skill_name}/tags
    """
    resp = app_server.api_request(
        "PUT",
        f"{_POOL_BASE}/integ-pool-tags-miss-01/tags",
        json=["automation"],
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


# ------------------------------------------------------------------ #
# batch-delete
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_batch_delete_partial(app_server) -> None:
    """Test purpose:
    - Verify POST /pool/batch-delete with a mix of existing and
      non-existent names returns per-skill results (success for
      existing, failure for missing).

    Test flow:
    1. Create pool skill ``integ-pool-bd-a``.
    2. POST batch-delete with ``["integ-pool-bd-a", "integ-pool-bd-ghost"]``.
    3. Assert ``integ-pool-bd-a`` succeeds, ``integ-pool-bd-ghost`` fails.

    API endpoints:
    - POST /api/skills/pool/batch-delete
    """
    name = "integ-pool-bd-a"
    ghost = "integ-pool-bd-ghost"
    try:
        _create_pool_skill(app_server, name)

        resp = app_server.api_request(
            "POST",
            f"{_POOL_BASE}/batch-delete",
            json=[name, ghost],
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        results = resp.json().get("results", {})
        assert results[name]["success"] is True
        assert results[ghost]["success"] is False
    finally:
        _delete_pool_skill_quietly(app_server, name)


@pytest.mark.integration
@pytest.mark.p0
def test_pool_batch_delete_all_success(app_server) -> None:
    """Test purpose:
    - Verify POST /pool/batch-delete succeeds for all names when all
      skills exist. This is the normal-flow batch cleanup scenario.

    Test flow:
    1. Create 3 pool skills.
    2. POST batch-delete with all 3 names.
    3. Assert all 3 succeed.
    4. GET /pool — assert none remain.

    API endpoints:
    - POST /api/skills/pool/batch-delete
    - GET  /api/skills/pool
    """
    names = [
        "integ-pool-bd-all-a",
        "integ-pool-bd-all-b",
        "integ-pool-bd-all-c",
    ]
    try:
        for n in names:
            _create_pool_skill(app_server, n)

        resp = app_server.api_request(
            "POST",
            f"{_POOL_BASE}/batch-delete",
            json=names,
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        results = resp.json().get("results", {})
        for n in names:
            assert results[n]["success"] is True

        remaining = _list_pool_skill_names(app_server)
        for n in names:
            assert n not in remaining
    finally:
        for n in names:
            _delete_pool_skill_quietly(app_server, n)


# ------------------------------------------------------------------ #
# upload-zip
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_upload_zip_valid(app_server) -> None:
    """Test purpose:
    - Verify POST /pool/upload-zip with a valid skill zip imports the
      skill into the pool. This is the happy-path for zip ingestion.

    Test flow:
    1. Build a zip with a single skill ``integ-pool-zip-01``.
    2. POST /pool/upload-zip.
    3. Assert 200 and ``count >= 1``.
    4. GET /pool — assert the skill appears.

    API endpoints:
    - POST /api/skills/pool/upload-zip
    - GET  /api/skills/pool
    """
    name = "integ-pool-zip-01"
    zip_bytes = _build_skill_zip(
        {
            name: _skill_md(name, "zip-imported pool skill"),
        },
    )
    try:
        resp = app_server.api_request(
            "POST",
            f"{_POOL_BASE}/upload-zip",
            files={
                "file": (
                    "skills.zip",
                    zip_bytes,
                    "application/zip",
                ),
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        payload = resp.json()
        assert payload.get("count", 0) >= 1

        assert name in _list_pool_skill_names(app_server)
    finally:
        _delete_pool_skill_quietly(app_server, name)


# ------------------------------------------------------------------ #
# upload from workspace
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_upload_from_workspace(app_server) -> None:
    """Test purpose:
    - Verify POST /pool/upload copies a workspace skill into the pool.
      Requires a pre-existing workspace skill as input.

    Test flow:
    1. Create agent + workspace skill via ``POST /api/agents/{id}/skills``.
    2. POST /pool/upload with ``workspace_id`` and ``skill_name``.
    3. Assert 200 and ``success=True``.
    4. GET /pool — assert skill appears.

    API endpoints:
    - POST /api/skills/pool/upload
    - GET  /api/skills/pool
    """
    agent_id = "integ_pool_upload_ws_01"
    skill_name = "integ-pool-from-ws-01"
    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Pool upload source",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_skill = app_server.api_request(
            "POST",
            f"/api/agents/{agent_id}/skills",
            json={
                "name": skill_name,
                "content": _skill_md(skill_name, "source for pool"),
                "enable": False,
            },
        )
        assert create_skill.status_code == 200, app_server.logs_tail()

        upload_resp = app_server.api_request(
            "POST",
            f"{_POOL_BASE}/upload",
            json={
                "workspace_id": agent_id,
                "skill_name": skill_name,
                "overwrite": False,
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert upload_resp.status_code == 200, app_server.logs_tail()
        assert upload_resp.json().get("success") is True

        assert skill_name in _list_pool_skill_names(app_server)
    finally:
        _delete_pool_skill_quietly(app_server, skill_name)
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}/skills/{skill_name}",
        )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


# ------------------------------------------------------------------ #
# download
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_download_no_targets_400(app_server) -> None:
    """Test purpose:
    - Verify POST /pool/download with an empty targets list returns
      400 ``No workspace targets provided``.

    API endpoints:
    - POST /api/skills/pool/download
    """
    resp = app_server.api_request(
        "POST",
        f"{_POOL_BASE}/download",
        json={
            "skill_name": "integ-pool-dl-notar-01",
            "targets": [],
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()
    assert "No workspace targets" in resp.json().get("detail", "")


@pytest.mark.integration
@pytest.mark.p0
def test_pool_download_to_workspace(app_server) -> None:
    """Test purpose:
    - Verify POST /pool/download copies a pool skill into a workspace.
      End-to-end happy path: create pool skill → create agent →
      download → verify in workspace.

    Test flow:
    1. Create pool skill ``integ-pool-dl-01``.
    2. Create agent.
    3. POST /pool/download targeting that agent.
    4. Assert 200 and ``downloaded`` list has 1 entry.
    5. GET /api/agents/{id}/skills — assert the skill appears.

    API endpoints:
    - POST /api/skills/pool/download
    - GET  /api/agents/{agentId}/skills
    """
    pool_name = "integ-pool-dl-01"
    agent_id = "integ_pool_dl_agent_01"

    try:
        _create_pool_skill(app_server, pool_name)

        create_agent = app_server.api_request(
            "POST",
            "/api/agents",
            json={
                "id": agent_id,
                "name": "Download target",
                "description": "",
            },
        )
        assert create_agent.status_code == 201, app_server.logs_tail()

        dl_resp = app_server.api_request(
            "POST",
            f"{_POOL_BASE}/download",
            json={
                "skill_name": pool_name,
                "targets": [{"workspace_id": agent_id}],
                "overwrite": False,
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert dl_resp.status_code == 200, app_server.logs_tail()
        downloaded = dl_resp.json().get("downloaded", [])
        assert len(downloaded) == 1
        assert downloaded[0]["workspace_id"] == agent_id

        ws_skills = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/skills",
            timeout=_HTTP_TIMEOUT,
        )
        assert ws_skills.status_code == 200, app_server.logs_tail()
        ws_names = {item["name"] for item in ws_skills.json()}
        assert pool_name in ws_names
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}/skills/{pool_name}",
        )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
        _delete_pool_skill_quietly(app_server, pool_name)


# ------------------------------------------------------------------ #
# import-builtin + update-builtin
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_import_builtin_and_update(app_server) -> None:
    """Test purpose:
    - Verify POST /pool/import-builtin imports a builtin skill into
      the pool, and POST /pool/{name}/update-builtin refreshes it.
      Uses ``file_reader-zh`` (smallest builtin).

    Test flow:
    1. POST /pool/import-builtin with ``skill_names=["file_reader-zh"]``.
    2. Assert 200 and ``imported`` list is non-empty.
    3. GET /pool — assert ``file_reader-zh`` appears.
    4. POST /pool/file_reader-zh/update-builtin.
    5. Assert 200.

    API endpoints:
    - POST /api/skills/pool/import-builtin
    - POST /api/skills/pool/{skill_name}/update-builtin
    - GET  /api/skills/pool
    """
    source = "file_reader-zh"
    pool_name = "file_reader"
    try:
        import_resp = app_server.api_request(
            "POST",
            f"{_POOL_BASE}/import-builtin",
            json={
                "skill_names": [source],
                "overwrite_conflicts": True,
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert import_resp.status_code == 200, app_server.logs_tail()
        payload = import_resp.json()
        total = len(payload.get("imported", [])) + len(
            payload.get("updated", []),
        )
        assert total >= 1

        assert pool_name in _list_pool_skill_names(app_server)

        update_resp = app_server.api_request(
            "POST",
            f"{_POOL_BASE}/{pool_name}/update-builtin",
            timeout=_HTTP_TIMEOUT,
        )
        assert update_resp.status_code == 200, app_server.logs_tail()
    finally:
        _delete_pool_skill_quietly(app_server, pool_name)


@pytest.mark.integration
@pytest.mark.p0
def test_pool_update_builtin_missing_400(app_server) -> None:
    """Test purpose:
    - Verify POST /pool/{name}/update-builtin for a non-existent
      skill returns 400.

    API endpoints:
    - POST /api/skills/pool/{skill_name}/update-builtin
    """
    resp = app_server.api_request(
        "POST",
        f"{_POOL_BASE}/integ-pool-nobuiltin-01/update-builtin",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()


# ------------------------------------------------------------------ #
# import from hub
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_pool_import_hub_invalid_400(app_server) -> None:
    """Test purpose:
    - Verify POST /pool/import with an invalid ``bundle_url`` returns
      400. The handler validates the URL before attempting to fetch.

    API endpoints:
    - POST /api/skills/pool/import
    """
    resp = app_server.api_request(
        "POST",
        f"{_POOL_BASE}/import",
        json={
            "bundle_url": "not-a-valid-url",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()


# ------------------------------------------------------------------ #
# hub install start → poll → complete
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_hub_install_start_poll_complete(app_server) -> None:
    """Test purpose:
    - Verify the async hub install pipeline: start → status poll →
      terminal state. Uses the ``file_reader-zh`` skill from the
      upstream repo (smallest builtin, ~1.6 KB).

    Test flow:
    1. Create agent.
    2. POST /skills/hub/install/start with the upstream
       ``file_reader-zh`` GitHub URL.
    3. Assert 200 and response contains ``task_id``.
    4. Poll GET /skills/hub/install/status/{task_id} until terminal.
    5. Assert status is ``completed`` or ``failed`` (network-dependent).
    6. Cleanup: delete agent + workspace skill.

    API endpoints:
    - POST /api/skills/hub/install/start
    - GET  /api/skills/hub/install/status/{task_id}
    """
    agent_id = "integ_hub_install_poll_01"
    skill_url = (
        "https://github.com/agentscope-ai/QwenPaw"
        "/tree/main/src/qwenpaw/agents/skills/file_reader-zh"
    )
    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Hub install poll agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        start_resp = app_server.api_request(
            "POST",
            f"/api/agents/{agent_id}/skills/hub/install/start",
            json={
                "bundle_url": skill_url,
                "enable": False,
            },
            timeout=30.0,
        )
        assert start_resp.status_code == 200, app_server.logs_tail()
        task_id = start_resp.json().get("task_id")
        assert task_id

        import time

        terminal = {"completed", "failed", "cancelled"}
        deadline = time.time() + 60
        last_status = None
        while time.time() < deadline:
            status_resp = app_server.api_request(
                "GET",
                f"/api/agents/{agent_id}/skills"
                f"/hub/install/status/{task_id}",
                timeout=_HTTP_TIMEOUT,
            )
            assert status_resp.status_code == 200, app_server.logs_tail()
            last_status = status_resp.json().get("status")
            if last_status in terminal:
                break
            time.sleep(1.0)

        assert (
            last_status in terminal
        ), f"task {task_id} stuck at {last_status}"
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}/skills/file_reader-zh",
        )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
