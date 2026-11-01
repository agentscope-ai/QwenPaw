# -*- coding: utf-8 -*-
"""TypeSafe evaluation uses provider settings and validates responses."""

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx2
import pytest
from agentscope.classifier import (
    BinaryAnswer,
    BinaryQuestion,
    JevClassifierModel,
)

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
        base_url="https://proxy.example",
        custom_headers={"X-Project": "demo"},
    )


_QUESTIONS = {
    "keep_in_context": BinaryQuestion(
        instructions="Keep this in active context?",
    ),
}


@pytest.mark.asyncio
async def test_evaluate_uses_provider_settings(provider, mock_typesafe):
    def handler(request):
        body = json.loads(request.content)
        assert request.url.host == "proxy.example"
        assert request.url.path == "/v1/systemone"
        assert request.headers["Authorization"] == "Bearer provider-key"
        assert request.headers["X-Project"] == "demo"
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

    mock_typesafe(handler)
    result = await provider.evaluate(
        state={"summary": "conversation segment"},
        model="jev-2",
        questions=_QUESTIONS,
    )
    assert result.model == "jev-2"
    assert result.content["keep_in_context"] == BinaryAnswer(probability=0.8)


@pytest.mark.asyncio
async def test_missing_key_is_explicit_error(provider):
    provider.api_key = ""
    with pytest.raises(TypeSafeEvaluationError, match="not configured"):
        await provider.evaluate(state="x", questions=_QUESTIONS)


@pytest.mark.asyncio
async def test_api_error_carries_http_status(provider, mock_typesafe):
    mock_typesafe(
        lambda _request: httpx2.Response(
            401,
            json={"error": {"message": "bad key"}},
        ),
    )
    with pytest.raises(TypeSafeEvaluationError) as exc_info:
        await provider.evaluate(state="x", questions=_QUESTIONS)
    assert exc_info.value.status_code == 401

    result = await provider.check_model_connection("jev-2")
    assert not result.success
    assert result.http_status == 401
    assert result.message.startswith("status=401: ")


@pytest.mark.asyncio
async def test_unsupported_answer_type_is_evaluation_error(
    provider,
    mock_typesafe,
):
    box = {
        "type": "box",
        "box": {"top": 0.1, "left": 0.1, "bottom": 0.9, "right": 0.9},
        "confidence": None,
    }
    mock_typesafe(
        lambda _request: httpx2.Response(
            200,
            json={
                "model": "jev-2",
                "answers": {"greeting": box},
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        ),
    )
    result = await provider.check_model_connection("jev-2")
    assert not result.success
    assert "Unsupported TypeSafe answer type" in result.message


@pytest.mark.asyncio
async def test_fetch_models_uses_sdk_listing(provider, mock_typesafe):
    def handler(request):
        assert request.url.path == "/v1/models"
        assert request.headers["X-Project"] == "demo"
        return httpx2.Response(
            200,
            json={
                "models": [
                    {
                        "name": "jev-2",
                        "description": "Jev 2",
                        "release_date": "2026-09-01",
                    },
                ],
            },
        )

    mock_typesafe(handler)
    models = await provider.fetch_models()
    assert [(m.id, m.model_type) for m in models] == [("jev-2", "decision")]
    assert await provider.check_connection() == (True, "")


@pytest.fixture(name="sdk_client")
def configured_sdk_client(monkeypatch):
    import typesafe_sdk as sdk

    client = SimpleNamespace(
        system_one=AsyncMock(
            return_value=SimpleNamespace(
                model="jev-2",
                answers={"q": sdk.NoulAnswer(type="noul", noul=0.2)},
                usage=sdk.Usage(input_tokens=20, output_tokens=1),
            ),
        ),
        aclose=AsyncMock(),
    )
    factory = Mock(return_value=client)
    monkeypatch.setattr(sdk, "AsyncTypeSafeClient", factory)
    return factory, client


@pytest.mark.asyncio
async def test_as_model_injects_same_instance_and_preserves_host_headers(
    provider,
    sdk_client,
):
    from reme.components.as_decision_model import AgentScopeAsDecisionModel

    factory, client = sdk_client
    model = provider.as_decision_model("jev-2")
    assert isinstance(model, JevClassifierModel)
    factory.assert_called_once()
    assert factory.call_args.kwargs["api_key"] == "provider-key"
    assert factory.call_args.kwargs["base_url"] == provider.base_url
    assert factory.call_args.kwargs["model"] == "jev-2"
    component = AgentScopeAsDecisionModel()
    component.model = model
    assert component.model is model
    response = await component(
        state={"task": "current"},
        questions={
            "q": {"type": "binary", "instructions": "Keep this result?"},
        },
    )
    assert response.content["q"].probability == 0.2
    assert response.usage.input_tokens == 20
    kwargs = client.system_one.await_args.kwargs
    assert kwargs["questions"]["q"].type == "noul"
    assert kwargs["extra_headers"] == provider.custom_headers
    await model(
        state="x",
        questions={"q": BinaryQuestion()},
        extra_headers={"X-Project": "override"},
    )
    assert client.system_one.await_args.kwargs["extra_headers"] == {
        "X-Project": "override",
    }
    await component.close()
    client.aclose.assert_not_awaited()
    await model.client.aclose()
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("max_retries", [0, 1])
async def test_as_model_preserves_timeout_and_retry_policy(
    provider,
    sdk_client,
    max_retries,
):
    model = provider.as_decision_model(
        "jev-2",
        timeout=3.5,
        max_retries=max_retries,
    )
    factory, _client = sdk_client
    assert factory.call_args.kwargs["timeout"] == 3.5
    assert factory.call_args.kwargs["retry"].max_retries == max_retries
    await model.client.aclose()


def test_as_model_requires_provider_key_before_constructing_sdk(
    monkeypatch,
    provider,
    sdk_client,
):
    provider.api_key = "  "
    monkeypatch.setenv("TYPESAFE_API_KEY", "environment-key")
    with pytest.raises(TypeSafeEvaluationError, match="not configured"):
        provider.as_decision_model("jev-2")
    factory, _client = sdk_client
    factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("construction_fails", [False, True])
async def test_cancelled_construction_finishes_and_closes_client(
    monkeypatch,
    provider,
    construction_fails,
):
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    entered, release = asyncio.Event(), threading.Event()
    closing, close_release = asyncio.Event(), asyncio.Event()

    async def close():
        closing.set()
        await close_release.wait()

    model = SimpleNamespace(
        client=SimpleNamespace(aclose=AsyncMock(side_effect=close)),
    )

    def construct(_self, *_args, **_kwargs):
        assert threading.get_ident() != loop_thread
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5), "Construction was not released"
        if construction_fails:
            raise RuntimeError("construction failed")
        return model

    monkeypatch.setattr(TypeSafeProvider, "as_decision_model", construct)
    task = asyncio.create_task(provider.as_decision_model_async("jev-2"))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        for _ in range(2):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        release.set()
        if not construction_fails:
            await asyncio.wait_for(closing.wait(), 2)
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done()
        close_release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert model.client.aclose.await_count == (
            0 if construction_fails else 1
        )
    finally:
        release.set()
        close_release.set()
        await asyncio.gather(task, return_exceptions=True)
