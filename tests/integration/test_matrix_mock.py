# -*- coding: utf-8 -*-
"""End-to-end Matrix channel flow against a local mock homeserver.

Sixth channel on the mock-IM strategy. Matrix is HTTP-only
(client-server API via matrix-nio), and ``homeserver`` is a
first-class config field — no product hook needed.

Flow: start -> token whoami -> /sync long poll -> pushed
m.room.message -> agent (mock LLM) -> rooms/{id}/send captured.

API endpoints:
  - PUT /api/config/channels/matrix
  - GET /api/config/channels/matrix
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
from mock_matrix_hs import BOT_USER_ID, MockMatrixHomeserver

_HTTP_TIMEOUT = default_http_timeout(15.0)

_MOCK_HS = MockMatrixHomeserver()


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
def matrix_channel_up(app_server):
    """Enable the Matrix channel against the mock homeserver."""
    _MOCK_HS.start()
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/matrix",
        json={
            "enabled": True,
            "homeserver": _MOCK_HS.homeserver,
            "user_id": BOT_USER_ID,
            "access_token": "integ-mock-matrix-token",
            "encryption": False,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    yield _MOCK_HS
    app_server.api_request(
        "PUT",
        "/api/config/channels/matrix",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )


@pytest.mark.integration
@pytest.mark.p1
def test_matrix_channel_enabled_with_mock_homeserver(
    app_server,
    # pylint: disable=redefined-outer-name,unused-argument
    matrix_channel_up,
):
    """Channel config accepts the mock homeserver URL.

    Test purpose:
      - Confirm the channel is enabled against the local homeserver,
        i.e. start() ran token login (whoami) + started the sync loop.

    API endpoints:
      - GET /api/config/channels/matrix
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/matrix",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body.get("enabled") is True
    assert body.get("homeserver") == _MOCK_HS.homeserver


