# -*- coding: utf-8 -*-
"""Unit tests for the reranker connectivity probe (test_reranker_model)."""

import asyncio
import socket
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from qwenpaw.agents.memory import reme_reranker as module
from qwenpaw.config.config import RerankerConfig

_TEST_BASE_URL = "https://example.com/v1"


def _config(**overrides) -> RerankerConfig:
    values = {
        "enabled": True,
        "api_key": f"probe-{int(time.time_ns())}",
        "base_url": _TEST_BASE_URL,
        "model_name": "test-reranker",
        "candidate_multiplier": 3,
        "timeout": 5.0,
    }
    values.update(overrides)
    return RerankerConfig(**values)


def _expected_indices() -> list[int]:
    return [expected for _, _, expected in module._TEST_SUITE]


class _FakeResponse:
    def __init__(self, payload=None, status_error=None):
        self._payload = payload
        self._status_error = status_error

    def raise_for_status(self):
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        return self._payload


class _FakeAsyncClient:
    # Every request the probe made, in order.
    posted: list[dict] = []
    # How many clients the probe constructed (one is expected per suite).
    created = 0

    @classmethod
    def reset(cls) -> None:
        cls.posted = []
        cls.created = 0

    def __init__(self, response=None, responses=None, post_error=None, **_kw):
        type(self).created += 1
        self._responses = list(responses) if responses else [response]
        self._served = 0
        self._post_error = post_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url, headers=None, json=None, extensions=None):
        type(self).posted.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "extensions": extensions,
            },
        )
        if self._post_error is not None:
            raise self._post_error
        served = self._served
        self._served += 1
        return self._responses[min(served, len(self._responses) - 1)]


def _results(*scores):
    """Build a /rerank payload from per-document relevance scores."""
    return {
        "results": [
            {"index": i, "relevance_score": s} for i, s in enumerate(scores)
        ],
    }


def _suite_scores(
    *,
    top_at=(0, 1, 2, 0, 1),
    base=0.9,
) -> list[dict]:
    """One payload per suite case placing the top score at *top_at*."""
    payloads = []
    for top in top_at:
        scores = [base if i == top else 0.1 for i in range(3)]
        payloads.append(_results(*scores))
    return payloads


def _install(monkeypatch, **client_kwargs) -> list[dict]:
    def factory(**kwargs):
        return _FakeAsyncClient(**kwargs, **client_kwargs)

    _FakeAsyncClient.reset()
    monkeypatch.setattr(module.httpx, "AsyncClient", factory)
    return _FakeAsyncClient.posted


@pytest.mark.asyncio
async def test_probe_reports_scores_and_correct_rank(monkeypatch) -> None:
    posted = _install(
        monkeypatch,
        responses=[
            _FakeResponse(payload=payload)
            for payload in _suite_scores(top_at=_expected_indices())
        ],
    )

    result = await module.test_reranker_model(_config())

    assert result.success is True
    assert result.total == 5
    assert result.correct_count == 5
    assert result.precision == 1.0
    assert len(result.cases) == 5
    assert result.cases[0].scores == [0.9, 0.1, 0.1]
    assert result.cases[0].correct is True
    assert result.latency_ms >= 0
    # One client for the whole suite, five sequential requests.
    assert _FakeAsyncClient.created == 1
    assert len(posted) == len(module._TEST_SUITE) == 5


@pytest.mark.asyncio
async def test_probe_suite_varies_expected_document_position() -> None:
    """A fixed-order service must not score perfect precision, so the suite
    must place the expected document at more than one index."""
    indices = _expected_indices()

    assert len(set(indices)) > 1
    for (_, documents, expected), index in zip(
        module._TEST_SUITE,
        indices,
        strict=True,
    ):
        assert 0 <= expected < len(documents)
        assert expected == index


