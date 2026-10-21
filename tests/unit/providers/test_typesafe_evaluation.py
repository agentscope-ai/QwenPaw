# -*- coding: utf-8 -*-
"""TypeSafe evaluation uses provider settings and validates responses."""

# pylint: disable=protected-access

import json
from types import SimpleNamespace

import httpx2
import pytest

from qwenpaw.providers.typesafe_provider import (
    TypeSafeEvaluationError,
    TypeSafeProvider,
)


@pytest.fixture(name="provider")
def configured_provider():
    return TypeSafeProvider(
        id="typesafe",
        name="TypeSafe",
        api_key="provider-key",
        base_url="https://proxy.example/v1",
        custom_headers={"X-Project": "demo"},
    )


@pytest.fixture(name="mock_transport")
def install_sdk_transport(monkeypatch):
    original_client = httpx2.AsyncClient

    def install(handler):
        clients = []

        def create_client(**kwargs):
            kwargs["transport"] = httpx2.MockTransport(handler)
            client = original_client(**kwargs)
            clients.append(client)
            return client

        monkeypatch.setattr(httpx2, "AsyncClient", create_client)
        return clients

    return install


@pytest.mark.asyncio
async def test_provider_key_precedes_legacy_credential(provider):
    assert await provider._evaluation_api_key() == "provider-key"


@pytest.mark.asyncio
async def test_legacy_credential_remains_usable(monkeypatch, provider):
    class LegacyStore:
        def __init__(self, _path):
            pass

        async def get(self, _ref):
            return SimpleNamespace(secrets={"api_key": "legacy-key"})

    provider.api_key = ""
    monkeypatch.setattr(
        "qwenpaw.providers.typesafe_provider.AsyncCredentialStore",
        LegacyStore,
    )
    assert await provider._evaluation_api_key() == "legacy-key"


@pytest.mark.asyncio
@pytest.mark.parametrize("base_path", ["/v1", "/v1/", "/gateway/v1/"])
async def test_evaluate_uses_provider_settings(
    mock_transport,
    provider,
    base_path,
):
    provider.base_url = f"https://proxy.example{base_path}"

    def handler(request):
        body = json.loads(request.content)
        assert request.url.host == "proxy.example"
        assert request.url.path == base_path.rstrip("/") + "/systemone"
        assert request.headers["Authorization"] == "Bearer provider-key"
        assert request.headers["X-Project"] == "demo"
        assert set(request.extensions["timeout"].values()) == {4.0}
        assert body == {
            "model": "jev-2",
            "state": {"summary": "conversation segment"},
            "questions": {
                "keep_in_context": {
                    "type": "noul",
                    "instructions": "Keep this in active context?",
                },
            },
        }
        return httpx2.Response(
            200,
            json={
                "model": "jev-2",
                "answers": {"keep_in_context": {"type": "noul", "noul": 0.8}},
                "usage": {"input_tokens": 20, "output_tokens": 4},
            },
        )

    clients = mock_transport(handler)
    result = await provider.evaluate(
        state={"summary": "conversation segment"},
        model="jev-2",
        questions={
            "keep_in_context": {
                "type": "noul",
                "instructions": "Keep this in active context?",
            },
        },
    )
    assert result["answers"]["keep_in_context"]["noul"] == 0.8
    assert result["usage"]["input_tokens"] == 20
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
async def test_choice_and_score_with_array_state(mock_transport, provider):
    questions = {
        "impact": {
            "type": "choice",
            "instructions": "Classify the operation",
            "criteria": {"routine": "Ordinary change", "risky": "Destructive"},
        },
        "severity": {
            "type": "score",
            "instructions": "Score the risk",
            "criteria": ["Low", "High"],
        },
    }
    answers = {
        "impact": {
            "type": "choice",
            "choice": "routine",
            "confidence": 0.9,
            "probabilities": {"routine": 0.9, "risky": 0.1},
        },
        "severity": {
            "type": "score",
            "score": 0.1,
            "confidence": 0.9,
            "legend": {0: "Low", 1: "High"},
            "probabilities": {0: 0.9, 1: 0.1},
        },
    }

    def handler(request):
        body = json.loads(request.content)
        assert body["state"] == ["write", "notes.txt"]
        assert body["questions"] == questions
        return httpx2.Response(
            200,
            json={
                "model": "jev-2",
                "answers": answers,
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
        )

    mock_transport(handler)
    result = await provider.evaluate(
        state=["write", "notes.txt"],
        questions=questions,
    )
    assert result["answers"] == json.loads(json.dumps(answers))


@pytest.mark.asyncio
async def test_missing_key_is_explicit_error(monkeypatch, provider):
    async def no_key(_provider):
        return None

    monkeypatch.setattr(TypeSafeProvider, "_evaluation_api_key", no_key)
    with pytest.raises(TypeSafeEvaluationError, match="not configured"):
        await provider.evaluate(
            state="x",
            questions={"q": {"type": "noul", "instructions": "x"}},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answers",
    [
        {},
        {"q": {"type": "score"}},
        {"q": {"type": "noul", "noul": False}},
        {
            "q": {
                "type": "choice",
                "choice": "safe",
                "confidence": 1.0,
                "probabilities": {"safe": 1.0},
            },
        },
    ],
)
async def test_invalid_response_envelope_is_rejected(
    mock_transport,
    provider,
    answers,
):
    clients = mock_transport(
        lambda _request: httpx2.Response(
            200,
            json={
                "model": "jev-2",
                "answers": answers,
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
        ),
    )
    with pytest.raises(
        TypeSafeEvaluationError,
        match="Invalid response envelope",
    ):
        await provider.evaluate(
            state="x",
            questions={"q": {"type": "noul", "instructions": "x"}},
        )
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [401, 429, 500, "timeout"])
async def test_sdk_failures_do_not_retry_and_close_client(
    mock_transport,
    provider,
    failure,
):
    requests = []

    def handler(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx2.ReadTimeout("Timed out", request=request)
        return httpx2.Response(failure, json={"error": "Unavailable"})

    clients = mock_transport(handler)
    with pytest.raises(TypeSafeEvaluationError):
        await provider.evaluate(
            state="x",
            questions={"q": {"type": "noul", "instructions": "x"}},
        )
    assert len(requests) == 1
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401])
async def test_model_connection_uses_evaluation(
    mock_transport,
    provider,
    status,
):
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "jev-2"
        assert body["state"] == "Hello"
        assert request.headers["X-Project"] == "demo"
        assert set(request.extensions["timeout"].values()) == {2.0}
        return httpx2.Response(
            status,
            json={
                "model": "jev-2",
                "answers": {"greeting": {"type": "noul", "noul": 0.9}},
                "usage": {"input_tokens": 10, "output_tokens": 2},
            }
            if status == 200
            else {"error": "Invalid key"},
        )

    clients = mock_transport(handler)
    result = await provider.check_model_connection("jev-2", timeout=2.0)
    assert result.success is (status == 200)
    assert result.http_status == (None if status == 200 else status)
    assert all(client.is_closed for client in clients)
