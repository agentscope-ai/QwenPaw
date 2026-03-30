# -*- coding: utf-8 -*-
"""Spec tests for the shared DingTalk OpenAPI client.

These tests are intentionally written against the client API that the
implementation is expected to provide.  They skip cleanly until the mainline
module exists, so they can be merged before the source file lands.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import aiohttp
import pytest


def _load_module():
    return pytest.importorskip("copaw.app.channels.dingtalk.openapi_client")


@dataclass
class _FakeResponse:
    status: int
    payload: dict[str, Any]

    async def json(self, content_type=None):  # pylint: disable=unused-argument
        return self.payload

    async def text(self):
        return json.dumps(self.payload, ensure_ascii=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        _ = (exc_type, exc, tb)
        return False


class _FakeSession:
    def __init__(self, responses: list[Any]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected request")
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)


def _new_client(module, **overrides):
    client = module.DingTalkOpenAPIClient(
        client_id=overrides.pop("client_id", "test-client-id"),
        client_secret=overrides.pop("client_secret", "test-client-secret"),
        http_session=overrides.pop("http_session", _FakeSession([])),
        base_url=overrides.pop(
            "base_url",
            "https://api.dingtalk.com",
        ),
        **overrides,
    )
    return client


def _patch_sleep(monkeypatch, module):
    delays: list[float] = []

    async def _fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(module.asyncio, "sleep", _fake_sleep)
    return delays


def test_missing_credentials_raise_clear_error():
    module = _load_module()
    client = _new_client(module, client_id="", client_secret="")

    with pytest.raises((ValueError, RuntimeError), match="client_id|missing"):
        asyncio.run(client.get_access_token())


def test_access_token_is_cached(monkeypatch):
    module = _load_module()
    fake_session = _FakeSession(
        [
            _FakeResponse(
                200,
                {"accessToken": "token-1", "expireIn": 3600},
            ),
        ],
    )
    client = _new_client(module, http_session=fake_session)

    token_1 = asyncio.run(client.get_access_token())
    token_2 = asyncio.run(client.get_access_token())

    assert token_1 == "token-1"
    assert token_2 == "token-1"
    assert len(fake_session.calls) == 1
    assert fake_session.calls[0]["method"] == "POST"
    assert "accessToken" in fake_session.calls[0]["url"]


def test_access_token_retries_retryable_status_and_succeeds(monkeypatch):
    module = _load_module()
    delays = _patch_sleep(monkeypatch, module)
    fake_session = _FakeSession(
        [
            _FakeResponse(503, {"code": "ServiceUnavailable"}),
            _FakeResponse(200, {"accessToken": "token-1", "expireIn": 3600}),
        ],
    )
    client = _new_client(module, http_session=fake_session)

    token = asyncio.run(client.get_access_token())

    assert token == "token-1"
    assert len(fake_session.calls) == 2
    assert delays and delays[0] > 0


def test_access_token_failure_raises():
    module = _load_module()
    fake_session = _FakeSession(
        [
            _FakeResponse(
                500,
                {"errcode": 500, "errmsg": "server error"},
            ),
        ],
    )
    client = _new_client(module, http_session=fake_session)

    with pytest.raises(Exception, match="accessToken|token|500"):
        asyncio.run(client.get_access_token())

    assert len(fake_session.calls) == 1


def test_request_json_success_injects_access_token(monkeypatch):
    module = _load_module()
    fake_session = _FakeSession(
        [
            _FakeResponse(200, {"ok": True, "data": {"value": 1}}),
        ],
    )
    client = _new_client(module, http_session=fake_session)

    async def _fake_get_access_token():
        return "token-xyz"

    monkeypatch.setattr(client, "get_access_token", _fake_get_access_token)

    result = asyncio.run(
        client.request_json(
            "POST",
            "/v1/test/resource",
            json_body={"hello": "world"},
        ),
    )

    assert result == {"ok": True, "data": {"value": 1}}
    assert len(fake_session.calls) == 1
    call = fake_session.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.dingtalk.com/v1/test/resource"
    assert call["json"] == {"hello": "world"}
    headers = call["headers"]
    assert headers["x-acs-dingtalk-access-token"] == "token-xyz"


def test_request_json_normalizes_bool_query_params(monkeypatch):
    module = _load_module()
    fake_session = _FakeSession(
        [
            _FakeResponse(200, {"ok": True}),
        ],
    )
    client = _new_client(module, http_session=fake_session)

    async def _fake_get_access_token():
        return "token-xyz"

    monkeypatch.setattr(client, "get_access_token", _fake_get_access_token)

    result = asyncio.run(
        client.request_json(
            "GET",
            "/v1/test/resource",
            params={
                "withPermissionRole": True,
                "includeSpace": False,
                "operatorId": "union-id",
                "empty": None,
            },
        ),
    )

    assert result == {"ok": True}
    assert fake_session.calls[0]["params"] == {
        "withPermissionRole": "true",
        "includeSpace": "false",
        "operatorId": "union-id",
    }


def test_request_json_retries_retryable_status_and_succeeds(monkeypatch):
    module = _load_module()
    delays = _patch_sleep(monkeypatch, module)
    fake_session = _FakeSession(
        [
            _FakeResponse(200, {"accessToken": "token-xyz"}),
            _FakeResponse(503, {"code": "ServiceUnavailable"}),
            _FakeResponse(200, {"ok": True}),
        ],
    )
    client = _new_client(module, http_session=fake_session)

    result = asyncio.run(
        client.request_json(
            "GET",
            "/v1/test/resource",
        ),
    )

    assert result == {"ok": True}
    assert len(fake_session.calls) == 3
    assert delays and delays[0] > 0


def test_request_json_retries_network_exception_for_get(monkeypatch):
    module = _load_module()
    delays = _patch_sleep(monkeypatch, module)
    fake_session = _FakeSession(
        [
            _FakeResponse(200, {"accessToken": "token-xyz"}),
            aiohttp.ClientConnectionError("connection reset"),
            _FakeResponse(200, {"ok": True}),
        ],
    )
    client = _new_client(module, http_session=fake_session)

    result = asyncio.run(
        client.request_json(
            "GET",
            "/v1/test/resource",
        ),
    )

    assert result == {"ok": True}
    assert len(fake_session.calls) == 3
    assert delays and delays[0] > 0


def test_request_json_does_not_retry_post_by_default(monkeypatch):
    module = _load_module()
    fake_session = _FakeSession(
        [
            _FakeResponse(200, {"accessToken": "token-xyz"}),
            _FakeResponse(503, {"code": "ServiceUnavailable"}),
            _FakeResponse(200, {"ok": True}),
        ],
    )
    client = _new_client(module, http_session=fake_session)

    with pytest.raises(Exception, match="503|ServiceUnavailable"):
        asyncio.run(
            client.request_json(
                "POST",
                "/v1/test/resource",
                json_body={"hello": "world"},
            ),
        )

    assert len(fake_session.calls) == 2


def test_request_json_can_retry_post_when_opted_in(monkeypatch):
    module = _load_module()
    delays = _patch_sleep(monkeypatch, module)
    fake_session = _FakeSession(
        [
            _FakeResponse(200, {"accessToken": "token-xyz"}),
            _FakeResponse(503, {"code": "ServiceUnavailable"}),
            _FakeResponse(200, {"ok": True}),
        ],
    )
    client = _new_client(module, http_session=fake_session)

    result = asyncio.run(
        client.request_json(
            "POST",
            "/v1/test/resource",
            json_body={"hello": "world"},
            retry_on_transient=True,
        ),
    )

    assert result == {"ok": True}
    assert len(fake_session.calls) == 3
    assert delays and delays[0] > 0


@pytest.mark.parametrize(
    "status,payload",
    [
        (400, {"errcode": 400, "errmsg": "bad request"}),
        (500, {"errcode": 500, "errmsg": "server error"}),
    ],
)
def test_request_json_failure_raises(status, payload, monkeypatch):
    module = _load_module()
    fake_session = _FakeSession([_FakeResponse(status, payload)])
    client = _new_client(module, http_session=fake_session)

    async def _fake_get_access_token():
        return "token-xyz"

    monkeypatch.setattr(client, "get_access_token", _fake_get_access_token)

    with pytest.raises(Exception, match="400|500|bad request|server error"):
        asyncio.run(
            client.request_json(
                "GET",
                "/v1/test/resource",
            ),
        )

    assert len(fake_session.calls) == 1


def test_request_json_final_failure_after_retries(monkeypatch):
    module = _load_module()
    delays = _patch_sleep(monkeypatch, module)
    fake_session = _FakeSession(
        [
            _FakeResponse(200, {"accessToken": "token-xyz"}),
            _FakeResponse(503, {"code": "ServiceUnavailable"}),
            _FakeResponse(503, {"code": "ServiceUnavailable"}),
            _FakeResponse(503, {"code": "ServiceUnavailable"}),
        ],
    )
    client = _new_client(module, http_session=fake_session)

    with pytest.raises(Exception, match="503|ServiceUnavailable|after retries"):
        asyncio.run(
            client.request_json(
                "GET",
                "/v1/test/resource",
            ),
        )

    assert len(fake_session.calls) == 4
    assert len(delays) == 2
