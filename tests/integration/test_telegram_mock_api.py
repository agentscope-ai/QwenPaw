# -*- coding: utf-8 -*-
"""End-to-end Telegram channel flow against a mock Bot API server.

Third channel on the mock-IM strategy (after QQ and DingTalk), and the
simplest: Telegram uses plain HTTP long polling, so the channel's
existing ``base_url`` config field (a product feature for Bot API
mirrors/proxies) is enough to point it at a local mock — no env
injection, no WebSocket.

Flow covered: start() -> getMe -> getUpdates long poll -> incoming
message -> agent (mock LLM) -> sendMessage recorded by the mock.

Coverage targets (``src/qwenpaw/app/channels/telegram/channel.py``):
  start/_polling loop/_build_content_parts_from_message/
  build_agent_request_from_native/send.

API endpoints:
  - PUT /api/config/channels/telegram
  - GET /api/config/channels/telegram
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
from mock_telegram_api import MockTelegramAPI

_HTTP_TIMEOUT = default_http_timeout(15.0)

_MOCK_API = MockTelegramAPI()


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
def telegram_channel_up(app_server):
    """Enable the Telegram channel pointed at the mock Bot API."""
    _MOCK_API.start()
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/telegram",
        json={
            "enabled": True,
            "bot_token": "123456:integ-mock-telegram-token",
            "base_url": _MOCK_API.base_url,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    yield _MOCK_API
    app_server.api_request(
        "PUT",
        "/api/config/channels/telegram",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )


def _push_until_reply(
    mock_api,
    *,
    text,
    chat_id,
    attempts: int = 4,
    **push_kwargs,
):
    """Push a message, retrying across zero-downtime channel reloads."""
    for _ in range(attempts):
        mock_api.push_text_message(
            text=text,
            chat_id=chat_id,
            **push_kwargs,
        )
        replied = mock_api.wait_for_sent_text(
            lambda t: MOCK_LLM_RESPONSE.split()[0] in t,
            timeout=25.0,
        )
        if replied is not None:
            return replied
        time.sleep(1.0)
    return None


@pytest.mark.integration
@pytest.mark.p1
def test_telegram_channel_enabled_with_mock_base_url(
    app_server,
    # pylint: disable=redefined-outer-name,unused-argument
    telegram_channel_up,
):
    """Channel config accepts the mock Bot API base_url.

    Test purpose:
      - Confirm the channel is enabled and its base_url points at the
        mock, i.e. start() ran against the local server rather than
        api.telegram.org.

    API endpoints:
      - GET /api/config/channels/telegram
    """
    resp = app_server.api_request(
        "GET",
        "/api/config/channels/telegram",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    body = resp.json()
    assert body.get("enabled") is True
    assert body.get("base_url") == _MOCK_API.base_url


@pytest.mark.integration
@pytest.mark.p0
def test_telegram_private_message_roundtrip(
    app_server,
    telegram_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A polled private message flows through the agent and back out.

    Test purpose:
      - Core Telegram loop: getUpdates -> content parts -> agent
        (mock LLM) -> send -> sendMessage captured by the mock.

    Test flow:
      1. Register mock LLM provider.
      2. Queue an incoming private text message.
      3. Poll the mock for a sendMessage carrying the LLM reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = _push_until_reply(
            telegram_channel_up,
            text="hello from mock telegram",
            chat_id=777101,
        )
        assert replied is not None, (
            f"no sendMessage captured; sent="
            f"{telegram_channel_up.sent_messages[-5:]} logs="
            f"{app_server.logs_tail()[-3000:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_telegram_group_mention_roundtrip(
    app_server,
    telegram_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A group message mentioning the bot completes the loop.

    Test purpose:
      - Cover the group path plus the mention-entity branch of
        _build_content_parts_from_message (bot handle stripped from
        the forwarded text).

    Test flow:
      1. Queue a group message prefixed with @<bot> plus a matching
         mention entity.
      2. Poll the mock for a sendMessage carrying the LLM reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        replied = _push_until_reply(
            telegram_channel_up,
            text="hello group from mock telegram",
            chat_id=-100777202,
            chat_type="group",
            mention_bot=True,
        )
        assert replied is not None, (
            f"no group sendMessage captured; sent="
            f"{telegram_channel_up.sent_messages[-5:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_telegram_long_reply_is_chunked(
    app_server,
    telegram_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A reply over Telegram's 4096-char limit is split into chunks.

    Test purpose:
      - Cover _chunk_text: the channel must split long agent replies
        into multiple sendMessage calls instead of failing.

    Test flow:
      1. Make the mock LLM answer with >4096 characters.
      2. Push a private message.
      3. Assert at least two sendMessage calls were recorded and each
         respects the length cap.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    marker = "LONGCHUNK"
    srv.response_text = marker + ("x" * 5000)
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        before = len(telegram_channel_up.sent_messages)
        found = None
        for _ in range(4):
            telegram_channel_up.push_text_message(
                text="give me a long answer",
                chat_id=777303,
            )
            found = telegram_channel_up.wait_for_sent_text(
                lambda t: marker in t,
                timeout=25.0,
            )
            if found is not None:
                break
            time.sleep(1.0)
        assert found is not None, (
            f"no long reply captured; sent="
            f"{telegram_channel_up.sent_messages[-3:]}"
        )
        # wait_for_sent_text returns on the *first* chunk carrying the
        # marker, so later chunks may not be recorded yet on a slow host.
        deadline = time.time() + 25.0
        new_msgs = telegram_channel_up.sent_messages[before:]
        while time.time() < deadline and len(new_msgs) < 2:
            time.sleep(0.3)
            new_msgs = telegram_channel_up.sent_messages[before:]
        assert (
            len(new_msgs) >= 2
        ), f"expected chunked sends, got {len(new_msgs)}"
        for msg in new_msgs:
            assert len(str(msg.get("text", ""))) <= 4096, msg
    finally:
        srv.response_text = None
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p1
def test_telegram_version_control_command(
    app_server,
    telegram_channel_up,  # pylint: disable=redefined-outer-name
):
    """/version is answered by the control-command path (no LLM).

    Test purpose:
      - Cover the control-command branch of
        BaseChannel._consume_one_request: the registry classifies
        /version as control, the workspace handles it directly, and
        the reply (containing a version string) goes out without any
        model configured.

    Test flow:
      1. Queue a private message "/version" (no LLM registered).
      2. Poll for a sendMessage whose text mentions qwenpaw/version.
    """
    replied = None
    for _ in range(4):
        telegram_channel_up.push_text_message(
            text="/version",
            chat_id=777505,
        )
        replied = telegram_channel_up.wait_for_sent_text(
            lambda t: "version" in t.lower() or "qwenpaw" in t.lower(),
            timeout=20.0,
        )
        if replied is not None:
            break
        time.sleep(1.0)
    assert replied is not None, (
        f"no /version reply; sent={telegram_channel_up.sent_messages[-5:]} "
        f"logs={app_server.logs_tail()[-2000:]}"
    )


@pytest.mark.integration
@pytest.mark.p2
def test_telegram_photo_message_download_path(
    app_server,
    telegram_channel_up,  # pylint: disable=redefined-outer-name
    mock_llm,  # pylint: disable=redefined-outer-name
):
    """A photo update drives the file download branch.

    Test purpose:
      - Cover _build_content_parts_from_message's photo handling plus
        _download_telegram_file (getFile against the mock), then check
        text still round-trips.

    Test flow:
      1. Queue a photo message with a caption.
      2. Queue a text message and expect the usual reply.
    """
    srv, mock_url = mock_llm
    srv.force_tool_call = False
    unregister_mock_provider(app_server, MOCK_LLM_PROVIDER_ID)
    provider_id = register_mock_provider(app_server, mock_url)
    try:
        telegram_channel_up.push_photo_message(
            chat_id=777707,
            caption="look at this photo",
        )
        replied = _push_until_reply(
            telegram_channel_up,
            text="after the photo",
            chat_id=777707,
        )
        assert replied is not None, (
            f"channel stopped after photo; sent="
            f"{telegram_channel_up.sent_messages[-3:]}"
        )
    finally:
        unregister_mock_provider(app_server, provider_id)


@pytest.mark.integration
@pytest.mark.p2
def test_telegram_bot_command_entity(
    app_server,
    telegram_channel_up,  # pylint: disable=redefined-outer-name
):
    """A bot_command entity marks the message as a command.

    Test purpose:
      - Cover the bot_command entity branch of
        _build_content_parts_from_message (has_bot_command=True),
        which lets group commands through without a mention.

    Test flow:
      1. Queue /version carrying a bot_command entity.
      2. Poll for a reply mentioning the version.
    """
    replied = None
    for _ in range(4):
        telegram_channel_up.push_command_message(
            command="/version",
            chat_id=777708,
        )
        replied = telegram_channel_up.wait_for_sent_text(
            lambda t: "version" in t.lower() or "qwenpaw" in t.lower(),
            timeout=20.0,
        )
        if replied is not None:
            break
        time.sleep(1.0)
    assert replied is not None, (
        f"no command reply; sent={telegram_channel_up.sent_messages[-5:]} "
        f"logs={app_server.logs_tail()[-2000:]}"
    )


@pytest.mark.integration
@pytest.mark.p1
def test_telegram_status_control_command(
    app_server,
    telegram_channel_up,  # pylint: disable=redefined-outer-name
):
    """/status is answered by the control-command path.

    Test purpose:
      - Cover the daemon status control handler through a real channel:
        the registry classifies /status as control, the workspace
        answers it directly, and a status report is delivered with no
        model configured.

    Test flow:
      1. Queue a private "/status" message.
      2. Poll for a sendMessage that reads like a status report.
    """
    replied = None
    for _ in range(4):
        telegram_channel_up.push_text_message(
            text="/status",
            chat_id=777506,
        )
        replied = telegram_channel_up.wait_for_sent_text(
            lambda t: "status" in t.lower()
            or "running" in t.lower()
            or "agent" in t.lower(),
            timeout=20.0,
        )
        if replied is not None:
            break
        time.sleep(1.0)
    assert replied is not None, (
        f"no /status reply; sent={telegram_channel_up.sent_messages[-5:]} "
        f"logs={app_server.logs_tail()[-2000:]}"
    )


@pytest.mark.integration
@pytest.mark.p2
def test_telegram_approval_control_command(
    app_server,
    telegram_channel_up,  # pylint: disable=redefined-outer-name
):
    """/approval reports the pending-approval queue.

    Test purpose:
      - Cover the approval control handler's listing branch with an
        empty queue: it must reply that nothing is pending rather than
        stay silent.

    Test flow:
      1. Queue a private "/approval" message.
      2. Poll for a reply that mentions approvals or an empty state.
    """
    replied = None
    for _ in range(4):
        telegram_channel_up.push_text_message(
            text="/approval",
            chat_id=777507,
        )
        # The handler localises its reply, so match on either the
        # English or the Chinese empty-queue wording.
        replied = telegram_channel_up.wait_for_sent_text(
            lambda t: "approval" in t.lower()
            or "pending" in t.lower()
            or "审批" in t,
            timeout=20.0,
        )
        if replied is not None:
            break
        time.sleep(1.0)
    assert replied is not None, (
        f"no /approval reply; sent={telegram_channel_up.sent_messages[-5:]} "
        f"logs={app_server.logs_tail()[-2000:]}"
    )


@pytest.mark.integration
@pytest.mark.p2
def test_telegram_daemon_version_control_command(
    app_server,
    telegram_channel_up,  # pylint: disable=redefined-outer-name
):
    """A two-word control command (/daemon version) is recognised.

    Test purpose:
      - Cover the registry's multi-token command matching: "/daemon
        version" must be classified as control rather than being split
        and sent to the model.

    Test flow:
      1. Queue a private "/daemon version" message.
      2. Poll for a reply carrying a version string.
    """
    replied = None
    for _ in range(4):
        telegram_channel_up.push_text_message(
            text="/daemon version",
            chat_id=777508,
        )
        replied = telegram_channel_up.wait_for_sent_text(
            lambda t: "version" in t.lower() or "qwenpaw" in t.lower(),
            timeout=20.0,
        )
        if replied is not None:
            break
        time.sleep(1.0)
    assert replied is not None, (
        "no /daemon version reply; "
        f"sent={telegram_channel_up.sent_messages[-5:]} "
        f"logs={app_server.logs_tail()[-2000:]}"
    )
