# -*- coding: utf-8 -*-
"""验证自定义决策模型的配置、传输、响应校验与故障处理。"""

import asyncio
import json

import httpx
import httpx2
import pytest
from agentscope.classifier import BinaryQuestion, ChoiceQuestion, ScoreQuestion
from typesafe_sdk import AsyncTypeSafeClient

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.exceptions import ProviderError
from qwenpaw.providers import ModelInfo, ProviderInfo, ProviderManager
from qwenpaw.providers import local_decision_model
from qwenpaw.providers.custom_decision_model import decision_base_url
from qwenpaw.providers.typesafe_provider import (
    TypeSafeEvaluationError,
    TypeSafeProvider,
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
            base_url="http://endpoint.test:8000/gateway/v1/",
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


def tool_reply(protocol, model, impact):
    labels = ("read_only", "routine", "risky", "unclear")
    probabilities = {label: float(label == impact) for label in labels}
    risks = ("destructive", "secret_exposure", "privilege_change")
    if protocol == "systemone":
        return {
            "model": model,
            "answers": {
                "impact": {
                    "type": "choice",
                    "choice": impact,
                    "confidence": 1,
                    "probabilities": probabilities,
                },
                **{name: {"type": "noul", "noul": 0} for name in risks},
            },
            "usage": {"input_tokens": 8, "output_tokens": 0},
        }
    answers = {"impact": probabilities, **dict.fromkeys(risks, 0)}
    return chat_reply(json.dumps(answers))


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
    replies.append((200, tool_reply(protocol, slot.model, "unclear")))
    checked = await manager.check_provider_model(slot.provider_id, slot.model)
    assert checked.success and checked.verification == "live"
    assert len(calls) == 1
    request, body = calls[0]
    assert request.url.port == 8000
    assert request.extensions["timeout"]["read"] == 7
    assert request.headers["authorization"] == "Bearer fixture-key"
    assert request.headers["X-Project"] == "decisions"
    assert body["model"] == slot.model
    if protocol == "systemone":
        assert request.url.path == "/gateway/v1/systemone"
        assert "content-encoding" not in request.headers
        questions = body["questions"]
        state = body["state"]
    else:
        assert request.url.path == "/gateway/v1/chat/completions"
        assert body["response_format"] == {"type": "json_object"}
        questions = json.loads(body["messages"][0]["content"].splitlines()[-1])
        state = json.loads(body["messages"][1]["content"])["state"]
    assert set(questions) == {
        "impact",
        "destructive",
        "secret_exposure",
        "privilege_change",
    }
    assert state["tool"] == "write_file" and state["target"] == "example.txt"


@pytest.mark.parametrize(
    "url",
    ["https://endpoint.test/v1", "http://localhost:0", "http://[::1]:65535"],
)
def test_decision_base_url_accepts_valid_ports(url):
    assert decision_base_url(url) == url


@pytest.mark.parametrize("port", ["-1", "65536"])
def test_decision_base_url_rejects_out_of_range_ports(port):
    with pytest.raises(TypeSafeEvaluationError, match="base URL"):
        decision_base_url(f"http://localhost:{port}/v1")


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["systemone", "chat_completions"])
async def test_invalid_saved_port_fails_probe_and_requires_approval(
    protocol,
    endpoint,
):
    calls, _ = endpoint
    manager, slot = await configure(protocol)
    await manager.update_provider_async(
        slot.provider_id,
        {"base_url": "http://localhost:8000v1"},
    )
    with pytest.raises(ProviderError, match="base URL"):
        await manager.set_default_model("decision", slot)
    result = await assess_tool_call("write_file", "notes.txt")
    assert result.needs_approval and result.error_type
    checked = await manager.check_provider_model(slot.provider_id, slot.model)
    assert not checked.success and "base URL" in checked.message
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "protocol, constructor, error",
    [
        (
            "systemone",
            "local_decision_model.AsyncTypeSafeClient",
            httpx2.InvalidURL,
        ),
        (
            "chat_completions",
            "custom_decision_model.AsyncOpenAI",
            httpx.InvalidURL,
        ),
    ],
)
async def test_client_setup_error_fails_probe_and_requires_approval(
    protocol,
    constructor,
    error,
    monkeypatch,
):
    manager, slot = await configure(protocol)

    def reject_settings(**_kwargs):
        raise error("Invalid fixture URL")

    monkeypatch.setattr(f"qwenpaw.providers.{constructor}", reject_settings)
    result = await assess_tool_call("write_file", "notes.txt")
    assert (
        result.needs_approval
        and result.error_type == "TypeSafeEvaluationError"
    )
    checked = await manager.check_provider_model(slot.provider_id, slot.model)
    assert not checked.success and "client setup failed" in checked.message


