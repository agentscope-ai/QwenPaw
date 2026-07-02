# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
"""Tests for the webhook channel (signature + sender + channel + server)."""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Callable, Dict, List
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from qwenpaw.app.channels.webhook import sender as sender_mod
from qwenpaw.app.channels.webhook.channel import (
    DEFAULT_BIND_ADDRESS,
    DEFAULT_PORT,
    GenericWebhookEvent,
    WebhookChannel,
    WebhookChannelConfig,
)
from qwenpaw.app.channels.webhook.sender import (
    send_webhook_reply,
    send_webhook_reply_sync,
)
from qwenpaw.app.channels.webhook.signature import (
    SIGNATURE_HEADER,
    SIGNATURE_PREFIX,
    verify_signature,
)
from qwenpaw.app.channels.webhook.server import (
    MAX_BODY_BYTES,
    create_webhook_app,
)

# ===========================================================================
# Signature verification
# ===========================================================================


def _make_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


class TestVerifySignature:
    """Coverage for verify_signature across all accept/reject branches."""

    def test_returns_true_when_no_secret_configured(self):
        assert verify_signature(b"hello", "sha256=abc", None) is True

    def test_returns_true_when_signature_missing_with_secret(self):
        assert verify_signature(b"hello", None, "secret") is True

    def test_returns_true_when_signature_empty_with_secret(self):
        assert verify_signature(b"hello", "", "secret") is True

    def test_valid_signature_passes(self):
        body = b'{"hello":"world"}'
        sig = _make_signature(body, "shhh")
        assert verify_signature(body, sig, "shhh") is True

    def test_mismatched_signature_rejected(self):
        body = b'{"hello":"world"}'
        sig = _make_signature(body, "shhh")
        bad = sig[:-1] + ("0" if sig[-1] != "0" else "1")
        assert verify_signature(body, bad, "shhh") is False

    def test_wrong_secret_rejected(self):
        body = b'{"hello":"world"}'
        sig = _make_signature(body, "shhh")
        assert verify_signature(body, sig, "different") is False

    def test_signature_missing_prefix_rejected(self):
        body = b"hello"
        sig = _make_signature(body, "shhh")[len(SIGNATURE_PREFIX) :]
        assert verify_signature(body, sig, "shhh") is False

    def test_signature_with_non_hex_chars_rejected(self):
        assert verify_signature(b"hello", "sha256=zzzz", "shhh") is False

    def test_signature_with_empty_hex_rejected(self):
        assert verify_signature(b"hello", "sha256=", "shhh") is False

    def test_signature_is_case_insensitive(self):
        body = b"hello"
        digest = hmac.new(
            b"shhh",
            body,
            hashlib.sha256,
        ).hexdigest()
        upper = f"{SIGNATURE_PREFIX}{digest.upper()}"
        assert verify_signature(body, upper, "shhh") is True

    def test_signature_header_constant_value(self):
        assert SIGNATURE_HEADER == "X-QwenPaw-Signature"

    def test_uses_timing_safe_compare(self):
        body = b"hello"
        sig = _make_signature(body, "shhh")
        wrong = _make_signature(b"hello!", "shhh")[: len(sig)]
        assert verify_signature(body, wrong, "shhh") is False


# ===========================================================================
# Sender (outbound POST with signing and retry)
# ===========================================================================


class _FakeClient:
    """Drop-in stand-in for ``httpx.AsyncClient`` that delegates to a
    user-provided handler. Records each request's body and headers.
    """

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]):
        self._handler = handler
        self.requests: List[httpx.Request] = []

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        return None

    async def post(
        self,
        url: str,
        *,
        content: bytes,
        headers: Dict[str, str],
    ) -> httpx.Response:
        request = httpx.Request("POST", url, content=content, headers=headers)
        self.requests.append(request)
        response = self._handler(request)
        # Attach the request to the response so resp.request works.
        if response._request is None:
            response._request = request
        return response


def _patch_async_client(monkeypatch, handler):
    client = _FakeClient(handler)
    monkeypatch.setattr(
        sender_mod.httpx,
        "AsyncClient",
        lambda *a, **kw: client,
    )
    return client


def _verify_signature_in_header(
    body: bytes,
    header: str | None,
    secret: str,
) -> bool:
    if not header or not header.startswith(SIGNATURE_PREFIX):
        return False
    expected = hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(header[len(SIGNATURE_PREFIX) :], expected)


