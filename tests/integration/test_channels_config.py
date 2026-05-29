# -*- coding: utf-8 -*-
"""Smoke tests for channels config (global/scoped + health/restart)."""
from __future__ import annotations

import pytest


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_channels_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped /config/channels supports full payload update and
      readback for the selected channel switch.

    Test flow:
    1. Create a dedicated test agent and read full profile channels payload.
    2. PUT /api/agents/{agentId}/config/channels with toggled console enabled.
    3. GET /api/agents/{agentId}/config/channels and assert value changed.
    4. Restore baseline payload and delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}
    - PUT /api/agents/{agentId}/config/channels
    - GET /api/agents/{agentId}/config/channels
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_channels_01"
    channels_endpoint = f"/api/agents/{agent_id}/config/channels"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped channels agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    original_channels = None
    try:
        get_agent = app_server.api_request("GET", f"/api/agents/{agent_id}")
        assert get_agent.status_code == 200, app_server.logs_tail()
        original_channels = get_agent.json().get("channels")
        assert isinstance(original_channels, dict), app_server.logs_tail()
        assert "console" in original_channels, app_server.logs_tail()

        updated_channels = dict(original_channels)
        updated_console = dict(updated_channels.get("console") or {})
        updated_console["enabled"] = not bool(
            updated_console.get("enabled", False),
        )
        updated_channels["console"] = updated_console

        put_resp = app_server.api_request(
            "PUT",
            channels_endpoint,
            json=updated_channels,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert bool(
            put_resp.json().get("console", {}).get("enabled", False),
        ) == bool(
            updated_console["enabled"],
        )

        get_after = app_server.api_request("GET", channels_endpoint)
        assert get_after.status_code == 200, app_server.logs_tail()
        assert bool(
            get_after.json().get("console", {}).get("enabled", False),
        ) == bool(
            updated_console["enabled"],
        )
    finally:
        if isinstance(original_channels, dict):
            restore = app_server.api_request(
                "PUT",
                channels_endpoint,
                json=original_channels,
            )
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_single_channel_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify agent-scoped /config/channels/{channel_name} update path supports
      deterministic readback for one channel.

    Test flow:
    1. Create a dedicated test agent and choose one available channel type.
    2. GET scoped single-channel config as baseline.
    3. PUT scoped single-channel config with toggled enabled value.
    4. GET again and assert value changed.
    5. Restore baseline and delete test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/channels/types
    - GET /api/agents/{agentId}/config/channels/{channel_name}
    - PUT /api/agents/{agentId}/config/channels/{channel_name}
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_single_channel_01"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped single channel agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    channel_name = None
    baseline = None
    try:
        types_resp = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/config/channels/types",
        )
        assert types_resp.status_code == 200, app_server.logs_tail()
        channel_types = types_resp.json()
        assert isinstance(channel_types, list) and channel_types
        channel_name = (
            "console" if "console" in channel_types else str(channel_types[0])
        )

        endpoint = f"/api/agents/{agent_id}/config/channels/{channel_name}"
        get_before = app_server.api_request("GET", endpoint)
        assert get_before.status_code == 200, app_server.logs_tail()
        baseline = get_before.json()
        assert isinstance(baseline, dict)
        assert "enabled" in baseline

        updated = dict(baseline)
        updated["enabled"] = not bool(baseline.get("enabled", False))

        put_resp = app_server.api_request("PUT", endpoint, json=updated)
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert bool(put_resp.json().get("enabled", False)) == bool(
            updated["enabled"],
        )

        get_after = app_server.api_request("GET", endpoint)
        assert get_after.status_code == 200, app_server.logs_tail()
        assert bool(get_after.json().get("enabled", False)) == bool(
            updated["enabled"],
        )
    finally:
        if channel_name and isinstance(baseline, dict):
            endpoint = f"/api/agents/{agent_id}/config/channels/{channel_name}"
            restore = app_server.api_request("PUT", endpoint, json=baseline)
            assert restore.status_code == 200, app_server.logs_tail()
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")


