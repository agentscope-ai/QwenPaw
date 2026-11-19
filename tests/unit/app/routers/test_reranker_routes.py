# -*- coding: utf-8 -*-
"""Reranker probe endpoints: trust-gated local targets and tidy responses."""

import secrets
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.agents.memory.reme_reranker import RerankerTestResult
from qwenpaw.app import auth
from qwenpaw.app.routers import workspace

_TEST_BASE_URL = "https://api.example.com/v1"
_TEST_KEY = f"probe-{secrets.token_hex(12)}"


def _config(**overrides) -> dict:
    values = {
        "enabled": True,
        "api_key": _TEST_KEY,
        "base_url": _TEST_BASE_URL,
        "model_name": "probe-reranker",
        "candidate_multiplier": 3,
        "timeout": 10,
        "auto_verify_interval_hours": 0,
    }
    values.update(overrides)
    return values


def _client(monkeypatch, *, allow_no_auth_hosts=("127.0.0.1",)) -> TestClient:
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "has_registered_users", lambda: True)
    monkeypatch.setattr(auth, "is_trusted_proxy", lambda _request: False)
    monkeypatch.setattr(auth, "resolve_client_ip", lambda _request: "10.0.0.9")
    config = SimpleNamespace(
        security=SimpleNamespace(
            allow_no_auth_hosts=list(allow_no_auth_hosts),
        ),
    )
    monkeypatch.setattr(auth, "_get_config_cached", lambda: (config, []))
    app = FastAPI()
    app.include_router(workspace.router, prefix="/api")
    return TestClient(app, client=("10.0.0.9", 50000))


def _probe_result(**overrides) -> RerankerTestResult:
    values = {
        "success": True,
        "latency_ms": 42,
        "message": "Reranker service is available",
        "total": 5,
        "correct_count": 5,
        "precision": 1.0,
        "cases": [],
    }
    values.update(overrides)
    return RerankerTestResult(**values)


def test_trusted_caller_may_probe_local_endpoint(monkeypatch) -> None:
    captured = {}

    async def fake_probe(reranker, *, allow_private=False):
        captured["allow_private"] = allow_private
        return _probe_result()

    monkeypatch.setattr(workspace, "probe_and_record", fake_probe)
    monkeypatch.setattr(workspace, "get_history", lambda _fp: [])

    client = _client(monkeypatch, allow_no_auth_hosts=("10.0.0.9",))
    response = client.post("/api/workspace/reranker/test", json=_config())

    assert response.status_code == 200
    assert captured["allow_private"] is True


def test_untrusted_caller_cannot_probe_local_endpoint(monkeypatch) -> None:
    captured = {}

    async def fake_probe(reranker, *, allow_private=False):
        captured["allow_private"] = allow_private
        return _probe_result()

    monkeypatch.setattr(workspace, "probe_and_record", fake_probe)
    monkeypatch.setattr(workspace, "get_history", lambda _fp: [])

    client = _client(monkeypatch, allow_no_auth_hosts=("192.168.1.5",))
    response = client.post(
        "/api/workspace/reranker/test",
        json=_config(base_url="http://127.0.0.1:8000/v1"),
    )

    assert response.status_code == 200
    assert captured["allow_private"] is False


def test_probe_response_masks_api_key_and_reuses_history(monkeypatch) -> None:
    calls = []

    async def fake_probe(reranker, *, allow_private=False):
        calls.append((reranker.api_key, allow_private))
        return _probe_result(message=f"auth failed for {_TEST_KEY}")

    monkeypatch.setattr(workspace, "probe_and_record", fake_probe)
    monkeypatch.setattr(
        workspace,
        "get_history",
        lambda fingerprint: [
            {
                "ts": 1,
                "latency_ms": 5,
                "precision": 1.0,
                "correct_count": 5,
                "total": 5,
            },
        ],
    )

    client = _client(monkeypatch, allow_no_auth_hosts=("10.0.0.9",))
    response = client.post("/api/workspace/reranker/test", json=_config())

    body = response.json()
    assert response.status_code == 200
    assert _TEST_KEY not in body["message"]
    assert body["message"] == "auth failed for ***"
    assert body["history"][0]["precision"] == 1.0
    assert calls == [(_TEST_KEY, True)]


def test_probe_response_omits_history_for_failed_run(monkeypatch) -> None:
    async def fake_probe(reranker, *, allow_private=False):
        return _probe_result(success=False, message="boom")

    monkeypatch.setattr(workspace, "probe_and_record", fake_probe)
    monkeypatch.setattr(
        workspace,
        "get_history",
        lambda fingerprint: pytest.fail("history must not be read on failure"),
    )

    client = _client(monkeypatch, allow_no_auth_hosts=("10.0.0.9",))
    response = client.post("/api/workspace/reranker/test", json=_config())

    body = response.json()
    assert body["success"] is False
    assert body["history"] is None


def test_history_endpoint_returns_digest_series(monkeypatch) -> None:
    monkeypatch.setattr(
        workspace,
        "get_history",
        lambda fingerprint: [
            {
                "ts": 1,
                "latency_ms": 5,
                "precision": 0.5,
                "correct_count": 1,
                "total": 2,
            },
        ],
    )

    client = _client(monkeypatch)
    response = client.get(
        "/api/workspace/reranker/history",
        params={"fingerprint": "sha256:" + "a" * 64},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["fingerprint"] == "sha256:" + "a" * 64
    assert body["history"][0]["precision"] == 0.5
