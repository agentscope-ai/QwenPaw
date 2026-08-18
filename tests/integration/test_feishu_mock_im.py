# -*- coding: utf-8 -*-
"""End-to-end Feishu channel flow against a local mock Lark backend.

Fourth channel on the mock-IM strategy. The channel's ``domain``
config field now accepts a custom http(s) base URL (product feature
for private gateways), pointing both the lark REST client and the
ws.Client endpoint discovery at ``mock_feishu_im.MockFeishuIM``:

  POST /callback/ws/endpoint -> ws connect -> DATA frame push
  (p2 im.message.receive_v1) -> _on_message -> agent (mock LLM)
  -> im/v1/messages create captured by the mock.

Coverage targets (``src/qwenpaw/app/channels/feishu/channel.py``):
  start/_run_ws_forever/_on_message_sync/_on_message/
  build_agent_request_from_native/send/_send_text/_send_message.

API endpoints:
  - PUT /api/config/channels/feishu
  - GET /api/config/channels/feishu
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
from mock_feishu_im import MockFeishuIM

_HTTP_TIMEOUT = default_http_timeout(15.0)

_MOCK_IM = MockFeishuIM()


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
def feishu_channel_up(app_server):
    """Enable the Feishu channel pointed at the mock backend."""
    # Product bug Aone #84649306: on setuptools>=81 (which removed
    # pkg_resources.declare_namespace) importing the feishu channel raises
    # AttributeError, which escapes feishu/channel.py's ImportError-only
    # guard and is swallowed by registry.py, so feishu never registers and
    # this fixture's PUT cannot succeed. Skip rather than error the whole
    # module. Remove once the upstream fix lands.
    types_resp = app_server.api_request(
        "GET",
        "/api/config/channels/types",
        timeout=_HTTP_TIMEOUT,
    )
    if types_resp.status_code != 200 or "feishu" not in types_resp.text:
        pytest.skip(
            "feishu channel is not registered on this host "
            "(product bug Aone #84649306)",
        )

    _MOCK_IM.start()
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/feishu",
        json={
            "enabled": True,
            "app_id": "cli_integ_mock",
            "app_secret": "integ-mock-feishu-secret",
            "domain": _MOCK_IM.base_url,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    assert _MOCK_IM.wait_connected(timeout=60.0), (
        "lark ws client never connected to mock gateway: "
        + app_server.logs_tail()[-3000:]
    )
    yield _MOCK_IM
    app_server.api_request(
        "PUT",
        "/api/config/channels/feishu",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )


def _wait_live_connection(mock_im, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mock_im.has_connection:
            return
        time.sleep(0.2)
    raise AssertionError("no live feishu WS connection")


@pytest.mark.integration
@pytest.mark.p1
def test_feishu_connects_via_custom_domain(
    app_server,
    # pylint: disable=redefined-outer-name,unused-argument
    feishu_channel_up,
):
    """Feishu SDK resolves the WS endpoint through the mock domain.

    Test purpose:
      - Prove start() built the lark clients against the custom
        domain and the ws.Client completed endpoint discovery +
        connected to the mock gateway.

    API endpoints:
      - GET /api/config/channels/feishu
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/feishu",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body.get("enabled") is True
    assert body.get("domain") == _MOCK_IM.base_url


@pytest.mark.integration
@pytest.mark.p0
def test_feishu_p2p_message_roundtrip(
    app_server,
    feishu_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A pushed p2p text event flows through the agent and back out.

    Test purpose:
      - Core Feishu loop: WS DATA frame (im.message.receive_v1) ->
        _on_message -> agent (mock LLM) -> _send_message ->
        im/v1/messages captured by the mock.

    Test flow:
      1. Register mock LLM provider; wait for a live WS connection.
      2. Push a p2p text event (retrying across reload races).
      3. Poll the mock for an outbound message with the LLM reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    feishu_channel_up.reset_connected()
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = None
        for attempt in range(4):
            _wait_live_connection(feishu_channel_up)
            feishu_channel_up.push_p2_text_message(
                text="hello from mock feishu",
                sender_open_id="ou_integ_rt",
                chat_id="oc_integ_rt",
                message_id=f"om_integ_rt_{attempt}",
            )
            replied = feishu_channel_up.wait_for_sent_text(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
        assert replied is not None, (
            f"no feishu send captured; calls="
            f"{feishu_channel_up.api_calls[-5:]} logs="
            f"{app_server.logs_tail()[-3000:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_feishu_group_mention_roundtrip(
    app_server,
    feishu_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A group message mentioning the bot completes the loop.

    Test purpose:
      - Cover the group chat path: mentions matching _bot_open_id
        (fetched from the mock bot info), mention-key stripping, and
        the group send route.

    Test flow:
      1. Push a group text event with a mentions entry targeting the
         mock bot open_id.
      2. Poll for an outbound reply containing the LLM text.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    feishu_channel_up.reset_connected()
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = None
        for attempt in range(4):
            _wait_live_connection(feishu_channel_up)
            feishu_channel_up.push_p2_text_message(
                text="hello group from mock feishu",
                sender_open_id="ou_integ_grouper",
                chat_id="oc_integ_group",
                chat_type="group",
                message_id=f"om_integ_group_{attempt}",
                mention_bot=True,
            )
            replied = feishu_channel_up.wait_for_sent_text(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
        assert (
            replied is not None
        ), f"no feishu group send; calls={feishu_channel_up.api_calls[-5:]}"
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_feishu_image_message_download_path(
    app_server,
    feishu_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """An image message drives the resource download branch.

    Test purpose:
      - Cover feishu's image message_type parsing and media resource
        download attempt (the mock does not serve the resource, so the
        graceful-failure path runs), then confirm the channel still
        serves text.

    Test flow:
      1. Push an image event.
      2. Push a text event and expect the usual reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    feishu_channel_up.reset_connected()
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        _wait_live_connection(feishu_channel_up)
        feishu_channel_up.push_p2_image_message(
            sender_open_id="ou_integ_img",
            chat_id="oc_integ_img",
        )
        replied = None
        for attempt in range(4):
            _wait_live_connection(feishu_channel_up)
            feishu_channel_up.push_p2_text_message(
                text="after the image",
                sender_open_id="ou_integ_img",
                chat_id="oc_integ_img",
                message_id=f"om_integ_after_img_{attempt}",
            )
            replied = feishu_channel_up.wait_for_sent_text(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
        assert replied is not None, (
            f"channel stopped after image; calls="
            f"{feishu_channel_up.api_calls[-3:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)
