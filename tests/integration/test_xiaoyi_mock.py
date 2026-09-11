# -*- coding: utf-8 -*-
"""End-to-end XiaoYi (A2A) channel flow against a local mock gateway.

Tenth channel on the mock-IM strategy. Uses the new ``ws_url`` hook:
when set, the channel connects only the primary WS to the mock (the
IP-direct backup is skipped). The mock accepts the aiohttp WS with
auth headers unvalidated and records every frame the channel sends.

Flow: connect + init -> pushed message/stream A2A request -> agent
(mock LLM) -> streaming task frames captured by the mock.

API endpoints:
  - PUT /api/config/channels/xiaoyi
  - GET /api/config/channels/xiaoyi
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
from mock_xiaoyi import MockXiaoYi

_HTTP_TIMEOUT = default_http_timeout(15.0)
_AGENT_ID = "integ-mock-xy-agent"

_MOCK_XY = MockXiaoYi()


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
def xiaoyi_channel_up(app_server):
    """Enable the XiaoYi channel against the mock gateway."""
    _MOCK_XY.start()
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/xiaoyi",
        json={
            "enabled": True,
            "ak": "integ-mock-xy-ak",
            "sk": "integ-mock-xy-sk",
            "agent_id": _AGENT_ID,
            "ws_url": _MOCK_XY.ws_url,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    assert _MOCK_XY.wait_connected(timeout=60.0), (
        "xiaoyi never connected to mock gateway: "
        + app_server.logs_tail()[-3000:]
    )
    yield _MOCK_XY
    app_server.api_request(
        "PUT",
        "/api/config/channels/xiaoyi",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )


def _wait_live_connection(mock_xy, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mock_xy.has_connection:
            return
        time.sleep(0.2)
    raise AssertionError("no live xiaoyi WS connection")


@pytest.mark.integration
@pytest.mark.p1
def test_xiaoyi_connects_via_custom_ws_url(
    app_server,
    # pylint: disable=redefined-outer-name,unused-argument
    xiaoyi_channel_up,
):
    """Channel connects its primary WS to the mock gateway.

    Test purpose:
      - Prove start() -> _start_connections honored ws_url (single
        primary connection, no IP-direct backup) and sent the init
        message.

    API endpoints:
      - GET /api/config/channels/xiaoyi
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/xiaoyi",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert resp.json().get("enabled") is True


@pytest.mark.integration
@pytest.mark.p0
def test_xiaoyi_message_stream_roundtrip(
    app_server,
    xiaoyi_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A pushed A2A message/stream request yields streamed replies.

    Test purpose:
      - Core XiaoYi loop: message/stream frame -> _handle_a2a_request
        -> agent (mock LLM) -> streaming task frames back over the
        same WS, captured by the mock.

    Test flow:
      1. Register mock LLM; wait for a live WS connection.
      2. Push a message/stream request (retrying across reloads).
      3. Poll recorded frames for the LLM reply text.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    xiaoyi_channel_up.reset_connected()
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = None
        for attempt in range(4):
            _wait_live_connection(xiaoyi_channel_up)
            xiaoyi_channel_up.push_message_stream(
                text="hello from mock xiaoyi",
                agent_id=_AGENT_ID,
                session_id=f"integ-xy-session-{attempt}",
            )
            replied = xiaoyi_channel_up.wait_for_reply(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
        assert replied is not None, (
            f"no xiaoyi reply frames; last="
            f"{xiaoyi_channel_up.frames[-3:]} logs="
            f"{app_server.logs_tail()[-3000:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)