@pytest.mark.asyncio
async def test_probe_flags_fixed_order_service(monkeypatch) -> None:
    """Top score always at index 0 must fail the cases whose expected document
    sits elsewhere."""
    _install(
        monkeypatch,
        responses=[
            _FakeResponse(payload=payload)
            for payload in _suite_scores(top_at=(0, 0, 0, 0, 0))
        ],
    )

    result = await module.test_reranker_model(_config())

    assert result.success is True
    assert result.correct_count == sum(
        1 for i in _expected_indices() if i == 0
    )
    assert result.precision < 1.0
    assert [case.correct for case in result.cases] == [
        expected == 0 for expected in _expected_indices()
    ]


@pytest.mark.asyncio
async def test_probe_tied_top_scores_count_as_incorrect(monkeypatch) -> None:
    """A service returning identical scores for every document has no ranking
    signal and must not pass with perfect precision."""
    _install(
        monkeypatch,
        response=_FakeResponse(payload=_results(0.0, 0.0, 0.0)),
    )

    result = await module.test_reranker_model(_config())

    assert result.success is True
    assert result.total == 5
    assert result.correct_count == 0
    assert result.precision == 0.0
    assert all(case.correct is False for case in result.cases)


@pytest.mark.asyncio
async def test_probe_rejects_non_finite_scores(monkeypatch) -> None:
    """NaN/Infinity carry no ranking signal and must fail the probe instead of
    accidentally winning the max() comparison."""
    for bad in (float("nan"), float("inf"), float("-inf")):
        payload = {
            "results": [
                {"index": 0, "relevance_score": bad},
                {"index": 1, "relevance_score": 0.1},
                {"index": 2, "relevance_score": 0.1},
            ],
        }
        _install(monkeypatch, response=_FakeResponse(payload=payload))

        result = await module.test_reranker_model(_config())

        assert result.success is False
        assert "non-finite" in result.message


@pytest.mark.asyncio
async def test_probe_without_scores_skips_ranking_verdict(
    monkeypatch,
) -> None:
    payload = {"results": [{"index": 0}, {"index": 1}, {"index": 2}]}
    _install(monkeypatch, response=_FakeResponse(payload=payload))

    result = await module.test_reranker_model(_config())

    assert result.success is True
    assert result.precision is None
    assert result.total == 5
    assert result.incomplete_count == 5
    assert result.cases[0].scores is None
    assert result.cases[0].correct is None


@pytest.mark.asyncio
async def test_probe_incomplete_cases_do_not_inflate_precision(monkeypatch):
    """Two correctly ranked cases and three without scores must report 2/5,
    not 2/2."""
    unranked = {"results": [{"index": 0}, {"index": 1}, {"index": 2}]}
    ranked = _results(0.9, 0.1, 0.1)
    # Cases 0 and 3 expect index 0; cases 1/2/4 expect 1/2 but are unscored.
    payloads = [ranked, unranked, unranked, ranked, unranked]
    _install(
        monkeypatch,
        responses=[_FakeResponse(payload=p) for p in payloads],
    )

    result = await module.test_reranker_model(_config())

    assert result.success is True
    assert result.total == 5
    assert result.correct_count == 2
    assert result.incomplete_count == 3
    assert result.precision == 2 / 5


@pytest.mark.asyncio
async def test_probe_rejects_duplicate_indices(monkeypatch) -> None:
    """Duplicate indices are invalid for the runtime path too; they must not
    be scored as if they were distinct documents."""
    payload = {"results": [{"index": 0}, {"index": 0}, {"index": 1}]}
    _install(monkeypatch, response=_FakeResponse(payload=payload))

    result = await module.test_reranker_model(_config())

    assert result.success is False
    assert "invalid document indices" in result.message


@pytest.mark.asyncio
async def test_probe_rejects_out_of_range_indices(monkeypatch) -> None:
    payload = {"results": [{"index": 0}, {"index": 1}, {"index": 9}]}
    _install(monkeypatch, response=_FakeResponse(payload=payload))

    result = await module.test_reranker_model(_config())

    assert result.success is False
    assert "invalid document indices" in result.message


@pytest.mark.asyncio
async def test_probe_refuses_blank_api_key_like_runtime(monkeypatch) -> None:
    posted = _install(
        monkeypatch,
        response=_FakeResponse(
            payload=_results(
                0.9,
                0.1,
                0.1,
            ),
        ),
    )

    result = await module.test_reranker_model(_config(api_key="   "))

    assert result.success is False
    assert "API key" in result.message
    # Aligned with call_reranker_api: no request, and never an empty Bearer.
    assert posted == []


