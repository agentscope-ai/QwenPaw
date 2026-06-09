# -*- coding: utf-8 -*-
"""Integration tests for channel configuration HTTP API.

Covers global ``/api/config/channels/*`` endpoints: channel type
listing, per-channel config CRUD, health checks, and restart.
The existing ``test_channels_config.py`` focuses on agent-scoped
channel config + restart; this module covers the global-scope
counterparts plus broader type/health contracts.

Test ordering: read-only tests first, then write tests that
toggle channel state, to avoid health-check failures caused by
channel restart lag.
"""
from __future__ import annotations

import copy

import pytest

_CHANNEL_HTTP_TIMEOUT = 15.0

_EXPECTED_BUILTIN_TYPES = {
    "console",
    "discord",
    "dingtalk",
    "feishu",
    "telegram",
    "qq",
    "wecom",
    "wechat",
    "matrix",
    "mattermost",
    "mqtt",
    "onebot",
    "imessage",
    "voice",
    "sip",
    "xiaoyi",
    "yuanbao",
}


# ------------------------------------------------------------------ #
# read-only tests (no state mutation)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p1
def test_channel_types_returns_all_builtin(app_server) -> None:
    """Test purpose:
    - Verify GET /api/config/channels/types lists all 17 builtin
      channel types.

    Test flow:
    1. GET /api/config/channels/types.
    2. Assert response is a list containing at least the 17 known
       builtin channel keys.

    API endpoints:
    - GET /api/config/channels/types
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/types",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    types = resp.json()
    assert isinstance(types, list)
    type_set = set(types)
    missing = _EXPECTED_BUILTIN_TYPES - type_set
    assert not missing, f"missing builtin types: {missing}"


@pytest.mark.integration
@pytest.mark.p1
def test_channel_list_returns_console_enabled(app_server) -> None:
    """Test purpose:
    - Verify GET /api/config/channels returns a dict that includes
      the console channel in an enabled state (default config).

    Test flow:
    1. GET /api/config/channels.
    2. Assert response is dict with 'console' key.
    3. Assert console.enabled is true.

    API endpoints:
    - GET /api/config/channels
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    channels = resp.json()
    assert isinstance(channels, dict)
    assert "console" in channels
    console_cfg = channels["console"]
    assert isinstance(console_cfg, dict)
    assert console_cfg.get("enabled") is True


