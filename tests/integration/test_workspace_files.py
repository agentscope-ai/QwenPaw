# -*- coding: utf-8 -*-
"""HTTP smoke tests for workspace file APIs (working/memory)."""
from __future__ import annotations


import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_api_workspace_working_file_list_put_get(app_server) -> None:
    """Test purpose:
    - Verify workspace working-file APIs are usable: builtin seed files exist,
      new file writes succeed, reads match, and list results include new files.

    Test flow:
    1. POST /api/agents to create a test agent.
    2. GET /api/workspace/files with X-Agent-Id; check seed files.
    3. PUT /api/workspace/files/{md_name} to write a test markdown file.
    4. GET /api/workspace/files/{md_name} and verify content roundtrip.
    5. GET /api/workspace/files again and confirm the new file appears.
    6. DELETE /api/agents/{agentId} for cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/workspace/files
    - PUT /api/workspace/files/{md_name}
    - GET /api/workspace/files/{md_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_ws_01"
    headers = {"X-Agent-Id": agent_id}
    md_stem = "integ_smoke_note"
    expected_seed_files = {
        "SOUL.md",
        "PROFILE.md",
        "MEMORY.md",
        "HEARTBEAT.md",
        "BOOTSTRAP.md",
        "AGENTS.md",
    }

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Workspace smoke agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        list_before = app_server.api_request(
            "GET",
            "/api/workspace/files",
            headers=headers,
        )
        assert list_before.status_code == 200, app_server.logs_tail()
        list_before_payload = list_before.json()
        assert isinstance(list_before_payload, list)
        seed_names = {f["filename"] for f in list_before_payload}
        missing_seed_files = sorted(expected_seed_files - seed_names)
        assert not missing_seed_files, (
            f"workspace seed files missing: {missing_seed_files}; "
            f"have={sorted(seed_names)}"
        )

        content = "# integration\nline2\n"
        put_resp = app_server.api_request(
            "PUT",
            f"/api/workspace/files/{md_stem}",
            headers=headers,
            json={"content": content},
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json() == {"written": True}

        get_resp = app_server.api_request(
            "GET",
            f"/api/workspace/files/{md_stem}",
            headers=headers,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        assert get_resp.json()["content"] == content.strip()

        list_after = app_server.api_request(
            "GET",
            "/api/workspace/files",
            headers=headers,
        )
        assert list_after.status_code == 200, app_server.logs_tail()
        names = {f["filename"] for f in list_after.json()}
        assert f"{md_stem}.md" in names
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_api_workspace_memory_file_list_put_get(app_server) -> None:
    """Test purpose:
    - Verify workspace memory-file APIs support write/read/list roundtrip under
      an explicit agent context.

    Test flow:
    1. Create a test agent.
    2. GET /api/workspace/memory and assert list response shape.
    3. PUT /api/workspace/memory/{md_name} with test content.
    4. GET /api/workspace/memory/{md_name} and verify content matches.
    5. GET /api/workspace/memory again and assert new file appears.
    6. Delete test agent for cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/workspace/memory
    - PUT /api/workspace/memory/{md_name}
    - GET /api/workspace/memory/{md_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_mem_01"
    headers = {"X-Agent-Id": agent_id}
    md_stem = "integ_memory_note"
    content = "# memory integration\nfacts: 42\n"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={"id": agent_id, "name": "Memory smoke agent", "description": ""},
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        list_before = app_server.api_request(
            "GET",
            "/api/workspace/memory",
            headers=headers,
        )
        assert list_before.status_code == 200, app_server.logs_tail()
        assert isinstance(list_before.json(), list)

        put_resp = app_server.api_request(
            "PUT",
            f"/api/workspace/memory/{md_stem}",
            headers=headers,
            json={"content": content},
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json() == {"written": True}

        get_resp = app_server.api_request(
            "GET",
            f"/api/workspace/memory/{md_stem}",
            headers=headers,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        assert get_resp.json()["content"] == content.strip()

        list_after = app_server.api_request(
            "GET",
            "/api/workspace/memory",
            headers=headers,
        )
        assert list_after.status_code == 200, app_server.logs_tail()
        names = {f["filename"] for f in list_after.json()}
        assert f"{md_stem}.md" in names
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_api_workspace_header_and_scoped_consistency(app_server) -> None:
    """Test purpose:
    - Verify workspace file APIs are consistent between header-based agent
      context and explicit agent-scoped routes.

    Test flow:
    1. Create a test agent.
    2. Write a working file via header route (X-Agent-Id).
    3. Read the same file via scoped route and verify content matches.
    4. Overwrite via scoped route and read back via header route.
    5. Cleanup by deleting the test agent.

    API endpoints:
    - POST /api/agents
    - PUT /api/workspace/files/{md_name}
    - GET /api/workspace/files/{md_name}
    - PUT /api/agents/{agentId}/workspace/files/{md_name}
    - GET /api/agents/{agentId}/workspace/files/{md_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_ws_scope_01"
    headers = {"X-Agent-Id": agent_id}
    md_stem = "scope_consistency_note"
    v1 = "# scope consistency v1\n"
    v2 = "# scope consistency v2\n"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Workspace scoped agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        put_header = app_server.api_request(
            "PUT",
            f"/api/workspace/files/{md_stem}",
            headers=headers,
            json={"content": v1},
        )
        assert put_header.status_code == 200, app_server.logs_tail()
        assert put_header.json() == {"written": True}

        get_scoped = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/workspace/files/{md_stem}",
        )
        assert get_scoped.status_code == 200, app_server.logs_tail()
        assert get_scoped.json()["content"] == v1.strip()

        put_scoped = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}/workspace/files/{md_stem}",
            json={"content": v2},
        )
        assert put_scoped.status_code == 200, app_server.logs_tail()
        assert put_scoped.json() == {"written": True}

        get_header = app_server.api_request(
            "GET",
            f"/api/workspace/files/{md_stem}",
            headers=headers,
        )
        assert get_header.status_code == 200, app_server.logs_tail()
        assert get_header.json()["content"] == v2.strip()
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
