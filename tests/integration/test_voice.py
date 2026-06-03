# -*- coding: utf-8 -*-
"""Integration tests for the Twilio-facing voice router.

Note: voice_router is mounted at the app root (no /api prefix), so the
test paths are ``/voice/...`` rather than ``/api/voice/...``.
"""
from __future__ import annotations

import pytest

_VOICE_HTTP_TIMEOUT = 15.0


@pytest.mark.integration
@pytest.mark.p2
def test_voice_incoming_without_voice_channel_returns_error_twiml(
    app_server,
) -> None:
    """Test purpose:
    - Verify POST /voice/incoming gracefully degrades to an error TwiML
      response when the voice channel is not configured (default state).
      A Twilio webhook receiving anything other than valid TwiML would
      surface as a call failure to the operator.

    Test flow:
    1. POST /voice/incoming with empty form. No X-Twilio-Signature is
       needed because the dependency short-circuits when no voice channel
       is attached to the channel manager.
    2. Assert 200 status, content-type application/xml, and the body
       contains the "Voice channel is not available" hint.

    API endpoints:
    - POST /voice/incoming
    """
    resp = app_server.api_request(
        "POST",
        "/voice/incoming",
        timeout=_VOICE_HTTP_TIMEOUT,
    )
    assert resp.status_code == 200, app_server.logs_tail()
    content_type = resp.headers.get("content-type", "")
    assert "xml" in content_type.lower(), content_type
    assert "Voice channel is not available" in resp.text


@pytest.mark.integration
@pytest.mark.p2
def test_voice_status_callback_without_voice_channel_returns_204(
    app_server,
) -> None:
    """Test purpose:
    - Verify POST /voice/status-callback returns 204 with an empty body
      when the voice channel is not configured. Twilio expects a 2xx ack
      regardless of internal state; 5xx would cause Twilio to retry.

    Test flow:
    1. POST /voice/status-callback with empty form (no signature; dep
       short-circuits without a voice channel).
    2. Assert 204 status and empty response body.

    API endpoints:
    - POST /voice/status-callback
    """
    resp = app_server.api_request(
        "POST",
        "/voice/status-callback",
        timeout=_VOICE_HTTP_TIMEOUT,
    )
    assert resp.status_code == 204, app_server.logs_tail()
    assert resp.content == b""
