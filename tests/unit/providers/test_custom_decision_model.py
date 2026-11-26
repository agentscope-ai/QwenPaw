# -*- coding: utf-8 -*-
"""验证自定义决策模型的配置、传输、响应校验与故障处理。"""

import json

import httpx
import httpx2
import pytest
from agentscope.classifier import BinaryQuestion, ChoiceQuestion, ScoreQuestion
from typesafe_sdk import AsyncTypeSafeClient

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.providers import ModelInfo, ProviderInfo, ProviderManager
from qwenpaw.providers import local_decision_model
from qwenpaw.providers.typesafe_provider import (
    TypeSafeEvaluationError,
    resolve_decision_model,
)
from qwenpaw.security.decision_model import assess_tool_call


@pytest.fixture
def endpoint(monkeypatch):
    calls = []
    replies = []

    def handler(request):
        calls.append((request, json.loads(request.content)))
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        if isinstance(request, httpx2.Request):
            return httpx2.Response(status, json=body)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(
        httpx.AsyncHTTPTransport,
        "handle_async_request",
        httpx.MockTransport(handler).handle_async_request,
    )
    monkeypatch.setattr(
        local_decision_model,
        "AsyncTypeSafeClient",
        lambda **kw: AsyncTypeSafeClient(
            transport=httpx2.MockTransport(handler),
            **kw,
        ),
    )
    return calls, replies


async def configure(protocol):
    manager = ProviderManager.get_instance()
    await manager.add_custom_provider(
        ProviderInfo(
            id="my-endpoint",
            name="My endpoint",
            base_url="http://endpoint.test/gateway/v1/",
            api_key="fixture-key",
            custom_headers={"X-Project": "decisions"},
        ),
    )
    await manager.add_model_to_provider(
        "my-endpoint",
        ModelInfo(
            id="my-decision",
            name="My decision",
            model_type="decision",
            decision_protocol=protocol,
        ),
    )
    slot = ModelSlotConfig(provider_id="my-endpoint", model="my-decision")
    await manager.set_default_model("decision", slot)
    return manager, slot


