# -*- coding: utf-8 -*-
"""Proactive sends (POST /api/messages/send) through mock-IM channels.

Drives each mock-connected channel's ``send()`` path directly via the
messages API — no inbound WS push needed. This covers the proactive
branches (cron/agent-initiated sends) that the roundtrip tests skip:
target resolution from ``target_user`` handles, token reuse, and the
channel-specific outbound APIs, all observable at the mock sinks.

API endpoints:
  - POST /api/messages/send
  - PUT  /api/config/channels/qq
  - PUT  /api/config/channels/telegram
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout
from mock_qq_im import MockQQIM
from mock_telegram_api import MockTelegramAPI

_HTTP_TIMEOUT = default_http_timeout(15.0)

_MOCK_QQ = MockQQIM()
_MOCK_TG = MockTelegramAPI()


def APP_SERVER_EXTRA_ENV() -> dict:  # noqa: N802 - conftest contract
    """Point QQ endpoints at this module's own mock instance."""
    _MOCK_QQ.start()
    return {
        "QQ_TOKEN_URL": _MOCK_QQ.token_url,
        "QQ_API_BASE": _MOCK_QQ.api_base,
    }


@pytest.fixture(scope="module")
def qq_up(app_server):
    """Enable the QQ channel against this module's mock."""
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/qq",
        json={
            "enabled": True,
            "app_id": "integ-proactive-qq-app",
            "client_secret": "integ-proactive-qq-secret",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    assert _MOCK_QQ.wait_identified(timeout=60.0), app_server.logs_tail()[
        -3000:
    ]
    yield _MOCK_QQ
    app_server.api_request(
        "PUT",
        "/api/config/channels/qq",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )


@pytest.fixture(scope="module")
def telegram_up(app_server):
    """Enable the Telegram channel against this module's mock."""
    _MOCK_TG.start()
    put = app_server.api_request(
        "PUT",
        "/api/config/channels/telegram",
        json={
            "enabled": True,
            "bot_token": "123456:integ-proactive-tg-token",
            "base_url": _MOCK_TG.base_url,
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert put.status_code == 200, app_server.logs_tail()
    yield _MOCK_TG
    app_server.api_request(
        "PUT",
        "/api/config/channels/telegram",
        json={"enabled": False},
        timeout=_HTTP_TIMEOUT,
    )


@pytest.mark.integration
@pytest.mark.p1
def test_proactive_send_qq_c2c(
    app_server,
    qq_up,  # pylint: disable=redefined-outer-name
):
    """POST /api/messages/send delivers via the QQ channel.

    Test purpose:
      - Cover the proactive send path: messages router -> channel
        manager -> QQChannel.send (async token fetch + c2c POST),
        without any inbound message context.

    Test flow:
      1. POST /api/messages/send {channel: qq, target_user: openid}.
      2. Assert 200 and the mock recorded a /v2/users/.../messages
         POST with the text.
    """
    import time as _time

    resp = None
    deadline = _time.time() + 60.0
    while _time.time() < deadline:
        resp = app_server.api_request(
            "POST",
            "/api/messages/send",
            json={
                "channel": "qq",
                "target_user": "integ-qq-proactive-user",
                "target_session": "qq:integ-qq-proactive-user",
                "text": "proactive hello via qq",
            },
            timeout=default_http_timeout(30.0),
        )
        if resp.status_code == 200:
            break
        _time.sleep(1.0)
    assert resp is not None and resp.status_code == 200, (
        f"{resp.status_code} {resp.text} " + app_server.logs_tail()[-2000:]
    )
    sent = qq_up.wait_for_sent_text(
        lambda text: "proactive hello via qq" in text,
        timeout=30.0,
        path_prefix="/v2/users/integ-qq-proactive-user/",
    )
    assert sent is not None, qq_up.api_calls[-5:]


@pytest.mark.integration
@pytest.mark.p1
def test_proactive_send_telegram_chat(
    app_server,
    telegram_up,  # pylint: disable=redefined-outer-name
):
    """POST /api/messages/send delivers via the Telegram channel.

    Test purpose:
      - Cover TelegramChannel.send in the proactive path (chat_id from
        target_user, no meta), observable as a sendMessage call.

    Test flow:
      1. POST /api/messages/send {channel: telegram, target_user}.
      2. Assert 200 and the mock recorded sendMessage with the text.
    """
    # The enabling PUT triggers an async reload; the channel may not be
    # registered yet on the first try. Retry until it is.
    import time as _time

    resp = None
    deadline = _time.time() + 60.0
    while _time.time() < deadline:
        resp = app_server.api_request(
            "POST",
            "/api/messages/send",
            json={
                "channel": "telegram",
                "target_user": "777909",
                "target_session": "telegram:777909",
                "text": "proactive hello via telegram",
            },
            timeout=default_http_timeout(30.0),
        )
        if resp.status_code == 200:
            break
        _time.sleep(1.0)
    assert resp is not None and resp.status_code == 200, (
        f"{resp.status_code} {resp.text} " + app_server.logs_tail()[-2000:]
    )
    sent = telegram_up.wait_for_sent_text(
        lambda text: "proactive hello via telegram" in text,
        timeout=30.0,
    )
    assert sent is not None, telegram_up.sent_messages[-5:]


@pytest.mark.integration
@pytest.mark.p2
def test_proactive_send_unknown_channel_404(app_server):
    """Sending to a channel that is not running returns an error.

    Test purpose:
      - Cover the messages router's channel-not-found branch.
    """
    resp = app_server.api_request(
        "POST",
        "/api/messages/send",
        json={
            "channel": "discord",
            "target_user": "someone",
            "target_session": "discord:someone",
            "text": "should fail",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (400, 404, 500), resp.text
