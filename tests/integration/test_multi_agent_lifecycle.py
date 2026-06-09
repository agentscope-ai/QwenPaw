# -*- coding: utf-8 -*-
"""Integration tests for multi-agent lifecycle management.

Covers agent creation (with full options, auto-id, workspace init),
updates, ordering, enable/disable routing effects, workspace isolation,
deletion behaviour, and error boundaries (duplicate, reserved, invalid
format, too short, nonexistent).
"""
from __future__ import annotations

import re
import time

import pytest

from tests.integration.helpers import (
    create_agent,
    delete_agent_quietly,
    scoped,
    toggle_agent,
)

_AGENT_HTTP_TIMEOUT = 15.0


# ------------------------------------------------------------------ #
# creation — positive flow
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_create_agent_with_full_options(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents with id, name, description, and
      language creates an agent with all fields persisted.

    Test flow:
    1. POST /api/agents with full options.
    2. GET /api/agents/{id} and verify all fields.
    3. Cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}
    """
    agent_id = "integ_ma_full_01"
    try:
        resp = app_server.api_request(
            "POST",
            "/api/agents",
            json={
                "id": agent_id,
                "name": "Full Options Agent",
                "description": "test agent with all fields",
                "language": "zh",
            },
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert resp.status_code == 201, app_server.logs_tail()
        body = resp.json()
        assert body.get("id") == agent_id
        assert body.get("enabled") is True
        assert "workspace_dir" in body

        get_resp = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        profile = get_resp.json()
        assert profile.get("name") == "Full Options Agent"
        assert profile.get("description") == ("test agent with all fields")
        assert "workspace_dir" in profile
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_create_agent_auto_id_when_omitted(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents without an id returns 201 with an
      auto-generated id matching the expected pattern.

    Test flow:
    1. POST /api/agents with name only (no id).
    2. Assert 201 + returned id is alphanumeric 2-64 chars.
    3. Cleanup.

    API endpoints:
    - POST /api/agents
    - DELETE /api/agents/{agentId}
    """
    resp = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "name": "Auto ID Agent",
            "description": "no explicit id",
        },
        timeout=_AGENT_HTTP_TIMEOUT,
    )
    assert resp.status_code == 201, app_server.logs_tail()
    body = resp.json()
    auto_id = body.get("id", "")
    assert len(auto_id) >= 2
    assert re.match(
        r"^[a-zA-Z0-9][a-zA-Z0-9_-]*[a-zA-Z0-9]$",
        auto_id,
    ), f"auto id does not match pattern: {auto_id}"

    delete_agent_quietly(app_server, auto_id)


@pytest.mark.integration
@pytest.mark.p0
def test_create_agent_workspace_initialized(app_server) -> None:
    """Test purpose:
    - Verify that creating an agent initializes the workspace
      directory with expected subdirectories and files.

    Test flow:
    1. POST /api/agents.
    2. GET /api/agents/{id} to find workspace_dir.
    3. Check sessions/, memory/, jobs.json, chats.json exist.
    4. Cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}
    """
    from pathlib import Path

    agent_id = "integ_ma_ws_init_01"
    try:
        create_agent(app_server, agent_id)

        get_resp = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        ws_dir = Path(get_resp.json().get("workspace_dir", ""))
        assert ws_dir.is_dir(), f"workspace_dir not found: {ws_dir}"

        assert (ws_dir / "sessions").is_dir()
        assert (ws_dir / "memory").is_dir()
        assert (ws_dir / "jobs.json").is_file()
        assert (ws_dir / "chats.json").is_file()
    finally:
        delete_agent_quietly(app_server, agent_id)