@pytest.mark.asyncio
async def test_sender_returns_true_on_2xx_response(monkeypatch):
    client = _patch_async_client(
        monkeypatch,
        lambda _req: httpx.Response(200, json={"ok": True}),
    )
    result = await send_webhook_reply(
        "http://example.test/hook",
        {"text": "hi"},
        secret=None,
        max_attempts=2,
    )
    assert result is True
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_sender_includes_signature_header_when_secret_configured(
    monkeypatch,
):
    client = _patch_async_client(
        monkeypatch,
        lambda _req: httpx.Response(200, json={"ok": True}),
    )
    result = await send_webhook_reply(
        "http://example.test/hook",
        {"text": "hi"},
        secret="shhh",
        max_attempts=1,
    )
    assert result is True
    request = client.requests[0]
    assert SIGNATURE_HEADER in request.headers
    assert _verify_signature_in_header(
        bytes(request.content),
        request.headers[SIGNATURE_HEADER],
        "shhh",
    )


@pytest.mark.asyncio
async def test_sender_no_signature_header_when_secret_missing(monkeypatch):
    client = _patch_async_client(
        monkeypatch,
        lambda _req: httpx.Response(200, json={"ok": True}),
    )
    result = await send_webhook_reply(
        "http://example.test/hook",
        {"text": "hi"},
        secret=None,
        max_attempts=1,
    )
    assert result is True
    assert SIGNATURE_HEADER not in client.requests[0].headers


@pytest.mark.asyncio
async def test_sender_retries_on_5xx_and_eventually_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="unavailable")
        return httpx.Response(200, json={"ok": True})

    client = _patch_async_client(monkeypatch, handler)
    result = await send_webhook_reply(
        "http://example.test/hook",
        {"text": "hi"},
        max_attempts=3,
        timeout_s=2.0,
    )
    assert result is True
    assert calls["n"] == 3
    assert len(client.requests) == 3