@pytest.mark.asyncio
async def test_probe_cancels_a_slow_request(monkeypatch):
    manager, slot = await configure("chat_completions")
    attempts = []

    async def wait_for_reply(_provider, **request):
        attempts.append(request["timeout"])
        await asyncio.Event().wait()

    monkeypatch.setattr(TypeSafeProvider, "evaluate", wait_for_reply)
    async with asyncio.timeout(3):
        checked = await manager.check_provider_model(
            slot.provider_id,
            slot.model,
            timeout=0.05,
        )
    assert not checked.success and "timed out" in checked.message
    assert attempts == [0.05]


@pytest.mark.asyncio
async def test_switch_existing_model_and_classify(endpoint):
    _, replies = endpoint
    manager, slot = await configure("systemone")
    previous, _ = resolve_decision_model(slot)
    await manager.update_model_config(
        slot.provider_id,
        slot.model,
        {"decision_protocol": "chat_completions"},
    )
    provider, model = resolve_decision_model(slot)
    assert previous.get_decision_protocol(model) == "systemone"
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
async def test_chat_keeps_existing_approval_without_calling_model(endpoint):
    calls, _ = endpoint
    await configure("chat_completions")
    result = await assess_tool_call(
        "write_file",
        "notes.txt",
        baseline_ask=True,
    )
    assert result.needs_approval and result.error_type is None
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "protocol, baseline_ask, impact, needs_approval",
    [
        ("chat_completions", False, "routine", False),
        ("chat_completions", False, "risky", True),
        ("chat_completions", False, "unclear", True),
        ("systemone", True, "routine", False),
    ],
)
async def test_custom_tool_approval(
    protocol,
    baseline_ask,
    impact,
    needs_approval,
    endpoint,
):
    calls, replies = endpoint
    _, slot = await configure(protocol)
    replies.append((200, tool_reply(protocol, slot.model, impact)))

    result = await assess_tool_call(
        "write_file",
        "notes.txt",
        baseline_ask=baseline_ask,
    )
    assert result.needs_approval is needs_approval
    assert result.error_type is None
    assert len(calls) == 1
    assert calls[0][0].extensions["timeout"]["read"] == 7


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "protocol, reply",
    [
        ("systemone", httpx2.ReadTimeout("fixture timeout")),
        ("chat_completions", httpx.ReadTimeout("fixture timeout")),
        ("chat_completions", (200, chat_reply("{}", finish="length"))),
        ("chat_completions", (200, chat_reply("{}"))),
    ],
)
async def test_missing_decisions_request_user_approval(
    protocol,
    reply,
    endpoint,
):
    calls, replies = endpoint
    await configure(protocol)
    replies.append(reply)
    result = await assess_tool_call("write_file", "notes.txt")
    assert len(calls) == 1
    assert result.needs_approval and result.error_type


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
    refusal = dict.fromkeys(
        ("impact", "destructive", "secret_exposure", "privilege_change"),
    )
    replies.append((200, chat_reply(json.dumps(refusal))))
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
    replies.append(
        (200, tool_reply("chat_completions", slot.model, "routine")),
    )
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
