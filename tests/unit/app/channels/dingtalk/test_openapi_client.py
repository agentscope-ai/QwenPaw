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
    def __init__(self, responses: list[_FakeResponse]):
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if not self.responses:
            raise AssertionError("unexpected request")
        return self.responses.pop(0)

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
