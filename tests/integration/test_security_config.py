# -*- coding: utf-8 -*-
"""HTTP smoke tests for security guards (file/tool guard + skill scanner)."""
from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p0
def test_global_file_guard_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify file-guard enabled flag supports update and readback.

    Test flow:
    1. GET current file-guard config.
    2. PUT toggled ``enabled`` value.
    3. GET file-guard and assert new value is visible.
    4. Restore original value.

    API endpoints:
    - GET /api/config/security/file-guard
    - PUT /api/config/security/file-guard
    """
    get_before = app_server.api_request(
        "GET",
        "/api/config/security/file-guard",
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    assert isinstance(before, dict)
    assert "enabled" in before

    updated_enabled = not bool(before.get("enabled", True))

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/security/file-guard",
            json={"enabled": updated_enabled},
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert bool(put_resp.json().get("enabled")) == updated_enabled

        get_after = app_server.api_request(
            "GET",
            "/api/config/security/file-guard",
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert bool(after.get("enabled")) == updated_enabled
        for k, v in before.items():
            if k != "enabled":
                assert after.get(k) == v, f"side-effect on {k}"
    finally:
        restore = app_server.api_request(
            "PUT",
            "/api/config/security/file-guard",
            json={"enabled": before.get("enabled", True)},
        )
        assert restore.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p0
def test_global_tool_guard_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify tool-guard enabled flag supports update and readback.

    Test flow:
    1. GET current tool-guard config.
    2. PUT same payload with toggled ``enabled``.
    3. GET tool-guard and verify ``enabled`` changed.
    4. Restore original payload.

    API endpoints:
    - GET /api/config/security/tool-guard
    - PUT /api/config/security/tool-guard
    """
    get_before = app_server.api_request(
        "GET",
        "/api/config/security/tool-guard",
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    assert isinstance(before, dict)
    assert "enabled" in before

    updated = dict(before)
    updated["enabled"] = not bool(before.get("enabled", True))

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/security/tool-guard",
            json=updated,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert bool(put_resp.json().get("enabled")) == updated["enabled"]

        get_after = app_server.api_request(
            "GET",
            "/api/config/security/tool-guard",
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert bool(after.get("enabled")) == updated["enabled"]
        for k, v in before.items():
            if k != "enabled":
                assert after.get(k) == v, f"side-effect on {k}"
    finally:
        restore = app_server.api_request(
            "PUT",
            "/api/config/security/tool-guard",
            json=before,
        )
        assert restore.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p0
def test_global_skill_scanner_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify skill-scanner config accepts updates and readback remains
      consistent.

    Test flow:
    1. GET /api/config/security/skill-scanner as baseline.
    2. PUT same payload with toggled ``mode``.
    3. GET /api/config/security/skill-scanner and verify changed value.
    4. Restore baseline payload.

    API endpoints:
    - GET /api/config/security/skill-scanner
    - PUT /api/config/security/skill-scanner
    """
    get_before = app_server.api_request(
        "GET",
        "/api/config/security/skill-scanner",
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    assert isinstance(before, dict)
    assert "mode" in before

    updated = dict(before)
    updated["mode"] = "off" if before.get("mode") != "off" else "warn"

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/security/skill-scanner",
            json=updated,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("mode") == updated["mode"]

        get_after = app_server.api_request(
            "GET",
            "/api/config/security/skill-scanner",
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert after.get("mode") == updated["mode"]
        for k, v in before.items():
            if k != "mode":
                assert after.get(k) == v, f"side-effect on {k}"
    finally:
        restore = app_server.api_request(
            "PUT",
            "/api/config/security/skill-scanner",
            json=before,
        )
        assert restore.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_skill_scanner_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped skill-scanner config supports update and readback
      without using X-Agent-Id header.

    Test flow:
    1. Create a dedicated test agent.
    2. GET /api/agents/{agentId}/config/security/skill-scanner as baseline.
    3. PUT the same endpoint with a changed ``mode`` value.
    4. GET again and assert updated value is persisted.
    5. Restore baseline and delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/security/skill-scanner
    - PUT /api/agents/{agentId}/config/security/skill-scanner
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_skill_scanner_01"
    endpoint = f"/api/agents/{agent_id}/config/security/skill-scanner"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped skill scanner agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    baseline = None
    try:
        get_before = app_server.api_request("GET", endpoint)
        assert get_before.status_code == 200, app_server.logs_tail()
        baseline = get_before.json()
        assert isinstance(baseline, dict)
        assert "mode" in baseline

        updated = dict(baseline)
        updated["mode"] = (
            "block" if baseline.get("mode") != "block" else "warn"
        )

        put_resp = app_server.api_request("PUT", endpoint, json=updated)
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert put_resp.json().get("mode") == updated["mode"]

        get_after = app_server.api_request("GET", endpoint)
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert after.get("mode") == updated["mode"]
        for k, v in baseline.items():
            if k != "mode":
                assert after.get(k) == v, f"side-effect on {k}"
    finally:
        if isinstance(baseline, dict):
            restore = app_server.api_request("PUT", endpoint, json=baseline)
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_skill_scanner_whitelist_add_delete(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped skill-scanner whitelist supports add and remove flow.

    Test flow:
    1. Create a dedicated test agent.
    2. POST whitelist endpoint with a unique skill name.
    3. GET scoped skill-scanner config and assert whitelist contains the skill.
    4. DELETE whitelist entry by skill name.
    5. GET config again and assert whitelist no longer contains it.
    6. Delete test agent.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/config/security/skill-scanner/whitelist
    - GET /api/agents/{agentId}/config/security/skill-scanner
    - DELETE .../skill-scanner/whitelist/{skill_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_skill_white_01"
    skill_name = "integ_whitelist_skill_01"
    base = f"/api/agents/{agent_id}/config/security/skill-scanner"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped skill whitelist agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        add_resp = app_server.api_request(
            "POST",
            f"{base}/whitelist",
            json={"skill_name": skill_name, "content_hash": "sha256:testhash"},
        )
        assert add_resp.status_code == 200, app_server.logs_tail()
        assert add_resp.json().get("whitelisted") is True
        assert add_resp.json().get("skill_name") == skill_name

        get_after_add = app_server.api_request("GET", base)
        assert get_after_add.status_code == 200, app_server.logs_tail()
        whitelist_after_add = get_after_add.json().get("whitelist")
        assert isinstance(whitelist_after_add, list)
        skill_names_after_add = {
            entry.get("skill_name") for entry in whitelist_after_add
        }
        assert skill_name in skill_names_after_add

        del_resp = app_server.api_request(
            "DELETE",
            f"{base}/whitelist/{skill_name}",
        )
        assert del_resp.status_code == 200, app_server.logs_tail()
        assert del_resp.json().get("removed") is True
        assert del_resp.json().get("skill_name") == skill_name

        get_after_del = app_server.api_request("GET", base)
        assert get_after_del.status_code == 200, app_server.logs_tail()
        whitelist_after_del = get_after_del.json().get("whitelist")
        assert isinstance(whitelist_after_del, list)
        skill_names_after_del = {
            entry.get("skill_name") for entry in whitelist_after_del
        }
        assert skill_name not in skill_names_after_del
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_skill_scanner_blocked_history_delete_paths(
    app_server,
) -> None:
    """Test purpose:
    - Verify agent-scoped blocked-history delete paths keep stable contract for
      clear-all and missing-index cases.

    Test flow:
    1. Create a dedicated test agent.
    2. DELETE blocked-history and assert clear result.
    3. DELETE blocked-history/{index} for missing index; assert 404.
    4. Delete test agent.

    API endpoints:
    - POST /api/agents
    - DELETE .../skill-scanner/blocked-history
    - DELETE .../skill-scanner/blocked-history/{index}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_skill_hist_01"
    base = (
        f"/api/agents/{agent_id}/config/security/skill-scanner/blocked-history"
    )

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped skill history agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        clear_resp = app_server.api_request("DELETE", base)
        assert clear_resp.status_code == 200, app_server.logs_tail()
        assert clear_resp.json().get("cleared") is True

        remove_missing = app_server.api_request("DELETE", f"{base}/0")
        assert remove_missing.status_code == 404, app_server.logs_tail()
        assert "detail" in remove_missing.json()
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_file_guard_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped file-guard endpoint supports update and readback.

    Test flow:
    1. Create a dedicated test agent.
    2. GET scoped file-guard config as baseline.
    3. PUT scoped file-guard with toggled ``enabled`` value.
    4. GET again and verify updated value is persisted.
    5. Restore baseline and delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/security/file-guard
    - PUT /api/agents/{agentId}/config/security/file-guard
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_file_guard_01"
    endpoint = f"/api/agents/{agent_id}/config/security/file-guard"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped file guard agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    before = None
    try:
        get_before = app_server.api_request("GET", endpoint)
        assert get_before.status_code == 200, app_server.logs_tail()
        before = get_before.json()
        assert isinstance(before, dict)
        assert "enabled" in before

        updated_enabled = not bool(before.get("enabled", True))

        put_resp = app_server.api_request(
            "PUT",
            endpoint,
            json={"enabled": updated_enabled},
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert bool(put_resp.json().get("enabled")) == updated_enabled

        get_after = app_server.api_request("GET", endpoint)
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert bool(after.get("enabled")) == updated_enabled
        for k, v in before.items():
            if k != "enabled":
                assert after.get(k) == v, f"side-effect on {k}"
    finally:
        if isinstance(before, dict):
            restore = app_server.api_request(
                "PUT",
                endpoint,
                json={"enabled": before.get("enabled", True)},
            )
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_tool_guard_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped tool-guard endpoint supports update and readback.

    Test flow:
    1. Create a dedicated test agent.
    2. GET scoped tool-guard config as baseline.
    3. PUT scoped tool-guard with toggled ``enabled`` value.
    4. GET again and verify updated value is persisted.
    5. Restore baseline and delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/security/tool-guard
    - PUT /api/agents/{agentId}/config/security/tool-guard
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_tool_guard_01"
    endpoint = f"/api/agents/{agent_id}/config/security/tool-guard"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped tool guard agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    before = None
    try:
        get_before = app_server.api_request("GET", endpoint)
        assert get_before.status_code == 200, app_server.logs_tail()
        before = get_before.json()
        assert isinstance(before, dict)
        assert "enabled" in before

        updated = dict(before)
        updated["enabled"] = not bool(before.get("enabled", True))

        put_resp = app_server.api_request("PUT", endpoint, json=updated)
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert bool(put_resp.json().get("enabled")) == updated["enabled"]

        get_after = app_server.api_request("GET", endpoint)
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert bool(after.get("enabled")) == updated["enabled"]
        for k, v in before.items():
            if k != "enabled":
                assert after.get(k) == v, f"side-effect on {k}"
    finally:
        if isinstance(before, dict):
            restore = app_server.api_request("PUT", endpoint, json=before)
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
