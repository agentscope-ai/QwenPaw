# -*- coding: utf-8 -*-
"""TypeSafe evaluation uses provider settings and validates responses."""

# pylint: disable=protected-access

import asyncio
import json

import httpx2
import pytest
from agentscope.classifier import (
    BinaryAnswer,
    BinaryQuestion,
    ChoiceAnswer,
    ChoiceQuestion,
    ScoreAnswer,
    ScoreQuestion,
)

from qwenpaw.exceptions import ProviderError
from qwenpaw.providers.provider_discovery import classify_discovery_error

from qwenpaw.providers.typesafe_provider import (
    TypeSafeProvider,
)


@pytest.fixture(name="provider")
def configured_provider():
    return TypeSafeProvider(
        id="typesafe",
        name="TypeSafe",
        api_key="provider-key",
        base_url="https://proxy.example",
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
@pytest.mark.parametrize("provider_key", ["provider-key", ""])
async def test_provider_and_environment_credentials(
    monkeypatch,
    mock_transport,
    provider,
    provider_key,
):
    provider.api_key = provider_key
    monkeypatch.setenv("TYPESAFE_API_KEY", "environment-key")

    def handler(request):
        expected_key = provider_key or "environment-key"
        assert request.headers["Authorization"] == f"Bearer {expected_key}"
        return httpx2.Response(200, json={"models": []})

    clients = mock_transport(handler)
    assert await provider.fetch_models() == []
    assert clients and all(client.is_closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_path",
    ["", "/", "/gateway"],
)
@pytest.mark.parametrize("extra_headers", [None, {"X-Request": "test"}])
async def test_classifier_uses_provider_settings(
    mock_transport,
    provider,
    base_path,
    extra_headers,
):
    provider.base_url = f"https://proxy.example{base_path}"

    def handler(request):
        body = json.loads(request.content)
        assert request.url.host == "proxy.example"
        assert request.url.path == base_path.rstrip("/") + "/v1/systemone"
        assert request.headers["Authorization"] == "Bearer provider-key"
        assert request.headers["X-Project"] == "demo"
        if extra_headers:
            assert request.headers["X-Request"] == "test"
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
    async with provider.open_classifier_model(
        "jev-2",
        timeout=4.0,
        max_retries=0,
    ) as classifier:
        result = await classifier(
            state={"summary": "conversation segment"},
            extra_headers=extra_headers,
            questions={
                "keep_in_context": BinaryQuestion(
                    instructions="Keep this in active context?",
                ),
            },
        )
    assert result.content["keep_in_context"] == BinaryAnswer(probability=0.8)
    assert result.usage.input_tokens == 20
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
    async with provider.open_classifier_model(
        "jev-2",
        timeout=4.0,
        max_retries=0,
    ) as classifier:
        result = await classifier(
            state=["write", "notes.txt"],
            questions={
                "impact": ChoiceQuestion(
                    instructions=questions["impact"]["instructions"],
                    criteria=questions["impact"]["criteria"],
                ),
                "severity": ScoreQuestion(
                    instructions=questions["severity"]["instructions"],
                    criteria=questions["severity"]["criteria"],
                ),
            },
        )
    assert result.content["impact"] == ChoiceAnswer(
        **{k: v for k, v in answers["impact"].items() if k != "type"},
    )
    assert result.content["severity"] == ScoreAnswer(
        **{k: v for k, v in answers["severity"].items() if k != "type"},
    )


@pytest.mark.asyncio
async def test_missing_key_is_explicit_error(monkeypatch, provider):
    provider.api_key = ""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="not configured") as error:
        async with provider.open_classifier_model(
            "jev-2",
            timeout=4.0,
            max_retries=0,
        ):
            pytest.fail("missing key must prevent model creation")
    assert error.value.details["error_type"] == "not_configured"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answers",
    [
        {"q": {"type": "score"}},
        {"q": {"type": "noul", "noul": False}},
    ],
)
async def test_invalid_response_envelope_is_rejected(
    mock_transport,
    provider,
    answers,
):
    payload = {
        "model": "jev-2",
        "answers": answers,
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }
    clients = mock_transport(
        lambda _request: httpx2.Response(
            200,
            json=payload,
        ),
    )
    with pytest.raises(
        ProviderError,
        match="TypeSafeAPIResponseValidationError",
    ):
        async with provider.open_classifier_model(
            "jev-2",
            timeout=4.0,
            max_retries=0,
        ) as classifier:
            await classifier(
                state="x",
                questions={"q": BinaryQuestion(instructions="x")},
            )
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [401, 429, 500, "timeout", "invalid-key"])
async def test_sdk_failures_do_not_retry_and_close_client(
    mock_transport,
    provider,
    failure,
):
    requests = []
    if failure == "invalid-key":
        provider.api_key = "invalid key"

    def handler(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx2.ReadTimeout("Timed out", request=request)
        return httpx2.Response(failure, json={"error": "Unavailable"})

    clients = mock_transport(handler)
    with pytest.raises(ProviderError):
        async with provider.open_classifier_model(
            "jev-2",
            timeout=4.0,
            max_retries=0,
        ) as classifier:
            await classifier(
                state="x",
                questions={"q": BinaryQuestion(instructions="x")},
            )
    assert len(requests) == (0 if failure == "invalid-key" else 1)
    assert len(clients) == (0 if failure == "invalid-key" else 1)
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401])
async def test_model_connection_uses_classifier(
    mock_transport,
    provider,
    status,
):
    provider.base_url = "https://proxy.example/gateway"

    def handler(request):
        assert request.url.path == "/gateway/v1/systemone"
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    ["classify", "fetch_models", "check_connection"],
)
async def test_cancellation_closes_client(mock_transport, provider, operation):
    def handler(_request):
        raise asyncio.CancelledError

    clients = mock_transport(handler)
    with pytest.raises(asyncio.CancelledError):
        if operation == "classify":
            async with provider.open_classifier_model(
                "jev-2",
                timeout=4.0,
                max_retries=0,
            ) as classifier:
                await classifier(
                    state="x",
                    questions={"q": BinaryQuestion(instructions="x")},
                )
        else:
            await getattr(provider, operation)()
    assert clients and all(client.is_closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_path",
    ["", "/", "/gateway"],
)
async def test_model_discovery_uses_provider_settings(
    mock_transport,
    provider,
    base_path,
):
    provider.base_url = f"https://proxy.example{base_path}"
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "GET"
        assert request.url.host == "proxy.example"
        assert request.url.path == base_path.rstrip("/") + "/v1/models"
        assert request.headers["Authorization"] == "Bearer provider-key"
        assert request.headers["X-Project"] == "demo"
        assert set(request.extensions["timeout"].values()) == {2.0}
        return httpx2.Response(
            200,
            json={
                "models": [
                    {
                        "name": "jev-2",
                        "description": "Decision model",
                        "release_date": "2026-09-15",
                    },
                ],
            },
        )

    clients = mock_transport(handler)
    models = await provider.fetch_models(timeout=2.0)
    assert [(m.id, m.name, m.model_type) for m in models] == [
        ("jev-2", "jev-2", "decision"),
    ]
    assert await provider.check_connection(timeout=2.0) == (True, "")
    assert len(requests) == 2
    assert len(clients) == 2 and all(client.is_closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["fetch_models", "check_connection"])