@pytest.mark.asyncio
async def test_probe_reports_http_timeout(monkeypatch) -> None:
    _install(monkeypatch, post_error=httpx.TimeoutException("slow"))

    result = await module.test_reranker_model(_config())

    assert result.success is False
    assert "timed out" in result.message


@pytest.mark.asyncio
async def test_probe_hard_deadline_cancels_slow_drip(
    monkeypatch,
) -> None:
    _install(monkeypatch, post_error=asyncio.TimeoutError())

    result = await module.test_reranker_model(_config())

    assert result.success is False
    assert "timed out" in result.message


@pytest.mark.asyncio
async def test_probe_strips_html_from_http_error(monkeypatch) -> None:
    response = SimpleNamespace(
        status_code=500,
        text="<html><body>Internal Server Error</body></html>",
    )
    error = httpx.HTTPStatusError(
        "server error",
        request=MagicMock(),
        response=response,
    )
    _install(monkeypatch, response=_FakeResponse(status_error=error))

    result = await module.test_reranker_model(_config())

    assert result.success is False
    assert "HTTP 500" in result.message
    assert "Internal Server Error" in result.message
    assert "<html>" not in result.message


@pytest.mark.asyncio
async def test_probe_redacts_api_key_from_http_error_body(monkeypatch) -> None:
    """A provider that echoes the Authorization header must not get the key
    into the returned message, which the sweep logs."""
    config = _config()
    error = httpx.HTTPStatusError(
        "unauthorized",
        request=MagicMock(),
        response=SimpleNamespace(
            status_code=401,
            text=f"<html>bad token {config.api_key}</html>",
        ),
    )
    _install(monkeypatch, response=_FakeResponse(status_error=error))

    result = await module.test_reranker_model(config)

    assert result.success is False
    assert config.api_key not in result.message
    assert "***" in result.message


@pytest.mark.asyncio
async def test_probe_redacts_api_key_from_generic_error(monkeypatch) -> None:
    config = _config()
    _install(monkeypatch, post_error=RuntimeError(f"boom {config.api_key}"))

    result = await module.test_reranker_model(config)

    assert result.success is False
    assert config.api_key not in result.message
    assert "***" in result.message


@pytest.mark.asyncio
async def test_probe_requires_base_url() -> None:
    result = await module.test_reranker_model(_config(base_url=" "))

    assert result.success is False
    assert "base URL" in result.message


def test_suite_deadline_covers_all_five_requests() -> None:
    """The suite budget must cover validation plus every sequential request;
    the client mirrors this value, so it must not be derived from fewer than
    five requests."""
    for timeout in (1.0, 1.5, 9.0, 30.0):
        deadline = module.reranker_suite_deadline_seconds(timeout)
        assert deadline >= len(module._TEST_SUITE) * timeout
        # Plus explicit overhead for DNS validation and connection setup.
        assert deadline > len(module._TEST_SUITE) * timeout
    # Cross-language contract pin: agent.test.ts asserts 5 * timeout + 15 s
    # for the browser, so these exact values must not drift.
    assert module.reranker_suite_deadline_seconds(1.5) == 17.5
    assert module.reranker_suite_deadline_seconds(9.0) == 55.0


@pytest.mark.asyncio
async def test_probe_deadline_is_not_per_request_only(monkeypatch) -> None:
    """Five 9-second responses must fit inside the suite, so the per-request
    budget alone (which the browser used to apply) would be too short."""
    timeout = 9.0
    deadline = module.reranker_suite_deadline_seconds(timeout)
    assert deadline > timeout

    _install(
        monkeypatch,
        responses=[
            _FakeResponse(payload=payload)
            for payload in _suite_scores(top_at=_expected_indices())
        ],
    )

    result = await module.test_reranker_model(_config(timeout=timeout))

    assert result.success is True
    assert result.correct_count == 5


