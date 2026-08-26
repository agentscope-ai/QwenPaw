# -*- coding: utf-8 -*-
"""Unit tests for agents/skill_system/hub.py pure logic & mocked I/O.

Coverage-driven backfill: hub.py sat at ~14% coverage. These tests
exercise the env config readers, cancellation hooks, GitHub response
cache, HTTP fetch primitives (retry/backoff/limits), bundle tree
normalization, provider URL parsers, zip→bundle converters, provider
routing and the install pipeline — with all network I/O mocked.
"""
# pylint: disable=wrong-import-position,protected-access,redefined-outer-name,too-many-public-methods,unused-argument,unused-import,unused-variable,use-implicit-booleaness-not-comparison  # noqa: E501
from __future__ import annotations

import asyncio
import base64
import importlib
import io
import json
import time
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest

hub = importlib.import_module("qwenpaw.agents.skill_system.hub")
from qwenpaw.exceptions import (  # noqa: E402
    ConfigurationException,
    SkillConflictError,
    SkillImportCancelled,
    SkillsError,
)


def _run(coro):
    return (
        asyncio.get_event_loop_policy()
        .new_event_loop()
        .run_until_complete(
            coro,
        )
    )


@pytest.fixture(autouse=True)
def _clean_hub_state():
    """Reset module-level caches between tests."""
    hub._github_cache.clear()
    hub._github_cache_key_locks.clear()
    hub._in_flight = 0
    hub._drain_event.set()
    yield
    hub._github_cache.clear()
    hub._github_cache_key_locks.clear()
    hub._in_flight = 0
    hub._drain_event.set()


def _make_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


SKILL_MD = "---\nname: demo-skill\n---\n# Demo\nbody"


# ---------------------------------------------------------------------------
# Env-driven config
# ---------------------------------------------------------------------------


