# -*- coding: utf-8 -*-
"""End-to-end WeCom AI Bot channel flow against a local TLS mock.

Eleventh channel on the mock-IM strategy, TLS edition: the aibot SDK
hardwires a certifi-based SSL context, so the mock serves wss with a
runtime-generated CA whose trust is injected into the app subprocess
via APP_SERVER_EXTRA_ENV (PYTHONPATH sitecustomize patches
certifi.where to a bundle containing the mock CA). Uses the wecom
``ws_url`` product hook.

Flow: subscribe (auth) -> pushed aibot_msg_callback text -> agent
(mock LLM) -> stream/respond frames captured by the mock.

API endpoints:
  - PUT /api/config/channels/wecom
  - GET /api/config/channels/wecom
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
from mock_wecom_gateway import MockWeComGateway

_HTTP_TIMEOUT = default_http_timeout(15.0)

_MOCK_WC = MockWeComGateway()


def APP_SERVER_EXTRA_ENV() -> dict:  # noqa: N802 - conftest contract
    """Inject mock-CA trust into the app subprocess."""
    _MOCK_WC.start()
    return {
        "PYTHONPATH": _MOCK_WC.pysite_dir,
        "INTEG_CA_BUNDLE": _MOCK_WC.ca_bundle,
    }


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
def wecom_channel_up(app_server):
    """Enable the WeCom channel against the TLS mock gateway."""
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/wecom",
        json={
            "enabled": True,
            "bot_id": "integ-mock-wecom-bot",
            "secret": "integ-mock-wecom-secret",
            "ws_url": _MOCK_WC.ws_url,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    assert _MOCK_WC.wait_subscribed(timeout=60.0), (
        "wecom never subscribed against mock gateway: "
        + app_server.logs_tail()[-3000:]
    )
    yield _MOCK_WC
    app_server.api_request(
        "PUT",
        "/api/config/channels/wecom",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )


def _wait_live_connection(mock_wc, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mock_wc.has_connection:
            return
        time.sleep(0.2)
    raise AssertionError("no live wecom WS connection")


@pytest.mark.integration
@pytest.mark.p1
def test_wecom_subscribes_over_tls(
    app_server,
    # pylint: disable=redefined-outer-name,unused-argument
    wecom_channel_up,
):
    """The aibot SDK completes wss + subscribe against the mock.

    Test purpose:
      - Prove the TLS trust injection works end-to-end: the SDK's
        certifi context accepted the mock CA and the auth subscribe
        round-tripped.

    API endpoints:
      - GET /api/config/channels/wecom
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/wecom",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body.get("enabled") is True


@pytest.mark.integration
@pytest.mark.p0
def test_wecom_text_message_roundtrip(
    app_server,
    wecom_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A pushed text callback flows through the agent and back out.

    Test purpose:
      - Core WeCom loop: aibot_msg_callback -> _on_message -> agent
        (mock LLM) -> stream/respond frames captured by the mock.

    Test flow:
      1. Register mock LLM; wait for a live WS connection.
      2. Push a single-chat text callback (retrying across reloads).
      3. Poll recorded frames for the LLM reply text.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    wecom_channel_up.reset_subscribed()
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = None
        for attempt in range(4):
            _wait_live_connection(wecom_channel_up)
            wecom_channel_up.push_text_message(
                text="hello from mock wecom",
                userid=f"integ-wecom-user-{attempt}",
                chatid=f"integ-wecom-chat-{attempt}",
            )
            replied = wecom_channel_up.wait_for_reply(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
        assert replied is not None, (
            f"no wecom reply frames; last={wecom_channel_up.frames[-3:]} "
            f"logs={app_server.logs_tail()[-3000:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_wecom_group_chat_message(
    app_server,
    wecom_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A group-chat callback completes the loop.

    Test purpose:
      - Cover the group branch of wecom's _on_message (chattype
        "group", @mention stripping for slash commands) plus the
        shared reply path.

    Test flow:
      1. Push a group text callback.
      2. Poll recorded frames for the LLM reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    wecom_channel_up.reset_subscribed()
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = None
        for attempt in range(4):
            _wait_live_connection(wecom_channel_up)
            wecom_channel_up.push_text_message(
                text="hello wecom group",
                userid=f"integ-wecom-grouper-{attempt}",
                chatid=f"integ-wecom-groupchat-{attempt}",
                chat_type="group",
            )
            replied = wecom_channel_up.wait_for_reply(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
        assert (
            replied is not None
        ), f"no wecom group reply; frames={wecom_channel_up.frames[-3:]}"
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_wecom_image_message_download_path(
    app_server,
    wecom_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """An image callback drives the media download branch.

    Test purpose:
      - Cover wecom's image msgtype parsing plus the media download
        attempt (graceful failure against the mock), then confirm text
        still round-trips.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        _wait_live_connection(wecom_channel_up)
        wecom_channel_up.push_image_message(
            userid="integ-wecom-imager",
            chatid="integ-wecom-imgchat",
        )
        replied = None
        for attempt in range(4):
            _wait_live_connection(wecom_channel_up)
            wecom_channel_up.push_text_message(
                text="after the wecom image",
                userid="integ-wecom-imager",
                chatid="integ-wecom-imgchat",
                msgid=f"integ-wecom-after-img-{attempt}",
            )
            replied = wecom_channel_up.wait_for_reply(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
        assert replied is not None, (
            f"channel stopped after image; frames="
            f"{wecom_channel_up.frames[-3:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_wecom_enter_chat_sends_welcome(
    app_server,
    wecom_channel_up,  # pylint: disable=redefined-outer-name
):
    """An enter_chat event triggers the configured welcome reply.

    Test purpose:
      - Cover wecom's _on_enter_chat path: with welcome_text set, the
        channel answers the event via reply_welcome.

    Test flow:
      1. Configure welcome_text; wait for reconnect.
      2. Push an event.enter_chat frame.
      3. Poll recorded frames for the welcome text, then restore.
    """
    welcome = "INTEG_WELCOME_TEXT"
    wecom_channel_up.reset_subscribed()
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/wecom",
        json={
            "enabled": True,
            "bot_id": "integ-mock-wecom-bot",
            "secret": "integ-mock-wecom-secret",
            "ws_url": _MOCK_WC.ws_url,
            "welcome_text": welcome,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    assert wecom_channel_up.wait_subscribed(
        timeout=60.0,
    ), app_server.logs_tail()[-2000:]
    try:
        replied = None
        for _ in range(4):
            _wait_live_connection(wecom_channel_up)
            wecom_channel_up.push_enter_chat(userid="integ-wecom-entrant")
            replied = wecom_channel_up.wait_for_reply(
                lambda t: welcome in t,
                timeout=20.0,
            )
            if replied is not None:
                break
        assert (
            replied is not None
        ), f"no welcome reply; frames={wecom_channel_up.frames[-3:]}"
    finally:
        wecom_channel_up.reset_subscribed()
        app_server.api_request(
            "PUT",
            "/api/config/channels/wecom",
            json={
                "enabled": True,
                "bot_id": "integ-mock-wecom-bot",
                "secret": "integ-mock-wecom-secret",
                "ws_url": _MOCK_WC.ws_url,
                "welcome_text": "",
            },
            timeout=_HTTP_TIMEOUT,
        )
        wecom_channel_up.wait_subscribed(timeout=60.0)
