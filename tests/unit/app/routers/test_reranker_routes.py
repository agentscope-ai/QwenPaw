# -*- coding: utf-8 -*-
"""Reranker probe endpoints: trust-gated local targets and tidy responses."""

import json
import secrets
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.agents.memory.reme_reranker import RerankerTestResult
from qwenpaw.agents.memory.reranker_auto_probe import RerankerProbeOutcome
from qwenpaw.agents.memory.reranker_history import (
    RerankerHistoryRecord,
    service_fingerprint,
)
from qwenpaw.app import auth
from qwenpaw.app.routers import workspace
from qwenpaw.config.config import RerankerConfig

_TEST_BASE_URL = "https://api.example.com/v1"
_TEST_KEY = f"probe-{secrets.token_hex(12)}"
_SAVED_FINGERPRINT = "sha256:" + "a" * 64


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
        "incomplete_count": 0,
        "precision": 1.0,
        "cases": [],
    }
    values.update(overrides)
    return RerankerTestResult(**values)


def _saved_config() -> RerankerConfig:
    return RerankerConfig(
        enabled=True,
        api_key=_TEST_KEY,
        base_url=_TEST_BASE_URL,
        model_name="probe-reranker",
        timeout=10,
        auto_verify_interval_hours=24,
    )


def test_trusted_caller_may_probe_local_endpoint(monkeypatch) -> None:
    captured = {}

    async def fake_probe(reranker, *, allow_private=False):
        captured["allow_private"] = allow_private
        return RerankerProbeOutcome(
            result=_probe_result(),
            fingerprint=_SAVED_FINGERPRINT,
        )

    monkeypatch.setattr(workspace, "probe_and_record", fake_probe)

    client = _client(monkeypatch, allow_no_auth_hosts=("10.0.0.9",))
    response = client.post("/api/workspace/reranker/test", json=_config())

    assert response.status_code == 200
    assert captured["allow_private"] is True


def test_untrusted_caller_cannot_probe_local_endpoint(monkeypatch) -> None:
    captured = {}

    async def fake_probe(reranker, *, allow_private=False):
        captured["allow_private"] = allow_private
        return RerankerProbeOutcome(
            result=_probe_result(),
            fingerprint=_SAVED_FINGERPRINT,
        )

    monkeypatch.setattr(workspace, "probe_and_record", fake_probe)

    client = _client(monkeypatch, allow_no_auth_hosts=("192.168.1.5",))
    response = client.post(
        "/api/workspace/reranker/test",
        json=_config(base_url="http://127.0.0.1:8000/v1"),
    )

    assert response.status_code == 200
    assert captured["allow_private"] is False


def test_probe_response_masks_api_key_and_reuses_returned_series(
    monkeypatch,
) -> None:
    calls = []
    series = [
        RerankerHistoryRecord(
            ts=1,
            latency_ms=5,
            precision=1.0,
            correct_count=5,
            total=5,
        ),
    ]

    async def fake_probe(reranker, *, allow_private=False):
        calls.append((reranker.api_key, allow_private))
        return RerankerProbeOutcome(
            result=_probe_result(message=f"auth failed for {_TEST_KEY}"),
            fingerprint=_SAVED_FINGERPRINT,
            history=series,
        )

    monkeypatch.setattr(workspace, "probe_and_record", fake_probe)
    monkeypatch.setattr(
        workspace,
        "get_history",
        lambda fingerprint: pytest.fail("the route must reuse the series"),
    )

    client = _client(monkeypatch, allow_no_auth_hosts=("10.0.0.9",))
    response = client.post("/api/workspace/reranker/test", json=_config())

    body = response.json()
    assert response.status_code == 200
    assert _TEST_KEY not in body["message"]
    assert body["message"] == "auth failed for ***"
    assert body["fingerprint"] == _SAVED_FINGERPRINT
    assert body["history"][0]["precision"] == 1.0
    assert body["history_error"] is None
    assert body["incomplete_count"] == 0
    assert calls == [(_TEST_KEY, True)]


def test_probe_response_omits_history_for_failed_run(monkeypatch) -> None:
    async def fake_probe(reranker, *, allow_private=False):
        return RerankerProbeOutcome(
            result=_probe_result(success=False, message="boom"),
            fingerprint=_SAVED_FINGERPRINT,
            history=None,
        )

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
    assert body["history_error"] is None


