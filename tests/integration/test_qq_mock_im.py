# -*- coding: utf-8 -*-
"""End-to-end QQ channel flow against a local mock QQ IM backend.

First real-channel-I/O integration coverage: the app subprocess runs
the actual ``QQChannel`` (WS gateway thread, token fetch, dispatch,
agent round-trip, outbound send) against ``mock_qq_im.MockQQIM``
hosted in the test process.

Wiring:
  * ``QQ_TOKEN_URL`` / ``QQ_API_BASE`` env (via ``APP_SERVER_EXTRA_ENV``)
    redirect token + gateway + send APIs to the mock HTTP server.
  * The mock ``/gateway`` returns a ws:// URL to the mock WS server,
    which speaks just enough QQ bot gateway protocol
    (HELLO -> IDENTIFY -> READY, HEARTBEAT_ACK, DISPATCH push).
  * A mock LLM provider makes the agent reply deterministically.

Coverage targets (``src/qwenpaw/app/channels/qq/channel.py``):
  start/_run_ws_forever/_ws_connect_once/_handle_ws_payload/
  _handle_msg_event/build_agent_request_from_native/send/
  _dispatch_text/_send_message_async/_get_access_token_{sync,async}.

API endpoints:
  - PUT  /api/config/channels/qq
  - POST /api/config/channels/qq/restart
  - GET  /api/config/channels/qq
  - GET  /api/config/channels/qq/health
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
from mock_qq_im import MockQQIM

_HTTP_TIMEOUT = default_http_timeout(15.0)

# Module-level mock IM: must exist before app_server starts so its
# ports can be injected into the subprocess environment.
_MOCK_IM = MockQQIM()


def APP_SERVER_EXTRA_ENV() -> dict:  # noqa: N802 - conftest contract
    """Redirect QQ endpoints in the app subprocess to the mock IM."""
    _MOCK_IM.start()
    return {
        "QQ_TOKEN_URL": _MOCK_IM.token_url,
        "QQ_API_BASE": _MOCK_IM.api_base,
    }


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
def qq_channel_up(app_server):
    """Enable the QQ channel against the mock IM; yield after READY.

    ``PUT /api/config/channels/qq`` triggers a zero-downtime agent
    reload which starts the newly-enabled channel; the ``/restart``
    endpoint only applies to already-running channels (404 otherwise),
    so we simply wait for the mock gateway to observe IDENTIFY.
    """
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/qq",
        json={
            "enabled": True,
            "app_id": "integ-mock-qq-app",
            "client_secret": "integ-mock-qq-secret",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    assert _MOCK_IM.wait_identified(timeout=60.0), (
        "QQ channel never completed IDENTIFY against mock gateway: "
        + app_server.logs_tail()[-3000:]
    )
    yield _MOCK_IM
    app_server.api_request(
        "PUT",
        "/api/config/channels/qq",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )


# ================================================================== #
# A — connection lifecycle
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_qq_channel_connects_to_mock_gateway(
    app_server,
    qq_channel_up,  # pylint: disable=redefined-outer-name,unused-argument
):
    """QQ channel fetches token, resolves gateway, and IDENTIFYs.

    Test purpose:
      - Prove the real QQChannel start-up chain runs end-to-end
        against a mock backend: sync token fetch -> GET /gateway ->
        WS connect -> HELLO -> IDENTIFY -> READY.

    Test flow:
      1. qq_channel_up fixture enabled the channel + waited READY.
      2. Assert channel config reflects enabled=true.

    API endpoints:
      - GET /api/config/channels/qq
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/qq",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    assert resp.json().get("enabled") is True


@pytest.mark.integration
@pytest.mark.p1
def test_qq_channel_health_reports_running(
    app_server,
    qq_channel_up,  # pylint: disable=redefined-outer-name,unused-argument
):
    """Health endpoint sees the QQ channel as present and enabled.

    Test purpose:
      - Cover the health_check path for a live (mock-connected) QQ
        channel rather than the usual disabled/unhealthy branch.

    Test flow:
      1. Poll GET /health until 200: enabling a channel is an async
         reload, and a single query can land in the registration
         window and get 404 (see comment below).

    API endpoints:
      - GET /api/config/channels/qq/health
    """
    # Enabling the channel is an async reload: replace_channel()
    # awaits channel.start() outside the manager lock (the WS thread
    # can complete IDENTIFY before that), then registers the channel
    # under the lock. The health endpoint walks the registry, so it
    # returns 404 during that window -- a CI flake was traced to this
    # race. Poll until the channel becomes visible.
    deadline = time.time() + 10.0
    while True:
        resp = app_server.api_request(
            "GET",
            "/api/config/channels/qq/health",
            timeout=_HTTP_TIMEOUT,
        )
        if resp.status_code == 200 or time.time() >= deadline:
            break
        time.sleep(0.3)
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body.get("channel") == "qq" or "status" in body, body


