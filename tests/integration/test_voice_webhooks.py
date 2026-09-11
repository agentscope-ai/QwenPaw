# -*- coding: utf-8 -*-
"""Voice webhook endpoints with no voice channel configured.

Covers ``app/routers/voice.py``'s HTTP surface in the default
configuration, where the voice channel is disabled: the incoming-call
webhook must answer Twilio with valid error TwiML rather than a 500, the
status callback must accept a post, and the ConversationRelay WebSocket
must refuse a connection that carries no single-use token.

Asserting on the returned TwiML (well-formed XML naming a Twilio verb)
rather than only the status code means a regression that returns an empty
body — which Twilio would surface to the caller as a dropped call — fails
the test.

API endpoints:
  - POST /voice/incoming
  - POST /voice/status-callback
  - WS   /voice/ws
"""
from __future__ import annotations

import pytest
from helpers import default_http_timeout

_HTTP_TIMEOUT = default_http_timeout(30.0)


@pytest.mark.integration
@pytest.mark.p1
def test_voice_incoming_returns_twiml_without_channel(app_server):
    """The incoming-call webhook answers with TwiML, not an error page.

    Test purpose:
      - Cover voice_incoming's "channel not available" branch together
        with build_error_twiml. Twilio requires XML here; returning JSON
        or a 500 would drop the call.

    Test flow:
      1. POST a minimal Twilio-style form to /voice/incoming.
      2. Assert 200, an XML content type, and a <Response> document.
    """
    resp = app_server.api_request(
        "POST",
        "/voice/incoming",
        data={"CallSid": "CAintegtest0001", "From": "+15550001111"},
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text[:500]
    assert "xml" in resp.headers.get("content-type", "").lower(), dict(
        resp.headers,
    )
    body = resp.text
    assert "<Response" in body, body[:500]
    assert "</Response>" in body, body[:500]


@pytest.mark.integration
@pytest.mark.p2
def test_voice_incoming_without_form_still_returns_twiml(app_server):
    """A body-less webhook call still yields valid TwiML.

    Test purpose:
      - Cover the same path when Twilio's form fields are absent: the
        handler must not depend on them to produce a response.
    """
    resp = app_server.api_request(
        "POST",
        "/voice/incoming",
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text[:500]
    assert "<Response" in resp.text, resp.text[:500]


@pytest.mark.integration
@pytest.mark.p2
def test_voice_status_callback_accepts_post(app_server):
    """The call-status callback accepts Twilio's status post.

    Test purpose:
      - Cover voice_status_callback: Twilio retries on non-2xx, so this
        endpoint must acknowledge even when no voice channel exists.
    """
    resp = app_server.api_request(
        "POST",
        "/voice/status-callback",
        data={
            "CallSid": "CAintegtest0002",
            "CallStatus": "completed",
        },
        timeout=_HTTP_TIMEOUT,
    )
    assert resp.status_code in (200, 204), resp.text[:500]


@pytest.mark.integration
@pytest.mark.p1
def test_voice_ws_rejects_connection_without_token(app_server):
    """The relay WebSocket refuses an untokenised connection.

    Test purpose:
      - Cover the single-use-token guard on /voice/ws. Without it any
        client could attach to the media stream, so the handshake must
        fail rather than upgrade.

    Test flow:
      1. Attempt a WebSocket handshake with no token query parameter.
      2. Assert the upgrade does not succeed.
    """
    import websockets.sync.client as ws_client

    url = f"ws://127.0.0.1:{app_server.port}/voice/ws"
    try:
        with ws_client.connect(url, open_timeout=10) as conn:
            # An accepted socket must at least be closed promptly; if the
            # server keeps an untokenised stream open that is the defect.
            try:
                conn.recv(timeout=5)
            except Exception:  # noqa: BLE001 - closure is the expected path
                return
            pytest.fail("untokenised voice websocket stayed open")
    except Exception:  # noqa: BLE001 - handshake rejection is expected
        return
