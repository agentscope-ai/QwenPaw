# -*- coding: utf-8 -*-
"""Smoke tests for global /api/skills (CRUD, batch, validation)."""
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
def test_skills_create_list_delete(app_server) -> None:
    """Test purpose:
    - Verify core workspace skill lifecycle: create, list, and delete.

    Test flow:
    1. Create a test agent.
    2. POST /api/skills with valid SKILL.md frontmatter.
    3. GET /api/skills and verify created skill appears.
    4. DELETE /api/skills/{skill_name} and verify deletion succeeds.
    5. GET /api/skills again and verify skill no longer appears.
    6. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/skills
    - GET /api/skills
    - DELETE /api/skills/{skill_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_skills_crud_01"
    headers = {"X-Agent-Id": agent_id}
    skill_name = "integ-skill-crud-01"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Skills CRUD agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_skill = app_server.api_request(
            "POST",
            "/api/skills",
            headers=headers,
            json={
                "name": skill_name,
                "content": _skill_md(skill_name, "integration CRUD skill"),
                "enable": True,
            },
        )
        assert create_skill.status_code == 200, app_server.logs_tail()
        create_payload = create_skill.json()
        assert create_payload.get("created") is True
        assert create_payload.get("name") == skill_name

        list_after_create = app_server.api_request(
            "GET",
            "/api/skills",
            headers=headers,
        )
        assert list_after_create.status_code == 200, app_server.logs_tail()
        names_after_create = {
            item["name"] for item in list_after_create.json()
        }
        assert skill_name in names_after_create

        delete_skill = app_server.api_request(
            "DELETE",
            f"/api/skills/{skill_name}",
            headers=headers,
        )
        assert delete_skill.status_code == 200, app_server.logs_tail()
        assert delete_skill.json().get("deleted") is True

        list_after_delete = app_server.api_request(
            "GET",
            "/api/skills",
            headers=headers,
        )
        assert list_after_delete.status_code == 200, app_server.logs_tail()
        names_after_delete = {
            item["name"] for item in list_after_delete.json()
        }
        assert skill_name not in names_after_delete
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p0
def test_skills_disable_enable(app_server) -> None:
    """Test purpose:
    - Verify single-skill disable/enable endpoints update enabled state.

    Test flow:
    1. Create a test agent and one enabled skill.
    2. POST /api/skills/{skill}/disable and assert success.
    3. GET /api/skills and assert skill ``enabled`` is False.
    4. POST /api/skills/{skill}/enable and assert success.
    5. GET /api/skills and assert skill ``enabled`` is True.
    6. Cleanup skill and agent.

    API endpoints:
    - POST /api/agents
    - POST /api/skills
    - POST /api/skills/{skill_name}/disable
    - POST /api/skills/{skill_name}/enable
    - GET /api/skills
    - DELETE /api/skills/{skill_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_skills_toggle_01"
    headers = {"X-Agent-Id": agent_id}
    skill_name = "integ-skill-toggle-01"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Skills toggle agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_skill = app_server.api_request(
            "POST",
            "/api/skills",
            headers=headers,
            json={
                "name": skill_name,
                "content": _skill_md(skill_name, "integration toggle skill"),
                "enable": True,
            },
        )
        assert create_skill.status_code == 200, app_server.logs_tail()

        disable_resp = app_server.api_request(
            "POST",
            f"/api/skills/{skill_name}/disable",
            headers=headers,
        )
        assert disable_resp.status_code == 200, app_server.logs_tail()
        assert disable_resp.json().get("disabled") is True

        list_after_disable = app_server.api_request(
            "GET",
            "/api/skills",
            headers=headers,
        )
        assert list_after_disable.status_code == 200, app_server.logs_tail()
        by_name = {item["name"]: item for item in list_after_disable.json()}
        assert by_name[skill_name]["enabled"] is False

        enable_resp = app_server.api_request(
            "POST",
            f"/api/skills/{skill_name}/enable",
            headers=headers,
        )
        assert enable_resp.status_code == 200, app_server.logs_tail()
        assert enable_resp.json().get("enabled") is True

        list_after_enable = app_server.api_request(
            "GET",
            "/api/skills",
            headers=headers,
        )
        assert list_after_enable.status_code == 200, app_server.logs_tail()
        by_name = {item["name"]: item for item in list_after_enable.json()}
        assert by_name[skill_name]["enabled"] is True
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/skills/{skill_name}",
            headers=headers,
        )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_skills_batch_enable_disable_delete(app_server) -> None:
    """Test purpose:
    - Verify batch skill operations return per-skill results and update states.

    Test flow:
    1. Create a test agent and two disabled skills.
    2. POST /api/skills/batch-enable and verify both succeed.
    3. POST /api/skills/batch-disable and verify both succeed.
    4. POST /api/skills/batch-delete and verify both succeed.
    5. GET /api/skills and verify both are removed.
    6. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/skills
    - POST /api/skills/batch-enable
    - POST /api/skills/batch-disable
    - POST /api/skills/batch-delete
    - GET /api/skills
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_skills_batch_01"
    headers = {"X-Agent-Id": agent_id}
    skill_names = ["integ-skill-batch-01", "integ-skill-batch-02"]

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Skills batch agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        for skill_name in skill_names:
            create_skill = app_server.api_request(
                "POST",
                "/api/skills",
                headers=headers,
                json={
                    "name": skill_name,
                    "content": _skill_md(
                        skill_name,
                        "integration batch skill",
                    ),
                    "enable": False,
                },
            )
            assert create_skill.status_code == 200, app_server.logs_tail()

        batch_enable = app_server.api_request(
            "POST",
            "/api/skills/batch-enable",
            headers=headers,
            json=skill_names,
        )
        assert batch_enable.status_code == 200, app_server.logs_tail()
        enable_results = batch_enable.json().get("results", {})
        for skill_name in skill_names:
            assert enable_results.get(skill_name, {}).get("success") is True

        batch_disable = app_server.api_request(
            "POST",
            "/api/skills/batch-disable",
            headers=headers,
            json=skill_names,
        )
        assert batch_disable.status_code == 200, app_server.logs_tail()
        disable_results = batch_disable.json().get("results", {})
        for skill_name in skill_names:
            assert disable_results.get(skill_name, {}).get("success") is True

        batch_delete = app_server.api_request(
            "POST",
            "/api/skills/batch-delete",
            headers=headers,
            json=skill_names,
        )
        assert batch_delete.status_code == 200, app_server.logs_tail()
        delete_results = batch_delete.json().get("results", {})
        for skill_name in skill_names:
            assert delete_results.get(skill_name, {}).get("success") is True

        list_after_delete = app_server.api_request(
            "GET",
            "/api/skills",
            headers=headers,
        )
        assert list_after_delete.status_code == 200, app_server.logs_tail()
        remaining_names = {item["name"] for item in list_after_delete.json()}
        for skill_name in skill_names:
            assert skill_name not in remaining_names
    finally:
        for skill_name in skill_names:
            app_server.api_request(
                "DELETE",
                f"/api/skills/{skill_name}",
                headers=headers,
            )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_skills_create_duplicate_name_rejected(app_server) -> None:
    """Test purpose:
    - Verify creating a workspace skill with duplicated name is rejected.

    Test flow:
    1. Create a test agent.
    2. POST /api/skills once with a fixed skill name and assert success.
    3. POST /api/skills again with the same name.
    4. Assert status 409 and detail includes conflict reason metadata.
    5. Cleanup skill and agent.

    API endpoints:
    - POST /api/agents
    - POST /api/skills
    - DELETE /api/skills/{skill_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_skills_dup_01"
    headers = {"X-Agent-Id": agent_id}
    skill_name = "integ-skill-dup-01"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Skills duplicate agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        first_create = app_server.api_request(
            "POST",
            "/api/skills",
            headers=headers,
            json={
                "name": skill_name,
                "content": _skill_md(
                    skill_name,
                    "integration duplicate skill",
                ),
                "enable": True,
            },
        )
        assert first_create.status_code == 200, app_server.logs_tail()

        second_create = app_server.api_request(
            "POST",
            "/api/skills",
            headers=headers,
            json={
                "name": skill_name,
                "content": _skill_md(
                    skill_name,
                    "integration duplicate skill",
                ),
                "enable": True,
            },
        )
        assert second_create.status_code == 409, app_server.logs_tail()
        detail = second_create.json().get("detail", {})
        assert detail.get("reason") == "conflict"
        assert "suggested_name" in detail
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/skills/{skill_name}",
            headers=headers,
        )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_skills_create_invalid_skill_md_rejected(app_server) -> None:
    """Test purpose:
    - Verify create skill rejects invalid SKILL.md frontmatter content.

    Test flow:
    1. Create a test agent.
    2. POST /api/skills with invalid frontmatter (missing description).
    3. Assert status 400 and detail mentions frontmatter requirement.
    4. Assert the invalid skill does not appear in GET /api/skills.
    5. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/skills
    - GET /api/skills
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_skills_invalid_md_01"
    headers = {"X-Agent-Id": agent_id}
    skill_name = "integ-skill-invalid-md-01"
    invalid_md = (
        "---\n"
        f"name: {skill_name}\n"
        "---\n\n"
        "# Invalid Skill\n"
        "missing description in frontmatter\n"
    )

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Skills invalid md agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_invalid = app_server.api_request(
            "POST",
            "/api/skills",
            headers=headers,
            json={
                "name": skill_name,
                "content": invalid_md,
                "enable": True,
            },
        )
        assert create_invalid.status_code == 400, app_server.logs_tail()
        detail = str(create_invalid.json().get("detail", ""))
        assert "frontmatter" in detail

        list_resp = app_server.api_request(
            "GET",
            "/api/skills",
            headers=headers,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        names = {item["name"] for item in list_resp.json()}
        assert skill_name not in names
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_skills_batch_enable_partial_success(app_server) -> None:
    """Test purpose:
    - Verify batch-enable returns per-skill results and allows partial success
      when some skill names do not exist.

    Test flow:
    1. Create a test agent and one disabled skill.
    2. POST /api/skills/batch-enable with one existing and one missing skill.
    3. Assert existing skill success=true and missing one success=false.
    4. GET /api/skills and verify existing skill becomes enabled.
    5. Cleanup skill and agent.

    API endpoints:
    - POST /api/agents
    - POST /api/skills
    - POST /api/skills/batch-enable
    - GET /api/skills
    - DELETE /api/skills/{skill_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_skills_batch_partial_01"
    headers = {"X-Agent-Id": agent_id}
    existing_skill = "integ-skill-batch-partial-existing"
    missing_skill = "integ-skill-batch-partial-missing"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Skills batch partial agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_existing = app_server.api_request(
            "POST",
            "/api/skills",
            headers=headers,
            json={
                "name": existing_skill,
                "content": _skill_md(
                    existing_skill,
                    "integration batch partial skill",
                ),
                "enable": False,
            },
        )
        assert create_existing.status_code == 200, app_server.logs_tail()

        batch_enable = app_server.api_request(
            "POST",
            "/api/skills/batch-enable",
            headers=headers,
            json=[existing_skill, missing_skill],
        )
        assert batch_enable.status_code == 200, app_server.logs_tail()
        results = batch_enable.json().get("results", {})
        assert results.get(existing_skill, {}).get("success") is True
        assert results.get(missing_skill, {}).get("success") is False
        assert results.get(missing_skill, {}).get("reason") == "not_found"

        list_resp = app_server.api_request(
            "GET",
            "/api/skills",
            headers=headers,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        by_name = {item["name"]: item for item in list_resp.json()}
        assert by_name[existing_skill]["enabled"] is True
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/skills/{existing_skill}",
            headers=headers,
        )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_skills_enable_missing_skill_returns_404(app_server) -> None:
    """Test purpose:
    - Verify enabling a non-existing workspace skill returns 404.

    Test flow:
    1. Create a test agent.
    2. POST /api/skills/{skill_name}/enable with a missing skill name.
    3. Assert status is 404 and detail indicates skill not found.
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/skills/{skill_name}/enable
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_skills_enable_missing_01"
    headers = {"X-Agent-Id": agent_id}
    missing_skill = "integ-skill-enable-missing"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Skills enable missing agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        enable_resp = app_server.api_request(
            "POST",
            f"/api/skills/{missing_skill}/enable",
            headers=headers,
        )
        assert enable_resp.status_code == 404, app_server.logs_tail()
        detail = str(enable_resp.json().get("detail", ""))
        assert detail in {"Skill not found", "not_found"}
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_skills_batch_delete_partial_success(app_server) -> None:
    """Test purpose:
    - Verify batch-delete returns per-skill results and supports partial
      success when some skill names do not exist.

    Test flow:
    1. Create a test agent and one disabled skill.
    2. POST /api/skills/batch-delete with one existing and one missing skill.
    3. Assert existing skill delete result is success=true.
    4. Assert missing skill delete result is success=false with reason.
    5. GET /api/skills and verify existing skill is removed.
    6. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/skills
    - POST /api/skills/batch-delete
    - GET /api/skills
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_skills_batch_delete_partial_01"
    headers = {"X-Agent-Id": agent_id}
    existing_skill = "integ-skill-batch-delete-existing"
    missing_skill = "integ-skill-batch-delete-missing"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Skills batch delete partial agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_existing = app_server.api_request(
            "POST",
            "/api/skills",
            headers=headers,
            json={
                "name": existing_skill,
                "content": _skill_md(
                    existing_skill,
                    "integration batch delete partial",
                ),
                "enable": False,
            },
        )
        assert create_existing.status_code == 200, app_server.logs_tail()

        batch_delete = app_server.api_request(
            "POST",
            "/api/skills/batch-delete",
            headers=headers,
            json=[existing_skill, missing_skill],
        )
        assert batch_delete.status_code == 200, app_server.logs_tail()
        results = batch_delete.json().get("results", {})
        assert results.get(existing_skill, {}).get("success") is True
        assert results.get(missing_skill, {}).get("success") is False
        assert results.get(missing_skill, {}).get("reason") == "delete_failed"

        list_resp = app_server.api_request(
            "GET",
            "/api/skills",
            headers=headers,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        names = {item["name"] for item in list_resp.json()}
        assert existing_skill not in names
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p2
def test_skills_batch_disable_partial_success(app_server) -> None:
    """Test purpose:
    - Verify batch-disable returns per-skill results and supports partial
      success when some skill names do not exist.

    Test flow:
    1. Create a test agent and one enabled skill.
    2. POST /api/skills/batch-disable with one existing and one missing skill.
    3. Assert existing skill disable result is success=true.
    4. Assert missing skill disable result is success=false.
    5. GET /api/skills and verify existing skill becomes disabled.
    6. Cleanup skill and agent.

    API endpoints:
    - POST /api/agents
    - POST /api/skills
    - POST /api/skills/batch-disable
    - GET /api/skills
    - DELETE /api/skills/{skill_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_skills_batch_disable_partial_01"
    headers = {"X-Agent-Id": agent_id}
    existing_skill = "integ-skill-batch-disable-existing"
    missing_skill = "integ-skill-batch-disable-missing"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Skills batch disable partial agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        create_existing = app_server.api_request(
            "POST",
            "/api/skills",
            headers=headers,
            json={
                "name": existing_skill,
                "content": _skill_md(
                    existing_skill,
                    "integration batch disable partial",
                ),
                "enable": True,
            },
        )
        assert create_existing.status_code == 200, app_server.logs_tail()

        batch_disable = app_server.api_request(
            "POST",
            "/api/skills/batch-disable",
            headers=headers,
            json=[existing_skill, missing_skill],
        )
        assert batch_disable.status_code == 200, app_server.logs_tail()
        results = batch_disable.json().get("results", {})
        assert results.get(existing_skill, {}).get("success") is True
        assert results.get(missing_skill, {}).get("success") is False

        list_resp = app_server.api_request(
            "GET",
            "/api/skills",
            headers=headers,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        by_name = {item["name"]: item for item in list_resp.json()}
        assert by_name[existing_skill]["enabled"] is False
    finally:
        app_server.api_request(
            "DELETE",
            f"/api/skills/{existing_skill}",
            headers=headers,
        )
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
