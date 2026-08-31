# -*- coding: utf-8 -*-
"""End-to-end DingTalk channel flow against a local mock backend.

Second channel on the mock-IM strategy (after QQ). The real
``DingTalkChannel`` in the app subprocess connects its
``dingtalk_stream`` SDK to ``mock_dingtalk_im.MockDingTalkIM`` via the
channel's ``endpoint`` config field (which monkey-patches the SDK's
open-connection API), then:

  open-connection -> WS connect -> CALLBACK push (chatbot text)
  -> handler.process -> agent (mock LLM) -> reply via sessionWebhook
  -> recorded by the mock HTTP sink.

No env injection is needed: ``endpoint`` is a first-class product
config field (used for sandboxes), so plain PUT config suffices.

Coverage targets (``src/qwenpaw/app/channels/dingtalk/``):
  channel.py start/_apply_custom_endpoint/_stream_loop/
  _send_via_session_webhook/send_content_parts; handler.py process.

API endpoints:
  - PUT /api/config/channels/dingtalk
  - GET /api/config/channels/dingtalk
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
from mock_dingtalk_im import MockDingTalkIM

_HTTP_TIMEOUT = default_http_timeout(15.0)

_MOCK_IM = MockDingTalkIM()


def _push_until_reply(
    mock_im,
    *,
    text,
    sender_staff_id,
    conversation_id,
    conversation_type,
    attempts: int = 4,
):
    """Push, waiting for an LLM reply; retry on reload races.

    A zero-downtime reload can drop an in-flight message when the old
    channel instance stops mid-processing, so retry with fresh pushes
    until the mock webhook sink records the agent reply.
    """
    baseline = len(mock_im.replied_texts())
    for _ in range(attempts):
        _wait_live_connection_simple(mock_im)
        mock_im.push_chatbot_text(
            text=text,
            sender_staff_id=sender_staff_id,
            conversation_id=conversation_id,
            conversation_type=conversation_type,
        )
        # Poll for a *new* reply: matching on text alone would return
        # instantly on a stale reply from an earlier test in this file.
        deadline = time.time() + 20.0
        replied = None
        while time.time() < deadline:
            texts = mock_im.replied_texts()
            if len(texts) > baseline:
                fresh = [
                    t
                    for t in texts[baseline:]
                    if MOCK_LLM_RESPONSE.split()[0] in t
                ]
                if fresh:
                    replied = fresh[0]
                    break
            time.sleep(0.3)
        if replied is not None:
            return replied
    return None


def _wait_live_connection_simple(mock_im, timeout: float = 30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mock_im.has_connection:
            return
        time.sleep(0.2)
    raise AssertionError("no live dingtalk WS connection")


def _wait_live_connection(mock_im, app_server, timeout: float = 60.0):
    """Wait until the mock WS has a live SDK connection."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if mock_im.has_connection:
            return
        time.sleep(0.2)
    raise AssertionError(
        "no live dingtalk WS connection: " + app_server.logs_tail()[-3000:],
    )


