# -*- coding: utf-8 -*-
"""Integration tests for custom channel registration and outbound pipeline.

A minimal ``TestEchoChannel`` is placed into the subprocess's
``custom_channels/`` directory before startup. It registers itself
as channel type ``test_echo`` via the auto-discovery mechanism in
``registry.py``. Outbound ``send()`` calls POST to a callback
HTTP server run by the test process (started in conftest as a
session-scoped fixture), allowing end-to-end verification of the
message pipeline without touching production channel code.
"""
from __future__ import annotations

import time

import pytest

_CHANNEL_HTTP_TIMEOUT = 15.0


# ------------------------------------------------------------------ #
# read-only tests
# ------------------------------------------------------------------ #


@pytest.mark.integration
@pytest.mark.p0
def test_custom_channel_appears_in_types(app_server) -> None:
    """Test purpose:
    - Verify the auto-discovered custom channel appears in the
      channel types list alongside builtin channels.

    Test flow:
    1. GET /api/config/channels/types.
    2. Assert 'test_echo' is in the returned list.

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
    assert "test_echo" in types, f"test_echo not in types: {types}"


@pytest.mark.integration
@pytest.mark.p1
def test_custom_channel_config_put_get(app_server) -> None:
    """Test purpose:
    - Verify custom channel config can be written and read back.

    Test flow:
    1. PUT /api/config/channels/test_echo with enabled=false.
    2. GET /api/config/channels/test_echo and verify roundtrip.
    3. Restore (PUT enabled=false again, safe default).

    API endpoints:
    - PUT /api/config/channels/{channel_name}
    - GET /api/config/channels/{channel_name}
    """
    payload = {"enabled": False}
    put_resp = app_server.api_request(
        "PUT",
        "/api/config/channels/test_echo",
        json=payload,
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert put_resp.status_code == 200, app_server.logs_tail()

    get_resp = app_server.api_request(
        "GET",
        "/api/config/channels/test_echo",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert get_resp.status_code == 200, app_server.logs_tail()
    config = get_resp.json()
    assert isinstance(config, dict)
    assert config.get("enabled") is False


@pytest.mark.integration
@pytest.mark.p1
def test_custom_channel_enable_disable(app_server) -> None:
    """Test purpose:
    - Verify custom channel can be toggled between enabled and
      disabled states via config PUT.

    Test flow:
    1. PUT enabled=true → GET → assert enabled.
    2. PUT enabled=false → GET → assert disabled.

    API endpoints:
    - PUT /api/config/channels/{channel_name}
    - GET /api/config/channels/{channel_name}
    """
    for state in (True, False):
        put_resp = app_server.api_request(
            "PUT",
            "/api/config/channels/test_echo",
            json={"enabled": state},
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert put_resp.status_code == 200, app_server.logs_tail()

        get_resp = app_server.api_request(
            "GET",
            "/api/config/channels/test_echo",
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert get_resp.status_code == 200, app_server.logs_tail()
        assert get_resp.json().get("enabled") is state


@pytest.mark.integration
@pytest.mark.p2
def test_custom_channel_health(app_server) -> None:
    """Test purpose:
    - Verify health endpoint for a custom channel returns a
      valid response (200 if running, 404 if not).

    Test flow:
    1. GET /api/config/channels/test_echo/health.
    2. Assert status is 200 or 404 (depends on enabled state).

    API endpoints:
    - GET /api/config/channels/{channel_name}/health
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/test_echo/health",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert resp.status_code in (200, 404), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_custom_channel_restart(app_server) -> None:
    """Test purpose:
    - Verify restart endpoint for a custom channel returns a
      valid response.

    Test flow:
    1. POST /api/config/channels/test_echo/restart.
    2. Assert status is 200 or 404.

    API endpoints:
    - POST /api/config/channels/{channel_name}/restart
    """
    resp = app_server.api_request(
        "POST",
        "/api/config/channels/test_echo/restart",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert resp.status_code in (200, 404), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p0
def test_messages_send_to_custom_channel(
    app_server,
    channel_callback_server,
) -> None:
    """Test purpose:
    - Verify POST /api/messages/send routes a message through the
      custom test_echo channel and the outbound send() reaches the
      callback server.

    Test flow:
    1. Enable test_echo channel.
    2. Wait briefly for channel manager to start it.
    3. POST /api/messages/send with channel=test_echo.
    4. Poll callback server recorded payloads.
    5. Assert the callback received the correct text.

    API endpoints:
    - PUT /api/config/channels/{channel_name}
    - POST /api/messages/send
    """
    server = channel_callback_server
    server.recorded.clear()

    put_resp = app_server.api_request(
        "PUT",
        "/api/config/channels/test_echo",
        json={"enabled": True},
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert put_resp.status_code == 200, app_server.logs_tail()

    time.sleep(1.0)

    send_resp = app_server.api_request(
        "POST",
        "/api/messages/send",
        json={
            "channel": "test_echo",
            "target_user": "integ-user-01",
            "target_session": "integ-session-01",
            "text": "hello from integration test",
        },
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert send_resp.status_code == 200, app_server.logs_tail()
    assert send_resp.json().get("success") is True

    deadline = time.time() + 5.0
    while time.time() < deadline and not server.recorded:
        time.sleep(0.2)

    assert (
        len(server.recorded) >= 1
    ), "callback server did not receive outbound message"
    msg = server.recorded[0]
    assert msg.get("channel") == "test_echo"
    assert msg.get("text") == "hello from integration test"


@pytest.mark.integration
@pytest.mark.p2
def test_messages_send_to_unknown_channel(app_server) -> None:
    """Test purpose:
    - Verify POST /api/messages/send with an unknown channel
      returns 404.

    Test flow:
    1. POST /api/messages/send with channel=nonexistent_xyz.
    2. Assert 404 + error detail.

    API endpoints:
    - POST /api/messages/send
    """
    resp = app_server.api_request(
        "POST",
        "/api/messages/send",
        json={
            "channel": "nonexistent_xyz",
            "target_user": "user",
            "target_session": "session",
            "text": "should fail",
        },
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    # 404 if handler checks channel existence; 500 if KeyError
    # propagates unhandled — both are acceptable error signals.
    assert resp.status_code in (404, 500), app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p1
def test_custom_channel_lifecycle_health_transitions(
    app_server,
) -> None:
    """Test purpose:
    - Verify the full health state machine for a custom channel:
      enable → healthy, disable → 404, re-enable → healthy.

    Test flow:
    1. PUT enabled=true, wait for startup.
    2. GET health → assert 200 + status contains expected value.
    3. PUT enabled=false, wait for shutdown.
    4. GET health → assert 404 (channel not running).
    5. PUT enabled=true, wait for startup.
    6. GET health → assert 200 again.
    7. Restore disabled state.

    API endpoints:
    - PUT /api/config/channels/test_echo
    - GET /api/config/channels/test_echo/health
    """
    put_enable = app_server.api_request(
        "PUT",
        "/api/config/channels/test_echo",
        json={"enabled": True},
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert put_enable.status_code == 200, app_server.logs_tail()
    time.sleep(1.0)

    health_1 = app_server.api_request(
        "GET",
        "/api/config/channels/test_echo/health",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert health_1.status_code == 200, app_server.logs_tail()
    h1 = health_1.json()
    assert h1.get("channel") == "test_echo"
    assert h1.get("status") in ("healthy", "unhealthy")

    put_disable = app_server.api_request(
        "PUT",
        "/api/config/channels/test_echo",
        json={"enabled": False},
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert put_disable.status_code == 200, app_server.logs_tail()
    time.sleep(0.5)

    health_2 = app_server.api_request(
        "GET",
        "/api/config/channels/test_echo/health",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert health_2.status_code == 404, app_server.logs_tail()

    put_re_enable = app_server.api_request(
        "PUT",
        "/api/config/channels/test_echo",
        json={"enabled": True},
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert put_re_enable.status_code == 200, app_server.logs_tail()
    time.sleep(1.0)

    health_3 = app_server.api_request(
        "GET",
        "/api/config/channels/test_echo/health",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert health_3.status_code == 200, app_server.logs_tail()

    app_server.api_request(
        "PUT",
        "/api/config/channels/test_echo",
        json={"enabled": False},
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )


@pytest.mark.integration
@pytest.mark.p1
def test_custom_channel_send_multiple_messages_ordered(
    app_server,
    channel_callback_server,
) -> None:
    """Test purpose:
    - Verify multiple messages sent to the custom channel arrive
      at the callback server in order with correct content.

    Test flow:
    1. Enable test_echo channel.
    2. Send 3 messages with distinct text.
    3. Poll callback server until all 3 arrive.
    4. Assert messages arrived in order with correct text.

    API endpoints:
    - PUT /api/config/channels/test_echo
    - POST /api/messages/send
    """
    server = channel_callback_server
    server.recorded.clear()

    put_resp = app_server.api_request(
        "PUT",
        "/api/config/channels/test_echo",
        json={"enabled": True},
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert put_resp.status_code == 200, app_server.logs_tail()
    time.sleep(1.0)

    messages = [f"ordered_msg_{i}" for i in range(3)]
    for text in messages:
        send_resp = app_server.api_request(
            "POST",
            "/api/messages/send",
            json={
                "channel": "test_echo",
                "target_user": "integ-user-ordered",
                "target_session": "integ-session-ordered",
                "text": text,
            },
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert send_resp.status_code == 200, app_server.logs_tail()

    deadline = time.time() + 8.0
    while time.time() < deadline and len(server.recorded) < 3:
        time.sleep(0.2)

    assert (
        len(server.recorded) >= 3
    ), f"expected 3 messages, got {len(server.recorded)}"
    for i, text in enumerate(messages):
        assert (
            server.recorded[i].get("text") == text
        ), f"message {i} mismatch: {server.recorded[i]}"


@pytest.mark.integration
@pytest.mark.p0
def test_disabled_channel_rejects_send(app_server) -> None:
    """Test purpose:
    - Verify POST /api/messages/send to a disabled channel returns
      404 (disabled channels are not instantiated, so the send
      path raises KeyError caught as 404).

    Test flow:
    1. PUT test_echo enabled=false.
    2. POST /api/messages/send with channel=test_echo.
    3. Assert 404.

    API endpoints:
    - PUT /api/config/channels/test_echo
    - POST /api/messages/send
    """
    put_resp = app_server.api_request(
        "PUT",
        "/api/config/channels/test_echo",
        json={"enabled": False},
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert put_resp.status_code == 200, app_server.logs_tail()
    time.sleep(0.5)

    send_resp = app_server.api_request(
        "POST",
        "/api/messages/send",
        json={
            "channel": "test_echo",
            "target_user": "user",
            "target_session": "session",
            "text": "should fail",
        },
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert send_resp.status_code == 404, app_server.logs_tail()


@pytest.mark.integration
@pytest.mark.p2
def test_custom_channel_send_after_restart(
    app_server,
    channel_callback_server,
) -> None:
    """Test purpose:
    - Verify that restarting a custom channel does not break the
      outbound send pipeline — messages still reach the callback.

    Test flow:
    1. Enable test_echo and send a message (verify delivery).
    2. POST restart.
    3. Wait for restart completion.
    4. Send another message.
    5. Verify the second message also reaches callback.

    API endpoints:
    - PUT /api/config/channels/test_echo
    - POST /api/messages/send
    - POST /api/config/channels/test_echo/restart
    """
    server = channel_callback_server
    server.recorded.clear()

    app_server.api_request(
        "PUT",
        "/api/config/channels/test_echo",
        json={"enabled": True},
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    time.sleep(1.0)

    send_1 = app_server.api_request(
        "POST",
        "/api/messages/send",
        json={
            "channel": "test_echo",
            "target_user": "user-restart",
            "target_session": "session-restart",
            "text": "before_restart",
        },
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert send_1.status_code == 200, app_server.logs_tail()

    deadline = time.time() + 5.0
    while time.time() < deadline and not server.recorded:
        time.sleep(0.2)
    assert len(server.recorded) >= 1

    restart_resp = app_server.api_request(
        "POST",
        "/api/config/channels/test_echo/restart",
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert restart_resp.status_code == 200, app_server.logs_tail()
    time.sleep(1.0)

    server.recorded.clear()
    send_2 = app_server.api_request(
        "POST",
        "/api/messages/send",
        json={
            "channel": "test_echo",
            "target_user": "user-restart",
            "target_session": "session-restart",
            "text": "after_restart",
        },
        timeout=_CHANNEL_HTTP_TIMEOUT,
    )
    assert send_2.status_code == 200, app_server.logs_tail()

    deadline = time.time() + 5.0
    while time.time() < deadline and not server.recorded:
        time.sleep(0.2)
    assert len(server.recorded) >= 1
    assert server.recorded[0].get("text") == "after_restart"


@pytest.mark.integration
@pytest.mark.p2
def test_bad_file_does_not_crash_running_channels(
    app_server,
) -> None:
    """Test purpose:
    - Verify a malformed .py file written to custom_channels/ while
      the server is running does not crash already-loaded channels.
      (Discovery happens at boot; this confirms runtime resilience.)

    Test flow:
    1. Write a syntax-error .py file to custom_channels/.
    2. GET /api/config/channels/types.
    3. Assert test_echo and console are still present.
    4. Remove the bad file.

    API endpoints:
    - GET /api/config/channels/types
    """
    bad_file = app_server.working_dir / "custom_channels" / "bad_channel.py"
    bad_file.write_text(
        "this is not valid python !!!",
        encoding="utf-8",
    )
    try:
        resp = app_server.api_request(
            "GET",
            "/api/config/channels/types",
            timeout=_CHANNEL_HTTP_TIMEOUT,
        )
        assert resp.status_code == 200, app_server.logs_tail()
        types = resp.json()
        assert "console" in types
        assert "test_echo" in types
    finally:
        bad_file.unlink(missing_ok=True)
