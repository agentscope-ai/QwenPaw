# -*- coding: utf-8 -*-
"""Integration tests for multi-agent configuration isolation.

Verifies that agent-scoped configuration changes do not leak between
agents or pollute the global config. Covers inheritance from global
defaults, bidirectional isolation, config persistence across agent
lifecycle events, and security config isolation.
"""
from __future__ import annotations

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
# inheritance — new agents get global defaults
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_new_agent_inherits_global_heartbeat_defaults(
    app_server,
) -> None:
    """Test purpose:
    - Verify a newly created agent's scoped heartbeat config
      matches the global heartbeat defaults.

    Test flow:
    1. GET /api/config/heartbeat (global).
    2. Create agent.
    3. GET /api/agents/{id}/config/heartbeat (scoped).
    4. Assert enabled, every, target fields match global.
    5. Cleanup.

    API endpoints:
    - GET /api/config/heartbeat
    - POST /api/agents
    - GET /api/agents/{agentId}/config/heartbeat
    """
    agent_id = "integ_iso_hb_inherit_01"

    global_resp = app_server.api_request(
        "GET",
        "/api/config/heartbeat",
        timeout=_AGENT_HTTP_TIMEOUT,
    )
    assert global_resp.status_code == 200, app_server.logs_tail()
    global_hb = global_resp.json()

    try:
        create_agent(app_server, agent_id)

        scoped_resp = app_server.api_request(
            "GET",
            scoped(agent_id, "/config/heartbeat"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert scoped_resp.status_code == 200, app_server.logs_tail()
        scoped_hb = scoped_resp.json()

        assert scoped_hb.get("enabled") == global_hb.get("enabled")
        assert scoped_hb.get("every") == global_hb.get("every")
        assert scoped_hb.get("target") == global_hb.get("target")
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_new_agent_inherits_global_tool_guard_defaults(
    app_server,
) -> None:
    """Test purpose:
    - Verify a newly created agent's scoped tool-guard config
      matches the global tool-guard defaults.

    Test flow:
    1. GET /api/config/security/tool-guard (global).
    2. Create agent.
    3. GET /api/agents/{id}/config/security/tool-guard (scoped).
    4. Assert enabled field matches.
    5. Cleanup.

    API endpoints:
    - GET /api/config/security/tool-guard
    - POST /api/agents
    - GET /api/agents/{agentId}/config/security/tool-guard
    """
    agent_id = "integ_iso_tg_inherit_01"

    global_resp = app_server.api_request(
        "GET",
        "/api/config/security/tool-guard",
        timeout=_AGENT_HTTP_TIMEOUT,
    )
    assert global_resp.status_code == 200, app_server.logs_tail()
    global_tg = global_resp.json()

    try:
        create_agent(app_server, agent_id)

        scoped_resp = app_server.api_request(
            "GET",
            scoped(agent_id, "/config/security/tool-guard"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert scoped_resp.status_code == 200, app_server.logs_tail()
        scoped_tg = scoped_resp.json()

        assert scoped_tg.get("enabled") == global_tg.get("enabled")
    finally:
        delete_agent_quietly(app_server, agent_id)


# ------------------------------------------------------------------ #
# bidirectional isolation
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_scoped_heartbeat_does_not_affect_global(app_server) -> None:
    """Test purpose:
    - Verify modifying an agent's scoped heartbeat config does
      not change the global heartbeat config.

    Test flow:
    1. GET global heartbeat baseline.
    2. Create agent.
    3. PUT scoped heartbeat with toggled enabled.
    4. GET global heartbeat → assert unchanged.
    5. Cleanup.

    API endpoints:
    - GET /api/config/heartbeat
    - POST /api/agents
    - PUT /api/agents/{agentId}/config/heartbeat
    """
    agent_id = "integ_iso_hb_global_01"

    global_before = app_server.api_request(
        "GET",
        "/api/config/heartbeat",
        timeout=_AGENT_HTTP_TIMEOUT,
    )
    assert global_before.status_code == 200, app_server.logs_tail()
    global_baseline = global_before.json()

    try:
        create_agent(app_server, agent_id)

        scoped_get = app_server.api_request(
            "GET",
            scoped(agent_id, "/config/heartbeat"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        scoped_hb = scoped_get.json()
        modified = dict(scoped_hb)
        modified["enabled"] = not bool(scoped_hb.get("enabled"))

        put_resp = app_server.api_request(
            "PUT",
            scoped(agent_id, "/config/heartbeat"),
            json=modified,
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        global_after = app_server.api_request(
            "GET",
            "/api/config/heartbeat",
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert global_after.status_code == 200, app_server.logs_tail()
        assert global_after.json().get("enabled") == (
            global_baseline.get("enabled")
        )
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p0
def test_two_agents_diverge_heartbeat_independently(
    app_server,
) -> None:
    """Test purpose:
    - Verify two agents can have different heartbeat configs
      without interfering with each other.

    Test flow:
    1. Create agent_a and agent_b.
    2. PUT agent_a heartbeat enabled=true.
    3. PUT agent_b heartbeat enabled=false.
    4. GET agent_a heartbeat → enabled=true.
    5. GET agent_b heartbeat → enabled=false.
    6. Cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/heartbeat
    - PUT /api/agents/{agentId}/config/heartbeat
    """
    a_id = "integ_iso_hb_div_a"
    b_id = "integ_iso_hb_div_b"
    try:
        create_agent(app_server, a_id)
        create_agent(app_server, b_id)

        get_a = app_server.api_request(
            "GET",
            scoped(a_id, "/config/heartbeat"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        hb_a = get_a.json()
        hb_a_mod = dict(hb_a)
        hb_a_mod["enabled"] = True

        get_b = app_server.api_request(
            "GET",
            scoped(b_id, "/config/heartbeat"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        hb_b = get_b.json()
        hb_b_mod = dict(hb_b)
        hb_b_mod["enabled"] = False

        app_server.api_request(
            "PUT",
            scoped(a_id, "/config/heartbeat"),
            json=hb_a_mod,
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        app_server.api_request(
            "PUT",
            scoped(b_id, "/config/heartbeat"),
            json=hb_b_mod,
            timeout=_AGENT_HTTP_TIMEOUT,
        )

        verify_a = app_server.api_request(
            "GET",
            scoped(a_id, "/config/heartbeat"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        verify_b = app_server.api_request(
            "GET",
            scoped(b_id, "/config/heartbeat"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert verify_a.json().get("enabled") is True
        assert verify_b.json().get("enabled") is False
    finally:
        delete_agent_quietly(app_server, a_id)
        delete_agent_quietly(app_server, b_id)


@pytest.mark.integration
@pytest.mark.p0
def test_tools_toggle_isolated_with_full_cycle(app_server) -> None:
    """Test purpose:
    - Verify toggling a tool in one agent does not affect the
      same tool in another agent, including re-enable.

    Test flow:
    1. Create agent_a and agent_b.
    2. GET agent_a tools to find a tool name.
    3. PATCH disable tool in agent_a.
    4. GET agent_a tools → tool is disabled.
    5. GET agent_b tools → same tool is still enabled.
    6. PATCH re-enable tool in agent_a.
    7. GET agent_a tools → tool is enabled again.
    8. Cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/tools
    - PATCH /api/agents/{agentId}/tools/{name}/toggle
    """
    a_id = "integ_iso_tool_cycle_a"
    b_id = "integ_iso_tool_cycle_b"
    try:
        create_agent(app_server, a_id)
        create_agent(app_server, b_id)

        tools_resp = app_server.api_request(
            "GET",
            scoped(a_id, "/tools"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert tools_resp.status_code == 200, app_server.logs_tail()
        tools = tools_resp.json()
        assert isinstance(tools, list) and len(tools) > 0
        tool_name = tools[0].get("name", tools[0].get("tool_name"))
        assert tool_name

        disable_resp = app_server.api_request(
            "PATCH",
            scoped(a_id, f"/tools/{tool_name}/toggle"),
            json={"enabled": False},
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert disable_resp.status_code == 200, app_server.logs_tail()

        a_tools = app_server.api_request(
            "GET",
            scoped(a_id, "/tools"),
            timeout=_AGENT_HTTP_TIMEOUT,
        ).json()
        a_tool = next(
            (
                t
                for t in a_tools
                if t.get("name", t.get("tool_name")) == tool_name
            ),
            None,
        )
        assert a_tool is not None
        assert a_tool.get("enabled") is False

        b_tools = app_server.api_request(
            "GET",
            scoped(b_id, "/tools"),
            timeout=_AGENT_HTTP_TIMEOUT,
        ).json()
        b_tool = next(
            (
                t
                for t in b_tools
                if t.get("name", t.get("tool_name")) == tool_name
            ),
            None,
        )
        assert b_tool is not None
        assert b_tool.get("enabled") is True

        enable_resp = app_server.api_request(
            "PATCH",
            scoped(a_id, f"/tools/{tool_name}/toggle"),
            json={"enabled": True},
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert enable_resp.status_code == 200, app_server.logs_tail()

        a_tools_after = app_server.api_request(
            "GET",
            scoped(a_id, "/tools"),
            timeout=_AGENT_HTTP_TIMEOUT,
        ).json()
        a_tool_after = next(
            (
                t
                for t in a_tools_after
                if t.get("name", t.get("tool_name")) == tool_name
            ),
            None,
        )
        assert a_tool_after is not None
        assert a_tool_after.get("enabled") is True
    finally:
        delete_agent_quietly(app_server, a_id)
        delete_agent_quietly(app_server, b_id)


@pytest.mark.integration
@pytest.mark.p1
def test_channel_config_diverge_across_agents(app_server) -> None:
    """Test purpose:
    - Verify two agents can have different channel configs for
      the same channel (console) without interference.

    Test flow:
    1. Create agent_a and agent_b.
    2. GET both scoped console configs.
    3. PUT agent_a console bot_prefix="aaa".
    4. PUT agent_b console bot_prefix="bbb".
    5. GET agent_a → "aaa"; GET agent_b → "bbb".
    6. Cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/channels/console
    - PUT /api/agents/{agentId}/config/channels/console
    """
    a_id = "integ_iso_ch_div_a"
    b_id = "integ_iso_ch_div_b"
    try:
        create_agent(app_server, a_id)
        create_agent(app_server, b_id)

        get_a = app_server.api_request(
            "GET",
            scoped(a_id, "/config/channels/console"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        get_b = app_server.api_request(
            "GET",
            scoped(b_id, "/config/channels/console"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        cfg_a = get_a.json()
        cfg_b = get_b.json()

        cfg_a_mod = dict(cfg_a)
        cfg_a_mod["bot_prefix"] = "aaa"
        cfg_b_mod = dict(cfg_b)
        cfg_b_mod["bot_prefix"] = "bbb"

        app_server.api_request(
            "PUT",
            scoped(a_id, "/config/channels/console"),
            json=cfg_a_mod,
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        app_server.api_request(
            "PUT",
            scoped(b_id, "/config/channels/console"),
            json=cfg_b_mod,
            timeout=_AGENT_HTTP_TIMEOUT,
        )

        verify_a = app_server.api_request(
            "GET",
            scoped(a_id, "/config/channels/console"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        verify_b = app_server.api_request(
            "GET",
            scoped(b_id, "/config/channels/console"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert verify_a.json().get("bot_prefix") == "aaa"
        assert verify_b.json().get("bot_prefix") == "bbb"
    finally:
        delete_agent_quietly(app_server, a_id)
        delete_agent_quietly(app_server, b_id)


# ------------------------------------------------------------------ #
# config persistence across agent lifecycle
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_config_persists_after_agent_disable_enable(
    app_server,
) -> None:
    """Test purpose:
    - Verify that scoped config changes persist after an agent is
      disabled and re-enabled.

    Test flow:
    1. Create agent.
    2. PUT scoped heartbeat enabled=true.
    3. Disable agent.
    4. Re-enable agent.
    5. GET scoped heartbeat → enabled still true.
    6. Cleanup.

    API endpoints:
    - POST /api/agents
    - PUT /api/agents/{agentId}/config/heartbeat
    - PATCH /api/agents/{agentId}/toggle
    - GET /api/agents/{agentId}/config/heartbeat
    """
    agent_id = "integ_iso_persist_toggle_01"
    try:
        create_agent(app_server, agent_id)

        get_hb = app_server.api_request(
            "GET",
            scoped(agent_id, "/config/heartbeat"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        hb = get_hb.json()
        modified = dict(hb)
        modified["enabled"] = True

        app_server.api_request(
            "PUT",
            scoped(agent_id, "/config/heartbeat"),
            json=modified,
            timeout=_AGENT_HTTP_TIMEOUT,
        )

        toggle_agent(app_server, agent_id, False)
        time.sleep(0.5)
        toggle_agent(app_server, agent_id, True)
        time.sleep(0.5)

        verify = app_server.api_request(
            "GET",
            scoped(agent_id, "/config/heartbeat"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert verify.status_code == 200, app_server.logs_tail()
        assert verify.json().get("enabled") is True
    finally:
        delete_agent_quietly(app_server, agent_id)


@pytest.mark.integration
@pytest.mark.p1
def test_delete_recreate_agent_gets_fresh_config(
    app_server,
) -> None:
    """Test purpose:
    - Verify that deleting an agent and recreating it with the
      same id results in fresh default config, not the old values.

    Test flow:
    1. Create agent.
    2. PUT scoped heartbeat enabled=true (non-default).
    3. DELETE agent.
    4. Recreate agent with same id.
    5. GET scoped heartbeat → should be default (not true).
    6. Cleanup.

    API endpoints:
    - POST /api/agents
    - PUT /api/agents/{agentId}/config/heartbeat
    - DELETE /api/agents/{agentId}
    - GET /api/agents/{agentId}/config/heartbeat
    """
    agent_id = "integ_iso_recreate_01"
    try:
        create_agent(app_server, agent_id)

        get_hb = app_server.api_request(
            "GET",
            scoped(agent_id, "/config/heartbeat"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        original_enabled = get_hb.json().get("enabled")

        modified = dict(get_hb.json())
        modified["enabled"] = not bool(original_enabled)
        app_server.api_request(
            "PUT",
            scoped(agent_id, "/config/heartbeat"),
            json=modified,
            timeout=_AGENT_HTTP_TIMEOUT,
        )

        app_server.api_request(
            "DELETE",
            f"/api/agents/{agent_id}",
            timeout=_AGENT_HTTP_TIMEOUT,
        )

        create_agent(app_server, agent_id)

        verify = app_server.api_request(
            "GET",
            scoped(agent_id, "/config/heartbeat"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert verify.status_code == 200, app_server.logs_tail()
        assert (
            verify.json().get("enabled") != modified["enabled"]
        ), "config leaked from deleted agent"
    finally:
        delete_agent_quietly(app_server, agent_id)


# ------------------------------------------------------------------ #
# security config isolation
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_running_config_max_iters_isolated(app_server) -> None:
    """Test purpose:
    - Verify changing agent_a's running-config max_iters does
      not affect agent_b's running-config.

    Test flow:
    1. Create agent_a and agent_b.
    2. GET agent_a running-config baseline.
    3. PUT agent_a running-config with max_iters=42.
    4. GET agent_a running-config → max_iters==42.
    5. GET agent_b running-config → max_iters unchanged.
    6. Restore agent_a and cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/workspace/running-config
    - PUT /api/agents/{agentId}/workspace/running-config
    """
    a_id = "integ_iso_running_a"
    b_id = "integ_iso_running_b"
    try:
        create_agent(app_server, a_id)
        create_agent(app_server, b_id)

        get_b = app_server.api_request(
            "GET",
            scoped(b_id, "/workspace/running-config"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_b.status_code == 200, app_server.logs_tail()
        b_baseline = get_b.json()

        get_a = app_server.api_request(
            "GET",
            scoped(a_id, "/workspace/running-config"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_a.status_code == 200, app_server.logs_tail()
        a_baseline = get_a.json()

        modified = dict(a_baseline)
        modified["max_iters"] = 42

        put_a = app_server.api_request(
            "PUT",
            scoped(a_id, "/workspace/running-config"),
            json=modified,
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert put_a.status_code == 200, app_server.logs_tail()

        verify_a = app_server.api_request(
            "GET",
            scoped(a_id, "/workspace/running-config"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert verify_a.json().get("max_iters") == 42

        verify_b = app_server.api_request(
            "GET",
            scoped(b_id, "/workspace/running-config"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert verify_b.json().get("max_iters") == b_baseline.get(
            "max_iters",
        )
    finally:
        delete_agent_quietly(app_server, a_id)
        delete_agent_quietly(app_server, b_id)


@pytest.mark.integration
@pytest.mark.p2
def test_acp_config_isolated_across_agents(app_server) -> None:
    """Test purpose:
    - Verify modifying ACP config for one agent does not affect
      another agent's ACP config.

    Test flow:
    1. Create agent_a and agent_b.
    2. GET agent_a ACP baseline.
    3. PUT agent_a ACP with modified value.
    4. GET agent_b ACP → unchanged.
    5. Cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/acp
    - PUT /api/agents/{agentId}/config/acp
    """
    a_id = "integ_iso_acp_a"
    b_id = "integ_iso_acp_b"
    try:
        create_agent(app_server, a_id)
        create_agent(app_server, b_id)

        get_a = app_server.api_request(
            "GET",
            scoped(a_id, "/config/acp"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_a.status_code == 200, app_server.logs_tail()
        acp_a = get_a.json()

        get_b_before = app_server.api_request(
            "GET",
            scoped(b_id, "/config/acp"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_b_before.status_code == 200, app_server.logs_tail()
        b_baseline = get_b_before.json()

        modified = dict(acp_a)
        modified["enabled"] = not bool(acp_a.get("enabled", False))
        app_server.api_request(
            "PUT",
            scoped(a_id, "/config/acp"),
            json=modified,
            timeout=_AGENT_HTTP_TIMEOUT,
        )

        get_b_after = app_server.api_request(
            "GET",
            scoped(b_id, "/config/acp"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_b_after.json().get("enabled") == b_baseline.get(
            "enabled",
        )
    finally:
        delete_agent_quietly(app_server, a_id)
        delete_agent_quietly(app_server, b_id)


# ------------------------------------------------------------------ #
# remaining isolation checks
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p2
def test_approval_level_isolated_across_agents(app_server) -> None:
    """Test purpose:
    - Verify modifying approval_level for one agent does not affect
      another agent's approval_level.

    Test flow:
    1. Create agent_a and agent_b.
    2. GET agent_b running-config as baseline.
    3. PUT agent_a running-config with approval_level=CONFIRM.
    4. GET agent_a running-config → approval_level changed.
    5. GET agent_b running-config → approval_level unchanged.
    6. Cleanup.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/workspace/running-config
    - PUT /api/agents/{agentId}/workspace/running-config
    """
    a_id = "integ_iso_approval_a"
    b_id = "integ_iso_approval_b"
    try:
        create_agent(app_server, a_id)
        create_agent(app_server, b_id)

        get_b = app_server.api_request(
            "GET",
            scoped(b_id, "/workspace/running-config"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_b.status_code == 200, app_server.logs_tail()
        b_baseline = get_b.json()

        get_a = app_server.api_request(
            "GET",
            scoped(a_id, "/workspace/running-config"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        a_cfg = get_a.json()
        modified = dict(a_cfg)
        modified["approval_level"] = "CONFIRM"

        app_server.api_request(
            "PUT",
            scoped(a_id, "/workspace/running-config"),
            json=modified,
            timeout=_AGENT_HTTP_TIMEOUT,
        )

        verify_a = app_server.api_request(
            "GET",
            scoped(a_id, "/workspace/running-config"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert verify_a.json().get("approval_level") == "CONFIRM"

        get_b_after = app_server.api_request(
            "GET",
            scoped(b_id, "/workspace/running-config"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_b_after.json().get(
            "approval_level",
        ) == b_baseline.get("approval_level")
    finally:
        delete_agent_quietly(app_server, a_id)
        delete_agent_quietly(app_server, b_id)


@pytest.mark.integration
@pytest.mark.p2
def test_workspace_files_isolated_across_agents(app_server) -> None:
    """Test purpose:
    - Verify a workspace file written to one agent is not visible
      in another agent's workspace.

    Test flow:
    1. Create agent_a and agent_b.
    2. PUT a markdown file in agent_a workspace.
    3. GET agent_a workspace files → file present.
    4. GET agent_b workspace files → file absent.
    5. Cleanup.

    API endpoints:
    - POST /api/agents
    - PUT /api/agents/{agentId}/workspace/files/{md_name}
    - GET /api/agents/{agentId}/workspace/files
    """
    a_id = "integ_iso_wf_a"
    b_id = "integ_iso_wf_b"
    try:
        create_agent(app_server, a_id)
        create_agent(app_server, b_id)

        put_file = app_server.api_request(
            "PUT",
            scoped(a_id, "/workspace/files/isolation_marker.md"),
            json={"content": "# isolation marker"},
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert put_file.status_code == 200, app_server.logs_tail()

        get_a_files = app_server.api_request(
            "GET",
            scoped(a_id, "/workspace/files"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_a_files.status_code == 200, app_server.logs_tail()
        a_files = get_a_files.json()
        a_names = [f.get("filename", f.get("name", "")) for f in a_files]
        assert any("isolation_marker" in n for n in a_names)

        get_b_files = app_server.api_request(
            "GET",
            scoped(b_id, "/workspace/files"),
            timeout=_AGENT_HTTP_TIMEOUT,
        )
        assert get_b_files.status_code == 200, app_server.logs_tail()
        b_files = get_b_files.json()
        b_names = [f.get("filename", f.get("name", "")) for f in b_files]
        assert not any("isolation_marker" in n for n in b_names)
    finally:
        delete_agent_quietly(app_server, a_id)
        delete_agent_quietly(app_server, b_id)