@pytest.mark.asyncio
async def test_probe_enforces_suite_deadline_across_requests(monkeypatch):
    """A server that never answers must be cut off by the suite budget, not
    left to run for 5 x timeout."""
    monkeypatch.setattr(
        module,
        "reranker_suite_deadline_seconds",
        lambda _timeout: 0.05,
    )

    async def slow_post(self, url, headers=None, json=None, extensions=None):
        await asyncio.sleep(1)
        return _FakeResponse(payload=_results(0.9, 0.1, 0.1))

    _install(monkeypatch)
    monkeypatch.setattr(_FakeAsyncClient, "post", slow_post)

    result = await module.test_reranker_model(_config(timeout=1.0))

    assert result.success is False
    assert "timed out" in result.message


@pytest.mark.asyncio
async def test_probe_deadline_covers_url_validation(monkeypatch):
    """URL validation (DNS resolution) runs inside the same suite deadline."""
    monkeypatch.setattr(
        module,
        "reranker_suite_deadline_seconds",
        lambda _timeout: 0.05,
    )

    async def slow_validate(*_args, **_kwargs):
        await asyncio.sleep(1)
        return [
            module._ResolvedTarget(
                request_url="https://example.com/v1/rerank",
                host_header="example.com",
                sni_hostname="example.com",
                secure=True,
            ),
        ]

    _install(monkeypatch)
    monkeypatch.setattr(module, "_validate_reranker_base_url", slow_validate)

    result = await module.test_reranker_model(_config(timeout=1.0))

    assert result.success is False
    assert "timed out" in result.message


@pytest.mark.asyncio
async def test_probe_rejects_private_target_by_default(monkeypatch) -> None:
    posted = _install(
        monkeypatch,
        response=_FakeResponse(payload=_results(*(0.9, 0.1, 0.1))),
    )

    result = await module.test_reranker_model(
        _config(base_url="http://127.0.0.1:8000/v1"),
    )

    assert result.success is False
    assert "non-public address" in result.message
    # Rejected before any probe request was sent.
    assert posted == []


@pytest.mark.asyncio
async def test_probe_can_verify_local_endpoint_when_trusted(
    monkeypatch,
) -> None:
    """The runtime reranker supports a local deployment; a trusted caller may
    verify the same endpoint instead of being rejected before the probe."""
    posted = _install(
        monkeypatch,
        responses=[
            _FakeResponse(payload=payload)
            for payload in _suite_scores(top_at=_expected_indices())
        ],
    )

    result = await module.test_reranker_model(
        _config(base_url="http://127.0.0.1:8000/v1"),
        allow_private=True,
    )

    assert result.success is True
    assert result.correct_count == 5
    assert len(posted) == 5
    assert posted[0]["url"] == "http://127.0.0.1:8000/v1/rerank"


@pytest.mark.asyncio
async def test_probe_still_rejects_unusable_addresses_when_trusted(
    monkeypatch,
) -> None:
    _install(
        monkeypatch,
        response=_FakeResponse(payload=_results(0.9, 0.1, 0.1)),
    )

    result = await module.test_reranker_model(
        _config(base_url="http://0.0.0.0:8000/v1"),
        allow_private=True,
    )

    assert result.success is False
    assert "non-public address" in result.message


def _fake_dns(addresses: list[str]):
    """Replace the loop resolver so hostname probes never touch real DNS."""

    class _FakeLoop:
        async def getaddrinfo(self, host, port, type=None):
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, port))
                for addr in addresses
            ]

    return _FakeLoop()


@pytest.mark.asyncio
async def test_probe_pins_resolved_address_and_keeps_origin(monkeypatch):
    """Hostname probes dial the validated IP while Host/SNI keep the
    configured origin, so a hostname cannot re-resolve to a different
    address between validation and the request (DNS rebinding)."""
    monkeypatch.setattr(
        module.asyncio,
        "get_running_loop",
        lambda: _fake_dns(["93.184.216.34"]),
    )
    posted = _install(
        monkeypatch,
        responses=[
            _FakeResponse(payload=payload)
            for payload in _suite_scores(top_at=_expected_indices())
        ],
    )

    result = await module.test_reranker_model(
        _config(base_url="https://reranker.example/v1"),
    )

    assert result.success is True
    assert result.correct_count == 5
    assert posted[0]["url"] == "https://93.184.216.34/v1/rerank"
    assert posted[0]["headers"]["Host"] == "reranker.example"
    assert posted[0]["extensions"] == {"sni_hostname": "reranker.example"}


