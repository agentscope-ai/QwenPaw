# -*- coding: utf-8 -*-
"""TypeSafe evaluation uses provider settings and validates responses."""

import json

import httpx2
import pytest
from agentscope.classifier import BinaryAnswer, BinaryQuestion

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