def chat_reply(content, finish="stop"):
    return {
        "id": "fixture",
        "object": "chat.completion",
        "model": "my-decision",
        "created": 1,
        "choices": [
            {
                "index": 0,
                "finish_reason": finish,
                "message": {"role": "assistant", "content": content},
            },
        ],
        "usage": {
            "prompt_tokens": 8,
            "completion_tokens": 4,
            "total_tokens": 12,
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["systemone", "chat_completions"])
async def test_select_reload_and_probe(protocol, endpoint, monkeypatch):
    calls, replies = endpoint
    manager, slot = await configure(protocol)
    original_chat = manager.default_models["chat"]
    monkeypatch.setattr(ProviderManager, "_instance", None)
    manager = ProviderManager.get_instance()
    assert manager.default_models["decision"] == slot
    assert manager.default_models["chat"] == original_chat
    provider = manager.get_provider(slot.provider_id)
    assert provider.get_model_info(slot.model).decision_protocol == protocol
    if protocol == "systemone":
        replies.append(
            (
                200,
                {
                    "model": slot.model,
                    "answers": {"greeting": {"type": "noul", "noul": 0.95}},
                    "usage": {"input_tokens": 8, "output_tokens": 0},
                },
            ),
        )
        path = "/gateway/v1/systemone"
    else:
        replies.append((200, chat_reply('{"greeting":0.95}')))
        path = "/gateway/v1/chat/completions"
    checked = await manager.check_provider_model(slot.provider_id, slot.model)
    assert checked.success and checked.verification == "live"
    assert len(calls) == 1
    request, body = calls[0]
    assert request.url.path == path
    assert request.headers["authorization"] == "Bearer fixture-key"
    assert request.headers["X-Project"] == "decisions"
    assert body["model"] == slot.model
    if protocol == "systemone":
        assert body["questions"]["greeting"]["type"] == "noul"
        assert "content-encoding" not in request.headers
    else:
        assert body["response_format"] == {"type": "json_object"}
        assert json.loads(body["messages"][1]["content"])["state"] == "Hello"


@pytest.mark.asyncio
async def test_switch_existing_model_and_classify(endpoint):
    _, replies = endpoint
    manager, slot = await configure("systemone")
    await manager.update_model_config(
        slot.provider_id,
        slot.model,
        {"decision_protocol": "chat_completions"},
    )
    provider, model = resolve_decision_model(slot)
    replies.append(
        (
            200,
            chat_reply(
                json.dumps(
                    {
                        "keep": 0.8,
                        "route": {"a": 0.2, "b": 0.8},
                        "score": {"0": 0.3, "1": 0.7},
                    },
                ),
            ),
        ),
    )
    response = await provider.evaluate(
        model=model,
        state={"task": "sample"},
        questions={
            "keep": BinaryQuestion(),
            "route": ChoiceQuestion(criteria={"a": None, "b": None}),
            "score": ScoreQuestion(criteria=["low", "high"]),
        },
    )
    assert response.content["keep"].probability == 0.8
    assert response.content["route"].choice == "b"
    assert response.content["score"].score == pytest.approx(0.7)
    assert response.usage.input_tokens == 8


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "{}",
        '{"keep":true}',
        '{"keep":2}',
        '{"keep":NaN}',
    ],
)
async def test_malformed_chat_decisions_are_rejected(content, endpoint):
    _, replies = endpoint
    _, slot = await configure("chat_completions")
    provider, model = resolve_decision_model(slot)
    replies.append((200, chat_reply(content)))
    with pytest.raises(TypeSafeEvaluationError):
        await provider.evaluate(
            model=model,
            state="sample",
            questions={"keep": BinaryQuestion()},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reply",
    [
        httpx.ReadTimeout("fixture timeout"),
        (200, chat_reply("{}", finish="length")),
        (200, chat_reply("{}")),
    ],
)
async def test_missing_chat_decisions_request_user_approval(reply, endpoint):
    calls, replies = endpoint
    await configure("chat_completions")
    replies.append(reply)
    result = await assess_tool_call(
        "write_file",
        "notes.txt",
        baseline_ask=True,
    )
    assert calls and result.needs_approval and result.error_type


@pytest.mark.asyncio
async def test_switch_protocol_discards_old_probe_and_rejects_refusal(
    endpoint,
):
    _, replies = endpoint
    manager, slot = await configure("systemone")
    replies.append((404, {"error": "unknown route"}))
    assert not (
        await manager.check_provider_model(slot.provider_id, slot.model)
    ).success
    await manager.update_model_config(
        slot.provider_id,
        slot.model,
        {"decision_protocol": "chat_completions"},
    )
    provider, _ = resolve_decision_model(slot)
    assert (
        provider.get_model_info(slot.model).availability_status == "unverified"
    )
    replies.append((200, chat_reply('{"greeting":null}')))
    assert not (
        await manager.check_provider_model(slot.provider_id, slot.model)
    ).success


@pytest.mark.asyncio
async def test_unavailable_custom_model_stays_unavailable(endpoint):
    _, replies = endpoint
    manager, slot = await configure("chat_completions")
    replies.append((401, {"error": {"message": "Unauthorized"}}))
    checked = await manager.check_provider_model(slot.provider_id, slot.model)
    assert not checked.success and checked.http_status == 401
    with pytest.raises(TypeSafeEvaluationError):
        resolve_decision_model(slot)
    replies.append((200, chat_reply('{"greeting":0.95}')))
    assert (
        await manager.check_provider_model(slot.provider_id, slot.model)
    ).success


@pytest.mark.asyncio
@pytest.mark.parametrize("distribution", [{"a": 1}, {"a": 0.9, "b": 0.9}])
async def test_choice_checks_all_candidates_and_total_probability(
    distribution,
    endpoint,
):
    _, replies = endpoint
    _, slot = await configure("chat_completions")
    provider, model = resolve_decision_model(slot)
    replies.append((200, chat_reply(json.dumps({"route": distribution}))))
    with pytest.raises(TypeSafeEvaluationError):
        await provider.evaluate(
            model=model,
            state="sample",
            questions={
                "route": ChoiceQuestion(criteria={"a": None, "b": None}),
            },
        )