@pytest.mark.asyncio
async def test_probe_keeps_explicit_port_and_private_hostname(monkeypatch):
    monkeypatch.setattr(
        module.asyncio,
        "get_running_loop",
        lambda: _fake_dns(["10.0.0.5"]),
    )
    posted = _install(
        monkeypatch,
        responses=[
            _FakeResponse(payload=payload)
            for payload in _suite_scores(top_at=_expected_indices())
        ],
    )

    result = await module.test_reranker_model(
        _config(base_url="http://reranker.lan:8000/v1"),
        allow_private=True,
    )

    assert result.success is True
    assert posted[0]["url"] == "http://10.0.0.5:8000/v1/rerank"
    assert posted[0]["headers"]["Host"] == "reranker.lan:8000"
    # Plain HTTP needs no TLS SNI.
    assert posted[0]["extensions"] is None


@pytest.mark.asyncio
async def test_probe_pins_ipv6_literal_with_brackets(monkeypatch) -> None:
    posted = _install(
        monkeypatch,
        responses=[
            _FakeResponse(payload=payload)
            for payload in _suite_scores(top_at=_expected_indices())
        ],
    )

    result = await module.test_reranker_model(
        _config(base_url="http://[::1]:8000/v1"),
        allow_private=True,
    )

    assert result.success is True
    assert posted[0]["url"] == "http://[::1]:8000/v1/rerank"
    assert posted[0]["headers"]["Host"] == "[::1]:8000"


@pytest.mark.asyncio
async def test_probe_falls_back_to_next_validated_address(monkeypatch):
    """A dual-stack hostname with an IPv4-only service must still verify:
    the probe retries the remaining validated addresses within the suite
    deadline."""
    monkeypatch.setattr(
        module.asyncio,
        "get_running_loop",
        lambda: _fake_dns(["::1", "127.0.0.1"]),
    )
    posted = _install(
        monkeypatch,
        responses=[
            _FakeResponse(payload=payload)
            for payload in _suite_scores(top_at=_expected_indices())
        ],
    )

    async def post(self, url, headers=None, json=None, extensions=None):
        type(self).posted.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "extensions": extensions,
            },
        )
        if "[::1]" in url:
            raise httpx.ConnectError("connection refused")
        served = self._served
        self._served += 1
        return self._responses[min(served, len(self._responses) - 1)]

    monkeypatch.setattr(_FakeAsyncClient, "post", post)

    result = await module.test_reranker_model(
        _config(base_url="http://reranker.lan:8000/v1"),
        allow_private=True,
    )

    assert result.success is True
    assert result.correct_count == 5
    urls = [entry["url"] for entry in posted]
    assert urls[0] == "http://[::1]:8000/v1/rerank"
    assert urls[1] == "http://127.0.0.1:8000/v1/rerank"
    assert len(urls) == 6  # one refused connect, then the five-case suite


@pytest.mark.asyncio
async def test_probe_rejects_embedded_credentials(monkeypatch) -> None:
    _install(
        monkeypatch,
        response=_FakeResponse(payload=_results(0.9, 0.1, 0.1)),
    )

    result = await module.test_reranker_model(
        _config(base_url="https://user:pass@example.com/v1"),
        allow_private=True,
    )

    assert result.success is False
    assert "credentials" in result.message


def test_extract_scores_ignores_boolean_relevance_scores() -> None:
    scores, correct = module._extract_scores(
        [
            {"index": 0, "relevance_score": True},
            {"index": 1, "relevance_score": False},
            {"index": 2, "relevance_score": False},
        ],
        3,
        0,
    )

    assert scores is None
    assert correct is None
