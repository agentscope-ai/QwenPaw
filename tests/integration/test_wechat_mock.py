# -*- coding: utf-8 -*-
"""End-to-end WeChat (iLink) channel flow against a local mock.

Seventh channel on the mock-IM strategy, hook-free: the channel's
``base_url`` config field points the ILinkClient at
``mock_wechat_ilink.MockWeChatILink``, and a preset ``bot_token``
skips QR login. Pure HTTP long polling.

Flow: start -> getupdates long poll -> inbound text msg -> agent
(mock LLM) -> sendmessage captured by the mock.

API endpoints:
  - PUT /api/config/channels/wechat
  - GET /api/config/channels/wechat
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
from mock_wechat_ilink import MockWeChatILink

_HTTP_TIMEOUT = default_http_timeout(15.0)

_MOCK_WX = MockWeChatILink()


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
def wechat_channel_up(app_server):
    """Enable the WeChat channel against the mock iLink backend."""
    _MOCK_WX.start()
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/wechat",
        json={
            "enabled": True,
            "bot_token": "integ-mock-wechat-token",
            "base_url": _MOCK_WX.base_url,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    yield _MOCK_WX
    app_server.api_request(
        "PUT",
        "/api/config/channels/wechat",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )


@pytest.mark.integration
@pytest.mark.p1
def test_wechat_channel_enabled_with_mock_base_url(
    app_server,
    # pylint: disable=redefined-outer-name,unused-argument
    wechat_channel_up,
):
    """Channel config accepts the mock iLink base_url.

    Test purpose:
      - Confirm the channel starts with a preset token (no QR login)
        against the local mock backend.

    API endpoints:
      - GET /api/config/channels/wechat
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/wechat",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body.get("enabled") is True
    assert body.get("base_url") == _MOCK_WX.base_url


@pytest.mark.integration
@pytest.mark.p0
def test_wechat_text_message_roundtrip(
    app_server,
    wechat_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A polled text message flows through the agent and back out.

    Test purpose:
      - Core loop: getupdates -> _on_message -> agent (mock LLM) ->
        send_text -> sendmessage captured by the mock.

    Test flow:
      1. Register mock LLM provider.
      2. Queue an inbound text message (retrying across reloads).
      3. Poll the mock for a sendmessage carrying the LLM reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = None
        for _ in range(4):
            wechat_channel_up.push_text_message(
                text="hello from mock wechat",
            )
            replied = wechat_channel_up.wait_for_sent_text(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
            time.sleep(1.0)
        assert replied is not None, (
            f"no wechat sendmessage captured; sent="
            f"{wechat_channel_up.sent_messages[-5:]} logs="
            f"{app_server.logs_tail()[-3000:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_wechat_group_message_uses_group_session(
    app_server,
    wechat_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A group message (group_id set) completes the loop.

    Test purpose:
      - Cover the group branch of _on_message (session key derived
        from group_id) and the group reply path.

    Test flow:
      1. Queue an inbound message carrying a group_id.
      2. Poll for a sendmessage reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = None
        for attempt in range(4):
            token = wechat_channel_up.push_group_text_message(
                text="hello wechat group",
                group_id="integ-wx-group-1",
                context_token=f"ctx-integ-group-{attempt}",
            )
            del token
            replied = wechat_channel_up.wait_for_sent_text(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
            time.sleep(1.0)
        assert replied is not None, (
            f"no wechat group reply; sent="
            f"{wechat_channel_up.sent_messages[-5:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_wechat_image_message_download_path(
    app_server,
    wechat_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """An image item drives the media download branch.

    Test purpose:
      - Cover wechat's image item parsing plus _download_media (which
        fails gracefully against the unreachable URL), then confirm
        text still round-trips.

    Test flow:
      1. Queue an image message.
      2. Queue a text message and expect the usual reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        wechat_channel_up.push_image_message()
        replied = None
        for _ in range(4):
            wechat_channel_up.push_text_message(
                text="after the wechat image",
            )
            replied = wechat_channel_up.wait_for_sent_text(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
            time.sleep(1.0)
        assert replied is not None, (
            f"channel stopped after image; sent="
            f"{wechat_channel_up.sent_messages[-3:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)
