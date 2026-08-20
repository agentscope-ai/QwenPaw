# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Tests for ``AnySearchProvider``'s 402 quota-exceeded handling (A/B/C
branches) and the auto-registration message parser.

Real B-scenario response body (from websearch-console-config-plan.md
section 2.5), used verbatim below to validate the parsing regex against
actual observed provider behavior rather than a guessed shape:

    {"code":-1,"message":"Your account and API key have been automatically
    generated. Use the API key below to continue.\\nusername=as_auto_...\\n
    password=...\\napi_key=as_sk_....","request_id":"..."}
"""
# pylint: disable=protected-access
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from qwenpaw.agents.tools.websearch import (
    AnySearchProvider,
    _parse_auto_registered_credentials,
)

_REAL_B_MESSAGE = (
    "Your account and API key have been automatically generated. "
    "Use the API key below to continue.\n"
    "username=as_auto_Zpq983GDZvsW\n"
    "password=UYt0NW6PtaKy\n"
    "api_key=as_sk_00d83dc1b2f507950d7e5412952b5fdf."
)


def _http_402(message: str) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.anysearch.com/v1/search")
    response = httpx.Response(
        402,
        json={"code": -1, "message": message, "request_id": "req-1"},
        request=request,
    )
    return httpx.HTTPStatusError(
        "402 Payment Required",
        request=request,
        response=response,
    )


# ---------------------------------------------------------------------------
# _parse_auto_registered_credentials
# ---------------------------------------------------------------------------


def test_parse_auto_registered_credentials_real_sample() -> None:
    creds = _parse_auto_registered_credentials(_REAL_B_MESSAGE)
    assert creds == {
        "username": "as_auto_Zpq983GDZvsW",
        "password": "UYt0NW6PtaKy",
        # Trailing sentence period must be stripped, not part of the key.
        "api_key": "as_sk_00d83dc1b2f507950d7e5412952b5fdf",
    }


def test_parse_auto_registered_credentials_no_match_returns_empty() -> None:
    assert _parse_auto_registered_credentials("unrelated message") == {}


# ---------------------------------------------------------------------------
# Scenario A: anonymous free quota exhausted, registration pending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_a_retries_once_then_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = _http_402("anonymous free quota has been used up, try again later")
    post_mock = AsyncMock(side_effect=[error, error])
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._post",
        post_mock,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._current_agent_anysearch_key",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch.asyncio.sleep",
        AsyncMock(return_value=None),
    )

    provider = AnySearchProvider()
    with pytest.raises(ValueError, match="anonymous free quota"):
        await provider.search("qwen")

    # First call fails with 402; scenario A retries exactly once (no key).
    assert post_mock.await_count == 2
    for call in post_mock.await_args_list:
        assert "Authorization" not in call.kwargs["headers"]


# ---------------------------------------------------------------------------
# Scenario B: auto-registration succeeds, key persisted, retry succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scenario_b_parses_credentials_stores_and_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = _http_402(_REAL_B_MESSAGE)
    success = {"code": 0, "data": {"results": [{"title": "ok"}]}}
    post_mock = AsyncMock(side_effect=[error, success])
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._post",
        post_mock,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._current_agent_anysearch_key",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch.get_current_workspace_dir",
        lambda: tmp_path,
    )

    put_mock = AsyncMock()
    with patch(
        "qwenpaw.agents.tools.websearch.anysearch.AsyncCredentialStore.put",
        put_mock,
    ):
        provider = AnySearchProvider()
        results = await provider.search("qwen")

    assert results == [{"title": "ok"}]
    assert post_mock.await_count == 2
    # Retry call must carry the freshly parsed key.
    retry_headers = post_mock.await_args_list[1].kwargs["headers"]
    assert (
        retry_headers["Authorization"]
        == "Bearer as_sk_00d83dc1b2f507950d7e5412952b5fdf"
    )
    put_mock.assert_awaited_once()
    stored_record = put_mock.await_args.args[0]
    assert stored_record.ref == "tool/web_search/anysearch"
    assert stored_record.kind == "static"
    assert (
        stored_record.secrets["api_key"]
        == "as_sk_00d83dc1b2f507950d7e5412952b5fdf"
    )


@pytest.mark.asyncio
async def test_scenario_b_missing_api_key_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive: if the provider ever sends "automatically generated"
    without a parseable api_key, fail loudly instead of silently retrying
    with an empty Authorization header."""
    error = _http_402("Your account has been automatically generated.")
    post_mock = AsyncMock(side_effect=[error])
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._post",
        post_mock,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._current_agent_anysearch_key",
        AsyncMock(return_value=""),
    )

    provider = AnySearchProvider()
    with pytest.raises(ValueError, match="missing api_key"):
        await provider.search("qwen")

    assert post_mock.await_count == 1


@pytest.mark.asyncio
async def test_scenario_b_credential_store_failure_still_completes_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persisting the new key may fail (disk full, permissions); the
    in-memory key must still be used to complete the current call."""
    error = _http_402(_REAL_B_MESSAGE)
    success = {"code": 0, "data": {"results": []}}
    post_mock = AsyncMock(side_effect=[error, success])
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._post",
        post_mock,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._current_agent_anysearch_key",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch.get_current_workspace_dir",
        lambda: Path("/tmp/fake-workspace"),
    )

    with patch(
        "qwenpaw.agents.tools.websearch.anysearch.AsyncCredentialStore.put",
        AsyncMock(side_effect=OSError("disk full")),
    ):
        provider = AnySearchProvider()
        results = await provider.search("qwen")

    assert results == []
    retry_headers = post_mock.await_args_list[1].kwargs["headers"]
    assert (
        retry_headers["Authorization"]
        == "Bearer as_sk_00d83dc1b2f507950d7e5412952b5fdf"
    )


# ---------------------------------------------------------------------------
# Unrecognized 402 body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unrecognized_402_message_raises_with_status_and_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = _http_402("some other quota error we don't recognize")
    post_mock = AsyncMock(side_effect=[error])
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._post",
        post_mock,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._current_agent_anysearch_key",
        AsyncMock(return_value=""),
    )

    provider = AnySearchProvider()
    with pytest.raises(ValueError, match="402"):
        await provider.search("qwen")


@pytest.mark.asyncio
async def test_non_402_http_error_propagates_unhandled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "https://api.anysearch.com/v1/search")
    response = httpx.Response(500, json={"error": "boom"}, request=request)
    error = httpx.HTTPStatusError(
        "500 Internal Server Error",
        request=request,
        response=response,
    )
    post_mock = AsyncMock(side_effect=[error])
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._post",
        post_mock,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.websearch.anysearch._current_agent_anysearch_key",
        AsyncMock(return_value=""),
    )

    provider = AnySearchProvider()
    with pytest.raises(httpx.HTTPStatusError):
        await provider.search("qwen")