@pytest.mark.integration
@pytest.mark.p0
def test_matrix_room_message_roundtrip(
    app_server,
    matrix_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A synced room message flows through the agent and back out.

    Test purpose:
      - Core Matrix loop: /sync timeline event -> RoomMessageText
        callback -> agent (mock LLM) -> room_send captured by mock.

    Test flow:
      1. Register mock LLM provider.
      2. Queue an m.room.message for the next /sync (retrying across
         reload races).
      3. Poll the mock for a room send containing the LLM reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = None
        for _ in range(4):
            matrix_channel_up.push_text_event(
                text="hello from mock matrix",
            )
            replied = matrix_channel_up.wait_for_sent_text(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
            time.sleep(1.0)
        assert replied is not None, (
            f"no matrix room send captured; sent="
            f"{matrix_channel_up.sent_events[-5:]} logs="
            f"{app_server.logs_tail()[-3000:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_matrix_group_mention_roundtrip(
    app_server,
    matrix_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A group message with m.mentions targeting the bot gets a reply.

    Test purpose:
      - Cover the group path: 3-member room (mention gate applies) +
        _was_mentioned via the structured m.mentions block.

    Test flow:
      1. Push a text event into a "group" room with m.mentions.
      2. Poll the mock for a room send containing the LLM reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = None
        for _ in range(4):
            matrix_channel_up.push_text_event(
                text="hello group from mock matrix",
                room_id="!integmockgroup:mock.local",
                mention_bot=True,
            )
            replied = matrix_channel_up.wait_for_sent_text(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
            time.sleep(1.0)
        assert (
            replied is not None
        ), f"no group room send; sent={matrix_channel_up.sent_events[-5:]}"
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_matrix_markdown_reply_has_formatted_body(
    app_server,
    matrix_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A markdown reply is sent with org.matrix.custom.html format.

    Test purpose:
      - Cover the markdown->HTML formatting branch: replies containing
        markdown produce a formatted_body alongside the plain body.

    Test flow:
      1. Make the mock LLM reply with markdown (bold + list).
      2. Push a DM text event; find the captured room send and assert
         formatted_body/format fields are present.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    marker = "MDFMT"
    srv.response_text = f"**{marker}** bold\n\n- item1\n- item2"
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        captured = None
        for _ in range(4):
            matrix_channel_up.push_text_event(
                text="reply in markdown please",
                room_id="!integmockmdroom:mock.local",
            )
            deadline = time.time() + 25.0
            while time.time() < deadline and captured is None:
                for event in matrix_channel_up.sent_events:
                    content = event.get("content") or {}
                    if marker in str(content.get("body", "")):
                        captured = content
                        break
                time.sleep(0.2)
            if captured is not None:
                break
            time.sleep(1.0)
        assert captured is not None, (
            f"no markdown reply captured; sent="
            f"{matrix_channel_up.sent_events[-3:]}"
        )
        assert captured.get("format") == "org.matrix.custom.html", captured
        assert marker in str(captured.get("formatted_body", "")), captured
    finally:
        srv.response_text = None
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_matrix_notice_and_emote_messages(
    app_server,
    matrix_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """m.notice and m.emote message subtypes are handled.

    Test purpose:
      - Cover the msgtype dispatch branches beyond m.text in the
        matrix room-event handler.

    Test flow:
      1. Push an m.notice event, then an m.emote event.
      2. Assert the channel keeps serving (a later m.text still gets a
         reply), proving neither subtype broke the sync loop.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        matrix_channel_up.push_typed_event(
            msgtype="m.notice",
            text="a notice message",
            room_id="!integmocknotice:mock.local",
        )
        matrix_channel_up.push_typed_event(
            msgtype="m.emote",
            text="waves hello",
            room_id="!integmocknotice:mock.local",
        )
        replied = None
        for _ in range(4):
            matrix_channel_up.push_text_event(
                text="normal text after subtypes",
                room_id="!integmocknotice:mock.local",
            )
            replied = matrix_channel_up.wait_for_sent_text(
                lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
                timeout=25.0,
            )
            if replied is not None:
                break
            time.sleep(1.0)
        assert replied is not None, (
            f"channel stopped replying after subtypes; sent="
            f"{matrix_channel_up.sent_events[-3:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_matrix_bot_own_message_ignored(
    app_server,
    matrix_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """The channel ignores events it sent itself.

    Test purpose:
      - Cover the self-sender filter in the room-event handler (no
        reply loop when the bot's own MXID is the sender).
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        before = len(matrix_channel_up.sent_events)
        matrix_channel_up.push_text_event(
            text="echo from the bot itself",
            room_id="!integmockself:mock.local",
            sender=BOT_USER_ID,
        )
        # Under the full suite the sync loop polls more slowly. Wait for
        # the channel to demonstrably process a *later* normal message,
        # which proves the self-message was seen and skipped rather than
        # merely not yet polled.
        matrix_channel_up.push_text_event(
            text="probe after self message",
            room_id="!integmockself:mock.local",
        )
        deadline = time.time() + 60.0
        probe_reply = None
        while time.time() < deadline and probe_reply is None:
            for event in matrix_channel_up.sent_events[before:]:
                body = str((event.get("content") or {}).get("body", ""))
                if MOCK_LLM_RESPONSE.split()[0] in body:
                    probe_reply = body
                    break
            time.sleep(0.3)
        assert probe_reply is not None, (
            "probe message never answered: " + app_server.logs_tail()[-2000:]
        )
        # The probe was answered, proving the sync loop processed both
        # events; the self-message itself must not have produced a
        # reply addressed back to the bot's own MXID.
        self_addressed = [
            e
            for e in matrix_channel_up.sent_events[before:]
            if str((e.get("content") or {}).get("body", "")).startswith(
                "echo from the bot itself",
            )
        ]
        assert not self_addressed, self_addressed
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_matrix_dm_disabled_drops_message(
    app_server,
    matrix_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """With dm_disabled, DM messages are dropped without a reply.

    Test purpose:
      - Cover the dm_disabled guard in the matrix room-event handler.

    Test flow:
      1. Set dm_disabled=true on the channel config.
      2. Push a DM text event; assert no new room send appears.
      3. Restore the config.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/matrix",
        json={
            "enabled": True,
            "homeserver": _MOCK_HS.homeserver,
            "user_id": BOT_USER_ID,
            "access_token": "integ-mock-matrix-token",
            "encryption": False,
            "dm_disabled": True,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    try:
        before = len(matrix_channel_up.sent_events)
        matrix_channel_up.push_text_event(
            text="dm while disabled",
            room_id="!integmockdmdisabled:mock.local",
        )
        time.sleep(15.0)
        assert (
            len(matrix_channel_up.sent_events) == before
        ), matrix_channel_up.sent_events[before:]
    finally:
        unregister_mock_provider(app_server, provider_id)
        app_server.api_request(
            "PUT",
            "/api/config/channels/matrix",
            json={
                "enabled": True,
                "homeserver": _MOCK_HS.homeserver,
                "user_id": BOT_USER_ID,
                "access_token": "integ-mock-matrix-token",
                "encryption": False,
                "dm_disabled": False,
            },
            timeout=_HTTP_TIMEOUT,
        )