@pytest.mark.parametrize(
    "failure",
    [
        401,
        403,
        404,
        429,
        500,
        "timeout",
        "network",
        "invalid-response",
        "invalid-key",
        "missing-key",
    ],
)
async def test_model_discovery_failures_close_client_without_retry(
    monkeypatch,
    mock_transport,
    provider,
    operation,
    failure,
):
    requests = []
    if failure == "invalid-key":
        provider.api_key = "invalid key"
    elif failure == "missing-key":
        provider.api_key = ""
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)

    def handler(request):
        requests.append(request)
        if failure == "timeout":
            raise httpx2.ReadTimeout("Timed out", request=request)
        if failure == "network":
            raise httpx2.ConnectError("Connection failed", request=request)
        if failure == "invalid-response":
            # Metadata requirements come from the SDK's response model.
            return httpx2.Response(200, json={"models": [{"name": "jev-2"}]})
        return httpx2.Response(failure, json={"error": "Unavailable"})

    clients = mock_transport(handler)
    if operation == "fetch_models":
        with pytest.raises(ProviderError) as error:
            await provider.fetch_models()
        expected_kind = {
            401: "authentication",
            403: "authorization",
            404: "unsupported",
            "timeout": "timeout",
            "network": "network",
            "invalid-response": "invalid_response",
        }.get(failure, "provider_unavailable")
        assert (
            classify_discovery_error(error.value, str(error.value))
            == expected_kind
        )
    else:
        success, message = await provider.check_connection()
        assert not success
        assert message
        if isinstance(failure, int):
            assert str(failure) in message
        assert "provider-key" not in message
    assert len(requests) == (
        0 if failure in ("invalid-key", "missing-key") else 1
    )
    assert len(clients) == (
        0 if failure in ("invalid-key", "missing-key") else 1
    )
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answers",
    [
        {},
        {
            "greeting": {
                "type": "choice",
                "choice": "safe",
                "confidence": 1.0,
                "probabilities": {"safe": 1.0},
            },
        },
    ],
)
async def test_connection_rejects_missing_or_wrong_answer(
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
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                },
            },
        ),
    )
    result = await provider.check_model_connection("jev-2")
    assert not result.success
    assert all(client.is_closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize("usage", ["missing", {}, None, False, "invalid"])
async def test_usage_follows_sdk_response_contract(
    mock_transport,
    provider,
    usage,
):
    payload = {
        "model": "jev-2",
        "answers": {"q": {"type": "noul", "noul": 0.8}},
    }
    if usage != "missing":
        payload["usage"] = usage
    clients = mock_transport(
        lambda _request: httpx2.Response(
            200,
            json=payload,
        ),
    )
    if usage == {}:
        async with provider.open_classifier_model(
            "jev-2",
            timeout=4.0,
            max_retries=0,
        ) as classifier:
            result = await classifier(
                state="x",
                questions={"q": BinaryQuestion(instructions="x")},
            )
        assert result.content["q"] == BinaryAnswer(probability=0.8)
        assert result.usage.input_tokens is None
        assert result.usage.output_tokens is None
    else:
        with pytest.raises(
            ProviderError,
            match="TypeSafeAPIResponseValidationError",
        ):
            async with provider.open_classifier_model(
                "jev-2",
                timeout=4.0,
                max_retries=0,
            ) as classifier:
                await classifier(
                    state="x",
                    questions={"q": BinaryQuestion(instructions="x")},
                )
    assert clients and all(client.is_closed for client in clients)