class TestEnvConfig:
    def test_github_cache_ttl_default(self, monkeypatch):
        monkeypatch.delenv("QWENPAW_GITHUB_CACHE_TTL", raising=False)
        assert hub._github_cache_ttl() == 300.0

    def test_github_cache_ttl_custom(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_GITHUB_CACHE_TTL", "10")
        assert hub._github_cache_ttl() == 10.0

    def test_github_cache_ttl_negative_clamped(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_GITHUB_CACHE_TTL", "-5")
        assert hub._github_cache_ttl() == 0.0

    def test_github_cache_ttl_invalid(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_GITHUB_CACHE_TTL", "abc")
        assert hub._github_cache_ttl() == 300.0

    def test_http_timeout_default_and_min(self, monkeypatch):
        monkeypatch.delenv("QWENPAW_SKILLS_HUB_HTTP_TIMEOUT", raising=False)
        assert hub._hub_http_timeout() == 30.0
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_TIMEOUT", "1")
        assert hub._hub_http_timeout() == 3.0
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_TIMEOUT", "bad")
        assert hub._hub_http_timeout() == 30.0

    def test_http_retries(self, monkeypatch):
        monkeypatch.delenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", raising=False)
        assert hub._hub_http_retries() == 3
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", "0")
        assert hub._hub_http_retries() == 0
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", "x")
        assert hub._hub_http_retries() == 3

    def test_backoff_base_and_cap(self, monkeypatch):
        monkeypatch.delenv(
            "QWENPAW_SKILLS_HUB_HTTP_BACKOFF_BASE",
            raising=False,
        )
        monkeypatch.delenv(
            "QWENPAW_SKILLS_HUB_HTTP_BACKOFF_CAP",
            raising=False,
        )
        assert hub._hub_http_backoff_base() == 0.8
        assert hub._hub_http_backoff_cap() == 6.0
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_BASE", "0.05")
        assert hub._hub_http_backoff_base() == 0.1  # clamped
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_BASE", "2")
        assert hub._hub_http_backoff_base() == 2.0
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_BASE", "bad")
        assert hub._hub_http_backoff_base() == 0.8
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_CAP", "0.1")
        assert hub._hub_http_backoff_cap() == 0.5  # clamped
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_CAP", "bad")
        assert hub._hub_http_backoff_cap() == 6.0

    def test_compute_backoff_seconds(self, monkeypatch):
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_BASE", "1")
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_BACKOFF_CAP", "10")
        assert hub._compute_backoff_seconds(1) == 1.0
        assert hub._compute_backoff_seconds(2) == 2.0
        assert hub._compute_backoff_seconds(3) == 4.0
        assert hub._compute_backoff_seconds(10) == 10.0  # capped
        assert hub._compute_backoff_seconds(0) == 1.0  # attempt clamped >=0

    def test_hub_url_builders(self, monkeypatch):
        monkeypatch.delenv("QWENPAW_SKILLS_HUB_BASE_URL", raising=False)
        assert hub._hub_base_url() == "https://clawhub.ai"
        assert hub._hub_search_path() == "/api/v1/search"
        assert "{slug}" in hub._hub_version_path()
        assert "{slug}" in hub._hub_detail_path()
        assert "{slug}" in hub._hub_file_path()
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_BASE_URL", "http://h/")
        assert hub._hub_base_url() == "http://h/"

    def test_join_url(self):
        assert hub._join_url("https://a.b/", "/x") == "https://a.b/x"
        assert hub._join_url("https://a.b", "x") == "https://a.b/x"


# ---------------------------------------------------------------------------
# Cancellation hooks
# ---------------------------------------------------------------------------


class TestCancellation:
    def test_no_checker_noop(self):
        hub._ensure_not_cancelled()  # must not raise

    def test_checker_true_raises(self):
        with hub._with_cancel_checker(lambda: True):
            with pytest.raises(SkillImportCancelled):
                hub._ensure_not_cancelled()

    def test_checker_false_ok(self):
        with hub._with_cancel_checker(lambda: False):
            hub._ensure_not_cancelled()

    def test_checker_restored_after_context(self):
        with hub._with_cancel_checker(lambda: True):
            pass
        hub._ensure_not_cancelled()  # checker gone again

    def test_checker_exception_swallowed(self):
        def _boom():
            raise RuntimeError("checker exploded")

        with hub._with_cancel_checker(_boom):
            hub._ensure_not_cancelled()  # must not raise


# ---------------------------------------------------------------------------
# GitHub response cache
# ---------------------------------------------------------------------------


class TestGithubCache:
    def test_set_and_get(self):
        hub._github_cache_set("k", {"v": 1})
        assert hub._github_cache_get("k") == {"v": 1}

    def test_get_expired(self):
        hub._github_cache["k"] = (time.monotonic() - 10**6, "old")
        assert hub._github_cache_get("k") is None
        assert "k" not in hub._github_cache

    def test_has_miss_sentinel(self):
        assert hub._github_cached("missing") is hub._GITHUB_CACHE_MISS

    def test_prune_expired(self):
        hub._github_cache["old"] = (time.monotonic() - 10**6, "x")
        hub._github_cache["fresh"] = (time.monotonic(), "y")
        hub._github_cache_prune()
        assert "old" not in hub._github_cache
        assert "fresh" in hub._github_cache

    def test_prune_lru_cap(self, monkeypatch):
        monkeypatch.setattr(hub, "_GITHUB_CACHE_MAX_ENTRIES", 2)
        now = time.monotonic()
        hub._github_cache["a"] = (now, 1)
        hub._github_cache["b"] = (now, 2)
        hub._github_cache["c"] = (now, 3)
        hub._github_cache_prune()
        assert len(hub._github_cache) == 2
        assert "a" not in hub._github_cache

    def test_set_triggers_prune_over_cap(self, monkeypatch):
        monkeypatch.setattr(hub, "_GITHUB_CACHE_MAX_ENTRIES", 1)
        hub._github_cache_set("a", 1)
        hub._github_cache_set("b", 2)
        assert len(hub._github_cache) <= 2

    def test_cache_lock_cleanup(self):
        async def _go():
            async with hub._github_cache_lock("k"):
                assert "k" in hub._github_cache_key_locks
            assert "k" not in hub._github_cache_key_locks

        _run(_go())

    def test_cached_call_hit(self):
        hub._github_cache_set("k", "cached")
        calls = []

        async def _factory():
            calls.append(1)
            return "fresh"

        assert _run(hub._github_cached_call("k", _factory)) == "cached"
        assert calls == []

    def test_cached_call_miss_then_factory(self):
        calls = []

        async def _factory():
            calls.append(1)
            return "fresh"

        assert _run(hub._github_cached_call("k", _factory)) == "fresh"
        assert calls == [1]
        assert hub._github_cache_get("k") == "fresh"

    def test_cached_call_thundering_herd_single_fetch(self):
        calls = []

        async def _factory():
            calls.append(1)
            await asyncio.sleep(0.02)
            return "value"

        async def _go():
            return await asyncio.gather(
                hub._github_cached_call("k", _factory),
                hub._github_cached_call("k", _factory),
            )

        results = _run(_go())
        assert results == ["value", "value"]
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Shared client / request tracking / close
# ---------------------------------------------------------------------------


class TestClientLifecycle:
    def test_build_async_client(self):
        client = hub._build_async_client()
        assert isinstance(client, httpx.AsyncClient)

    def test_get_async_client_singleton(self):
        async def _go():
            hub._async_client = None
            c1 = await hub._get_async_client()
            c2 = await hub._get_async_client()
            assert c1 is c2
            await c1.aclose()

        _run(_go())

    def test_get_async_client_rebuilds_after_close(self):
        async def _go():
            hub._async_client = None
            c1 = await hub._get_async_client()
            await c1.aclose()
            c2 = await hub._get_async_client()
            assert c2 is not c1
            await c2.aclose()

        _run(_go())

    def test_track_request_counts(self):
        async def _go():
            assert hub._in_flight == 0
            async with hub._track_request():
                assert hub._in_flight == 1
                assert not hub._drain_event.is_set()
            assert hub._in_flight == 0
            assert hub._drain_event.is_set()

        _run(_go())

    def test_track_request_counts_on_error(self):
        async def _go():
            with pytest.raises(RuntimeError):
                async with hub._track_request():
                    raise RuntimeError("boom")
            assert hub._in_flight == 0
            assert hub._drain_event.is_set()

        _run(_go())

    def test_aclose_hub_client_no_client(self):
        async def _go():
            hub._async_client = None
            await hub.aclose_hub_client()
            assert hub._async_client is None

        _run(_go())

    def test_aclose_hub_client_closes_open(self):
        async def _go():
            hub._async_client = None
            client = await hub._get_async_client()
            await hub.aclose_hub_client()
            assert client.is_closed
            assert hub._async_client is None

        _run(_go())

    def test_aclose_hub_client_drain_timeout_warns(self, monkeypatch):
        async def _wait_for(fut, timeout=None):
            raise asyncio.TimeoutError

        monkeypatch.setattr(hub.asyncio, "wait_for", _wait_for)

        async def _go():
            hub._async_client = None
            await hub.aclose_hub_client()

        _run(_go())  # must not raise


# ---------------------------------------------------------------------------
# HTTP primitives: _maybe_retry / headers / limits / streaming
# ---------------------------------------------------------------------------


class TestMaybeRetry:
    def test_no_retry_when_exhausted(self):
        result = _run(
            hub._maybe_retry(3, 3, "http://x", RuntimeError("e"), "reason"),
        )
        assert result is False

    def test_retry_sleeps_and_returns_true(self, monkeypatch):
        sleeps = []

        async def _fake_sleep(delay):
            sleeps.append(delay)

        monkeypatch.setattr(hub.asyncio, "sleep", _fake_sleep)
        monkeypatch.setattr(hub, "_compute_backoff_seconds", lambda a: 0.01)
        result = _run(
            hub._maybe_retry(1, 3, "http://x", RuntimeError("e"), "reason"),
        )
        assert result is True
        assert sleeps == [0.01]

    def test_retry_checks_cancellation(self, monkeypatch):
        async def _fake_sleep(delay):
            pass

        monkeypatch.setattr(hub.asyncio, "sleep", _fake_sleep)
        with hub._with_cancel_checker(lambda: True):
            with pytest.raises(SkillImportCancelled):
                _run(
                    hub._maybe_retry(
                        1,
                        3,
                        "http://x",
                        RuntimeError("e"),
                        "reason",
                    ),
                )


class TestRequestHeaders:
    def test_accept_header(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.delenv("GH_TOKEN", raising=False)
        headers = hub._request_headers("https://api.github.com/x", "app/json")
        assert headers == {"Accept": "app/json"}

    def test_github_token_added(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok-1")
        headers = hub._request_headers("https://api.github.com/x", "a")
        assert headers["Authorization"] == "Bearer tok-1"

    def test_token_not_added_for_other_hosts(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok-1")
        headers = hub._request_headers("https://example.com/x", "a")
        assert "Authorization" not in headers

    def test_gh_token_fallback(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        monkeypatch.setenv("GH_TOKEN", "tok-2")
        headers = hub._request_headers("https://api.github.com/x", "a")
        assert headers["Authorization"] == "Bearer tok-2"


class TestCheckMaxBytes:
    def test_within_limit(self):
        hub._check_max_bytes("http://x", 10, 100)  # no raise

    def test_over_limit(self):
        with pytest.raises(SkillsError, match="too large"):
            hub._check_max_bytes("http://x", 101, 100)

    def test_none_values_skipped(self):
        hub._check_max_bytes("http://x", None, None)
        hub._check_max_bytes("http://x", 999, None)


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        content: bytes = b"",
        headers: dict | None = None,
        url: str = "http://x.test/data",
    ):
        self.status_code = status_code
        self._content = content
        self.headers = headers or {}
        self.request = httpx.Request("GET", url)

    async def aread(self) -> bytes:
        return self._content

    async def aiter_bytes(self, chunk_size=None):
        yield self._content

    @property
    def content(self) -> bytes:
        return self._content

    @property
    def text(self) -> str:
        return self._content.decode("utf-8", errors="replace")


class _StreamCtx:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    async def __aexit__(self, *args):
        return False


class _FakeClient:
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls = 0

    def stream(self, method, url, **kwargs):
        self.calls += 1
        return _StreamCtx(self._responses.pop(0))


@pytest.fixture()
def no_sleep(monkeypatch):
    async def _fake_sleep(delay):
        pass

    monkeypatch.setattr(hub.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(hub, "_compute_backoff_seconds", lambda a: 0.0)


class TestHttpFetch:
    def _fetch(self, client, url="http://x.test/data", **kwargs):
        async def _fake_client():
            return client

        with patch.object(hub, "_get_async_client", _fake_client):
            return _run(hub._http_fetch(url, **kwargs))

    def test_success(self):
        client = _FakeClient(
            [_FakeResponse(200, b"hello", {"Content-Length": "5"})],
        )
        assert self._fetch(client) == b"hello"

    def test_invalid_max_bytes(self):
        with pytest.raises(ConfigurationException):
            self._fetch(_FakeClient([]), max_bytes=0)

    def test_content_length_over_limit(self):
        client = _FakeClient(
            [_FakeResponse(200, b"x" * 10, {"Content-Length": "10"})],
        )
        with pytest.raises(SkillsError, match="too large"):
            self._fetch(client, max_bytes=5)

    def test_streaming_over_limit(self):
        client = _FakeClient([_FakeResponse(200, b"x" * 10)])
        with pytest.raises(SkillsError, match="exceeded limit"):
            self._fetch(client, max_bytes=5)

    def test_truncated_response(self, no_sleep, monkeypatch):
        # RemoteProtocolError is retryable; exhaust retries with one response.
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", "0")
        client = _FakeClient(
            [_FakeResponse(200, b"abc", {"Content-Length": "10"})],
        )
        with pytest.raises(httpx.RemoteProtocolError):
            self._fetch(client)

    def test_truncation_check_skipped_with_content_encoding(self):
        client = _FakeClient(
            [
                _FakeResponse(
                    200,
                    b"abc",
                    {"Content-Length": "10", "Content-Encoding": "gzip"},
                ),
            ],
        )
        assert self._fetch(client) == b"abc"

    def test_truncation_check_skipped_with_transfer_encoding(self):
        client = _FakeClient(
            [
                _FakeResponse(
                    200,
                    b"abc",
                    {"Content-Length": "10", "Transfer-Encoding": "chunked"},
                ),
            ],
        )
        assert self._fetch(client) == b"abc"

    def test_bad_content_length_ignored(self):
        client = _FakeClient(
            [_FakeResponse(200, b"abc", {"Content-Length": "abc"})],
        )
        assert self._fetch(client) == b"abc"

    def test_4xx_raises(self):
        client = _FakeClient([_FakeResponse(404, b"nope")])
        with pytest.raises(httpx.HTTPStatusError):
            self._fetch(client)

    def test_github_403_rate_limit(self):
        client = _FakeClient(
            [
                _FakeResponse(
                    403,
                    b'{"message": "API rate limit exceeded"}',
                    url="https://api.github.com/repos/x/y",
                ),
            ],
        )
        with pytest.raises(SkillsError, match="rate limit"):
            self._fetch(client, url="https://api.github.com/repos/x/y")

    def test_429_after_retries_with_github_hint(self, no_sleep, monkeypatch):
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", "1")
        client = _FakeClient(
            [_FakeResponse(429, b"slow down"), _FakeResponse(429, b"again")],
        )
        with pytest.raises(SkillsError, match="429") as exc:
            self._fetch(client, url="https://api.github.com/repos/x/y")
        assert "GITHUB_TOKEN" in str(exc.value)

    def test_429_non_github_no_hint(self, no_sleep, monkeypatch):
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", "0")
        client = _FakeClient([_FakeResponse(429, b"slow")])
        with pytest.raises(SkillsError, match="429") as exc:
            self._fetch(client, url="https://example.com/x")
        assert "GITHUB_TOKEN" not in str(exc.value)

    def test_5xx_after_retries(self, no_sleep, monkeypatch):
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", "0")
        client = _FakeClient([_FakeResponse(500, b"boom")])
        with pytest.raises(SkillsError, match="500"):
            self._fetch(client)

    def test_retryable_then_success(self, no_sleep, monkeypatch):
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", "1")
        client = _FakeClient(
            [
                _FakeResponse(503, b"unavailable"),
                _FakeResponse(200, b"ok", {"Content-Length": "2"}),
            ],
        )
        assert self._fetch(client) == b"ok"
        assert client.calls == 2

    def test_transport_error_retried(self, no_sleep, monkeypatch):
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", "1")
        client = _FakeClient(
            [
                httpx.ConnectError("conn refused"),
                _FakeResponse(200, b"ok", {"Content-Length": "2"}),
            ],
        )
        assert self._fetch(client) == b"ok"

    def test_transport_error_exhausted(self, no_sleep, monkeypatch):
        monkeypatch.setenv("QWENPAW_SKILLS_HUB_HTTP_RETRIES", "0")
        client = _FakeClient([httpx.ConnectError("conn refused")])
        with pytest.raises(httpx.ConnectError):
            self._fetch(client)

    def test_cancel_before_fetch(self):
        with hub._with_cancel_checker(lambda: True):
            with pytest.raises(SkillImportCancelled):
                self._fetch(_FakeClient([]))

    def test_custom_timeout_accepted(self):
        client = _FakeClient(
            [_FakeResponse(200, b"ok", {"Content-Length": "2"})],
        )
        assert self._fetch(client, timeout=5.0) == b"ok"


class TestStreamToBytes:
    def test_empty_chunks_skipped(self):
        class _Resp:
            headers = {}
            request = httpx.Request("GET", "http://x")

            async def aiter_bytes(self, chunk_size=None):
                yield b""
                yield b"ab"

        out = _run(
            hub._stream_to_bytes(
                _Resp(),
                full_url="http://x",
                max_bytes=None,
                expected_length=None,
            ),
        )
        assert out == b"ab"

    def test_cancel_mid_stream(self):
        class _Resp:
            headers = {}
            request = httpx.Request("GET", "http://x")

            async def aiter_bytes(self, chunk_size=None):
                yield b"ab"

        with hub._with_cancel_checker(lambda: True):
            with pytest.raises(SkillImportCancelled):
                _run(
                    hub._stream_to_bytes(
                        _Resp(),
                        full_url="http://x",
                        max_bytes=None,
                        expected_length=None,
                    ),
                )


class TestHttpWrappers:
    def _patch_fetch(self, payload):
        async def _fake_fetch(
            url,
            params=None,
            accept="application/json",
            max_bytes=None,
            timeout=None,
        ):
            return payload

        return patch.object(hub, "_http_fetch", _fake_fetch)

    def test_http_get_decodes(self):
        with self._patch_fetch("héllo".encode("utf-8")):
            assert _run(hub._http_get("http://x")) == "héllo"

    def test_http_bytes_get(self):
        with self._patch_fetch(b"\x00\x01"):
            assert _run(hub._http_bytes_get("http://x")) == b"\x00\x01"

    def test_http_json_get(self):
        with self._patch_fetch(json.dumps({"a": 1}).encode()):
            assert _run(hub._http_json_get("http://x")) == {"a": 1}

    def test_http_text_get(self):
        with self._patch_fetch(b"plain"):
            assert _run(hub._http_text_get("http://x")) == "plain"

    def test_public_alias(self):
        assert hub.http_json_get is hub._http_json_get


# ---------------------------------------------------------------------------
# Search normalization
# ---------------------------------------------------------------------------


class TestNormSearchItems:
    def test_list_input(self):
        assert hub._norm_search_items([{"a": 1}, "x"]) == [{"a": 1}]

    def test_dict_with_items_key(self):
        for key in ("items", "skills", "results", "data"):
            assert hub._norm_search_items({key: [{"n": 1}]}) == [{"n": 1}]

    def test_single_skill_dict(self):
        assert hub._norm_search_items({"name": "a", "slug": "b"}) == [
            {"name": "a", "slug": "b"},
        ]

    def test_other(self):
        assert hub._norm_search_items({"x": 1}) == []
        assert hub._norm_search_items(None) == []
        assert hub._norm_search_items("str") == []


# ---------------------------------------------------------------------------
# Bundle tree helpers
# ---------------------------------------------------------------------------


class TestSafePathParts:
    @pytest.mark.parametrize(
        "path,expected",
        [
            ("a/b/c", ["a", "b", "c"]),
            ("a//b", ["a", "b"]),
            ("", None),
            ("/abs", None),
            ("a/./b", None),
            ("a/../b", None),
            ("//", None),
        ],
    )
    def test_paths(self, path, expected):
        assert hub._safe_path_parts(path) == expected


class TestTreeInsert:
    def test_nested(self):
        tree: dict = {}
        hub._tree_insert(tree, ["a", "b", "c.md"], "content")
        assert tree == {"a": {"b": {"c.md": "content"}}}

    def test_overwrites_non_dict_child(self):
        tree: dict = {"a": "leaf"}
        hub._tree_insert(tree, ["a", "b"], "x")
        assert tree == {"a": {"b": "x"}}


class TestFilesToTree:
    def test_split_references_scripts(self):
        files = {
            "references/r1.md": "r",
            "scripts/s1.py": "s",
            "SKILL.md": "m",
            "other.txt": "o",
        }
        refs, scripts = hub._files_to_tree(files)
        assert refs == {"r1.md": "r"}
        assert scripts == {"s1.py": "s"}

    def test_bad_entries_skipped(self):
        files = {"/bad": "x", "..": "y", "references": "top-only"}
        refs, scripts = hub._files_to_tree(files)
        assert refs == {}
        assert scripts == {}

    def test_non_string_skipped(self):
        refs, scripts = hub._files_to_tree({1: "x", "a": 2})  # type: ignore
        assert refs == {}
        assert scripts == {}


class TestSanitizeTree:
    def test_filters_bad_keys(self):
        tree = {
            "ok": "v",
            ".": "x",
            "..": "y",
            "a/b": "z",
            "a\\b": "w",
            "nested": {"k": "v", 1: "bad"},
            "num": 5,
        }
        out = hub._sanitize_tree(tree)
        assert out == {"ok": "v", "nested": {"k": "v"}}

    def test_non_dict(self):
        assert hub._sanitize_tree("x") == {}
        assert hub._sanitize_tree(None) == {}


class TestBundleHasContent:
    @pytest.mark.parametrize(
        "payload,expected",
        [
            ({"content": "x"}, True),
            ({"skill_md": "x"}, True),
            ({"skillMd": "x"}, True),
            ({"content": "  "}, False),
            ({"files": {"SKILL.md": "x"}}, True),
            ({"files": {"SKILL.md": 1}}, False),
            ({"files": "nope"}, False),
            ({}, False),
            ("notdict", False),
        ],
    )
    def test_variants(self, payload, expected):
        assert hub._bundle_has_content(payload) == expected


class TestExtractVersionHint:
    def test_requested_version_wins(self):
        assert hub._extract_version_hint({}, "v1") == "v1"

    def test_latest_version_dict(self):
        detail = {"latestVersion": {"version": "2.0"}}
        assert hub._extract_version_hint(detail, "") == "2.0"

    def test_skill_tags_latest(self):
        detail = {"skill": {"tags": {"latest": "3.0"}}}
        assert hub._extract_version_hint(detail, "") == "3.0"

    def test_nothing(self):
        assert hub._extract_version_hint({}, "") == ""
        assert hub._extract_version_hint({"latestVersion": "x"}, "") == ""
        assert hub._extract_version_hint({"skill": {}}, "") == ""


class TestNormalizeBundle:
    def test_full_bundle(self):
        data = {
            "name": "demo",
            "content": SKILL_MD,
            "references": {"r.md": "ref"},
            "scripts": {"s.py": "script"},
        }
        name, content, refs, scripts, extra = hub._normalize_bundle(data)
        assert name == "demo"
        assert content == SKILL_MD
        assert refs == {"r.md": "ref"}
        assert scripts == {"s.py": "script"}
        assert extra == {}

    def test_files_fallback(self):
        data = {
            "files": {
                "SKILL.md": SKILL_MD,
                "references/a.md": "r",
                "scripts/b.py": "s",
                "assets/c.txt": "c",
            },
        }
        name, content, refs, scripts, extra = hub._normalize_bundle(data)
        assert name == "demo-skill"  # from frontmatter
        assert content == SKILL_MD
        assert refs == {"a.md": "r"}
        assert scripts == {"b.py": "s"}
        assert extra == {"assets": {"c.txt": "c"}}

    def test_existing_trees_win_over_files(self):
        data = {
            "content": SKILL_MD,
            "name": "x",
            "references": {"keep.md": "k"},
            "files": {"references/other.md": "o"},
        }
        _, _, refs, _, _ = hub._normalize_bundle(data)
        assert refs == {"keep.md": "k"}

    def test_skill_wrapped_payload(self):
        data = {"skill": {"name": "wrapped", "content": SKILL_MD}}
        name, content, _, _, _ = hub._normalize_bundle(data)
        assert name == "wrapped"

    def test_non_dict_raises(self):
        with pytest.raises(SkillsError, match="not a valid JSON object"):
            hub._normalize_bundle([1, 2])

    def test_missing_content_raises(self):
        with pytest.raises(SkillsError, match="missing SKILL.md"):
            hub._normalize_bundle({"name": "x"})

    def test_missing_name_raises(self):
        with pytest.raises(SkillsError, match="missing skill name"):
            hub._normalize_bundle({"content": "no frontmatter here"})

    def test_bad_yaml_frontmatter_name_empty(self):
        with pytest.raises(SkillsError, match="missing skill name"):
            hub._normalize_bundle({"content": "---\n: bad: [yaml\n---\n"})

    def test_non_string_name_ignored(self):
        data = {"name": 123, "content": SKILL_MD}
        name, _, _, _, _ = hub._normalize_bundle(data)
        assert name == "demo-skill"

    def test_non_string_content_treated_empty(self):
        data = {"content": 5, "files": {"SKILL.md": SKILL_MD}, "name": "n"}
        _, content, _, _, _ = hub._normalize_bundle(data)
        assert content == SKILL_MD

    def test_files_bad_entries_skipped(self):
        data = {
            "name": "n",
            "content": SKILL_MD,
            "files": {"../evil": "x", 1: 2, "SKILL.md": "y"},
        }
        _, _, _, _, extra = hub._normalize_bundle(data)
        assert extra == {}


# ---------------------------------------------------------------------------
# Text & name helpers
# ---------------------------------------------------------------------------


class TestNameHelpers:
    def test_safe_fallback_name(self):
        assert hub._safe_fallback_name("My Skill!") == "My-Skill"
        assert hub._safe_fallback_name("///") == "imported-skill"

    def test_normalize_skill_key(self):
        assert hub._normalize_skill_key("Excel / XLSX") == "excel-xlsx"
        assert hub._normalize_skill_key("--a--") == "a"

    def test_sanitize_skill_dir_name(self):
        assert hub._sanitize_skill_dir_name("plain") == "plain"
        assert hub._sanitize_skill_dir_name("Excel / XLSX") == "excel-xlsx"
        assert hub._sanitize_skill_dir_name("") == "imported-skill"
        assert (
            hub._sanitize_skill_dir_name(None) == "imported-skill"
        )  # type: ignore

    def test_is_http_url(self):
        assert hub._is_http_url("https://a.b/c") is True
        assert hub._is_http_url("http://a.b") is True
        assert hub._is_http_url("ftp://a.b") is False
        assert hub._is_http_url("not a url") is False

    def test_is_probably_text_blob(self):
        assert hub._is_probably_text_blob(b"") is True
        assert hub._is_probably_text_blob(b"hello world") is True
        assert hub._is_probably_text_blob(b"\x00\x01binary") is False

    def test_extract_error_message_from_payload(self):
        assert hub._extract_error_message_from_payload(b"") == ""
        assert hub._extract_error_message_from_payload(b"\x00\x01") == ""
        assert (
            hub._extract_error_message_from_payload(b"plain error")
            == "plain error"
        )
        assert (
            hub._extract_error_message_from_payload(
                json.dumps({"error": "bad thing"}).encode(),
            )
            == "bad thing"
        )
        assert (
            hub._extract_error_message_from_payload(
                json.dumps({"message": "msg"}).encode(),
            )
            == "msg"
        )
        assert (
            hub._extract_error_message_from_payload(
                json.dumps({"other": 1}).encode(),
            )
            == '{"other": 1}'
        )
        assert hub._extract_error_message_from_payload(b"   ") == ""

    def test_format_http_error_body(self):
        request = httpx.Request("GET", "http://x")
        response = httpx.Response(
            500,
            content=b'{"error": "server exploded"}',
            request=request,
        )
        err = httpx.HTTPStatusError(
            "HTTP 500",
            request=request,
            response=response,
        )
        assert hub._format_http_error_body(err) == "server exploded"

    def test_format_http_error_body_empty(self):
        request = httpx.Request("GET", "http://x")
        response = httpx.Response(500, content=b"", request=request)
        err = httpx.HTTPStatusError(
            "HTTP 500",
            request=request,
            response=response,
        )
        assert hub._format_http_error_body(err) == str(err)


# ---------------------------------------------------------------------------
# Provider URL parsers
# ---------------------------------------------------------------------------


class TestUrlParsers:
    def test_clawhub_slug(self):
        assert (
            hub._extract_clawhub_slug_from_url("https://clawhub.ai/skills/foo")
            == "foo"
        )
        assert (
            hub._extract_clawhub_slug_from_url("https://clawhub.ai/owner/bar")
            == "bar"
        )
        assert hub._extract_clawhub_slug_from_url("https://clawhub.ai/") == ""
        assert (
            hub._extract_clawhub_slug_from_url("https://other.ai/skills/foo")
            == ""
        )

    def test_skills_sh_spec(self):
        assert hub._extract_skills_sh_spec(
            "https://skills.sh/owner/repo/skill",
        ) == ("owner", "repo", "skill")
        assert hub._extract_skills_sh_spec("https://www.skills.sh/o/r/s") == (
            "o",
            "r",
            "s",
        )
        assert hub._extract_skills_sh_spec("https://skills.sh/o/r") is None
        assert hub._extract_skills_sh_spec("https://other.sh/o/r/s") is None
        assert hub._extract_skills_sh_spec("https://skills.sh//r/s") is None

    def test_skillsmp_slug(self):
        assert (
            hub._extract_skillsmp_slug(
                "https://skillsmp.com/skills/abc-skill-md",
            )
            == "abc-skill-md"
        )
        assert (
            hub._extract_skillsmp_slug(
                "https://www.skillsmp.com/skills/x",
            )
            == "x"
        )
        assert hub._extract_skillsmp_slug("https://skillsmp.com/") == ""
        assert hub._extract_skillsmp_slug("https://skillsmp.com/other/x") == ""
        assert hub._extract_skillsmp_slug("https://other.com/skills/x") == ""

    def test_lobehub_identifier(self):
        assert (
            hub._extract_lobehub_identifier(
                "https://lobehub.com/skills/my-skill",
            )
            == "my-skill"
        )
        assert (
            hub._extract_lobehub_identifier(
                "https://market.lobehub.com/api/v1/skills/sk1/download",
            )
            == "sk1"
        )
        assert hub._extract_lobehub_identifier("https://lobehub.com/") == ""
        assert (
            hub._extract_lobehub_identifier("https://lobehub.com/other/x")
            == ""
        )
        assert (
            hub._extract_lobehub_identifier(
                "https://market.lobehub.com/api/v1/skills/sk1",
            )
            == ""
        )
        assert hub._extract_lobehub_identifier("https://unknown.com/a") == ""

    def test_modelscope_spec(self):
        assert hub._extract_modelscope_skill_spec(
            "https://modelscope.cn/skills/@owner/name",
        ) == ("@owner", "name", "")
        assert hub._extract_modelscope_skill_spec(
            "https://www.modelscope.cn/skills/o/n/archive/zip/master.zip",
        ) == ("o", "n", "master")
        assert hub._extract_modelscope_skill_spec(
            "https://modelscope.cn/skills/o/n/archive/zip/v1",
        ) == ("o", "n", "v1")
        assert (
            hub._extract_modelscope_skill_spec(
                "https://modelscope.cn/other/o/n",
            )
            is None
        )
        assert (
            hub._extract_modelscope_skill_spec(
                "https://modelscope.cn/skills/o",
            )
            is None
        )
        assert (
            hub._extract_modelscope_skill_spec(
                "https://modelscope.cn/skills//n",
            )
            is None
        )
        assert (
            hub._extract_modelscope_skill_spec("https://x.cn/skills/o/n")
            is None
        )

    def test_qwenpaw_spec(self):
        uuid = "12345678-1234-1234-1234-123456789abc"
        assert hub._extract_qwenpaw_skill_spec(
            f"https://platform.agentscope.io/skills/{uuid}",
        ) == ("", uuid, "")
        assert hub._extract_qwenpaw_skill_spec(
            "https://platform.agentscope.io/skills/@owner/name",
        ) == ("@owner", "name", "")
        assert hub._extract_qwenpaw_skill_spec(
            "https://platform.agentscope.io/skills/o/n/archive/zip/v2.zip",
        ) == ("o", "n", "v2")
        assert (
            hub._extract_qwenpaw_skill_spec(
                "https://platform.agentscope.io/skills/onlyone",
            )
            is None
        )
        assert (
            hub._extract_qwenpaw_skill_spec(
                "https://platform.agentscope.io/other/x",
            )
            is None
        )
        assert (
            hub._extract_qwenpaw_skill_spec(
                "https://platform.agentscope.io/skills//n",
            )
            is None
        )
        assert (
            hub._extract_qwenpaw_skill_spec("https://other.io/skills/x")
            is None
        )

    def test_aliyun_spec(self):
        assert (
            hub._extract_aliyun_skill_spec(
                "https://api.aliyun.com/agentexplorer/skills/sk-1",
            )
            == "sk-1"
        )
        assert (
            hub._extract_aliyun_skill_spec(
                "https://api.aliyun.com/AgentExplorer/Skills/sk-2",
            )
            == "sk-2"
        )
        assert (
            hub._extract_aliyun_skill_spec("https://api.aliyun.com/x") is None
        )
        assert (
            hub._extract_aliyun_skill_spec(
                "https://api.aliyun.com/agentexplorer/other/sk",
            )
            is None
        )
        assert (
            hub._extract_aliyun_skill_spec("https://other.com/a/b/c") is None
        )

    def test_github_spec(self):
        assert hub._extract_github_spec(
            "https://github.com/owner/repo",
        ) == ("owner", "repo", "", "")
        assert hub._extract_github_spec(
            "https://github.com/owner/repo/tree/dev/skills/x",
        ) == ("owner", "repo", "dev", "skills/x")
        assert hub._extract_github_spec(
            "https://github.com/owner/repo/blob/main/a.md",
        ) == ("owner", "repo", "main", "a.md")
        assert hub._extract_github_spec(
            "https://github.com/owner/repo/extra",
        ) == ("owner", "repo", "", "extra")
        assert hub._extract_github_spec("https://github.com/owner") is None
        assert hub._extract_github_spec("https://gitlab.com/o/r") is None

    def test_resolve_clawhub_slug(self):
        assert (
            hub._resolve_clawhub_slug("https://clawhub.ai/skills/s1") == "s1"
        )
        assert hub._resolve_clawhub_slug("https://other.ai/x") == ""


# ---------------------------------------------------------------------------
# GitHub URL helpers & path helpers
# ---------------------------------------------------------------------------


class TestGithubHelpers:
    def test_api_url(self):
        assert (
            hub._github_api_url("o", "r", "")
            == "https://api.github.com/repos/o/r"
        )
        assert (
            hub._github_api_url("o", "r", "/contents/x")
            == "https://api.github.com/repos/o/r/contents/x"
        )

    def test_encode_path(self):
        assert hub._github_encode_path("") == ""
        assert hub._github_encode_path("a b/c") == "a%20b/c"
        assert hub._github_encode_path("/lead/") == "lead"

    def test_join_repo_path(self):
        assert hub._join_repo_path("", "leaf") == "leaf"
        assert hub._join_repo_path("root/", "/leaf") == "root/leaf"

    def test_relative_from_root(self):
        assert hub._relative_from_root("/x/y", "") == "x/y"
        assert hub._relative_from_root("root/a/b", "root") == "a/b"
        assert hub._relative_from_root("other/a", "root") == "other/a"


# ---------------------------------------------------------------------------
# GitHub API functions (mocked HTTP)
# ---------------------------------------------------------------------------


class TestGithubApiFunctions:
    def _patch_json(self, monkeypatch, handler):
        async def _fake(url, params=None, timeout=None):
            return handler(url, params)

        monkeypatch.setattr(hub, "_http_json_get", _fake)

    def test_repo_exists_true(self, monkeypatch):
        self._patch_json(monkeypatch, lambda u, p: {"full_name": "o/r"})
        assert _run(hub._github_repo_exists("o", "r")) is True

    def test_repo_exists_false_on_error(self, monkeypatch):
        async def _fake(url, params=None, timeout=None):
            raise httpx.HTTPStatusError(
                "404",
                request=httpx.Request("GET", url),
                response=httpx.Response(404),
            )

        monkeypatch.setattr(hub, "_http_json_get", _fake)
        assert _run(hub._github_repo_exists("o", "r")) is False

    def test_repo_exists_empty_args(self):
        assert _run(hub._github_repo_exists("", "r")) is False

    def test_repo_exists_bad_payload(self, monkeypatch):
        self._patch_json(monkeypatch, lambda u, p: [1, 2])
        assert _run(hub._github_repo_exists("o", "r")) is False

    def test_default_branch_from_meta(self, monkeypatch):
        self._patch_json(monkeypatch, lambda u, p: {"default_branch": "dev"})
        assert _run(hub._github_get_default_branch("o", "r")) == "dev"

    def test_default_branch_fallback_main(self, monkeypatch):
        self._patch_json(monkeypatch, lambda u, p: {})
        assert _run(hub._github_get_default_branch("o", "r")) == "main"

    def test_list_skill_md_roots(self, monkeypatch):
        tree = {
            "tree": [
                {"path": "SKILL.md"},
                {"path": "skills/a/SKILL.md"},
                {"path": "skills/a/other.md"},
                {"path": "skills/a/SKILL.md"},  # duplicate root
                "not-a-dict",
                {"path": 5},
            ],
        }
        self._patch_json(monkeypatch, lambda u, p: tree)
        roots = _run(hub._github_list_skill_md_roots("o", "r", "main"))
        assert roots == ["", "skills/a"]

    def test_list_skill_md_roots_404(self, monkeypatch):
        async def _fake(url, params=None, timeout=None):
            raise httpx.HTTPStatusError(
                "404",
                request=httpx.Request("GET", url),
                response=httpx.Response(404),
            )

        monkeypatch.setattr(hub, "_http_json_get", _fake)
        assert _run(hub._github_list_skill_md_roots("o", "r", "main")) == []

    def test_list_skill_md_roots_other_error_raises(self, monkeypatch):
        async def _fake(url, params=None, timeout=None):
            raise httpx.HTTPStatusError(
                "500",
                request=httpx.Request("GET", url),
                response=httpx.Response(500),
            )

        monkeypatch.setattr(hub, "_http_json_get", _fake)
        with pytest.raises(httpx.HTTPStatusError):
            _run(hub._github_list_skill_md_roots("o", "r", "main"))

    def test_list_skill_md_roots_bad_shape(self, monkeypatch):
        self._patch_json(monkeypatch, lambda u, p: "nope")
        assert _run(hub._github_list_skill_md_roots("o", "r", "main")) == []
        hub._github_cache.clear()
        self._patch_json(monkeypatch, lambda u, p: {"tree": "x"})
        assert _run(hub._github_list_skill_md_roots("o", "r", "main")) == []

    def test_get_content_entry(self, monkeypatch):
        self._patch_json(monkeypatch, lambda u, p: {"type": "file"})
        entry = _run(hub._github_get_content_entry("o", "r", "a b", "main"))
        assert entry == {"type": "file"}

    def test_get_content_entry_bad_shape(self, monkeypatch):
        self._patch_json(monkeypatch, lambda u, p: [1])
        with pytest.raises(SkillsError, match="Unexpected GitHub response"):
            _run(hub._github_get_content_entry("o", "r", "p", "main"))

    def test_get_dir_entries(self, monkeypatch):
        self._patch_json(monkeypatch, lambda u, p: [{"type": "file"}, "x"])
        entries = _run(hub._github_get_dir_entries("o", "r", "d", "main"))
        assert entries == [{"type": "file"}]

    def test_get_dir_entries_root_path(self, monkeypatch):
        urls = []

        async def _fake(url, params=None, timeout=None):
            urls.append(url)
            return []

        monkeypatch.setattr(hub, "_http_json_get", _fake)
        _run(hub._github_get_dir_entries("o", "r", "", "main"))
        assert urls[0].endswith("/contents")

    def test_get_dir_entries_non_list(self, monkeypatch):
        self._patch_json(monkeypatch, lambda u, p: {"x": 1})
        assert _run(hub._github_get_dir_entries("o", "r", "d", "main")) == []

    def test_read_file_download_url(self, monkeypatch):
        async def _fake_text(url, params=None):
            return "downloaded"

        monkeypatch.setattr(hub, "_http_text_get", _fake_text)
        out = _run(hub._github_read_file({"download_url": "http://x/f"}))
        assert out == "downloaded"

    def test_read_file_base64_content(self):
        encoded = base64.b64encode(b"decoded content").decode()
        out = _run(hub._github_read_file({"content": encoded}))
        assert out == "decoded content"

    def test_read_file_bad_base64(self):
        with pytest.raises(SkillsError, match="Unable to read"):
            _run(hub._github_read_file({"content": "!!notbase64!!"}))

    def test_read_file_nothing(self):
        with pytest.raises(SkillsError, match="Unable to read"):
            _run(hub._github_read_file({}))

    def test_collect_tree_files(self, monkeypatch):
        dir_map = {
            "": [
                {"type": "file", "path": "SKILL.md"},
                {"type": "dir", "path": "sub"},
                {"type": "other", "path": "skip"},
                {"path": ""},
            ],
            "sub": [{"type": "file", "path": "sub/a.txt"}],
        }

        async def _dirs(owner, repo, path, ref):
            return dir_map.get(path, [])

        async def _read(entry):
            return f"content-of-{entry['path']}"

        monkeypatch.setattr(hub, "_github_get_dir_entries", _dirs)
        monkeypatch.setattr(hub, "_github_read_file", _read)
        files = _run(hub._github_collect_tree_files("o", "r", "main", ""))
        assert files == {
            "SKILL.md": "content-of-SKILL.md",
            "sub/a.txt": "content-of-sub/a.txt",
        }

    def test_collect_tree_files_max_cap(self, monkeypatch):
        async def _dirs(owner, repo, path, ref):
            return [{"type": "file", "path": f"f{i}"} for i in range(5)]

        async def _read(entry):
            return "x"

        monkeypatch.setattr(hub, "_github_get_dir_entries", _dirs)
        monkeypatch.setattr(hub, "_github_read_file", _read)
        files = _run(
            hub._github_collect_tree_files("o", "r", "main", "", max_files=2),
        )
        assert len(files) == 2


class TestResolveSkillsmpSpec:
    def test_bad_url_none(self):
        assert _run(hub._resolve_skillsmp_spec("https://x.com/")) is None

    def test_too_few_tokens(self):
        assert (
            _run(
                hub._resolve_skillsmp_spec("https://skillsmp.com/skills/a-b"),
            )
            is None
        )

    def test_repo_found(self, monkeypatch):
        async def _exists(owner, repo):
            return repo == "openclaw-skills"

        monkeypatch.setattr(hub, "_github_repo_exists", _exists)
        spec = _run(
            hub._resolve_skillsmp_spec(
                "https://skillsmp.com/skills/"
                "openclaw-openclaw-skills-himalaya-skill-md",
            ),
        )
        assert spec == ("openclaw", "openclaw-skills", "himalaya")

    def test_fallback_when_no_repo_found(self, monkeypatch):
        async def _exists(owner, repo):
            return False

        monkeypatch.setattr(hub, "_github_repo_exists", _exists)
        spec = _run(
            hub._resolve_skillsmp_spec(
                "https://skillsmp.com/skills/owner-repo-skill-name",
            ),
        )
        assert spec == ("owner", "repo", "skill-name")


# ---------------------------------------------------------------------------
# Zip → bundle converters
# ---------------------------------------------------------------------------


class TestLobehubZipToBundle:
    def test_valid_zip_with_frontmatter_name(self):
        payload = _make_zip(
            {
                "SKILL.md": SKILL_MD,
                "references/r.md": "ref",
                "scripts/s.py": "sc",
            },
        )
        bundle = hub._lobehub_zip_to_bundle("fallback", payload)
        assert bundle["name"] == "demo-skill"
        assert bundle["files"]["SKILL.md"] == SKILL_MD
        assert bundle["files"]["references/r.md"] == "ref"

    def test_name_falls_back_to_identifier(self):
        payload = _make_zip({"SKILL.md": "# no frontmatter"})
        bundle = hub._lobehub_zip_to_bundle("fallback-id", payload)
        assert bundle["name"] == "fallback-id"

    def test_nested_paths_dropped(self):
        payload = _make_zip(
            {"SKILL.md": SKILL_MD, "deep/nested/file.txt": "x"},
        )
        bundle = hub._lobehub_zip_to_bundle("id", payload)
        assert "deep/nested/file.txt" not in bundle["files"]

    def test_binary_files_skipped(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("SKILL.md", SKILL_MD)
            zf.writestr("img.bin", b"\x00\x01\x02binary")
        bundle = hub._lobehub_zip_to_bundle("id", buf.getvalue())
        assert "img.bin" not in bundle["files"]

    def test_bad_zip_with_error_message(self):
        payload = json.dumps({"error": "not found"}).encode()
        with pytest.raises(SkillsError, match="not found"):
            hub._lobehub_zip_to_bundle("id", payload)

    def test_bad_zip_generic(self):
        # Binary payload -> no extractable text -> generic zip message.
        with pytest.raises(SkillsError, match="valid zip"):
            hub._lobehub_zip_to_bundle("id", b"\x00\x01\x02notzip")

    def test_bad_zip_with_text_message(self):
        with pytest.raises(SkillsError, match="not a zip"):
            hub._lobehub_zip_to_bundle("id", b"not a zip")

    def test_missing_skill_md(self):
        payload = _make_zip({"other.md": "x"})
        with pytest.raises(SkillsError, match="missing SKILL.md"):
            hub._lobehub_zip_to_bundle("id", payload)

    def test_too_many_entries(self, monkeypatch):
        monkeypatch.setattr(hub, "SKILL_PACKAGE_MAX_ENTRIES", 0)
        payload = _make_zip({"SKILL.md": SKILL_MD})
        with pytest.raises(SkillsError, match="too many files"):
            hub._lobehub_zip_to_bundle("id", payload)

    def test_too_large(self, monkeypatch):
        monkeypatch.setattr(hub, "SKILL_PACKAGE_MAX_BYTES", 1)
        payload = _make_zip({"SKILL.md": SKILL_MD})
        with pytest.raises(SkillsError, match="too large"):
            hub._lobehub_zip_to_bundle("id", payload)


class TestModelscopeArchiveToBundle:
    def test_prefix_stripped(self):
        payload = _make_zip(
            {
                "skills-owner.name-main-abc/SKILL.md": SKILL_MD,
                "skills-owner.name-main-abc/references/r.md": "r",
            },
        )
        bundle = hub._modelscope_archive_to_bundle(payload, "fallback")
        assert bundle["name"] == "demo-skill"
        assert bundle["files"]["SKILL.md"] == SKILL_MD
        assert bundle["files"]["references/r.md"] == "r"

    def test_top_level_files_skipped(self):
        payload = _make_zip({"toplevel.txt": "x"})
        with pytest.raises(SkillsError, match="missing SKILL.md"):
            hub._modelscope_archive_to_bundle(payload, "f")

    def test_bad_zip(self):
        with pytest.raises(SkillsError, match="not a valid zip"):
            hub._modelscope_archive_to_bundle(b"junk", "f")

    def test_fallback_name_when_no_frontmatter(self):
        payload = _make_zip({"p/SKILL.md": "# plain"})
        bundle = hub._modelscope_archive_to_bundle(payload, "fallback-name")
        assert bundle["name"] == "fallback-name"

    def test_bad_yaml_fallback(self):
        payload = _make_zip({"p/SKILL.md": "---\n: [bad\n---\n"})
        bundle = hub._modelscope_archive_to_bundle(payload, "fb")
        assert bundle["name"] == "fb"

    def test_too_many_entries(self, monkeypatch):
        monkeypatch.setattr(hub, "SKILL_PACKAGE_MAX_ENTRIES", 0)
        payload = _make_zip({"p/SKILL.md": SKILL_MD})
        with pytest.raises(SkillsError, match="too many files"):
            hub._modelscope_archive_to_bundle(payload, "f")

    def test_too_large(self, monkeypatch):
        monkeypatch.setattr(hub, "SKILL_PACKAGE_MAX_BYTES", 1)
        payload = _make_zip({"p/SKILL.md": SKILL_MD})
        with pytest.raises(SkillsError, match="too large"):
            hub._modelscope_archive_to_bundle(payload, "f")

    def test_binary_skipped(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("p/SKILL.md", SKILL_MD)
            zf.writestr("p/x.bin", b"\x00\x01")
        bundle = hub._modelscope_archive_to_bundle(buf.getvalue(), "f")
        assert "x.bin" not in bundle["files"]


class TestQwenpawDetailArchiveToBundle:
    def test_flat_zip(self):
        payload = _make_zip({"SKILL.md": SKILL_MD, "references/r.md": "r"})
        bundle = hub._qwenpaw_detail_archive_to_bundle(payload, "fb")
        assert bundle["name"] == "demo-skill"
        assert bundle["files"]["references/r.md"] == "r"

    def test_bad_zip(self):
        with pytest.raises(SkillsError, match="not a valid zip"):
            hub._qwenpaw_detail_archive_to_bundle(b"junk", "f")

    def test_missing_skill_md(self):
        payload = _make_zip({"other.md": "x"})
        with pytest.raises(SkillsError, match="missing SKILL.md"):
            hub._qwenpaw_detail_archive_to_bundle(payload, "f")

    def test_fallback_name(self):
        payload = _make_zip({"SKILL.md": "# plain"})
        bundle = hub._qwenpaw_detail_archive_to_bundle(payload, "fb-name")
        assert bundle["name"] == "fb-name"

    def test_too_many(self, monkeypatch):
        monkeypatch.setattr(hub, "SKILL_PACKAGE_MAX_ENTRIES", 0)
        payload = _make_zip({"SKILL.md": SKILL_MD})
        with pytest.raises(SkillsError, match="too many files"):
            hub._qwenpaw_detail_archive_to_bundle(payload, "f")

    def test_too_large(self, monkeypatch):
        monkeypatch.setattr(hub, "SKILL_PACKAGE_MAX_BYTES", 1)
        payload = _make_zip({"SKILL.md": SKILL_MD})
        with pytest.raises(SkillsError, match="too large"):
            hub._qwenpaw_detail_archive_to_bundle(payload, "f")


class TestAliyunResponseToBundle:
    def test_valid(self):
        bundle = hub._aliyun_response_to_bundle(
            "sk-1",
            {"requestId": "r", "content": "# md"},
        )
        assert bundle == {"name": "sk-1", "files": {"SKILL.md": "# md"}}

    def test_non_dict_body(self):
        with pytest.raises(SkillsError, match="non-dict"):
            hub._aliyun_response_to_bundle("sk", [1])

    def test_missing_content(self):
        with pytest.raises(SkillsError, match="missing `content`"):
            hub._aliyun_response_to_bundle("sk", {"content": "  "})


# ---------------------------------------------------------------------------
# Provider fetchers (mocked network)
# ---------------------------------------------------------------------------


class TestFetchBundleSkillsSh:
    def test_invalid_url(self):
        with pytest.raises(ConfigurationException):
            _run(hub._fetch_bundle_from_skills_sh_url("https://x.com/", ""))

    def test_success(self, monkeypatch):
        async def _branch(owner, repo):
            return "dev"

        async def _fetch(**kwargs):
            assert kwargs["default_branch"] == "dev"
            return {"name": "skill", "files": {"SKILL.md": "x"}}, "https://src"

        monkeypatch.setattr(hub, "_github_get_default_branch", _branch)
        monkeypatch.setattr(
            hub,
            "_fetch_bundle_from_repo_and_skill_hint",
            _fetch,
        )
        bundle, url = _run(
            hub._fetch_bundle_from_skills_sh_url(
                "https://skills.sh/o/r/skill",
                "",
            ),
        )
        assert bundle["name"] == "skill"
        assert url == "https://src"


class TestFetchBundleFromRepoAndSkillHint:
    def test_direct_hit(self, monkeypatch):
        async def _content(owner, repo, path, ref):
            if path == "skills/myskill/SKILL.md":
                return {"type": "file", "download_url": "http://x"}
            raise httpx.HTTPStatusError(
                "404",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(404),
            )

        async def _read(entry):
            return "# skill md"

        async def _collect(**kwargs):
            return {"references/r.md": "r"}

        monkeypatch.setattr(hub, "_github_get_content_entry", _content)
        monkeypatch.setattr(hub, "_github_read_file", _read)
        monkeypatch.setattr(hub, "_github_collect_tree_files", _collect)
        bundle, source = _run(
            hub._fetch_bundle_from_repo_and_skill_hint(
                owner="o",
                repo="r",
                skill_hint="myskill",
                requested_version="",
                default_branch="main",
            ),
        )
        assert bundle["name"] == "myskill"
        assert bundle["files"]["SKILL.md"] == "# skill md"
        assert bundle["files"]["references/r.md"] == "r"
        assert source == "https://github.com/o/r"

    def test_fallback_scan(self, monkeypatch):
        async def _content(owner, repo, path, ref):
            if path == "found/SKILL.md":
                return {"type": "file"}
            raise httpx.HTTPStatusError(
                "404",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(404),
            )

        async def _roots(owner, repo, ref):
            return ["found"]

        async def _read(entry):
            return "# md"

        async def _collect(**kwargs):
            return {}

        monkeypatch.setattr(hub, "_github_get_content_entry", _content)
        monkeypatch.setattr(hub, "_github_list_skill_md_roots", _roots)
        monkeypatch.setattr(hub, "_github_read_file", _read)
        monkeypatch.setattr(hub, "_github_collect_tree_files", _collect)
        bundle, _ = _run(
            hub._fetch_bundle_from_repo_and_skill_hint(
                owner="o",
                repo="r",
                skill_hint="found-skill",
                requested_version="",
            ),
        )
        assert bundle["files"]["SKILL.md"] == "# md"

    def test_not_found_raises(self, monkeypatch):
        async def _content(owner, repo, path, ref):
            raise httpx.HTTPStatusError(
                "404",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(404),
            )

        async def _roots(owner, repo, ref):
            return []

        monkeypatch.setattr(hub, "_github_get_content_entry", _content)
        monkeypatch.setattr(hub, "_github_list_skill_md_roots", _roots)
        with pytest.raises(SkillsError, match="Could not find SKILL.md"):
            _run(
                hub._fetch_bundle_from_repo_and_skill_hint(
                    owner="o",
                    repo="r",
                    skill_hint="ghost",
                    requested_version="",
                ),
            )

    def test_non_404_error_raises(self, monkeypatch):
        async def _content(owner, repo, path, ref):
            raise httpx.HTTPStatusError(
                "500",
                request=httpx.Request("GET", "http://x"),
                response=httpx.Response(500),
            )

        monkeypatch.setattr(hub, "_github_get_content_entry", _content)
        with pytest.raises(httpx.HTTPStatusError):
            _run(
                hub._fetch_bundle_from_repo_and_skill_hint(
                    owner="o",
                    repo="r",
                    skill_hint="s",
                    requested_version="v1",
                ),
            )


class TestFetchBundleGithubUrl:
    def test_invalid_url(self):
        with pytest.raises(ConfigurationException):
            _run(hub._fetch_bundle_from_github_url("https://x.com/", ""))

    def test_skill_md_path_normalized(self, monkeypatch):
        captured = {}

        async def _branch(owner, repo):
            return ""

        async def _fetch(**kwargs):
            captured.update(kwargs)
            return {"name": "n", "files": {}}, "src"

        monkeypatch.setattr(hub, "_github_get_default_branch", _branch)
        monkeypatch.setattr(
            hub,
            "_fetch_bundle_from_repo_and_skill_hint",
            _fetch,
        )
        _run(
            hub._fetch_bundle_from_github_url(
                "https://github.com/o/r/tree/main/skills/x/SKILL.md",
                "",
            ),
        )
        assert captured["skill_hint"] == "skills/x"

    def test_bare_skill_md_path(self, monkeypatch):
        captured = {}

        async def _branch(owner, repo):
            raise RuntimeError("no meta")

        async def _fetch(**kwargs):
            captured.update(kwargs)
            return {"name": "n"}, "src"

        monkeypatch.setattr(hub, "_github_get_default_branch", _branch)
        monkeypatch.setattr(
            hub,
            "_fetch_bundle_from_repo_and_skill_hint",
            _fetch,
        )
        _run(
            hub._fetch_bundle_from_github_url(
                "https://github.com/o/r/tree/main/SKILL.md",
                "",
            ),
        )
        assert captured["skill_hint"] == ""
        assert captured["default_branch"] == "main"


class TestFetchBundleSkillsmpUrl:
    def test_invalid(self):
        with pytest.raises(ConfigurationException):
            _run(hub._fetch_bundle_from_skillsmp_url("https://x.com/", ""))


class TestFetchBundleLobehub:
    def test_invalid_url(self):
        with pytest.raises(ConfigurationException):
            _run(hub._fetch_bundle_from_lobehub_url("https://x.com/", ""))

    def test_success(self, monkeypatch):
        payload = _make_zip({"SKILL.md": SKILL_MD})

        async def _bytes(url, params=None, accept="", max_bytes=None):
            assert params is None
            return payload

        monkeypatch.setattr(hub, "_http_bytes_get", _bytes)
        bundle, url = _run(
            hub._fetch_bundle_from_lobehub_url(
                "https://lobehub.com/skills/my-skill",
                "",
            ),
        )
        assert bundle["name"] == "demo-skill"
        assert "lobehub" in url

    def test_version_param(self, monkeypatch):
        payload = _make_zip({"SKILL.md": SKILL_MD})
        seen = {}

        async def _bytes(url, params=None, accept="", max_bytes=None):
            seen["params"] = params
            return payload

        monkeypatch.setattr(hub, "_http_bytes_get", _bytes)
        _run(
            hub._fetch_bundle_from_lobehub_url(
                "https://lobehub.com/skills/my-skill",
                "v2",
            ),
        )
        assert seen["params"] == {"version": "v2"}

    def test_http_error(self, monkeypatch):
        async def _bytes(url, params=None, accept="", max_bytes=None):
            raise httpx.HTTPStatusError(
                "404",
                request=httpx.Request("GET", url),
                response=httpx.Response(404, content=b"gone"),
            )

        monkeypatch.setattr(hub, "_http_bytes_get", _bytes)
        with pytest.raises(SkillsError, match="download failed"):
            _run(
                hub._fetch_bundle_from_lobehub_url(
                    "https://lobehub.com/skills/x",
                    "",
                ),
            )

    def test_value_error(self, monkeypatch):
        async def _bytes(url, params=None, accept="", max_bytes=None):
            raise ValueError("bad value")

        monkeypatch.setattr(hub, "_http_bytes_get", _bytes)
        with pytest.raises(SkillsError, match="bad value"):
            _run(
                hub._fetch_bundle_from_lobehub_url(
                    "https://lobehub.com/skills/x",
                    "",
                ),
            )


class TestFetchBundleModelscope:
    def test_invalid_url(self):
        with pytest.raises(ConfigurationException):
            _run(hub._fetch_bundle_from_modelscope_url("https://x.com/", ""))

    def test_success(self, monkeypatch):
        payload = _make_zip({"wrap/SKILL.md": SKILL_MD})

        async def _bytes(url, params=None, accept="", max_bytes=None):
            assert "modelscope" in url
            return payload

        monkeypatch.setattr(hub, "_http_bytes_get", _bytes)
        bundle, _ = _run(
            hub._fetch_bundle_from_modelscope_url(
                "https://modelscope.cn/skills/@owner/name",
                "",
            ),
        )
        assert bundle["name"] == "demo-skill"

    def test_version_from_hint(self, monkeypatch):
        urls = []
        payload = _make_zip({"wrap/SKILL.md": SKILL_MD})

        async def _bytes(url, params=None, accept="", max_bytes=None):
            urls.append(url)
            return payload

        monkeypatch.setattr(hub, "_http_bytes_get", _bytes)
        _run(
            hub._fetch_bundle_from_modelscope_url(
                "https://modelscope.cn/skills/o/n/archive/zip/v9.zip",
                "",
            ),
        )
        assert "v9" in urls[0]

    def test_http_error(self, monkeypatch):
        async def _bytes(url, params=None, accept="", max_bytes=None):
            raise httpx.HTTPStatusError(
                "404",
                request=httpx.Request("GET", url),
                response=httpx.Response(404, content=b"nope"),
            )

        monkeypatch.setattr(hub, "_http_bytes_get", _bytes)
        with pytest.raises(SkillsError, match="download failed"):
            _run(
                hub._fetch_bundle_from_modelscope_url(
                    "https://modelscope.cn/skills/o/n",
                    "",
                ),
            )


class TestFetchBundleQwenpaw:
    def test_invalid_url(self):
        with pytest.raises(ConfigurationException):
            _run(hub._fetch_bundle_from_qwenpaw_url("https://x.com/", ""))

    def test_owner_path_uses_modelscope_converter(self, monkeypatch):
        payload = _make_zip({"wrap/SKILL.md": SKILL_MD})
        urls = []

        async def _bytes(url, params=None, accept="", max_bytes=None):
            urls.append(url)
            return payload

        monkeypatch.setattr(hub, "_http_bytes_get", _bytes)
        bundle, _ = _run(
            hub._fetch_bundle_from_qwenpaw_url(
                "https://platform.agentscope.io/skills/@owner/name",
                "",
            ),
        )
        assert bundle["name"] == "demo-skill"
        assert "/archive/zip/master" in urls[0]

    def test_uuid_path_uses_detail_converter(self, monkeypatch):
        uuid = "12345678-1234-1234-1234-123456789abc"
        payload = _make_zip({"SKILL.md": SKILL_MD})
        urls = []

        async def _bytes(url, params=None, accept="", max_bytes=None):
            urls.append(url)
            return payload

        monkeypatch.setattr(hub, "_http_bytes_get", _bytes)
        bundle, _ = _run(
            hub._fetch_bundle_from_qwenpaw_url(
                f"https://platform.agentscope.io/skills/{uuid}",
                "",
            ),
        )
        assert bundle["name"] == "demo-skill"
        assert "download" in urls[0]

    def test_requested_version_overrides(self, monkeypatch):
        urls = []
        payload = _make_zip({"wrap/SKILL.md": SKILL_MD})

        async def _bytes(url, params=None, accept="", max_bytes=None):
            urls.append(url)
            return payload

        monkeypatch.setattr(hub, "_http_bytes_get", _bytes)
        _run(
            hub._fetch_bundle_from_qwenpaw_url(
                "https://platform.agentscope.io/skills/o/n",
                "v5",
            ),
        )
        assert "v5" in urls[0]

    def test_http_error(self, monkeypatch):
        async def _bytes(url, params=None, accept="", max_bytes=None):
            raise httpx.HTTPStatusError(
                "500",
                request=httpx.Request("GET", url),
                response=httpx.Response(500, content=b"boom"),
            )

        monkeypatch.setattr(hub, "_http_bytes_get", _bytes)
        with pytest.raises(SkillsError, match="download failed"):
            _run(
                hub._fetch_bundle_from_qwenpaw_url(
                    "https://platform.agentscope.io/skills/o/n",
                    "",
                ),
            )


class TestFetchBundleAliyun:
    def test_invalid_url(self):
        with pytest.raises(ConfigurationException):
            _run(hub._fetch_bundle_from_aliyun_url("https://x.com/", ""))

    def test_success(self, monkeypatch):
        import qwenpaw.market.providers.aliyun as aliyun_mod

        async def _call(action, pathname, method):
            assert action == "GetSkillContent"
            return {"content": "# aliyun skill"}

        monkeypatch.setattr(
            aliyun_mod,
            "call_aliyun_action_async",
            _call,
        )
        bundle, url = _run(
            hub._fetch_bundle_from_aliyun_url(
                "https://api.aliyun.com/agentexplorer/skills/sk-9",
                "",
            ),
        )
        assert bundle["files"]["SKILL.md"] == "# aliyun skill"
        assert "aliyun" in url

    def test_call_failure(self, monkeypatch):
        import qwenpaw.market.providers.aliyun as aliyun_mod

        async def _call(action, pathname, method):
            raise RuntimeError("denied")

        monkeypatch.setattr(
            aliyun_mod,
            "call_aliyun_action_async",
            _call,
        )
        with pytest.raises(SkillsError, match="GetSkillContent failed"):
            _run(
                hub._fetch_bundle_from_aliyun_url(
                    "https://api.aliyun.com/agentexplorer/skills/sk-9",
                    "",
                ),
            )


# ---------------------------------------------------------------------------
# ClawHub hydrate / fetch
# ---------------------------------------------------------------------------


class TestHydrateClawhubPayload:
    def test_already_has_content(self):
        data = {"content": "x"}
        out = _run(
            hub._hydrate_clawhub_payload(
                data,
                slug="s",
                requested_version="",
            ),
        )
        assert out == data

    def test_non_dict_passthrough(self):
        out = _run(
            hub._hydrate_clawhub_payload("x", slug="s", requested_version=""),
        )
        assert out == "x"

    def test_no_skill_dict(self):
        data = {"other": 1}
        out = _run(
            hub._hydrate_clawhub_payload(data, slug="s", requested_version=""),
        )
        assert out == data

    def test_no_slug_returns_data(self):
        data = {"skill": {}}
        out = _run(
            hub._hydrate_clawhub_payload(data, slug="", requested_version=""),
        )
        assert out == data

    def test_no_version_hint_returns_data(self, monkeypatch):
        data = {"skill": {"slug": "s1"}}
        out = _run(
            hub._hydrate_clawhub_payload(
                data,
                slug="s1",
                requested_version="",
            ),
        )
        assert out == data

    def test_full_hydration(self, monkeypatch):
        version_payload = {
            "version": {
                "version": "1.0",
                "files": [{"path": "SKILL.md"}, {"path": "references/r.md"}],
            },
        }

        async def _json(url, params=None, timeout=None):
            return version_payload

        async def _text(url, params=None):
            return f"content-of-{params['path']}"

        monkeypatch.setattr(hub, "_http_json_get", _json)
        monkeypatch.setattr(hub, "_http_text_get", _text)
        data = {"skill": {"slug": "s1", "displayName": "Skill One"}}
        out = _run(
            hub._hydrate_clawhub_payload(
                data,
                slug="s1",
                requested_version="1.0",
            ),
        )
        assert out["name"] == "Skill One"
        assert out["files"]["SKILL.md"] == "content-of-SKILL.md"

    def test_version_response_bad_shape_returns_data(self, monkeypatch):
        async def _json(url, params=None, timeout=None):
            return "garbage"

        monkeypatch.setattr(hub, "_http_json_get", _json)
        data = {"skill": {"slug": "s1"}}
        out = _run(
            hub._hydrate_clawhub_payload(
                data,
                slug="s1",
                requested_version="1.0",
            ),
        )
        assert out == data

    def test_files_meta_not_list_returns_data(self, monkeypatch):
        async def _json(url, params=None, timeout=None):
            return {"version": {"version": "1.0", "files": "bad"}}

        monkeypatch.setattr(hub, "_http_json_get", _json)
        data = {"skill": {"slug": "s1"}}
        out = _run(
            hub._hydrate_clawhub_payload(
                data,
                slug="s1",
                requested_version="1.0",
            ),
        )
        assert out == data

    def test_skill_md_fetch_failed_raises(self, monkeypatch):
        version_payload = {
            "version": {"version": "1.0", "files": [{"path": "SKILL.md"}]},
        }

        async def _json(url, params=None, timeout=None):
            return version_payload

        async def _text(url, params=None):
            raise RuntimeError("fetch failed")

        monkeypatch.setattr(hub, "_http_json_get", _json)
        monkeypatch.setattr(hub, "_http_text_get", _text)
        data = {"skill": {"slug": "s1"}}
        with pytest.raises(SkillsError, match="Failed to fetch SKILL.md"):
            _run(
                hub._hydrate_clawhub_payload(
                    data,
                    slug="s1",
                    requested_version="1.0",
                ),
            )

    def test_empty_files_no_error_returns_data(self, monkeypatch):
        version_payload = {
            "version": {"version": "1.0", "files": [{"path": ""}, "bad"]},
        }

        async def _json(url, params=None, timeout=None):
            return version_payload

        monkeypatch.setattr(hub, "_http_json_get", _json)
        data = {"skill": {"slug": "s1"}}
        out = _run(
            hub._hydrate_clawhub_payload(
                data,
                slug="s1",
                requested_version="1.0",
            ),
        )
        assert out == data


class TestFetchBundleClawhub:
    def test_slug_required(self):
        with pytest.raises(ConfigurationException, match="slug is required"):
            _run(hub._fetch_bundle_from_clawhub_slug("", ""))

    def test_success(self, monkeypatch):
        async def _json(url, params=None, timeout=None):
            return {"content": "x", "name": "n"}

        monkeypatch.setattr(hub, "_http_json_get", _json)
        bundle, url = _run(hub._fetch_bundle_from_clawhub_slug("s1", ""))
        assert bundle == {"content": "x", "name": "n"}
        assert "/api/v1/skills/s1" in url

    def test_all_candidates_fail(self, monkeypatch):
        async def _json(url, params=None, timeout=None):
            raise RuntimeError("down")

        monkeypatch.setattr(hub, "_http_json_get", _json)
        with pytest.raises(SkillsError, match="importing from ClawHub"):
            _run(hub._fetch_bundle_from_clawhub_slug("s1", ""))

    def test_url_adapter_invalid(self):
        with pytest.raises(ConfigurationException):
            _run(hub._fetch_bundle_from_clawhub_url("https://other.ai/", ""))

    def test_url_adapter_success(self, monkeypatch):
        async def _json(url, params=None, timeout=None):
            return {"content": "c"}

        monkeypatch.setattr(hub, "_http_json_get", _json)
        bundle, _ = _run(
            hub._fetch_bundle_from_clawhub_url(
                "https://clawhub.ai/skills/s2",
                "",
            ),
        )
        assert bundle == {"content": "c"}


# ---------------------------------------------------------------------------
# Search API
# ---------------------------------------------------------------------------


class TestSearchHubSkills:
    def test_results_mapping(self, monkeypatch):
        async def _json(url, params=None, timeout=None):
            assert params == {"q": "pdf", "limit": 2}
            return {
                "items": [
                    {
                        "slug": "pdf-tool",
                        "name": "PDF Tool",
                        "description": "d",
                        "version": "1.0",
                        "url": "http://x",
                        "owner": {
                            "handle": "h",
                            "displayName": "Display",
                            "image": "http://img",
                        },
                    },
                    {"name": "no-slug-but-name"},
                    {"nothing": True},
                ],
            }

        monkeypatch.setattr(hub, "_http_json_get", _json)
        results = _run(hub.search_hub_skills("pdf", limit=2))
        assert len(results) == 2
        assert results[0].slug == "pdf-tool"
        assert results[0].author == "Display"
        assert results[0].icon_url == "http://img"
        assert results[1].slug == "no-slug-but-name"

    def test_owner_handle_fallback(self, monkeypatch):
        async def _json(url, params=None, timeout=None):
            return [
                {"slug": "s", "ownerHandle": "fallback-handle"},
            ]

        monkeypatch.setattr(hub, "_http_json_get", _json)
        results = _run(hub.search_hub_skills("x"))
        assert results[0].author == "fallback-handle"


# ---------------------------------------------------------------------------
# Provider routing
# ---------------------------------------------------------------------------


class TestProviderRouting:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://skills.sh/o/r/s", "skills-sh"),
            ("https://github.com/o/r", "github"),
            ("https://lobehub.com/skills/x", "lobehub"),
            ("https://platform.agentscope.io/skills/o/n", "qwenpaw"),
            ("https://modelscope.cn/skills/o/n", "modelscope"),
            (
                "https://api.aliyun.com/agentexplorer/skills/sk",
                "aliyun",
            ),
            ("https://skillsmp.com/skills/slug", "skillsmp"),
            ("https://clawhub.ai/skills/s", "clawhub"),
            ("https://example.com/bundle.json", "url"),
        ],
    )
    def test_match_provider(self, url, expected):
        name, fetcher = hub._match_provider(url)
        assert name == expected
        if expected == "url":
            assert fetcher is None
        else:
            assert fetcher is not None

    def test_classify_origin_empty(self):
        assert hub._classify_install_origin("") == ""

    def test_resolve_bundle_via_fetcher(self, monkeypatch):
        async def _fetcher(url, requested_version=""):
            return {"bundle": 1}, "resolved"

        monkeypatch.setattr(
            hub,
            "_match_provider",
            lambda url: ("github", _fetcher),
        )
        bundle, src = _run(hub._resolve_bundle_from_url("http://x", "v"))
        assert bundle == {"bundle": 1}
        assert src == "resolved"

    def test_resolve_bundle_fallback_json(self, monkeypatch):
        async def _json(url, params=None, timeout=None):
            return {"raw": 1}

        monkeypatch.setattr(hub, "_match_provider", lambda url: ("url", None))
        monkeypatch.setattr(hub, "_http_json_get", _json)
        bundle, src = _run(
            hub._resolve_bundle_from_url("http://x/bundle.json", ""),
        )
        assert bundle == {"raw": 1}
        assert src == "http://x/bundle.json"


# ---------------------------------------------------------------------------
# Install pipeline
# ---------------------------------------------------------------------------


class TestPrepareInstallPayload:
    def test_invalid_url(self):
        with pytest.raises(ConfigurationException, match="bundle_url"):
            _run(hub._prepare_install_payload("not-a-url", "", None))
        with pytest.raises(ConfigurationException):
            _run(hub._prepare_install_payload("", "", None))

    def test_full_flow(self, monkeypatch):
        async def _resolve(url, version):
            return (
                {"name": "My Skill", "content": SKILL_MD},
                "http://src",
            )

        monkeypatch.setattr(hub, "_resolve_bundle_from_url", _resolve)
        payload = _run(
            hub._prepare_install_payload("https://example.com/x", "", None),
        )
        assert payload.name == "My Skill"
        assert payload.source_url == "http://src"
        assert payload.installed_from == "url"

    def test_target_name_overrides(self, monkeypatch):
        async def _resolve(url, version):
            return {"name": "orig", "content": SKILL_MD}, "src"

        monkeypatch.setattr(hub, "_resolve_bundle_from_url", _resolve)
        payload = _run(
            hub._prepare_install_payload(
                "https://example.com/x",
                "",
                "Custom/Name",
            ),
        )
        assert payload.name == "custom-name"

    def test_name_sanitized(self, monkeypatch):
        async def _resolve(url, version):
            return {"name": "Excel / XLSX", "content": SKILL_MD}, "src"

        monkeypatch.setattr(hub, "_resolve_bundle_from_url", _resolve)
        payload = _run(
            hub._prepare_install_payload("https://example.com/x", "", None),
        )
        assert payload.name == "excel-xlsx"

    def test_cancelled_before_fetch(self):
        with hub._with_cancel_checker(lambda: True):
            with pytest.raises(SkillImportCancelled):
                _run(
                    hub._prepare_install_payload(
                        "https://example.com/x",
                        "",
                        None,
                    ),
                )


class TestInstallSkillFromHub:
    def test_success(self, monkeypatch, tmp_path):
        async def _prepare(url, version, target):
            return hub._InstallPayload(
                name="demo",
                content=SKILL_MD,
                references={},
                scripts={},
                extra_files={},
                source_url="http://src",
                installed_from="github",
            )

        class _Svc:
            def __init__(self, workspace_dir):
                pass

            def create_skill(self, **kwargs):
                return kwargs["name"]

            def enable_skill(self, name):
                return {"success": True}

        monkeypatch.setattr(hub, "_prepare_install_payload", _prepare)
        monkeypatch.setattr(hub, "SkillService", _Svc)
        result = _run(
            hub.install_skill_from_hub(
                workspace_dir=tmp_path,
                bundle_url="https://github.com/o/r",
                enable=True,
            ),
        )
        assert result.name == "demo"
        assert result.enabled is True
        assert result.installed_from == "github"

    def test_enable_failed(self, monkeypatch, tmp_path):
        async def _prepare(url, version, target):
            return hub._InstallPayload(
                name="demo",
                content=SKILL_MD,
                references={},
                scripts={},
                extra_files={},
                source_url="s",
                installed_from="",
            )

        class _Svc:
            def __init__(self, workspace_dir):
                pass

            def create_skill(self, **kwargs):
                return "demo"

            def enable_skill(self, name):
                return {"success": False}

        monkeypatch.setattr(hub, "_prepare_install_payload", _prepare)
        monkeypatch.setattr(hub, "SkillService", _Svc)
        result = _run(
            hub.install_skill_from_hub(
                workspace_dir=tmp_path,
                bundle_url="http://x",
                enable=True,
            ),
        )
        assert result.enabled is False

    def test_conflict(self, monkeypatch, tmp_path):
        async def _prepare(url, version, target):
            return hub._InstallPayload(
                name="demo",
                content=SKILL_MD,
                references={},
                scripts={},
                extra_files={},
                source_url="s",
                installed_from="",
            )

        class _Svc:
            def __init__(self, workspace_dir):
                pass

            def create_skill(self, **kwargs):
                return None

        monkeypatch.setattr(hub, "_prepare_install_payload", _prepare)
        monkeypatch.setattr(hub, "SkillService", _Svc)
        with pytest.raises(SkillConflictError):
            _run(
                hub.install_skill_from_hub(
                    workspace_dir=tmp_path,
                    bundle_url="http://x",
                ),
            )

    def test_cancelled(self, tmp_path):
        with pytest.raises(SkillImportCancelled):
            _run(
                hub.install_skill_from_hub(
                    workspace_dir=tmp_path,
                    bundle_url="http://x",
                    cancel_checker=lambda: True,
                ),
            )


class TestImportPoolSkillFromHub:
    def test_success(self, monkeypatch):
        async def _prepare(url, version, target):
            return hub._InstallPayload(
                name="pool-skill",
                content=SKILL_MD,
                references={},
                scripts={},
                extra_files={},
                source_url="s",
                installed_from="clawhub",
            )

        class _Pool:
            def create_skill(self, **kwargs):
                return kwargs["name"]

        monkeypatch.setattr(hub, "_prepare_install_payload", _prepare)
        monkeypatch.setattr(hub, "SkillPoolService", _Pool)
        result = _run(
            hub.import_pool_skill_from_hub(bundle_url="http://x"),
        )
        assert result.name == "pool-skill"
        assert result.enabled is False
        assert result.installed_from == "clawhub"

    def test_conflict(self, monkeypatch):
        async def _prepare(url, version, target):
            return hub._InstallPayload(
                name="dup",
                content=SKILL_MD,
                references={},
                scripts={},
                extra_files={},
                source_url="s",
                installed_from="",
            )

        class _Pool:
            def create_skill(self, **kwargs):
                return None

        monkeypatch.setattr(hub, "_prepare_install_payload", _prepare)
        monkeypatch.setattr(hub, "SkillPoolService", _Pool)
        with pytest.raises(SkillConflictError):
            _run(hub.import_pool_skill_from_hub(bundle_url="http://x"))


class TestBuildHubConflict:
    def test_shape(self):
        out = hub._build_hub_conflict("my-skill")
        assert out["reason"] == "conflict"
        assert out["skill_name"] == "my-skill"
        assert out["suggested_name"].startswith("my-skill")
        assert out["conflicts"][0]["reason"] == "conflict"
        assert "already exists" in out["message"]
