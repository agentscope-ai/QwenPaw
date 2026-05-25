# -*- coding: utf-8 -*-
"""HTTP smoke tests for agent-scoped /api/agents/{id}/skills endpoints."""
from __future__ import annotations

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