# ------------------------------------------------------------------ #
# update — positive flow
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_update_agent_roundtrip_with_side_effects(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/agents/{id} persists name and description
      changes and does not mutate other fields (workspace_dir,
      enabled).

    Test flow:
    1. Create agent and GET full profile as baseline.
    2. PUT with modified name + description.
    3. GET and verify changes persisted + other fields unchanged.
    4. Cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}
    - PUT /api/agents/{agentId}
    """
    agent_id = "integ_ma_update_01"
    try:
        create_agent(app_server, agent_id)

        get_before = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_before.status_code == 200, app_server.logs_tail()
        before = get_before.json()

        updated = dict(before)
        updated["name"] = "Updated Name"
        updated["description"] = "Updated description"

        put_resp = app_server.api_request(
            "PUT",
            f"/api/agents/{agent_id}",
            json=updated,
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        get_after = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert after.get("name") == "Updated Name"
        assert after.get("description") == "Updated description"
        assert after.get("workspace_dir") == before.get(
            "workspace_dir",
        )
        assert after.get("enabled") == before.get("enabled")
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_update_default_agent_allowed(app_server) -> None:
    """Test purpose:
    - Verify the default agent can be updated (name/description)
      even though it cannot be deleted or disabled.

    Test flow:
    1. GET /api/agents/default as baseline.
    2. PUT with modified description.
    3. GET and verify.
    4. Restore baseline.

    API endpoints:
    - GET /api/agents/default
    - PUT /api/agents/default
    """
    get_before = app_server.api_request(
        "GET",
        "/api/agents/default",
        timeout=_AGENT_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()

    updated = dict(before)
    updated["description"] = "integ-test-default-update"

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/agents/default",
            json=updated,
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        get_after = app_server.api_request(
            "GET",
            "/api/agents/default",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        assert (
            get_after.json().get("description") == "integ-test-default-update"
        )
    finally:
        app_server.api_request(
            "PUT",
            "/api/agents/default",
            json=before,
            timeout=_AGENT_HTTP_TIMEOUT,
        )


# ------------------------------------------------------------------ #
# ordering — positive flow
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_new_agent_appended_to_order(app_server) -> None:
    """Test purpose:
    - Verify a newly created agent appears at the end of the
      agent list.

    Test flow:
    1. GET /api/agents and note order.
    2. POST create new agent.
    3. GET /api/agents and verify new agent is last.
    4. Cleanup.

    API endpoints:
    - GET /api/agents
    - POST /api/agents
    """
    agent_id = "integ_ma_order_01"
    try:
        list_before = app_server.api_request(
            "GET",
            "/api/agents",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert list_before.status_code == 200, app_server.logs_tail()
        ids_before = [a["id"] for a in list_before.json().get("agents", [])]

        create_agent(app_server, agent_id)

        list_after = app_server.api_request(
            "GET",
            "/api/agents",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert list_after.status_code == 200, app_server.logs_tail()
        ids_after = [a["id"] for a in list_after.json().get("agents", [])]
        assert ids_after[-1] == agent_id
        assert ids_after[: len(ids_before)] == ids_before
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p0
def test_multi_agent_reorder_and_delete_order_adjusts(
    app_server,
) -> None:
    """Test purpose:
    - Verify reorder persists and deletion adjusts the order.

    Test flow:
    1. Create agents A, B, C.
    2. GET list → note full order.
    3. PUT /api/agents/order with [C, ..., A, B] arrangement.
    4. GET list and verify new order.
    5. DELETE A → GET list → A removed, C and B remain in order.
    6. Cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/agents
    - PUT /api/agents/order
    - DELETE /api/agents/{agentId}
    """
    a_id = "integ_ma_reorder_a"
    b_id = "integ_ma_reorder_b"
    c_id = "integ_ma_reorder_c"
    try:
        create_agent(app_server, a_id)
        create_agent(app_server, b_id)
        create_agent(app_server, c_id)

        list_resp = app_server.api_request(
            "GET",
            "/api/agents",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        all_ids = [a["id"] for a in list_resp.json().get("agents", [])]
        assert a_id in all_ids
        assert b_id in all_ids
        assert c_id in all_ids

        new_order = list(all_ids)
        new_order.remove(c_id)
        new_order.insert(0, c_id)

        reorder_resp = app_server.api_request(
            "PUT",
            "/api/agents/order",
            json={"agent_ids": new_order},
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert reorder_resp.status_code == 200, app_server.logs_tail()

        list_after_reorder = app_server.api_request(
            "GET",
            "/api/agents",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        ids_reordered = [
            a["id"] for a in list_after_reorder.json().get("agents", [])
        ]
        assert ids_reordered[0] == c_id

        del_resp = app_server.api_request(
            "DELETE",
            f"/api/agents/{a_id}",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert del_resp.status_code == 200, app_server.logs_tail()

        list_after_del = app_server.api_request(
            "GET",
            "/api/agents",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        ids_final = [a["id"] for a in list_after_del.json().get("agents", [])]
        assert a_id not in ids_final
        assert c_id in ids_final
        assert b_id in ids_final
        c_idx = ids_final.index(c_id)
        b_idx = ids_final.index(b_id)
        assert c_idx < b_idx
    finally:
        delete_agent_quietly(app_server, a_id)
        delete_agent_quietly(app_server, b_id)
        delete_agent_quietly(app_server, c_id)


# ------------------------------------------------------------------ #
# enable / disable — positive flow
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_disabled_agent_blocks_scoped_operations(app_server) -> None:
    """Test purpose:
    - Verify a disabled agent rejects scoped operations (403) but
      its profile is still readable via GET /api/agents/{id}.

    Test flow:
    1. Create agent and disable it.
    2. GET /api/agents/{id}/tools → assert 403.
    3. GET /api/agents/{id} → assert 200 (profile still readable).
    4. Cleanup.

    API endpoints:
    - POST /api/agents
    - PATCH /api/agents/{agentId}/toggle
    - GET /api/agents/{agentId}/tools
    - GET /api/agents/{agentId}
    """
    agent_id = "integ_ma_disable_01"
    try:
        create_agent(app_server, agent_id)

        toggle_resp = toggle_agent(app_server, agent_id, False)
        assert toggle_resp.status_code == 200, app_server.logs_tail()

        tools_resp = app_server.api_request(
            "GET",
            scoped(agent_id, "/tools"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert tools_resp.status_code == 403, (
            f"expected 403, got {tools_resp.status_code}: "
            f"{app_server.logs_tail()}"
        )

        profile_resp = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert profile_resp.status_code == 200, app_server.logs_tail()
    finally:
        toggle_agent(app_server, agent_id, True)
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_disabled_agent_re_enable_preserves_state(
    app_server,
) -> None:
    """Test purpose:
    - Verify that disabling and re-enabling an agent preserves
      workspace files written before disable.

    Test flow:
    1. Create agent and PUT a markdown file to its workspace.
    2. Disable agent.
    3. Re-enable agent.
    4. GET the file → content still present.
    5. Cleanup.

    API endpoints:
    - POST /api/agents
    - PUT /api/agents/{agentId}/workspace/files/{md_name}
    - PATCH /api/agents/{agentId}/toggle
    - GET /api/agents/{agentId}/workspace/files/{md_name}
    """
    agent_id = "integ_ma_preserve_01"
    try:
        create_agent(app_server, agent_id)

        put_file = app_server.api_request(
            "PUT",
            scoped(agent_id, "/workspace/files/persist_test.md"),
            json={"content": "# persist-test\ndata here"},
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert put_file.status_code == 200, app_server.logs_tail()

        toggle_agent(app_server, agent_id, False)
        time.sleep(0.5)
        toggle_agent(app_server, agent_id, True)
        time.sleep(1.0)

        get_file = app_server.api_request(
            "GET",
            scoped(agent_id, "/workspace/files/persist_test.md"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_file.status_code == 200, app_server.logs_tail()
        content = get_file.json().get("content", "")
        assert "persist-test" in content
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_toggle_shows_in_agent_list(app_server) -> None:
    """Test purpose:
    - Verify that toggling an agent's enabled state is reflected
      in GET /api/agents list response.

    Test flow:
    1. Create agent (starts enabled).
    2. Disable → GET list → agent shows enabled=false.
    3. Enable → GET list → agent shows enabled=true.
    4. Cleanup.

    API endpoints:
    - POST /api/agents
    - PATCH /api/agents/{agentId}/toggle
    - GET /api/agents
    """
    agent_id = "integ_ma_toggle_list_01"
    try:
        create_agent(app_server, agent_id)

        toggle_agent(app_server, agent_id, False)

        list_resp = app_server.api_request(
            "GET",
            "/api/agents",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert list_resp.status_code == 200, app_server.logs_tail()
        agents = list_resp.json().get("agents", [])
        target = next(
            (a for a in agents if a["id"] == agent_id),
            None,
        )
        assert target is not None
        assert target.get("enabled") is False

        toggle_agent(app_server, agent_id, True)

        list_resp2 = app_server.api_request(
            "GET",
            "/api/agents",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        agents2 = list_resp2.json().get("agents", [])
        target2 = next(
            (a for a in agents2 if a["id"] == agent_id),
            None,
        )
        assert target2 is not None
        assert target2.get("enabled") is True
    finally:
        delete_agent_quietly(app_server, agent_id)


# ------------------------------------------------------------------ #
# workspace isolation — positive flow
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_agent_workspace_dir_isolated(app_server) -> None:
    """Test purpose:
    - Verify two agents have different workspace directories.

    Test flow:
    1. Create agent_a and agent_b.
    2. GET each profile and compare workspace_dir.
    3. Assert they differ.
    4. Cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}
    """
    a_id = "integ_ma_iso_dir_a"
    b_id = "integ_ma_iso_dir_b"
    try:
        create_agent(app_server, a_id)
        create_agent(app_server, b_id)

        get_a = app_server.api_request(
            "GET",
            f"/api/agents/{a_id}",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        get_b = app_server.api_request(
            "GET",
            f"/api/agents/{b_id}",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_a.status_code == 200, app_server.logs_tail()
        assert get_b.status_code == 200, app_server.logs_tail()
        ws_a = get_a.json().get("workspace_dir")
        ws_b = get_b.json().get("workspace_dir")
        assert ws_a != ws_b, f"same workspace_dir: {ws_a}"
    finally:
        delete_agent_quietly(app_server, a_id)
        delete_agent_quietly(app_server, b_id)


@pytest.mark.integration
@pytest.mark.p0
def test_agent_chats_isolated(app_server) -> None:
    """Test purpose:
    - Verify chats created in agent_a are not visible to agent_b.

    Test flow:
    1. Create agent_a and agent_b.
    2. POST /api/agents/{a}/chats to create a chat in agent_a.
    3. GET /api/agents/{b}/chats → assert the chat is not present.
    4. Cleanup.

    API endpoints:
    - POST /api/agents
    - POST /api/agents/{agentId}/chats
    - GET /api/agents/{agentId}/chats
    """
    a_id = "integ_ma_iso_chat_a"
    b_id = "integ_ma_iso_chat_b"
    try:
        create_agent(app_server, a_id)
        create_agent(app_server, b_id)

        create_chat = app_server.api_request(
            "POST",
            scoped(a_id, "/chats"),
            json={
                "name": "isolation-test-chat",
                "session_id": "console:integ_user",
                "user_id": "integ_user",
            },
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert create_chat.status_code in (
            200,
            201,
        ), app_server.logs_tail()
        chat_data = create_chat.json()
        chat_id = chat_data.get("id", chat_data.get("chat_id", ""))

        get_b_chats = app_server.api_request(
            "GET",
            scoped(b_id, "/chats"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_b_chats.status_code == 200, app_server.logs_tail()
        b_chats = get_b_chats.json()
        b_chat_ids = []
        if isinstance(b_chats, list):
            b_chat_ids = [c.get("id", "") for c in b_chats]
        elif isinstance(b_chats, dict):
            b_chat_ids = [c.get("id", "") for c in b_chats.get("chats", [])]
        assert chat_id not in b_chat_ids
    finally:
        delete_agent_quietly(app_server, a_id)
        delete_agent_quietly(app_server, b_id)


@pytest.mark.integration
@pytest.mark.p1
def test_agent_workspace_files_isolated(app_server) -> None:
    """Test purpose:
    - Verify files written to agent_a's workspace are not visible
      in agent_b's workspace.

    Test flow:
    1. Create agent_a and agent_b.
    2. PUT a file in agent_a workspace.
    3. GET agent_b workspace files → file not present.
    4. Cleanup.

    API endpoints:
    - POST /api/agents
    - PUT /api/agents/{agentId}/workspace/files/{md_name}
    - GET /api/agents/{agentId}/workspace/files
    """
    a_id = "integ_ma_iso_file_a"
    b_id = "integ_ma_iso_file_b"
    try:
        create_agent(app_server, a_id)
        create_agent(app_server, b_id)

        put_file = app_server.api_request(
            "PUT",
            scoped(a_id, "/workspace/files/isolated_note.md"),
            json={"content": "# only-in-a"},
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert put_file.status_code == 200, app_server.logs_tail()

        get_b_files = app_server.api_request(
            "GET",
            scoped(b_id, "/workspace/files"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_b_files.status_code == 200, app_server.logs_tail()
        b_files = get_b_files.json()
        names = []
        if isinstance(b_files, list):
            names = [f.get("filename", f.get("name", "")) for f in b_files]
        elif isinstance(b_files, dict):
            names = [
                f.get("filename", f.get("name", ""))
                for f in b_files.get("files", [])
            ]
        assert not any("isolated_note" in n for n in names)
    finally:
        delete_agent_quietly(app_server, a_id)
        delete_agent_quietly(app_server, b_id)


# ------------------------------------------------------------------ #
# deletion — positive flow
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_delete_agent_workspace_dir_preserved(app_server) -> None:
    """Test purpose:
    - Verify deleting an agent does NOT remove its workspace
      directory from disk (by design).

    Test flow:
    1. Create agent and GET its workspace_dir.
    2. DELETE agent.
    3. Verify workspace_dir still exists on disk.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}
    - DELETE /api/agents/{agentId}
    """
    from pathlib import Path

    agent_id = "integ_ma_del_ws_01"
    try:
        create_agent(app_server, agent_id)

        get_resp = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        ws_dir = Path(get_resp.json().get("workspace_dir", ""))
        assert ws_dir.is_dir()

        del_resp = app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert del_resp.status_code == 200, app_server.logs_tail()

        assert ws_dir.is_dir(), f"workspace_dir deleted: {ws_dir}"
    finally:
        delete_agent_quietly(app_server, agent_id)


# ------------------------------------------------------------------ #
# error boundaries
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_create_agent_duplicate_id_rejected(app_server) -> None:
    """Test purpose:
    - Verify creating an agent with a duplicate id is rejected.

    Test flow:
    1. POST /api/agents with id=X → 201.
    2. POST /api/agents with same id=X → 400 or 409.
    3. Cleanup.

    API endpoints:
    - POST /api/agents
    """
    agent_id = "integ_ma_dup_01"
    try:
        create_agent(app_server, agent_id)

        resp2 = app_server.api_request(
            "POST",
            "/api/agents",
            json={
                "id": agent_id,
                "name": "Duplicate",
                "description": "",
            },
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert resp2.status_code in (400, 409), (
            f"expected 400/409, got {resp2.status_code}: "
            f"{app_server.logs_tail()}"
        )
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_create_agent_reserved_id_default_rejected(
    app_server,
) -> None:
    """Test purpose:
    - Verify creating an agent with id='default' is rejected.

    Test flow:
    1. POST /api/agents with id=default.
    2. Assert 400.

    API endpoints:
    - POST /api/agents
    """
    resp = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": "default",
            "name": "Should Fail",
            "description": "",
        },
        timeout=_AGENT_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_create_agent_invalid_id_format_rejected(
    app_server,
) -> None:
    """Test purpose:
    - Verify creating an agent with special characters in id
      is rejected.

    Test flow:
    1. POST /api/agents with id='agent@#!'.
    2. Assert 400 or 422.

    API endpoints:
    - POST /api/agents
    """
    resp = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": "agent@#!",
            "name": "Invalid ID",
            "description": "",
        },
        timeout=_AGENT_HTTP_TIMEOUT,
    )
    assert resp.status_code in (400, 422), (
        f"expected 400/422, got {resp.status_code}: "
        f"{app_server.logs_tail()}"
    )


@pytest.mark.integration
@pytest.mark.p2
def test_create_agent_id_too_short_rejected(app_server) -> None:
    """Test purpose:
    - Verify creating an agent with a single-char id (below
      minimum length of 2) is rejected.

    Test flow:
    1. POST /api/agents with id='a'.
    2. Assert 400 or 422.

    API endpoints:
    - POST /api/agents
    """
    resp = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": "a",
            "name": "Too Short",
            "description": "",
        },
        timeout=_AGENT_HTTP_TIMEOUT,
    )
    assert resp.status_code in (400, 422), (
        f"expected 400/422, got {resp.status_code}: "
        f"{app_server.logs_tail()}"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_delete_default_agent_rejected(app_server) -> None:
    """Test purpose:
    - Verify DELETE /api/agents/default is rejected with 400.

    Test flow:
    1. DELETE /api/agents/default.
    2. Assert 400.

    API endpoints:
    - DELETE /api/agents/default
    """
    resp = app_server.api_request(
        "DELETE",
        "/api/agents/default",
        timeout=_AGENT_HTTP_TIMEOUT,
    )
    assert resp.status_code == 400, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_delete_nonexistent_agent_returns_404(app_server) -> None:
    """Test purpose:
    - Verify DELETE for a nonexistent agent returns 404.

    Test flow:
    1. DELETE /api/agents/does_not_exist_xyz.
    2. Assert 404.

    API endpoints:
    - DELETE /api/agents/{agentId}
    """
    resp = app_server.api_request(
        "DELETE",
        "/api/agents/does_not_exist_xyz",
        timeout=_AGENT_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_toggle_default_agent_rejected(app_server) -> None:
    """Test purpose:
    - Verify disabling the default agent is rejected with 400.

    Test flow:
    1. PATCH /api/agents/default/toggle with enabled=false.
    2. Assert 400.

    API endpoints:
    - PATCH /api/agents/default/toggle
    """
    resp = toggle_agent(app_server, "default", False)
    assert resp.status_code == 400, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_reorder_partial_list_rejected(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/agents/order with an incomplete agent list
      is rejected.

    Test flow:
    1. GET /api/agents to get full list.
    2. PUT /api/agents/order with only a subset of ids.
    3. Assert 400 or 422.

    API endpoints:
    - GET /api/agents
    - PUT /api/agents/order
    """
    list_resp = app_server.api_request(
        "GET",
        "/api/agents",
        timeout=_AGENT_HTTP_TIMEOUT,
    )
    assert list_resp.status_code == 200, app_server.logs_tail()
    all_ids = [a["id"] for a in list_resp.json().get("agents", [])]
    assert len(all_ids) >= 2, "need at least 2 agents for test"

    partial = all_ids[:1]
    resp = app_server.api_request(
        "PUT",
        "/api/agents/order",
        json={"agent_ids": partial},
        timeout=_AGENT_HTTP_TIMEOUT,
    )
    assert resp.status_code in (400, 422), (
        f"expected 400/422, got {resp.status_code}: "
        f"{app_server.logs_tail()}"
    )