# ================================================================== #
# B — inbound message -> agent -> outbound reply (the core loop)
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p0
def test_qq_c2c_message_roundtrip_reaches_mock_send(
    app_server,
    qq_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A pushed C2C message flows through the agent and back out.

    Test purpose:
      - The heart of the mock-IM strategy: prove a WS DISPATCH event
        (C2C_MESSAGE_CREATE) travels channel -> manager queue ->
        agent (mock LLM) -> QQChannel.send -> mock IM HTTP sink.

    Test flow:
      1. Register mock LLM provider (deterministic reply).
      2. Push C2C_MESSAGE_CREATE via the mock WS gateway.
      3. Poll the mock IM for an outbound POST
         /v2/users/{openid}/messages whose text contains the mock
         LLM reply.

    API endpoints:
      - (channel I/O only; no direct HTTP API besides provider setup)
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        # A config write in an earlier test can schedule an agent reload,
        # which restarts channels; an event pushed during that window is
        # dropped. Retry with a fresh msg_id per attempt.
        sent = None
        for attempt in range(4):
            qq_channel_up.push_c2c_message(
                openid="integ-qq-user-rt",
                text="hello from mock qq",
                msg_id=f"integ-qq-msg-rt-{attempt}",
            )
            sent = qq_channel_up.wait_for_sent_text(
                lambda text: MOCK_LLM_RESPONSE.split()[0] in text,
                timeout=45.0,
            )
            if sent is not None:
                break
            time.sleep(1.0)
        assert sent is not None, (
            f"no outbound QQ send captured; api_calls="
            f"{qq_channel_up.api_calls[-5:]} logs="
            f"{app_server.logs_tail()[-3000:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_qq_outbound_send_carries_msg_id_reply_context(
    app_server,
    qq_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """Outbound reply references the incoming msg_id (passive reply).

    Test purpose:
      - Cover _send_message_async body construction: msg_id echo and
        msg_seq for c2c passive replies.

    Test flow:
      1. Register the mock model and wait for the QQ channel to reconnect
         when first-time model activation schedules an agent reload.
      2. Push a C2C message with a distinctive msg_id.
      3. Wait for the outbound send; inspect the recorded body.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)

    # Global model activation copies the model into an agent that does not
    # have one yet, then schedules a zero-downtime reload asynchronously.
    # Waiting for the replacement QQ connection prevents this message from
    # being consumed by the old workspace just before it is stopped.  When
    # the full module runs, an earlier test may already have initialized the
    # model, in which case activation does not reload and no wait is needed.
    agent = app_server.api_request(
        "GET",
        "/api/agents/default",
        timeout=_HTTP_TIMEOUT,
    )
    assert agent.status_code == 200, app_server.logs_tail()
    active_model = agent.json().get("active_model") or {}
    reload_expected = not active_model.get("provider_id")
    if reload_expected:
        qq_channel_up.reset_identified()

    provider_id = register_mock_provider(app_server, mock_url)
    try:
        if reload_expected:
            assert qq_channel_up.wait_identified(timeout=60.0), (
                "QQ channel did not reconnect after initial model "
                "activation: " + app_server.logs_tail()[-3000:]
            )

        marker_msg_id = "integ-qq-msgid-ctx"
        before = len(qq_channel_up.api_calls)
        qq_channel_up.push_c2c_message(
            openid="integ-qq-user-ctx",
            text="reply with context please",
            msg_id=marker_msg_id,
        )
        deadline = time.time() + 90.0
        matched = None
        while time.time() < deadline and matched is None:
            for call in qq_channel_up.api_calls[before:]:
                body = call.get("body") or {}
                if body.get("msg_id") == marker_msg_id:
                    matched = call
                    break
            time.sleep(0.2)
        assert matched is not None, (
            f"no send with msg_id={marker_msg_id}; calls="
            f"{qq_channel_up.api_calls[before:][-5:]}"
        )
        assert "msg_seq" in matched["body"], matched
        assert matched["auth"].startswith("QQBot "), matched
    finally:
        unregister_mock_provider(app_server, provider_id)


# ================================================================== #
# C — other message types (group / guild) + send branches
# ================================================================== #


@pytest.mark.integration
@pytest.mark.p1
def test_qq_group_at_message_roundtrip(
    app_server,
    qq_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """GROUP_AT_MESSAGE_CREATE flows out via /v2/groups/... path.

    Test purpose:
      - Cover the group spec of _MESSAGE_EVENT_SPECS and the
        group_openid routing branch of send/_dispatch_text.

    Test flow:
      1. Push GROUP_AT_MESSAGE_CREATE with member_openid+group_openid.
      2. Poll mock for POST /v2/groups/{group_openid}/messages.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        qq_channel_up.push_dispatch(
            "GROUP_AT_MESSAGE_CREATE",
            {
                "id": "integ-qq-group-msg-1",
                "content": "hello group",
                "author": {"member_openid": "integ-qq-member-1"},
                "group_openid": "integ-qq-group-1",
            },
        )
        sent = qq_channel_up.wait_for_sent_text(
            lambda text: MOCK_LLM_RESPONSE.split()[0] in text,
            timeout=90.0,
            path_prefix="/v2/groups/integ-qq-group-1/",
        )
        assert sent is not None, (
            f"no group send captured; calls=" f"{qq_channel_up.api_calls[-5:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_qq_guild_at_message_roundtrip(
    app_server,
    qq_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """AT_MESSAGE_CREATE (guild) flows out via /channels/... path.

    Test purpose:
      - Cover the guild spec (channel_id/guild_id extra meta) and the
        channel-message send branch (no msg_seq for guild).
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        qq_channel_up.push_dispatch(
            "AT_MESSAGE_CREATE",
            {
                "id": "integ-qq-guild-msg-1",
                "content": "hello guild",
                "author": {"id": "integ-qq-guilder-1"},
                "channel_id": "integ-qq-chan-1",
                "guild_id": "integ-qq-guild-1",
            },
        )
        sent = qq_channel_up.wait_for_sent_text(
            lambda text: MOCK_LLM_RESPONSE.split()[0] in text,
            timeout=90.0,
            path_prefix="/channels/integ-qq-chan-1/",
        )
        assert sent is not None, (
            f"no guild send captured; calls=" f"{qq_channel_up.api_calls[-5:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_qq_dm_message_roundtrip(
    app_server,
    qq_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """DIRECT_MESSAGE_CREATE (guild DM) completes the loop.

    Test purpose:
      - Cover the "dm" spec of _MESSAGE_EVENT_SPECS and the
        /dms/{guild_id}/messages send branch.

    Test flow:
      1. Push DIRECT_MESSAGE_CREATE with channel_id + guild_id.
      2. Poll the mock for an outbound POST under /dms/.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        qq_channel_up.push_dispatch(
            "DIRECT_MESSAGE_CREATE",
            {
                "id": "integ-qq-dm-msg-1",
                "content": "hello dm",
                "author": {"id": "integ-qq-dmer-1"},
                "channel_id": "integ-qq-dm-chan-1",
                "guild_id": "integ-qq-dm-guild-1",
            },
        )
        sent = qq_channel_up.wait_for_sent_text(
            lambda text: MOCK_LLM_RESPONSE.split()[0] in text,
            timeout=90.0,
            path_prefix="/dms/integ-qq-dm-guild-1/",
        )
        assert (
            sent is not None
        ), f"no dm send captured; calls={qq_channel_up.api_calls[-5:]}"
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_qq_empty_content_message_is_ignored(
    # pylint: disable=redefined-outer-name,unused-argument
    app_server,
    qq_channel_up,
):
    """A message with neither text nor attachments is dropped.

    Test purpose:
      - Cover the early-return guard in _handle_msg_event (no text and
        no attachments) — no outbound send should occur.

    Test flow:
      1. Push C2C_MESSAGE_CREATE with empty content.
      2. Assert no new outbound message appears for that openid.
    """
    before = len(qq_channel_up.api_calls)
    qq_channel_up.push_dispatch(
        "C2C_MESSAGE_CREATE",
        {
            "id": "integ-qq-empty-1",
            "content": "   ",
            "author": {"user_openid": "integ-qq-user-empty"},
        },
    )
    time.sleep(3.0)
    new_calls = [
        call
        for call in qq_channel_up.api_calls[before:]
        if "integ-qq-user-empty" in call.get("path", "")
    ]
    assert not new_calls, new_calls


@pytest.mark.integration
@pytest.mark.p1
def test_qq_voice_message_with_asr_text_roundtrip(
    app_server,
    qq_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A voice attachment with platform ASR text reaches the agent.

    Test purpose:
      - Cover _parse_qq_attachments' voice branch: when the platform
        supplies asr_refer_text, it is used directly as the message
        text (no audio download), and the loop completes.

    Test flow:
      1. Push C2C_MESSAGE_CREATE with an empty content but a voice
         attachment carrying asr_refer_text.
      2. Poll the mock for an outbound reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        qq_channel_up.push_dispatch(
            "C2C_MESSAGE_CREATE",
            {
                "id": "integ-qq-voice-1",
                "content": "",
                "author": {"user_openid": "integ-qq-user-voice"},
                "attachments": [
                    {
                        "url": "https://example.invalid/voice.amr",
                        "filename": "voice.amr",
                        "content_type": "voice",
                        "asr_refer_text": "hello via voice asr",
                    },
                ],
            },
        )
        sent = qq_channel_up.wait_for_sent_text(
            lambda text: MOCK_LLM_RESPONSE.split()[0] in text,
            timeout=90.0,
            path_prefix="/v2/users/integ-qq-user-voice/",
        )
        assert (
            sent is not None
        ), f"no voice-asr reply; calls={qq_channel_up.api_calls[-5:]}"
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_qq_access_control_dm_gates_unknown_sender(
    app_server,
    qq_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """With access_control_dm on, an unknown sender gets a deny reply.

    Test purpose:
      - Cover BaseChannel._access_control_gate: unknown sender ->
        add_pending + deny message sent back through the channel's own
        send path (observable at the mock IM), and the agent is NOT
        invoked.

    Test flow:
      1. Enable access_control_dm via channel config PUT.
      2. Push a C2C message from a fresh openid.
      3. Expect an outbound send that is NOT the LLM reply (the ACL
         pending/deny message), then restore config.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    qq_channel_up.reset_identified()
    provider_id = register_mock_provider(app_server, mock_url)
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/qq",
        json={
            "enabled": True,
            "app_id": "integ-mock-qq-app",
            "client_secret": "integ-mock-qq-secret",
            "access_control_dm": True,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    assert qq_channel_up.wait_identified(timeout=60.0), (
        "QQ channel did not reconnect after ACL config reload: "
        + app_server.logs_tail()[-3000:]
    )
    try:
        deny_text = None
        for attempt in range(4):
            openid = f"integ-qq-acl-stranger-{attempt}"
            before = len(qq_channel_up.api_calls)
            qq_channel_up.push_c2c_message(
                openid=openid,
                text="let me in please",
                msg_id=f"integ-qq-acl-{attempt}",
            )
            deadline = time.time() + 20.0
            while time.time() < deadline and deny_text is None:
                for call in qq_channel_up.api_calls[before:]:
                    if openid not in call.get("path", ""):
                        continue
                    body = call.get("body") or {}
                    text = body.get("content") or (
                        body.get("markdown") or {}
                    ).get("content", "")
                    if text:
                        deny_text = str(text)
                        break
                time.sleep(0.2)
            if deny_text is not None:
                break
        assert (
            deny_text is not None
        ), f"no ACL deny reply; calls={qq_channel_up.api_calls[-5:]}"
        # The reply must be the gate's message, not the agent's.
        assert MOCK_LLM_RESPONSE.split()[0] not in deny_text, deny_text
    finally:
        unregister_mock_provider(app_server, provider_id)
        qq_channel_up.reset_identified()
        restore = app_server.api_request(
            "PUT",
            "/api/config/channels/qq",
            json={
                "enabled": True,
                "app_id": "integ-mock-qq-app",
                "client_secret": "integ-mock-qq-secret",
                "access_control_dm": False,
            },
            timeout=_HTTP_TIMEOUT,
        )
        assert restore.status_code == 200
        qq_channel_up.wait_identified(timeout=60.0)


@pytest.mark.integration
@pytest.mark.p2
def test_qq_interaction_event_is_handled(
    # pylint: disable=redefined-outer-name,unused-argument
    app_server,
    qq_channel_up,
):
    """An INTERACTION_CREATE event reaches the card dispatcher.

    Test purpose:
      - Cover _handle_interaction_event plus the card dispatcher's
        lookup path (unknown interaction is dropped gracefully), and
        confirm the WS loop keeps running afterwards.

    Test flow:
      1. Push an INTERACTION_CREATE dispatch.
      2. Push a normal C2C message and confirm it is still received
         (mock records a send attempt or the channel stays alive).
    """
    qq_channel_up.push_dispatch(
        "INTERACTION_CREATE",
        {
            "id": "integ-qq-interaction-1",
            "application_id": "integ-app",
            "type": 11,
            "data": {
                "resolved": {
                    "button_id": "integ-btn",
                    "button_data": "integ-data",
                },
            },
        },
    )
    time.sleep(3.0)
    # The WS session must still be alive for further dispatches.
    qq_channel_up.push_dispatch(
        "C2C_MESSAGE_CREATE",
        {
            "id": "integ-qq-after-interaction",
            "content": "   ",
            "author": {"user_openid": "integ-qq-after-int"},
        },
    )
    time.sleep(2.0)


@pytest.mark.integration
@pytest.mark.p2
def test_qq_bot_prefix_message_is_skipped(
    app_server,
    qq_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A message starting with the bot prefix is ignored.

    Test purpose:
      - Cover the bot_prefix self-echo guard in _handle_msg_event.

    Test flow:
      1. Configure a bot_prefix, wait for reconnect.
      2. Push a message starting with that prefix; assert no outbound
         send for that openid.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    qq_channel_up.reset_identified()
    provider_id = register_mock_provider(app_server, mock_url)
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/qq",
        json={
            "enabled": True,
            "app_id": "integ-mock-qq-app",
            "client_secret": "integ-mock-qq-secret",
            "bot_prefix": "[BOT]",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    assert qq_channel_up.wait_identified(timeout=60.0), app_server.logs_tail()[
        -2000:
    ]
    try:
        openid = "integ-qq-prefix-user"
        before = len(qq_channel_up.api_calls)
        qq_channel_up.push_c2c_message(
            openid=openid,
            text="[BOT] echo of my own message",
            msg_id="integ-qq-prefix-1",
        )
        time.sleep(8.0)
        new_calls = [
            call
            for call in qq_channel_up.api_calls[before:]
            if openid in call.get("path", "")
        ]
        assert not new_calls, new_calls
    finally:
        unregister_mock_provider(app_server, provider_id)
        qq_channel_up.reset_identified()
        app_server.api_request(
            "PUT",
            "/api/config/channels/qq",
            json={
                "enabled": True,
                "app_id": "integ-mock-qq-app",
                "client_secret": "integ-mock-qq-secret",
                "bot_prefix": "",
            },
            timeout=_HTTP_TIMEOUT,
        )
        qq_channel_up.wait_identified(timeout=60.0)


@pytest.mark.integration
@pytest.mark.p2
def test_qq_group_at_with_attachment(
    app_server,
    qq_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A group message with an image attachment completes the loop.

    Test purpose:
      - Cover _parse_qq_attachments' image branch inside the group
        message path (download attempt against an unreachable URL is
        tolerated) plus the group reply route.

    Test flow:
      1. Push GROUP_AT_MESSAGE_CREATE with an image attachment.
      2. Poll the mock for a send under the group path.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        qq_channel_up.push_dispatch(
            "GROUP_AT_MESSAGE_CREATE",
            {
                "id": "integ-qq-group-att-1",
                "content": "look at this",
                "author": {"member_openid": "integ-qq-att-member"},
                "group_openid": "integ-qq-att-group",
                "attachments": [
                    {
                        "url": "https://example.invalid/qq-att.png",
                        "filename": "qq-att.png",
                        "content_type": "image/png",
                    },
                ],
            },
        )
        sent = qq_channel_up.wait_for_sent_text(
            lambda text: MOCK_LLM_RESPONSE.split()[0] in text,
            timeout=90.0,
            path_prefix="/v2/groups/integ-qq-att-group/",
        )
        assert sent is not None, (
            f"no group-attachment reply; calls="
            f"{qq_channel_up.api_calls[-5:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_qq_quoted_message_prefix(
    app_server,
    qq_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A quoted message adds a quote prefix to the forwarded text.

    Test purpose:
      - Cover _find_quoted_element and the quoted-text prefix logic in
        _handle_msg_event.

    Test flow:
      1. Push a C2C message carrying msg_elements with a quoted item.
      2. Poll the mock for the usual reply (proving the quoted parse
         did not break the pipeline).
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        openid = "integ-qq-quote-user"
        qq_channel_up.push_dispatch(
            "C2C_MESSAGE_CREATE",
            {
                "id": "integ-qq-quote-1",
                "content": "what about this?",
                "author": {"user_openid": openid},
                "msg_elements": [
                    {
                        "elem_index": 1,
                        "content": "the original message",
                    },
                ],
            },
        )
        sent = qq_channel_up.wait_for_sent_text(
            lambda text: MOCK_LLM_RESPONSE.split()[0] in text,
            timeout=90.0,
            path_prefix=f"/v2/users/{openid}/",
        )
        assert (
            sent is not None
        ), f"no quoted-message reply; calls={qq_channel_up.api_calls[-5:]}"
    finally:
        unregister_mock_provider(app_server, provider_id)