# ================================================================== #
# fixtures
# ================================================================== #


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
def dingtalk_channel_up(app_server):
    """Enable the DingTalk channel against the mock backend."""
    _MOCK_IM.start()
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/dingtalk",
        json={
            "enabled": True,
            "client_id": "integ-mock-dt-client",
            "client_secret": "integ-mock-dt-secret",
            "endpoint": _MOCK_IM.endpoint,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    assert _MOCK_IM.wait_connected(timeout=60.0), (
        "dingtalk SDK never connected to mock WS: "
        + app_server.logs_tail()[-3000:]
    )
    yield _MOCK_IM
    app_server.api_request(
        "PUT",
        "/api/config/channels/dingtalk",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )


# ================================================================== #
# A — connection lifecycle
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_dingtalk_connects_via_custom_endpoint(
    app_server,
    # pylint: disable=redefined-outer-name,unused-argument
    dingtalk_channel_up,
):
    """DingTalk SDK opens connection through the mock endpoint.

    Test purpose:
      - Prove start() -> _apply_custom_endpoint() -> SDK
        open-connection -> WS connect all run against the mock,
        covering the real startup chain.

    API endpoints:
      - GET /api/config/channels/dingtalk
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/dingtalk",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body.get("enabled") is True
    assert body.get("endpoint") == _MOCK_IM.endpoint


# ================================================================== #
# B — inbound chatbot message -> agent -> session webhook reply
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_dingtalk_dm_roundtrip_replies_via_session_webhook(
    app_server,
    dingtalk_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A 1:1 chatbot message flows through the agent and back out.

    Test purpose:
      - Core DingTalk loop: CALLBACK frame -> handler.process ->
        build_agent_request_from_native -> agent (mock LLM) ->
        send_content_parts -> _send_via_session_webhook -> mock sink.

    Test flow:
      1. Register mock LLM provider.
      2. Push a chatbot text CALLBACK (conversationType=1, DM).
      3. Poll the mock webhook sink for the LLM reply text.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    # Provider registration triggers a zero-downtime reload which
    # restarts the channel; wait for the fresh WS connection before
    # pushing, or the message lands on the dying instance.
    dingtalk_channel_up.reset_connected()
    provider_id = register_mock_provider(app_server, mock_url)
    # A provider change may or may not trigger a channel reload; wait
    # until a live WS connection exists (fresh or surviving one).
    _wait_live_connection(dingtalk_channel_up, app_server)
    try:
        replied = _push_until_reply(
            dingtalk_channel_up,
            text="hello from mock dingtalk dm",
            sender_staff_id="integ-dt-user-dm",
            conversation_id="cid-integ-dt-dm",
            conversation_type="1",
        )
        assert replied is not None, (
            f"no webhook reply captured; posts="
            f"{dingtalk_channel_up.webhook_posts[-5:]} logs="
            f"{app_server.logs_tail()[-3000:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_dingtalk_health_reports_channel(
    app_server,
    # pylint: disable=redefined-outer-name,unused-argument
    dingtalk_channel_up,
):
    """Health endpoint covers a live (mock-connected) DingTalk channel.

    Test purpose:
      - Exercise health_check on a running channel instead of the
        usual disabled/not-configured branch.

    API endpoints:
      - GET /api/config/channels/dingtalk/health
    """
    # Retry loop: the fixture waits for WS connection, but channel
    # registration in channel_manager may lag slightly behind.
    deadline = time.time() + 30.0
    resp = None
    while time.time() < deadline:
        resp = app_server.api_request(
            "GET",
            "/api/config/channels/dingtalk/health",
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code == 200:
            break
        time.sleep(0.5)
    assert resp is not None, "health request timed out"
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body.get("channel") == "dingtalk", body
    assert body.get("status") == "healthy", body


@pytest.mark.integration
@pytest.mark.p1
def test_dingtalk_rich_text_message_roundtrip(
    app_server,
    dingtalk_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A richText message is parsed and completes the loop.

    Test purpose:
      - Cover handler._parse_rich_content (richText segment walk) in
        addition to the plain-text path, then the shared reply chain.

    Test flow:
      1. Push a richText CALLBACK with two text segments.
      2. Poll the mock webhook sink for the LLM reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    dingtalk_channel_up.reset_connected()
    provider_id = register_mock_provider(app_server, mock_url)
    _wait_live_connection(dingtalk_channel_up, app_server)
    try:
        replied = None
        for _ in range(4):
            _wait_live_connection_simple(dingtalk_channel_up)
            dingtalk_channel_up.push_chatbot_rich_text(
                segments=[
                    {"text": "rich hello"},
                    {"text": "second segment"},
                ],
                sender_staff_id="integ-dt-user-rich",
            )
            replied = dingtalk_channel_up.wait_for_reply(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
        assert replied is not None, (
            f"no richText reply; posts="
            f"{dingtalk_channel_up.webhook_posts[-5:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_dingtalk_long_reply_uses_plain_text_payload(
    app_server,
    dingtalk_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """Replies over 3500 chars are sent as msgtype=text, not markdown.

    Test purpose:
      - Cover the length branch in _send_via_session_webhook: texts
        above 3500 chars skip markdown normalization and go out as a
        plain text payload.

    Test flow:
      1. Make the mock LLM reply with >3500 characters.
      2. Push a DM; find the captured webhook post and assert
         msgtype == "text".
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    marker = "DTLONGREPLY"
    srv.response_text = marker + ("y" * 4000)
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    dingtalk_channel_up.reset_connected()
    provider_id = register_mock_provider(app_server, mock_url)
    _wait_live_connection(dingtalk_channel_up, app_server)
    try:
        before = len(dingtalk_channel_up.webhook_posts)
        captured = None
        for _ in range(4):
            _wait_live_connection_simple(dingtalk_channel_up)
            dingtalk_channel_up.push_chatbot_text(
                text="please answer at length",
                sender_staff_id="integ-dt-user-long",
                conversation_id="cid-integ-dt-long",
                conversation_type="1",
            )
            deadline = time.time() + 25.0
            while time.time() < deadline and captured is None:
                for post in dingtalk_channel_up.webhook_posts[before:]:
                    body = post.get("body") or {}
                    text = (body.get("text") or {}).get("content", "")
                    if marker in text:
                        captured = body
                        break
                time.sleep(0.2)
            if captured is not None:
                break
        assert captured is not None, (
            f"no long-reply webhook post; posts="
            f"{dingtalk_channel_up.webhook_posts[before:][-3:]}"
        )
        assert captured.get("msgtype") == "text", captured
    finally:
        srv.response_text = None
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_dingtalk_picture_message_download_attempt(
    app_server,
    dingtalk_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A richText picture item drives the media download path.

    Test purpose:
      - Cover handler.py's downloadCode resolution branch: the channel
        attempts an OpenAPI media download (which the mock does not
        serve) and still completes the turn, replying to the caption.

    Test flow:
      1. Push a richText CALLBACK with a picture downloadCode plus a
         caption.
      2. Assert the channel keeps working (a following text message
         still gets a reply).
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    dingtalk_channel_up.reset_connected()
    provider_id = register_mock_provider(app_server, mock_url)
    _wait_live_connection(dingtalk_channel_up, app_server)
    try:
        _wait_live_connection_simple(dingtalk_channel_up)
        dingtalk_channel_up.push_chatbot_picture(
            caption="look at this picture",
            sender_staff_id="integ-dt-user-pic",
        )
        replied = _push_until_reply(
            dingtalk_channel_up,
            text="and now a normal message",
            sender_staff_id="integ-dt-user-pic",
            conversation_id="cid-integ-dt-pic",
            conversation_type="1",
            attempts=10,
        )
        assert replied is not None, (
            f"channel stopped replying after picture; posts="
            f"{dingtalk_channel_up.webhook_posts[-3:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_dingtalk_group_at_message(
    app_server,
    dingtalk_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A group message mentioning the bot completes the loop.

    Test purpose:
      - Cover the group conversation branch of handler.process
        (conversationType=2 with isInAtList) plus the group reply path
        with @-mention payload.

    Test flow:
      1. Push a group chatbot text CALLBACK (bot @-ed).
      2. Poll the webhook sink for the LLM reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    dingtalk_channel_up.reset_connected()
    provider_id = register_mock_provider(app_server, mock_url)
    _wait_live_connection(dingtalk_channel_up, app_server)
    try:
        replied = _push_until_reply(
            dingtalk_channel_up,
            text="hello dingtalk group",
            sender_staff_id="integ-dt-user-grp2",
            conversation_id="cid-integ-dt-grp2",
            conversation_type="2",
            attempts=10,
        )
        assert (
            replied is not None
        ), f"no group reply; posts={dingtalk_channel_up.webhook_posts[-3:]}"
    finally:
        unregister_mock_provider(app_server, provider_id)
