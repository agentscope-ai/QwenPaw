# -*- coding: utf-8 -*-
"""Integration tests for agent-scoped /api/agents/{id}/skills endpoints.

Covers active-skill CRUD (create, save, upload, channels, config, tags)
and their error branches, all through ``/api/agents/{agentId}/skills/*``.
"""
from __future__ import annotations

import io
import zipfile

import pytest


def _skill_md(name: str, description: str) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        "---\n\n"
        "# Integration Skill\n"
        "This skill is created by integration tests.\n"
    )


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_create_list_batch_delete(app_server) -> None:
    """Test purpose:
    - Verify workspace skills can be created, listed, and batch-deleted using
      only ``/api/agents/{agentId}/skills`` paths (no ``X-Agent-Id`` header).

    Test flow:
    1. Create a dedicated test agent.
    2. POST two skills under the scoped skills prefix.
    3. GET scoped skills list and assert both names appear.
    4. POST scoped ``batch-delete`` with both names; per-skill success.
    5. GET list again and assert both are gone.
    6. Defensive per-skill DELETE and DELETE agent in finally.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/skills
    - GET /api/agents/{agentId}/skills
    - POST /api/agents/{agentId}/skills/batch-delete
    - DELETE /api/agents/{agentId}/skills/{skill_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_skills_batch_01"
    base = f"/api/agents/{agent_id}/skills"
    skill_names = ["integ-scoped-skill-a", "integ-scoped-skill-b"]

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped skills agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        for skill_name in skill_names:
            create_skill = app_server.api_request(
                "POST",
                base,
                json={
                    "name": skill_name,
                    "content": _skill_md(skill_name, "scoped batch skill"),
                    "enable": False,
                },
            )
            assert create_skill.status_code == 200, app_server.logs_tail()

        list_before = app_server.api_request("GET", base)
        assert list_before.status_code == 200, app_server.logs_tail()
        names_before = {item["name"] for item in list_before.json()}
        for skill_name in skill_names:
            assert skill_name in names_before

        batch_delete = app_server.api_request(
            "POST",
            f"{base}/batch-delete",
            json=skill_names,
        )
        assert batch_delete.status_code == 200, app_server.logs_tail()
        results = batch_delete.json().get("results", {})
        for skill_name in skill_names:
            assert results.get(skill_name, {}).get("success") is True

        list_after = app_server.api_request("GET", base)
        assert list_after.status_code == 200, app_server.logs_tail()
        names_after = {item["name"] for item in list_after.json()}
        for skill_name in skill_names:
            assert skill_name not in names_after
    finally:
        for skill_name in skill_names:
            app_server.api_request("DELETE", f"{base}/{skill_name}")
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_skills_batch_enable_disable(app_server) -> None:
    """Test purpose:
    - Verify scoped batch-enable and batch-disable update ``enabled`` flags.

    Test flow:
    1. Create a dedicated test agent and two disabled workspace skills.
    2. POST scoped batch-enable and assert per-skill success plus list state.
    3. POST scoped batch-disable and assert per-skill success plus list state.
    4. POST scoped batch-delete for cleanup.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/skills
    - POST /api/agents/{agentId}/skills/batch-enable
    - POST /api/agents/{agentId}/skills/batch-disable
    - POST /api/agents/{agentId}/skills/batch-delete
    - GET /api/agents/{agentId}/skills
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_skills_batch_enable_01"
    base = f"/api/agents/{agent_id}/skills"
    skill_names = ["integ-scoped-batch-en-a", "integ-scoped-batch-en-b"]

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped batch enable agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        for skill_name in skill_names:
            create_skill = app_server.api_request(
                "POST",
                base,
                json={
                    "name": skill_name,
                    "content": _skill_md(skill_name, "batch enable skill"),
                    "enable": False,
                },
            )
            assert create_skill.status_code == 200, app_server.logs_tail()

        batch_en = app_server.api_request(
            "POST",
            f"{base}/batch-enable",
            json=skill_names,
        )
        assert batch_en.status_code == 200, app_server.logs_tail()
        en_results = batch_en.json().get("results", {})
        for skill_name in skill_names:
            assert en_results.get(skill_name, {}).get("success") is True

        list_after_en = app_server.api_request("GET", base)
        assert list_after_en.status_code == 200, app_server.logs_tail()
        by_name = {item["name"]: item for item in list_after_en.json()}
        for skill_name in skill_names:
            assert by_name[skill_name]["enabled"] is True

        batch_dis = app_server.api_request(
            "POST",
            f"{base}/batch-disable",
            json=skill_names,
        )
        assert batch_dis.status_code == 200, app_server.logs_tail()
        dis_results = batch_dis.json().get("results", {})
        for skill_name in skill_names:
            assert dis_results.get(skill_name, {}).get("success") is True

        list_after_dis = app_server.api_request("GET", base)
        assert list_after_dis.status_code == 200, app_server.logs_tail()
        by_name2 = {item["name"]: item for item in list_after_dis.json()}
        for skill_name in skill_names:
            assert by_name2[skill_name]["enabled"] is False

        batch_del = app_server.api_request(
            "POST",
            f"{base}/batch-delete",
            json=skill_names,
        )
        assert batch_del.status_code == 200, app_server.logs_tail()
    finally:
        for skill_name in skill_names:
            app_server.api_request("DELETE", f"{base}/{skill_name}")
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_skills_pool_refresh(app_server) -> None:
    """Test purpose:
    - Verify scoped POST skills/pool/refresh returns a list payload (local
      reconcile only, no hub credentials).

    Test flow:
    1. Create a dedicated test agent.
    2. POST scoped pool refresh.
    3. Assert 200 and JSON array response.
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/skills/pool/refresh
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_skills_pool_refresh_01"
    refresh_path = f"/api/agents/{agent_id}/skills/pool/refresh"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Pool refresh agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        refresh = app_server.api_request("POST", refresh_path)
        assert refresh.status_code == 200, app_server.logs_tail()
        payload = refresh.json()
        assert isinstance(payload, list)
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_skills_refresh(app_server) -> None:
    """Test purpose:
    - Verify scoped POST /skills/refresh returns a workspace skill list.

    Test flow:
    1. Create a dedicated test agent.
    2. POST /api/agents/{agentId}/skills/refresh.
    3. Assert 200 and JSON list (may be empty).
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/skills/refresh
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_skills_refresh_01"
    refresh_path = f"/api/agents/{agent_id}/skills/refresh"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Skills refresh agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        refresh = app_server.api_request("POST", refresh_path)
        assert refresh.status_code == 200, app_server.logs_tail()
        payload = refresh.json()
        assert isinstance(payload, list)
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_disable_enable_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify per-skill POST disable/enable under scoped skills prefix.

    Test flow:
    1. Create agent and one enabled skill via scoped POST.
    2. POST .../skills/{name}/disable and GET list -> enabled false.
    3. POST .../skills/{name}/enable and GET list -> enabled true.
    4. DELETE skill and agent.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/skills
    - POST /api/agents/{agentId}/skills/{skill_name}/disable
    - POST /api/agents/{agentId}/skills/{skill_name}/enable
    - GET /api/agents/{agentId}/skills
    - DELETE /api/agents/{agentId}/skills/{skill_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_skills_toggle_01"
    base = f"/api/agents/{agent_id}/skills"
    skill_name = "integ-scoped-skill-toggle-01"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped skill toggle agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_skill = app_server.api_request(
            "POST",
            base,
            json={
                "name": skill_name,
                "content": _skill_md(skill_name, "integration scoped toggle"),
                "enable": True,
            },
        )
        assert create_skill.status_code == 200, app_server.logs_tail()

        disable = app_server.api_request(
            "POST",
            f"{base}/{skill_name}/disable",
        )
        assert disable.status_code == 200, app_server.logs_tail()
        assert disable.json().get("disabled") is True

        list_disabled = app_server.api_request("GET", base)
        assert list_disabled.status_code == 200, app_server.logs_tail()
        by_name = {item["name"]: item for item in list_disabled.json()}
        assert by_name[skill_name]["enabled"] is False

        enable = app_server.api_request(
            "POST",
            f"{base}/{skill_name}/enable",
        )
        assert enable.status_code == 200, app_server.logs_tail()
        assert enable.json().get("enabled") is True

        list_enabled = app_server.api_request("GET", base)
        assert list_enabled.status_code == 200, app_server.logs_tail()
        by_name_2 = {item["name"]: item for item in list_enabled.json()}
        assert by_name_2[skill_name]["enabled"] is True
    finally:
        app_server.api_request("DELETE", f"{base}/{skill_name}")
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


# ------------------------------------------------------------------ #
# helpers for the new cases below
# ------------------------------------------------------------------ #


def _build_skill_zip(skills: dict[str, str]) -> bytes:
    """Build a zip containing one SKILL.md per skill name."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in skills.items():
            zf.writestr(f"{name}/SKILL.md", content)
    return buf.getvalue()


def _create_agent_and_skill(
    app_server,
    agent_id: str,
    skill_name: str,
    *,
    enable: bool = False,
    description: str = "active skill test",
):
    """Create agent + one workspace skill; asserts internally."""
    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": f"Agent {agent_id}",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    create_skill = app_server.api_request(
        "POST",
        f"/api/agents/{agent_id}/skills",
        json={
            "name": skill_name,
            "content": _skill_md(skill_name, description),
            "enable": enable,
        },
    )
    assert create_skill.status_code == 200, app_server.logs_tail()


def _cleanup_agent_skill(app_server, agent_id: str, *skill_names: str):
    for sn in skill_names:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}/skills/{sn}",
        )
    app_server.api_request("DELETE", f"/api/agents/{agent_id}")


# ------------------------------------------------------------------ #
# save — full lifecycle
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_save_config_channels_tags_lifecycle(
    app_server,
) -> None:
    """Test purpose:
    - Verify PUT /save updates content, then PUT channels/config/tags
      each persist and are readable back. This is the comprehensive
      happy-path across all four mutation endpoints for active skills.

    Test flow:
    1. Create agent + skill.
    2. PUT /skills/save with new content.
    3. PUT /{name}/channels with ``["dingtalk"]``.
    4. PUT /{name}/config with ``{"llm_model": "qwen-max"}``.
    5. PUT /{name}/tags with ``["automation"]``.
    6. GET /{name}/config — assert ``llm_model``.
    7. Cleanup.

    API endpoints:
    - PUT  /api/agents/{agentId}/skills/save
    - PUT  /api/agents/{agentId}/skills/{skill_name}/channels
    - PUT  /api/agents/{agentId}/skills/{skill_name}/config
    - PUT  /api/agents/{agentId}/skills/{skill_name}/tags
    - GET  /api/agents/{agentId}/skills/{skill_name}/config
    """
    agent_id = "integ_active_save_full_01"
    skill_name = "integ-active-full-01"
    base = f"/api/agents/{agent_id}/skills"
    _create_agent_and_skill(app_server, agent_id, skill_name)

    try:
        save_resp = app_server.api_request(
            "PUT",
            f"{base}/save",
            json={
                "name": skill_name,
                "content": _skill_md(skill_name, "updated content"),
            },
        )
        assert save_resp.status_code == 200, app_server.logs_tail()
        assert save_resp.json().get("success") is True

        ch_resp = app_server.api_request(
            "PUT",
            f"{base}/{skill_name}/channels",
            json=["dingtalk"],
        )
        assert ch_resp.status_code == 200, app_server.logs_tail()
        assert ch_resp.json().get("channels") == ["dingtalk"]

        cfg_resp = app_server.api_request(
            "PUT",
            f"{base}/{skill_name}/config",
            json={"config": {"llm_model": "qwen-max"}},
        )
        assert cfg_resp.status_code == 200, app_server.logs_tail()
        assert cfg_resp.json().get("updated") is True

        tags_resp = app_server.api_request(
            "PUT",
            f"{base}/{skill_name}/tags",
            json=["automation"],
        )
        assert tags_resp.status_code == 200, app_server.logs_tail()
        assert tags_resp.json()["tags"] == ["automation"]

        get_cfg = app_server.api_request(
            "GET",
            f"{base}/{skill_name}/config",
        )
        assert get_cfg.status_code == 200, app_server.logs_tail()
        assert get_cfg.json()["config"]["llm_model"] == "qwen-max"
    finally:
        _cleanup_agent_skill(app_server, agent_id, skill_name)


# ------------------------------------------------------------------ #
# save — error branches
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_save_missing_404(app_server) -> None:
    """Test purpose:
    - Verify PUT /skills/save returns 404 when the skill does not
      exist in the workspace.

    API endpoints:
    - PUT /api/agents/{agentId}/skills/save
    """
    agent_id = "integ_active_save_miss_01"
    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Save miss agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        resp = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}/skills/save",
            json={
                "name": "integ-nosuch-skill-01",
                "content": _skill_md("nosuch", "missing"),
            },
        )
        assert resp.status_code == 404, app_server.logs_tail()
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_save_conflict_409(app_server) -> None:
    """Test purpose:
    - Verify PUT /skills/save returns 409 when attempting a rename
      that collides with an existing skill.

    Test flow:
    1. Create agent + skill ``a`` + skill ``b``.
    2. PUT /save with ``source_name="a"`` and ``name="b"`` (rename
       a → b), ``overwrite=False``.
    3. Assert 409 and detail.reason == ``conflict``.

    API endpoints:
    - PUT /api/agents/{agentId}/skills/save
    """
    agent_id = "integ_active_save_conflict_01"
    skill_a = "integ-active-conf-a"
    skill_b = "integ-active-conf-b"

    _create_agent_and_skill(
        app_server,
        agent_id,
        skill_a,
    )
    create_b = app_server.api_request(
        "POST",
        f"/api/agents/{agent_id}/skills",
        json={
            "name": skill_b,
            "content": _skill_md(skill_b, "target"),
            "enable": False,
        },
    )
    assert create_b.status_code == 200, app_server.logs_tail()

    try:
        resp = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}/skills/save",
            json={
                "name": skill_b,
                "source_name": skill_a,
                "content": _skill_md(skill_b, "renamed"),
                "overwrite": False,
            },
        )
        assert resp.status_code == 409, app_server.logs_tail()
        assert resp.json().get("detail", {}).get("reason") == "conflict"
    finally:
        _cleanup_agent_skill(
            app_server,
            agent_id,
            skill_a,
            skill_b,
        )


# ------------------------------------------------------------------ #
# upload zip
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_upload_zip(app_server) -> None:
    """Test purpose:
    - Verify POST /skills/upload with a valid skill zip imports the
      skill into the agent workspace. Happy-path coverage.

    Test flow:
    1. Create agent.
    2. Build zip with skill ``integ-active-zip-01``.
    3. POST /skills/upload.
    4. Assert 200 and count >= 1.
    5. GET /skills — assert the skill appears.

    API endpoints:
    - POST /api/agents/{agentId}/skills/upload
    - GET  /api/agents/{agentId}/skills
    """
    agent_id = "integ_active_upload_zip_01"
    skill_name = "integ-active-zip-01"
    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Upload zip agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        zip_bytes = _build_skill_zip(
            {
                skill_name: _skill_md(skill_name, "zip upload test"),
            },
        )
        upload_resp = app_server.api_request(
            "POST",
            f"/api/agents/{agent_id}/skills/upload",
            files={
                "file": (
                    "skills.zip",
                    zip_bytes,
                    "application/zip",
                ),
            },
            data={"enable": "false"},
        )
        assert upload_resp.status_code == 200, app_server.logs_tail()
        assert upload_resp.json().get("count", 0) >= 1

        list_resp = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/skills",
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        names = {item["name"] for item in list_resp.json()}
        assert skill_name in names
    finally:
        _cleanup_agent_skill(app_server, agent_id, skill_name)


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_upload_zip_bad_archive(
    app_server,
) -> None:
    """Test purpose:
    - Verify POST /skills/upload with non-zip content-type returns
      400.

    API endpoints:
    - POST /api/agents/{agentId}/skills/upload
    """
    agent_id = "integ_active_upload_bad_01"
    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Upload bad agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        resp = app_server.api_request(
            "POST",
            f"/api/agents/{agent_id}/skills/upload",
            files={
                "file": (
                    "bad.txt",
                    b"not a zip",
                    "text/plain",
                ),
            },
        )
        assert resp.status_code == 400, app_server.logs_tail()
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
        )


# ------------------------------------------------------------------ #
# channels / config / tags — error branches
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_channels_missing_404(
    app_server,
) -> None:
    """Test purpose:
    - Verify PUT /{name}/channels returns 404 for a non-existent
      skill.

    API endpoints:
    - PUT /api/agents/{agentId}/skills/{skill_name}/channels
    """
    agent_id = "integ_active_ch_miss_01"
    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Channels miss agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        resp = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}/skills/nosuch-skill/channels",
            json=["dingtalk"],
        )
        assert resp.status_code == 404, app_server.logs_tail()
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
        )


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_config_missing_404(app_server) -> None:
    """Test purpose:
    - Verify PUT /{name}/config returns 404 for a non-existent skill.

    API endpoints:
    - PUT /api/agents/{agentId}/skills/{skill_name}/config
    """
    agent_id = "integ_active_cfg_miss_01"
    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Config miss agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        resp = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}/skills/nosuch-skill/config",
            json={"config": {"k": "v"}},
        )
        assert resp.status_code == 404, app_server.logs_tail()
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
        )


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_config_delete_clears(
    app_server,
) -> None:
    """Test purpose:
    - Verify DELETE /{name}/config clears config and GET returns
      empty. Happy-path for config deletion.

    Test flow:
    1. Create agent + skill + PUT config.
    2. DELETE config — assert ``cleared=True``.
    3. GET config — assert empty.

    API endpoints:
    - DELETE /api/agents/{agentId}/skills/{skill_name}/config
    - GET    /api/agents/{agentId}/skills/{skill_name}/config
    """
    agent_id = "integ_active_cfg_del_01"
    skill_name = "integ-active-cfg-del-01"
    base = f"/api/agents/{agent_id}/skills"
    _create_agent_and_skill(app_server, agent_id, skill_name)

    try:
        app_server.api_request(
            "PUT",
            f"{base}/{skill_name}/config",
            json={"config": {"temperature": 0.7}},
        )

        del_resp = app_server.api_request(
            "DELETE",
            f"{base}/{skill_name}/config",
        )
        assert del_resp.status_code == 200, app_server.logs_tail()
        assert del_resp.json().get("cleared") is True

        get_resp = app_server.api_request(
            "GET",
            f"{base}/{skill_name}/config",
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        assert get_resp.json()["config"] == {}
    finally:
        _cleanup_agent_skill(app_server, agent_id, skill_name)


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_config_delete_missing_404(
    app_server,
) -> None:
    """Test purpose:
    - Verify DELETE /{name}/config returns 404 for a non-existent
      skill.

    API endpoints:
    - DELETE /api/agents/{agentId}/skills/{skill_name}/config
    """
    agent_id = "integ_active_cfg_del_miss_01"
    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Config del miss agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        resp = app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}/skills/nosuch-skill/config",
        )
        assert resp.status_code == 404, app_server.logs_tail()
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
        )


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_tags_missing_404(app_server) -> None:
    """Test purpose:
    - Verify PUT /{name}/tags returns 404 for a non-existent skill.

    API endpoints:
    - PUT /api/agents/{agentId}/skills/{skill_name}/tags
    """
    agent_id = "integ_active_tags_miss_01"
    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Tags miss agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        resp = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}/skills/nosuch-skill/tags",
            json=["test-tag"],
        )
        assert resp.status_code == 404, app_server.logs_tail()
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
        )


# ------------------------------------------------------------------ #
# workspace → pool roundtrip
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_workspace_to_pool_roundtrip(
    app_server,
) -> None:
    """Test purpose:
    - Verify a skill can be created in a workspace, uploaded to the
      pool, downloaded back into a second workspace, forming a
      complete workspace → pool → workspace roundtrip.

    Test flow:
    1. Create agent_a + skill.
    2. POST /pool/upload from agent_a's workspace.
    3. Create agent_b.
    4. POST /pool/download targeting agent_b.
    5. GET agent_b's skills — assert the skill appears.

    API endpoints:
    - POST /api/skills/pool/upload
    - POST /api/skills/pool/download
    - GET  /api/agents/{agentId}/skills
    """
    agent_a = "integ_ws2pool_a_01"
    agent_b = "integ_ws2pool_b_01"
    skill_name = "integ-ws2pool-roundtrip-01"

    _create_agent_and_skill(
        app_server,
        agent_a,
        skill_name,
        description="roundtrip source",
    )

    try:
        upload_resp = app_server.api_request(
            "POST",
            "/api/skills/pool/upload",
            json={
                "workspace_id": agent_a,
                "skill_name": skill_name,
                "overwrite": False,
            },
        )
        assert upload_resp.status_code == 200, app_server.logs_tail()
        assert upload_resp.json().get("success") is True

        create_b = app_server.api_request(
            "POST",
            "/api/agents",
            json={
                "id": agent_b,
                "name": "Roundtrip target",
                "description": "",
            },
        )
        assert create_b.status_code == 201, app_server.logs_tail()

        dl_resp = app_server.api_request(
            "POST",
            "/api/skills/pool/download",
            json={
                "skill_name": skill_name,
                "targets": [{"workspace_id": agent_b}],
                "overwrite": False,
            },
        )
        assert dl_resp.status_code == 200, app_server.logs_tail()
        assert len(dl_resp.json().get("downloaded", [])) == 1

        ws_skills = app_server.api_request(
            "GET",
            f"/api/agents/{agent_b}/skills",
        )
        assert ws_skills.status_code == 200, app_server.logs_tail()
        ws_names = {item["name"] for item in ws_skills.json()}
        assert skill_name in ws_names
    finally:
        try:
            app_server.api_request(
                "DELETE",
                f"/api/skills/pool/{skill_name}",
            )
        except Exception:
            pass
        _cleanup_agent_skill(app_server, agent_a, skill_name)
        _cleanup_agent_skill(app_server, agent_b, skill_name)


# ------------------------------------------------------------------ #
# save rename preserves content
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_agent_scoped_skills_save_rename_preserves(
    app_server,
) -> None:
    """Test purpose:
    - Verify PUT /skills/save with ``source_name`` != ``name``
      performs a rename and the new name appears in the listing
      while the old name is gone. Happy-path for rename flow.

    Test flow:
    1. Create agent + skill ``old-name``.
    2. PUT /save with ``source_name="old-name"``, ``name="new-name"``.
    3. GET skills — assert ``new-name`` present, ``old-name`` absent.

    API endpoints:
    - PUT /api/agents/{agentId}/skills/save
    - GET /api/agents/{agentId}/skills
    """
    agent_id = "integ_active_rename_01"
    old_name = "integ-active-rename-old"
    new_name = "integ-active-rename-new"
    base = f"/api/agents/{agent_id}/skills"

    _create_agent_and_skill(
        app_server,
        agent_id,
        old_name,
        description="rename source",
    )

    try:
        save_resp = app_server.api_request(
            "PUT",
            f"{base}/save",
            json={
                "name": new_name,
                "source_name": old_name,
                "content": _skill_md(new_name, "renamed skill"),
                "overwrite": False,
            },
        )
        assert save_resp.status_code == 200, app_server.logs_tail()
        assert save_resp.json().get("success") is True

        list_resp = app_server.api_request("GET", base)
        assert list_resp.status_code == 200, app_server.logs_tail()
        names = {item["name"] for item in list_resp.json()}
        assert new_name in names
        assert old_name not in names
    finally:
        _cleanup_agent_skill(
            app_server,
            agent_id,
            old_name,
            new_name,
        )
