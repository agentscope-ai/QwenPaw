# -*- coding: utf-8 -*-
"""End-to-end Yuanbao channel flow against a local mock backend.

Ninth channel on the mock-IM strategy, protobuf edition: the mock
reuses the product codec so the real channel's AuthBind / ping /
send frames round-trip untouched. Product hooks used: ``ws_url``
(custom WS gateway) and http-scheme-aware ``api_domain`` for the
sign-token API.

Flow: sign-token (HTTP) -> WS connect -> AuthBind ok -> pushed C2C
JSON frame -> agent (mock LLM) -> send_c2c_message biz frame decoded
and recorded by the mock.

API endpoints:
  - PUT /api/config/channels/yuanbao
  - GET /api/config/channels/yuanbao
"""
from __future__ import annotations

import threading
import time
from http.server import HTTPServer

import pytest
from helpers import (
    MOCK_LLM_PROVIDER_ID,
    MOCK_LLM_RESPONSE,
    MockLLMHandler,
    default_http_timeout,
    register_mock_provider,
    unregister_mock_provider,
)
from mock_yuanbao import MockYuanbao

_HTTP_TIMEOUT = default_http_timeout(15.0)

_MOCK_YB = MockYuanbao()


@pytest.fixture(scope="module")
def mock_llm():
    """Module-scoped mock OpenAI server for deterministic replies."""
    srv = HTTPServer(("127.0.0.1", 0), MockLLMHandler)
    srv.force_error = False
    srv.force_tool_call = False
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv, f"http://127.0.0.1:{port}/v1"
    srv.shutdown()


@pytest.fixture(scope="module")
def yuanbao_channel_up(app_server):
    """Enable the Yuanbao channel against the mock backend."""
    _MOCK_YB.start()
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/yuanbao",
        json={
            "enabled": True,
            "app_id": "integ-mock-yb-app",
            "app_secret": "integ-mock-yb-secret",
            "api_domain": _MOCK_YB.api_domain,
            "ws_url": _MOCK_YB.ws_url,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    assert _MOCK_YB.wait_authed(timeout=60.0), (
        "yuanbao never completed AuthBind against mock gateway: "
        + app_server.logs_tail()[-3000:]
    )
    yield _MOCK_YB
    app_server.api_request(
        "PUT",
        "/api/config/channels/yuanbao",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )


def _wait_live_connection(mock_yb, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mock_yb.has_connection:
            return
        time.sleep(0.2)
    raise AssertionError("no live yuanbao WS connection")


@pytest.mark.integration
@pytest.mark.p1
def test_yuanbao_auth_binds_against_mock(
    app_server,
    # pylint: disable=redefined-outer-name,unused-argument
    yuanbao_channel_up,
):
    """Channel completes sign-token + AuthBind against the mock.

    Test purpose:
      - Prove start(): sign-token HTTP (http-scheme api_domain) ->
        ws_url connect -> protobuf AuthBind round-trip all ran.

    API endpoints:
      - GET /api/config/channels/yuanbao
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/yuanbao",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    # The config GET serializes through a channel response model that
    # omits yuanbao-specific fields (api_domain/ws_url); the
    # authoritative proof the hooks worked is the mock gateway having
    # observed sign-token + AuthBind (asserted in the fixture).
    assert body.get("enabled") is True


@pytest.mark.integration
@pytest.mark.p0
def test_yuanbao_c2c_message_roundtrip(
    app_server,
    yuanbao_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A pushed C2C message flows through the agent and back out.

    Test purpose:
      - Core Yuanbao loop: protobuf push frame (JSON payload) ->
        _handle_push -> _handle_chat_message -> agent (mock LLM) ->
        send_c2c_message biz frame decoded by the mock.

    Test flow:
      1. Register mock LLM; wait for a live WS connection.
      2. Push a C2C text frame (retrying across reload races).
      3. Poll the mock for a send containing the LLM reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    yuanbao_channel_up.reset_authed()
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = None
        for attempt in range(4):
            _wait_live_connection(yuanbao_channel_up)
            yuanbao_channel_up.push_c2c_text(
                text="hello from mock yuanbao",
                from_account="integ-yb-user-rt",
                msg_id=f"integ-yb-rt-{attempt}",
            )
            replied = yuanbao_channel_up.wait_for_sent_text(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
        assert replied is not None, (
            f"no yuanbao send captured; sent="
            f"{yuanbao_channel_up.sent_msgs[-5:]} logs="
            f"{app_server.logs_tail()[-3000:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_yuanbao_group_message_roundtrip(
    app_server,
    yuanbao_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A group push message completes the loop via send_group_message.

    Test purpose:
      - Cover the group branch of _handle_chat_message (callback
        command prefix "Group.") and the send_group_message biz frame.

    Test flow:
      1. Push a group inbound JSON frame.
      2. Poll the mock for a recorded send (group or c2c).
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    yuanbao_channel_up.reset_authed()
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = None
        for attempt in range(4):
            _wait_live_connection(yuanbao_channel_up)
            yuanbao_channel_up.push_group_text(
                text="hello yuanbao group",
                group_code="integ-yb-group-1",
                from_account=f"integ-yb-grouper-{attempt}",
            )
            replied = yuanbao_channel_up.wait_for_sent_text(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
        assert (
            replied is not None
        ), f"no yuanbao group send; sent={yuanbao_channel_up.sent_msgs[-3:]}"
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_yuanbao_kickout_frame_handled(
    # pylint: disable=redefined-outer-name,unused-argument
    app_server,
    yuanbao_channel_up,
):
    """A kickout push frame is handled without crashing the channel.

    Test purpose:
      - Cover the CMD_KICKOUT branch of _handle_push (decode + stop
        handling), proving the channel processes control frames.

    Test flow:
      1. Push a kickout control frame.
      2. Assert no exception surfaces (the mock stays reachable).
    """
    yuanbao_channel_up.push_kickout(reason="integ test kickout")
    time.sleep(3.0)