@pytest.mark.integration
@pytest.mark.p0
def test_global_channels_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify the global channels endpoint accepts a full channels payload and
      the updated value can be observed from list/get APIs.

    Test flow:
    1. GET /api/agents/default and extract ``channels`` as a valid PUT payload.
    2. GET /api/config/channels and keep current state for later comparison.
    3. Flip ``console.enabled`` in the payload and PUT /api/config/channels.
    4. GET /api/config/channels and GET /api/config/channels/console to verify
       the changed value is reflected.
    5. PUT original channels payload back, then verify restoration.

    API endpoints:
    - GET /api/agents/default
    - GET /api/config/channels
    - PUT /api/config/channels
    - GET /api/config/channels/console
    """
    get_agent = app_server.api_request("GET", "/api/agents/default")
    assert get_agent.status_code == 200, app_server.logs_tail()
    original_channels = get_agent.json().get("channels")
    assert isinstance(original_channels, dict), app_server.logs_tail()

    list_before = app_server.api_request("GET", "/api/config/channels")
    assert list_before.status_code == 200, app_server.logs_tail()
    before = list_before.json()
    assert isinstance(before, dict)
    assert "console" in before
    assert isinstance(before["console"], dict)
    assert "enabled" in before["console"]

    updated_channels = dict(original_channels)
    console_cfg = dict(updated_channels.get("console") or {})
    console_cfg["enabled"] = not bool(console_cfg.get("enabled", False))
    updated_channels["console"] = console_cfg

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/channels",
            json=updated_channels,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()
        assert isinstance(put_resp.json(), dict)

        list_after = app_server.api_request("GET", "/api/config/channels")
        assert list_after.status_code == 200, app_server.logs_tail()
        after_console_enabled = bool(
            list_after.json().get("console", {}).get("enabled", False),
        )
        assert after_console_enabled == console_cfg["enabled"]

        console_after = app_server.api_request(
            "GET",
            "/api/config/channels/console",
        )
        assert console_after.status_code == 200, app_server.logs_tail()
        assert (
            bool(console_after.json().get("enabled", False))
            == console_cfg["enabled"]
        )
    finally:
        restore_resp = app_server.api_request(
            "PUT",
            "/api/config/channels",
            json=original_channels,
        )
        assert restore_resp.status_code == 200, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_global_channel_health_minimal_contract(app_server) -> None:
    """Test purpose:
    - Verify channel health endpoint keeps a stable minimal contract for an
      available channel type.

    Test flow:
    1. GET /api/config/channels/types and select one available channel.
    2. GET /api/config/channels/{channel}/health for that channel.
    3. Accept either 200 (health payload) or 404 (channel not running), and
       validate response structure accordingly.

    API endpoints:
    - GET /api/config/channels/types
    - GET /api/config/channels/{channel}/health
    """
    types_resp = app_server.api_request("GET", "/api/config/channels/types")
    assert types_resp.status_code == 200, app_server.logs_tail()
    channel_types = types_resp.json()
    assert isinstance(channel_types, list)
    assert (
        channel_types
    ), "channels/types should return at least one channel type"

    channel_name = str(channel_types[0])
    health_resp = app_server.api_request(
        "GET",
        f"/api/config/channels/{channel_name}/health",
    )

    assert health_resp.status_code in (200, 404), app_server.logs_tail()
    payload = health_resp.json()
    assert isinstance(payload, dict)
    assert "detail" in payload

    if health_resp.status_code == 200:
        assert payload.get("channel") == channel_name
        assert payload.get("status") in {"healthy", "unhealthy", "disabled"}


@pytest.mark.integration
@pytest.mark.p1
def test_agent_scoped_channel_restart_when_healthy(app_server) -> None:
    """Test purpose:
    - Verify POST /api/agents/{agentId}/config/channels/{name}/restart succeeds
      when the channel reports ``healthy`` on the scoped health endpoint.

    Test flow:
    1. Create a dedicated test agent.
    2. GET scoped channel types and iterate channel names.
    3. For the first channel whose scoped health is 200 / ``healthy``,
       POST scoped restart and assert ``ChannelRestartResponse`` shape.
    4. Delete the test agent.

    API endpoints:
    - POST /api/agents
    - GET /api/agents/{agentId}/config/channels/types
    - GET /api/agents/{agentId}/config/channels/{channel_name}/health
    - POST /api/agents/{agentId}/config/channels/{channel_name}/restart
    - DELETE /api/agents/{agentId}
    """
    agent_id = "integ_scoped_channel_restart_01"

    create_agent = app_server.api_request(
        "POST",
        "/api/agents",
        json={
            "id": agent_id,
            "name": "Scoped channel restart agent",
            "description": "",
        },
    )
    assert create_agent.status_code == 201, app_server.logs_tail()

    try:
        types_resp = app_server.api_request(
            "GET",
            f"/api/agents/{agent_id}/config/channels/types",
        )
        assert types_resp.status_code == 200, app_server.logs_tail()
        channel_types = types_resp.json()
        assert isinstance(channel_types, list)
        assert channel_types, app_server.logs_tail()

        restarted = False
        for raw_name in channel_types:
            channel_name = str(raw_name)
            health_resp = app_server.api_request(
                "GET",
                f"/api/agents/{agent_id}/config/channels/"
                f"{channel_name}/health",
            )
            if health_resp.status_code != 200:
                continue
            health_payload = health_resp.json()
            if health_payload.get("status") != "healthy":
                continue

            restart_resp = app_server.api_request(
                "POST",
                f"/api/agents/{agent_id}/config/channels/"
                f"{channel_name}/restart",
            )
            assert restart_resp.status_code == 200, app_server.logs_tail()
            body = restart_resp.json()
            assert body.get("status") == "restarted"
            assert body.get("channel") == channel_name
            restarted = True
            break

        assert restarted, (
            "expected at least one channel with scoped health status=healthy "
            f"for agent {agent_id!r}; types={channel_types!r}"
        )
    finally:
        app_server.api_request("DELETE", f"/api/agents/{agent_id}")