def test_probe_endpoint_tolerates_malformed_existing_history(
    tmp_path,
    monkeypatch,
) -> None:
    """A null history entry must not turn a successful POST probe into 500."""
    from qwenpaw.agents.memory import reme_reranker
    from qwenpaw.agents.memory import reranker_history as history_module

    path = tmp_path / "reranker_history.json"
    monkeypatch.setattr(history_module, "_history_path", lambda: path)
    payload = _config()
    fp = service_fingerprint(RerankerConfig(**payload))
    path.write_text(
        json.dumps({fp: [None, {"ts": 7, "precision": 0.75}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        reme_reranker,
        "test_reranker_model",
        AsyncMock(return_value=_probe_result()),
    )

    client = _client(monkeypatch, allow_no_auth_hosts=("10.0.0.9",))
    response = client.post("/api/workspace/reranker/test", json=payload)

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["fingerprint"] == fp
    assert body["history_error"] is None
    assert len(body["history"]) == 2
    assert body["history"][0]["ts"] == 7
    assert body["history"][1]["precision"] == 1.0


def test_probe_endpoint_surfaces_history_write_error_without_500(
    tmp_path,
    monkeypatch,
) -> None:
    """A history write failure must not fail a successful probe with 500."""
    from qwenpaw.agents.memory import reme_reranker
    from qwenpaw.agents.memory import reranker_history as history_module

    path = tmp_path / "reranker_history.json"
    monkeypatch.setattr(history_module, "_history_path", lambda: path)
    monkeypatch.setattr(
        reme_reranker,
        "test_reranker_model",
        AsyncMock(return_value=_probe_result()),
    )

    def _boom(_data):
        raise PermissionError(
            13,
            f"Permission denied for {_TEST_KEY}",
            "/secret/working_dir/reranker_history.json.tmp",
        )

    monkeypatch.setattr(history_module, "_write", _boom)

    client = _client(monkeypatch, allow_no_auth_hosts=("10.0.0.9",))
    response = client.post("/api/workspace/reranker/test", json=_config())

    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["precision"] == 1.0
    assert body["history"] is None
    assert body["history_error"] is not None
    assert "Permission denied" in body["history_error"]
    assert "/secret/working_dir" not in body["history_error"]
    assert _TEST_KEY not in body["history_error"]


def test_history_endpoint_uses_saved_config_fingerprint(monkeypatch) -> None:
    monkeypatch.setattr(
        workspace,
        "get_agent_for_request",
        AsyncMock(return_value=SimpleNamespace(agent_id="default")),
    )
    monkeypatch.setattr(
        workspace,
        "load_reranker_config",
        AsyncMock(return_value=_saved_config()),
    )
    monkeypatch.setattr(
        workspace,
        "service_fingerprint",
        lambda _config: _SAVED_FINGERPRINT,
    )
    monkeypatch.setattr(
        workspace,
        "get_history",
        lambda fingerprint: (
            [
                {
                    "ts": 1,
                    "latency_ms": 5,
                    "precision": 0.5,
                    "correct_count": 1,
                    "total": 2,
                },
            ]
            if fingerprint == _SAVED_FINGERPRINT
            else []
        ),
    )

    client = _client(monkeypatch)
    # No client-supplied fingerprint: the browser never hashes.
    response = client.get("/api/workspace/reranker/history")

    body = response.json()
    assert response.status_code == 200
    assert body["fingerprint"] == _SAVED_FINGERPRINT
    assert body["history"][0]["precision"] == 0.5


def test_history_endpoint_without_saved_config(monkeypatch) -> None:
    monkeypatch.setattr(
        workspace,
        "get_agent_for_request",
        AsyncMock(return_value=SimpleNamespace(agent_id="default")),
    )
    monkeypatch.setattr(
        workspace,
        "load_reranker_config",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        workspace,
        "get_history",
        lambda fingerprint: pytest.fail("no fingerprint, no lookup"),
    )

    client = _client(monkeypatch)
    response = client.get("/api/workspace/reranker/history")

    body = response.json()
    assert response.status_code == 200
    assert body == {"fingerprint": "", "history": []}


def test_history_endpoint_tolerates_malformed_records(monkeypatch) -> None:
    """A null entry under a valid fingerprint must not 500 the endpoint."""
    monkeypatch.setattr(
        workspace,
        "get_agent_for_request",
        AsyncMock(return_value=SimpleNamespace(agent_id="default")),
    )
    monkeypatch.setattr(
        workspace,
        "load_reranker_config",
        AsyncMock(return_value=_saved_config()),
    )
    monkeypatch.setattr(
        workspace,
        "service_fingerprint",
        lambda _config: _SAVED_FINGERPRINT,
    )

    from qwenpaw.agents.memory import reranker_history as history_module

    monkeypatch.setattr(
        history_module,
        "_load",
        lambda: {_SAVED_FINGERPRINT: [None, {"ts": 7, "precision": 0.75}]},
    )

    client = _client(monkeypatch)
    response = client.get("/api/workspace/reranker/history")

    body = response.json()
    assert response.status_code == 200
    assert body["history"] == [
        {
            "ts": 7,
            "latency_ms": 0,
            "precision": 0.75,
            "correct_count": 0,
            "total": 0,
        },
    ]
