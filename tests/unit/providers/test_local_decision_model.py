# -*- coding: utf-8 -*-
"""Native SystemOne decisions feed approval and ReMe consumers."""

# pylint: disable=protected-access

import asyncio
import json
from types import SimpleNamespace

import httpx2 as httpx
import pytest
from typesafe_sdk import AsyncTypeSafeClient
from agentscope.classifier import BinaryQuestion

from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.providers import ProviderManager
from qwenpaw.providers.services.qwenpaw import QwenPawProvider
from qwenpaw.security import decision_model


@pytest.fixture(name="local")
def local_fixture(monkeypatch):
    # pylint: disable=too-many-statements
    provider = QwenPawProvider(
        id="qwenpaw-local",
        name="Local fixture",
        base_url="http://127.0.0.1:9000/v1",
        models=[
            {
                "id": "piccolo-fixture",
                "name": "Piccolo fixture",
                "model_type": "decision",
            },
        ],
    )
    state = SimpleNamespace(
        mode="ok",
        requests=[],
        clients=[],
        client_options=[],
    )

    def handler(req):
        # pylint: disable=too-many-branches
        state.requests.append(req)
        assert req.url.path == "/v1/systemone"
        assert "content-encoding" not in req.headers
        body = json.loads(req.content)
        assert body["model"] == "piccolo-fixture"
        assert set(body) == {"model", "state", "questions"}
        if state.mode == "http_error":
            return httpx.Response(503, json={"error": {"message": "Loading"}})
        if state.mode == "timeout":
            raise httpx.ReadTimeout("timeout", request=req)
        answers = {}
        for name, question in body["questions"].items():
            if question["type"] == "noul":
                answers[name] = {"type": "noul", "noul": 0.001}
            else:
                options = list(question["criteria"])
                selected = "routine" if "routine" in options else options[0]
                probabilities = dict.fromkeys(options, 0.0)
                probabilities[selected] = 1.0
                answers[name] = {
                    "type": "choice",
                    "choice": selected,
                    "confidence": 1.0,
                    "probabilities": probabilities,
                }
        if "impact" in answers:
            if state.mode == "missing_confidence":
                answers["impact"].pop("confidence")
            if state.mode == "low_confidence":
                answers["impact"]["confidence"] = 0.1
            if state.mode == "missing_probability":
                answers["impact"]["probabilities"].pop("risky")
            if state.mode == "bad_sum":
                answers["impact"]["probabilities"]["risky"] = 0.5
            if state.mode == "bad_choice":
                answers["impact"]["choice"] = "risky"
            if state.mode == "risk":
                answers["destructive"]["noul"] = 0.9
        if state.mode == "bad_json":
            return httpx.Response(200, text="invalid response")
        return httpx.Response(
            200,
            json={
                "model": "piccolo-fixture",
                "answers": answers,
                "usage": {"input_tokens": 40, "output_tokens": 0},
            },
        )

    def make_client(**kwargs):
        state.client_options.append(kwargs)
        client = AsyncTypeSafeClient(
            transport=httpx.MockTransport(handler),
            **kwargs,
        )
        state.clients.append(client)
        return client

    monkeypatch.setattr(
        "qwenpaw.providers.local_decision_model.AsyncTypeSafeClient",
        make_client,
    )
    slot = ModelSlotConfig(provider_id=provider.id, model="piccolo-fixture")
    manager = SimpleNamespace(
        default_models={"decision": slot},
        get_provider=lambda _: provider,
    )
    monkeypatch.setattr(ProviderManager, "get_instance", lambda: manager)
    state.provider = provider
    return state


@pytest.mark.asyncio
async def test_local_review_and_compaction_use_separate_timeout_budgets(local):
    await local.provider.evaluate(
        model="piccolo-fixture",
        state="A bounded local operation",
        questions={"q": BinaryQuestion(instructions="Safe?")},
    )
    assert local.client_options[-1]["timeout"] == 7.0

    await local.provider.evaluate(
        model="piccolo-fixture",
        state="A bounded local operation",
        questions={"q": BinaryQuestion(instructions="Safe?")},
        timeout=2,
    )
    assert local.client_options[-1]["timeout"] == 2

    classifier = await local.provider.as_decision_model_async(
        "piccolo-fixture",
    )
    try:
        assert local.client_options[-1]["timeout"] == 30
    finally:
        await classifier.client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,needs_approval",
    [
        ("ok", False),
        ("low_confidence", True),
        ("risk", True),
        ("missing_confidence", True),
        ("missing_probability", True),
        ("bad_sum", True),
        ("bad_choice", True),
        ("bad_json", True),
        ("http_error", True),
        ("timeout", True),
    ],
)
async def test_native_approval_uses_local_selection_and_fails_closed(
    local,
    mode,
    needs_approval,
):
    local.mode = mode
    result = await decision_model.assess_tool_call(
        "write_file",
        "/tmp/synthetic.txt",
        operation="write",
        baseline_ask=True,
        params={"content": "PRIVATE_VALUE_NOT_SENT"},
    )
    assert result.needs_approval is needs_approval
    assert len(local.requests) == 1
    assert "PRIVATE_VALUE_NOT_SENT" not in local.requests[0].content.decode()
    assert all(client._http_client.is_closed for client in local.clients)


@pytest.mark.asyncio
async def test_factory_and_reme_keep_native_answer_interface(local):
    from qwenpaw.agents.model_factory import create_decision_model_async
    from reme.components.as_decision_model import AgentScopeAsDecisionModel

    model = await create_decision_model_async(
        AgentProfileConfig(id="fixture", name="Fixture"),
    )
    component = AgentScopeAsDecisionModel()
    component.model = model
    try:
        response = await component(
            state="Synthetic tool result",
            questions={
                "keep": {"type": "binary", "instructions": "Relevant?"},
            },
        )
        assert response.content["keep"].probability == 0.001
        assert response.usage.input_tokens == 40
    finally:
        await component.close()
        await model.client.aclose()
    assert all(client._http_client.is_closed for client in local.clients)


@pytest.mark.asyncio
async def test_chat_model_is_not_silently_used_as_decision_model(local):
    local.provider.models[0].model_type = "chat"
    result = await decision_model.assess_tool_call(
        "write_file",
        "/tmp/example",
        operation="write",
    )
    assert result.needs_approval
    assert not local.requests


@pytest.mark.asyncio
async def test_cancelled_request_closes_client(local, monkeypatch):
    from qwenpaw.providers.local_decision_model import LocalDecisionModel

    async def cancel(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(LocalDecisionModel, "__call__", cancel)
    with pytest.raises(asyncio.CancelledError):
        await local.provider.evaluate(
            model="piccolo-fixture",
            state="x",
            questions={"q": BinaryQuestion(instructions="Relevant?")},
        )
    assert all(client._http_client.is_closed for client in local.clients)