@pytest.mark.integration
@pytest.mark.p1
def test_channel_get_console_config(app_server) -> None:
    """Test purpose:
    - Verify GET /api/config/channels/console returns a complete
      config dict with expected fields.

    Test flow:
    1. GET /api/config/channels/console.
    2. Assert 200 + response is dict with 'enabled' key.

    API endpoints:
    - GET /api/config/channels/console
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/console",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    config = resp.json()
    assert isinstance(config, dict)
    assert "enabled" in config


@pytest.mark.integration
@pytest.mark.p2
def test_channel_get_unknown_returns_404(app_server) -> None:
    """Test purpose:
    - Verify GET for a nonexistent channel name returns 404.

    Test flow:
    1. GET /api/config/channels/nonexistent_channel_xyz.
    2. Assert 404.

    API endpoints:
    - GET /api/config/channels/{channel_name}
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/nonexistent_channel_xyz",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_channel_health_console(app_server) -> None:
    """Test purpose:
    - Verify GET /api/config/channels/console/health returns a
      valid ChannelHealthResponse contract.

    Test flow:
    1. GET /api/config/channels/console/health.
    2. Assert 200 + response is dict with expected health fields.

    API endpoints:
    - GET /api/config/channels/{channel_name}/health
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/console/health",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    health = resp.json()
    assert isinstance(health, dict)
    assert "healthy" in health or "status" in health


@pytest.mark.integration
@pytest.mark.p2
def test_channel_health_unknown_returns_404(app_server) -> None:
    """Test purpose:
    - Verify health check for a nonexistent channel returns 404.

    Test flow:
    1. GET /api/config/channels/nonexistent_xyz/health.
    2. Assert 404.

    API endpoints:
    - GET /api/config/channels/{channel_name}/health
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/nonexistent_xyz/health",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_agent_scoped_channel_types_matches_global(
    app_server,
) -> None:
    """Test purpose:
    - Verify agent-scoped channel types endpoint returns the same
      set as the global endpoint.

    Test flow:
    1. GET /api/config/channels/types (global).
    2. GET /api/agents/default/config/channels/types (scoped).
    3. Assert both return the same set of types.

    API endpoints:
    - GET /api/config/channels/types
    - GET /api/agents/{agentId}/config/channels/types
    """
    global_resp = app_server.api_request(
        "GET",
        "/api/config/channels/types",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert global_resp.status_code == 200, app_server.logs_tail()
    global_types = set(global_resp.json())

    scoped_resp = app_server.api_request(
        "GET",
        "/api/agents/default/config/channels/types",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert scoped_resp.status_code == 200, app_server.logs_tail()
    scoped_types = set(scoped_resp.json())

    assert global_types == scoped_types


# ------------------------------------------------------------------ #
# write tests (mutate then restore state)
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_channel_put_console_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/config/channels/console persists a config
      change and GET reads it back correctly. Uses ``bot_prefix``
      instead of ``enabled`` to avoid channel lifecycle side effects.

    Test flow:
    1. GET current console config as baseline.
    2. PUT with a modified ``bot_prefix``.
    3. GET and assert the new value persists + other fields unchanged.
    4. Restore original config.

    API endpoints:
    - GET /api/config/channels/console
    - PUT /api/config/channels/console
    """
    get_before = app_server.api_request(
        "GET",
        "/api/config/channels/console",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    assert isinstance(before, dict)

    updated = dict(before)
    updated["bot_prefix"] = "integ-test-prefix"

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/channels/console",
            json=updated,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        get_after = app_server.api_request(
            "GET",
            "/api/config/channels/console",
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert after.get("bot_prefix") == "integ-test-prefix"
        for k, v in before.items():
            if k != "bot_prefix":
                assert after.get(k) == v, f"side-effect on {k}"
    finally:
        app_server.api_request(
            "PUT",
            "/api/config/channels/console",
            json=before,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p1
def test_channel_restart_console(app_server) -> None:
    """Test purpose:
    - Verify POST /api/config/channels/console/restart returns a
      valid restart response.

    Test flow:
    1. POST /api/config/channels/console/restart.
    2. Assert 200 + response is dict.

    API endpoints:
    - POST /api/config/channels/{channel_name}/restart
    """
    resp = app_server.api_request(
        "POST",
        "/api/config/channels/console/restart",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    payload = resp.json()
    assert isinstance(payload, dict)


@pytest.mark.integration
@pytest.mark.p2
def test_channel_restart_unknown_returns_404(app_server) -> None:
    """Test purpose:
    - Verify restart for a nonexistent channel returns 404.

    Test flow:
    1. POST /api/config/channels/nonexistent_xyz/restart.
    2. Assert 404.

    API endpoints:
    - POST /api/config/channels/{channel_name}/restart
    """
    resp = app_server.api_request(
        "POST",
        "/api/config/channels/nonexistent_xyz/restart",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_channel_put_disabled_channel_config(app_server) -> None:
    """Test purpose:
    - Verify PUT for a disabled channel (telegram) persists
      enabled=false without side effects.

    Test flow:
    1. GET /api/config/channels/telegram baseline.
    2. PUT with enabled=false explicitly.
    3. GET and verify enabled=false persisted.
    4. Restore baseline.

    API endpoints:
    - GET /api/config/channels/{channel_name}
    - PUT /api/config/channels/{channel_name}
    """
    get_before = app_server.api_request(
        "GET",
        "/api/config/channels/telegram",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    assert isinstance(before, dict)

    updated = dict(before)
    updated["enabled"] = False

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/channels/telegram",
            json=updated,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        get_after = app_server.api_request(
            "GET",
            "/api/config/channels/telegram",
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert after.get("enabled") is False
    finally:
        app_server.api_request(
            "PUT",
            "/api/config/channels/telegram",
            json=before,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p0
def test_channel_bulk_put_get_roundtrip(app_server) -> None:
    """Test purpose:
    - Verify PUT /api/config/channels (bulk) persists changes to
      multiple channel configs and GET reads them all back.

    Test flow:
    1. GET /api/config/channels as baseline.
    2. Change console bot_prefix in the bulk payload.
    3. PUT /api/config/channels with modified payload.
    4. GET /api/config/channels and verify change persisted.
    5. Restore baseline.

    API endpoints:
    - GET /api/config/channels
    - PUT /api/config/channels
    """
    get_before = app_server.api_request(
        "GET",
        "/api/config/channels",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    assert isinstance(before, dict)
    assert "console" in before

    updated = copy.deepcopy(before)
    updated["console"]["bot_prefix"] = "bulk-test-prefix"

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/channels",
            json=updated,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        get_after = app_server.api_request(
            "GET",
            "/api/config/channels",
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert after["console"].get("bot_prefix") == "bulk-test-prefix"
    finally:
        app_server.api_request(
            "PUT",
            "/api/config/channels",
            json=before,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p1
def test_channel_bulk_put_preserves_unmodified_channels(
    app_server,
) -> None:
    """Test purpose:
    - Verify bulk PUT that modifies only one channel does not
      produce side effects on other channels' config fields.

    Test flow:
    1. GET /api/config/channels as baseline.
    2. Deep-copy and modify only console.bot_prefix.
    3. PUT /api/config/channels with modified payload.
    4. GET /api/config/channels.
    5. Assert console.bot_prefix changed.
    6. Assert every field of telegram and discord configs
       matches baseline exactly (side-effect assertion).
    7. Restore baseline.

    API endpoints:
    - GET /api/config/channels
    - PUT /api/config/channels
    """
    get_before = app_server.api_request(
        "GET",
        "/api/config/channels",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    assert isinstance(before, dict)
    assert "console" in before

    updated = copy.deepcopy(before)
    updated["console"]["bot_prefix"] = "side-effect-test"

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/channels",
            json=updated,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        get_after = app_server.api_request(
            "GET",
            "/api/config/channels",
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert after["console"].get("bot_prefix") == "side-effect-test"

        for ch_name in ("telegram", "discord"):
            if ch_name not in before:
                continue
            for k, v in before[ch_name].items():
                assert (
                    after[ch_name].get(k) == v
                ), f"side-effect on {ch_name}.{k}"
    finally:
        app_server.api_request(
            "PUT",
            "/api/config/channels",
            json=before,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )


@pytest.mark.integration
@pytest.mark.p1
def test_channel_config_persists_after_restart(app_server) -> None:
    """Test purpose:
    - Verify that a channel config change persists after a
      channel restart (restart re-reads from disk, should see
      the new value).

    Test flow:
    1. GET /api/config/channels/console as baseline.
    2. PUT with modified bot_prefix.
    3. POST /api/config/channels/console/restart.
    4. Wait for restart to complete.
    5. GET /api/config/channels/console and verify new value
       persists (restart did not revert it).
    6. Restore baseline.

    API endpoints:
    - GET /api/config/channels/console
    - PUT /api/config/channels/console
    - POST /api/config/channels/console/restart
    """
    import time

    get_before = app_server.api_request(
        "GET",
        "/api/config/channels/console",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert get_before.status_code == 200, app_server.logs_tail()
    before = get_before.json()
    assert isinstance(before, dict)

    updated = dict(before)
    updated["bot_prefix"] = "restart-persist-test"

    try:
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/channels/console",
            json=updated,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        restart_resp = app_server.api_request(
            "POST",
            "/api/config/channels/console/restart",
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert restart_resp.status_code == 200, app_server.logs_tail()

        time.sleep(1.0)

        get_after = app_server.api_request(
            "GET",
            "/api/config/channels/console",
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert get_after.status_code == 200, app_server.logs_tail()
        after = get_after.json()
        assert after.get("bot_prefix") == "restart-persist-test"
    finally:
        app_server.api_request(
            "PUT",
            "/api/config/channels/console",
            json=before,
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