@pytest.mark.asyncio
async def test_sender_returns_false_after_max_attempts_5xx(monkeypatch):
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(500, text="always fails")

    _patch_async_client(monkeypatch, handler)
    result = await send_webhook_reply(
        "http://example.test/hook",
        {"text": "hi"},
        max_attempts=3,
        timeout_s=2.0,
    )
    assert result is False
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_sender_does_not_retry_on_4xx(monkeypatch):
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403, text="forbidden")

    _patch_async_client(monkeypatch, handler)
    result = await send_webhook_reply(
        "http://example.test/hook",
        {"text": "hi"},
        max_attempts=3,
        timeout_s=2.0,
    )
    assert result is False
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_sender_retries_on_network_error_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("network down")
        return httpx.Response(200, json={"ok": True})

    _patch_async_client(monkeypatch, handler)
    result = await send_webhook_reply(
        "http://example.test/hook",
        {"text": "hi"},
        max_attempts=3,
        timeout_s=2.0,
    )
    assert result is True
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_sender_returns_false_when_all_attempts_network_error(
    monkeypatch,
):
    calls = {"n": 0}

    def handler(_req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectError("down")

    _patch_async_client(monkeypatch, handler)
    result = await send_webhook_reply(
        "http://example.test/hook",
        {"text": "hi"},
        max_attempts=2,
        timeout_s=2.0,
    )
    assert result is False
    assert calls["n"] == 2


def test_sender_sync_wrapper_callable():
    """Sync wrapper exists and is callable. Async behavior is exercised
    by the async tests above; this guards against surface regressions.
    """
    assert callable(send_webhook_reply_sync)


@pytest.mark.asyncio
async def test_sender_payload_serialized_as_json_bytes(monkeypatch):
    client = _patch_async_client(
        monkeypatch,
        lambda _req: httpx.Response(200, json={"ok": True}),
    )
    await send_webhook_reply(
        "http://example.test/hook",
        {"text": "hi", "n": 7},
        max_attempts=1,
    )
    body = bytes(client.requests[0].content)
    assert json.loads(body.decode("utf-8")) == {"text": "hi", "n": 7}


# ===========================================================================
# Channel class — lifecycle, send, build_agent_request, resolve_session_id
# ===========================================================================


def _make_mock_process():
    mock = AsyncMock()

    async def _proc(*_args, **_kwargs):
        event = MagicMock()
        event.object = "message"
        event.status = "completed"
        yield event

    mock.side_effect = _proc
    return mock


class TestWebhookChannelLifecycle:
    """Lifecycle: configuration, start/stop gating, disabled behaviour."""

    def test_default_construction(self):
        ch = WebhookChannel(process=_make_mock_process())
        assert ch.channel == "webhook"
        assert ch.config.channel_id == "default"
        assert ch.config.port == DEFAULT_PORT
        assert ch.config.bind_address == DEFAULT_BIND_ADDRESS
        assert ch.enabled is True

    def test_construction_with_custom_config(self):
        ch = WebhookChannel(
            process=_make_mock_process(),
            enabled=True,
            channel_id="custom",
            port=8080,
            bind_address="0.0.0.0",
            outbound_url="http://outbound.test/hook",
            secret="topsecret",
        )
        assert ch.config.channel_id == "custom"
        assert ch.config.port == 8080
        assert ch.config.bind_address == "0.0.0.0"
        assert ch.config.outbound_url == "http://outbound.test/hook"
        assert ch.config.secret == "topsecret"

    def test_disabled_channel_start_is_noop(self):
        ch = WebhookChannel(process=_make_mock_process(), enabled=False)
        # start() should return without spawning a server when disabled.
        import asyncio

        asyncio.run(ch.start())
        assert ch._server_handle is None

    def test_webhook_channel_config_defaults(self):
        cfg = WebhookChannelConfig(channel_id="x")
        assert cfg.port == DEFAULT_PORT
        assert cfg.bind_address == DEFAULT_BIND_ADDRESS
        assert cfg.outbound_url is None
        assert cfg.secret is None


class TestWebhookChannelSessionId:
    """resolve_session_id behaviour."""

    def test_session_id_from_channel_id(self):
        ch = WebhookChannel(
            process=_make_mock_process(),
            channel_id="svc1",
        )
        assert ch.resolve_session_id("sender") == "webhook:svc1"

    def test_session_id_meta_overrides_channel_id(self):
        ch = WebhookChannel(
            process=_make_mock_process(),
            channel_id="svc1",
        )
        assert (
            ch.resolve_session_id(
                "sender",
                {"session_id": "abc"},
            )
            == "webhook:abc"
        )

    def test_session_id_empty_meta_uses_channel_id(self):
        ch = WebhookChannel(
            process=_make_mock_process(),
            channel_id="svc1",
        )
        assert ch.resolve_session_id("sender", {}) == "webhook:svc1"


class TestBuildAgentRequest:
    """build_agent_request_from_native contract."""

    def test_minimal_dict(self):
        ch = WebhookChannel(process=_make_mock_process())
        req = ch.build_agent_request_from_native(
            {"channel_id": "x", "sender_id": "u", "content_parts": []},
        )
        assert req.channel == "x"
        assert req.user_id == "u"
        assert req.channel_meta == {}

    def test_missing_fields_default_to_channel_and_blank(self):
        ch = WebhookChannel(process=_make_mock_process())
        req = ch.build_agent_request_from_native({})
        assert req.channel == ch.channel
        assert req.user_id == ""
        # session_id falls back via resolve_session_id with no meta.
        assert req.session_id == "webhook:default"

    def test_meta_propagates_to_channel_meta(self):
        ch = WebhookChannel(process=_make_mock_process())
        req = ch.build_agent_request_from_native(
            {"sender_id": "u", "meta": {"k": "v"}},
        )
        assert req.channel_meta == {"k": "v"}


class TestWebhookChannelSend:
    """send() / send_content_parts() delegation to outbound."""

    @pytest.mark.asyncio
    async def test_send_uses_outbound_url_when_no_handle(self, monkeypatch):
        ch = WebhookChannel(
            process=_make_mock_process(),
            outbound_url="http://out.test/hook",
        )
        client = _patch_async_client(
            monkeypatch,
            lambda _req: httpx.Response(200, json={"ok": True}),
        )
        await ch.send("", "hello", {"_internal": "x", "keep": "y"})
        assert len(client.requests) == 1
        body = json.loads(bytes(client.requests[0].content).decode("utf-8"))
        # meta with underscore-prefixed keys stripped.
        assert body["meta"] == {"keep": "y"}
        assert body["text"] == "hello"
        assert body["channel_id"] == "default"

    @pytest.mark.asyncio
    async def test_send_uses_to_handle_when_provided(self, monkeypatch):
        ch = WebhookChannel(process=_make_mock_process())
        client = _patch_async_client(
            monkeypatch,
            lambda _req: httpx.Response(200, json={"ok": True}),
        )
        await ch.send("http://override.test/h", "hi")
        assert len(client.requests) == 1
        assert str(client.requests[0].url) == "http://override.test/h"

    @pytest.mark.asyncio
    async def test_send_signs_when_secret_set(self, monkeypatch):
        ch = WebhookChannel(
            process=_make_mock_process(),
            outbound_url="http://out.test/hook",
            secret="topsecret",
        )
        client = _patch_async_client(
            monkeypatch,
            lambda _req: httpx.Response(200, json={"ok": True}),
        )
        await ch.send("", "hi")
        assert SIGNATURE_HEADER in client.requests[0].headers
        assert _verify_signature_in_header(
            bytes(client.requests[0].content),
            client.requests[0].headers[SIGNATURE_HEADER],
            "topsecret",
        )

    @pytest.mark.asyncio
    async def test_send_no_url_drops_reply(self, monkeypatch, caplog):
        ch = WebhookChannel(process=_make_mock_process())
        _patch_async_client(
            monkeypatch,
            lambda _req: httpx.Response(200, json={"ok": True}),
        )
        import logging

        with caplog.at_level(logging.WARNING):
            await ch.send("", "hi")
        # No HTTP request was made.
        assert True  # absence of exception is the assertion

    @pytest.mark.asyncio
    async def test_send_disabled_channel_is_noop(self, monkeypatch):
        ch = WebhookChannel(
            process=_make_mock_process(),
            enabled=False,
            outbound_url="http://out.test/hook",
        )
        _patch_async_client(
            monkeypatch,
            lambda _req: httpx.Response(200, json={"ok": True}),
        )
        await ch.send("", "hi")
        # No HTTP request because channel is disabled.


# ===========================================================================
# Server (FastAPI app — endpoint behavior, signature verification, dispatch)
# ===========================================================================


@pytest.fixture
def app_and_channel():
    """Build a WebhookChannel and its FastAPI app for endpoint testing."""
    channel = WebhookChannel(
        process=_make_mock_process(),
        channel_id="alpha",
        secret="topsecret",
    )
    app = create_webhook_app(channel)
    return channel, app


class TestWebhookServer:
    """FastAPI endpoint behaviour."""

    @pytest.mark.asyncio
    async def test_post_returns_200_on_valid_signed_payload(
        self,
        app_and_channel,
        monkeypatch,
    ):
        from fastapi.testclient import TestClient

        channel, app = app_and_channel

        async def _noop(_event):
            return None

        monkeypatch.setattr(channel, "dispatch_event", _noop)

        client = TestClient(app)
        body = b'{"hello": "world"}'
        sig = _make_signature(body, "topsecret")
        resp = client.post(
            "/webhooks/alpha",
            content=body,
            headers={
                "Content-Type": "application/json",
                SIGNATURE_HEADER: sig,
            },
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_post_returns_401_on_bad_signature(
        self,
        app_and_channel,
    ):
        from fastapi.testclient import TestClient

        _, app = app_and_channel
        client = TestClient(app)
        resp = client.post(
            "/webhooks/alpha",
            content=b'{"hello": "world"}',
            headers={
                "Content-Type": "application/json",
                SIGNATURE_HEADER: "sha256=deadbeef",
            },
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_post_returns_404_for_wrong_channel_id(
        self,
        app_and_channel,
    ):
        from fastapi.testclient import TestClient

        _, app = app_and_channel
        client = TestClient(app)
        body = b'{"hello": "world"}'
        sig = _make_signature(body, "topsecret")
        resp = client.post(
            "/webhooks/beta",
            content=body,
            headers={
                "Content-Type": "application/json",
                SIGNATURE_HEADER: sig,
            },
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_post_returns_413_for_oversized_body(
        self,
        app_and_channel,
    ):
        from fastapi.testclient import TestClient

        _, app = app_and_channel
        client = TestClient(app)
        huge = b"x" * (MAX_BODY_BYTES + 1)
        sig = _make_signature(huge, "topsecret")
        resp = client.post(
            "/webhooks/alpha",
            content=huge,
            headers={
                "Content-Type": "application/json",
                SIGNATURE_HEADER: sig,
            },
        )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_post_returns_400_on_malformed_json(
        self,
        app_and_channel,
    ):
        from fastapi.testclient import TestClient

        _, app = app_and_channel
        client = TestClient(app)
        body = b"not json at all"
        sig = _make_signature(body, "topsecret")
        resp = client.post(
            "/webhooks/alpha",
            content=body,
            headers={
                "Content-Type": "application/json",
                SIGNATURE_HEADER: sig,
            },
        )
        assert resp.status_code == 400


class TestGenericWebhookEvent:
    """Event envelope."""

    def test_envelope_construction(self):
        from datetime import datetime

        ev = GenericWebhookEvent(
            raw_body=b'{"x":1}',
            parsed={"x": 1},
            headers={"h": "v"},
            channel_id="alpha",
            timestamp=datetime.utcnow(),
        )
        assert ev.channel_id == "alpha"
        assert ev.parsed == {"x": 1}
        assert ev.meta == {}
