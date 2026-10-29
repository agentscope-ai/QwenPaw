# -*- coding: utf-8 -*-
"""Protocol integration checks for local ChatGPT subscriptions."""
# pylint: disable=protected-access,redefined-outer-name

import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from agentscope.agent import Agent, InjectionConfig
from agentscope.message import Msg, TextBlock, ToolResultBlock
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import FunctionTool, ToolChoice, Toolkit, ToolResponse
from openai import APIError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa

from qwenpaw.providers import chatgpt_provider as model_module
from qwenpaw.providers.oauth import chatgpt as auth_module
from qwenpaw.providers.provider import agent_thinking_level
from qwenpaw.security import secret_store
from qwenpaw.runtime.envelope import Envelope


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    cipher = Fernet(Fernet.generate_key())
    monkeypatch.setattr(secret_store, f"_get_fernet", lambda: cipher)
    return auth_module.ChatGPTAccounts(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "peer,forwarded,trusted,status",
    [
        ("127.0.0.1", "", ["127.0.0.1/32"], 200),
        ("127.0.0.1", "127.0.0.1", ["127.0.0.1/32"], 200),
        ("127.0.0.1", "203.0.113.7", ["127.0.0.1/32"], 403),
        ("203.0.113.7", "127.0.0.1", [], 403),
        ("203.0.113.7", "127.0.0.1", ["203.0.113.7/32"], 403),
    ],
)
async def test_account_controls_require_local_client_through_proxy(
    monkeypatch,
    peer,
    forwarded,
    trusted,
    status,
):
    from fastapi import Depends, FastAPI
    from qwenpaw.app import auth
    from qwenpaw.app.routers.chatgpt import require_local

    config = SimpleNamespace(
        security=SimpleNamespace(allow_no_auth_hosts=[]),
    )
    networks = auth._parse_networks(trusted)
    monkeypatch.setattr(auth, "_get_config_cached", lambda: (config, networks))
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "has_registered_users", lambda: True)
    monkeypatch.setattr(
        auth,
        "verify_token",
        lambda token: "alice" if token == "valid" else None,
    )
    app = FastAPI()

    @app.get("/api/account-controls", dependencies=[Depends(require_local)])
    async def account_controls():
        return {"available": True}

    app.add_middleware(auth.AuthMiddleware)
    app.add_middleware(auth.TrustedProxySchemeMiddleware)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(peer, 12345)),
        base_url="http://127.0.0.1:8088",
    ) as client:
        response = await client.get(
            "/api/account-controls",
            headers={
                "Authorization": "Bearer valid",
                "X-Forwarded-For": forwarded,
                "X-Forwarded-Proto": "https",
            },
        )
    assert response.status_code == status
    if status == 200:
        assert response.json() == {"available": True}
        assert response.headers["Cache-Control"] == "no-store"


def test_loopback_registration_identity_refresh_and_signout(
    accounts,
    monkeypatch,
):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        accounts,
        f"_discovery",
        lambda: {f"jwks_uri": f"test"},
    )
    monkeypatch.setattr(
        auth_module.jwt,
        f"PyJWKClient",
        lambda _: SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(
                key=private.public_key(),
            ),
        ),
    )
    started = accounts.start()
    query = parse_qs(urlsplit(started[f"authorize_url"]).query)
    attempt = accounts.attempt
    assert query[f"client_id"] == [f"dynamic_agent_client"]
    assert query[f"code_challenge"] == [
        auth_module.generate_code_challenge(attempt.verifier),
    ]
    claims = {
        f"iss": auth_module.ISSUER,
        f"sub": f"user",
        f"aud": f"oaiapp_test",
        f"exp": time.time() + 3600,
        f"nonce": attempt.nonce,
        f"email": f"user@example.test",
    }
    identity = jwt.encode(claims, private, algorithm=f"RS256")
    with pytest.raises(ValueError, match=f"nonce"):
        accounts._identity(identity, f"oaiapp_test", f"invalid")
    with pytest.raises(jwt.InvalidAudienceError):
        accounts._identity(identity, f"different", attempt.nonce)

    def exchange(form):
        assert form[f"client_id"] == f"oaiapp_test"
        assert form[f"redirect_uri"] == attempt.redirect
        assert form[f"code_verifier"] == attempt.verifier
        with accounts._lock().acquire(timeout=0):
            data = accounts._read()
            data[f"accounts"][f"oaiapp_other"] = {}
            accounts._save(data)
        return {
            f"access_token": f"secret-access",
            f"refresh_token": f"secret-refresh",
            f"id_token": identity,
            f"expires_in": 1,
            f"scope": auth_module.PLAN_SCOPE,
        }

    monkeypatch.setattr(accounts, f"_token", exchange)
    assert (
        httpx.get(attempt.redirect, params={f"state": f"wrong"}).status_code
        == 400
    )
    response = httpx.get(
        attempt.redirect,
        params={
            f"state": attempt.state,
            f"code": f"code",
            f"client_id": f"oaiapp_test",
        },
    )
    assert response.status_code == 200
    assert response.headers[f"content-type"].startswith(f"text/html")
    assert response.text == auth_module.oauth_success_html(f"openai-chatgpt")
    assert accounts.status()[f"sharing"]
    assert f"oaiapp_other" in accounts._read()[f"accounts"]
    assert f"secret-access" not in accounts.path.read_text()

    def renew(form):
        assert form[f"refresh_token"] == f"secret-refresh"
        assert form[f"client_id"] == f"oaiapp_test"
        return {
            f"access_token": f"rotated-access",
            f"refresh_token": f"rotated-refresh",
            f"expires_in": 3600,
        }

    monkeypatch.setattr(accounts, f"_token", renew)
    assert accounts.access_token() == f"rotated-access"
    assert (
        accounts._read()[f"accounts"][f"oaiapp_test"][f"refresh_token"]
        == f"rotated-refresh"
    )
    again = accounts.start(f"oaiapp_test")
    again_query = parse_qs(urlsplit(again[f"authorize_url"]).query)
    assert again_query[f"ext_agent_host_id"] == query[f"ext_agent_host_id"]
    assert again_query[f"client_id"] == [f"oaiapp_test"]
    assert f"agent_name_hint" not in again_query
    accounts.cancel(again[f"state"])

    def revocation_discovery():
        with accounts._lock().acquire(timeout=0):
            assert not accounts._read()[f"accounts"][f"oaiapp_test"].get(
                f"refresh_token",
            )
        return {f"revocation_endpoint": f"https://auth.example/revoke"}

    monkeypatch.setattr(accounts, f"_discovery", revocation_discovery)
    monkeypatch.setattr(
        auth_module.httpx,
        f"post",
        lambda *a, **k: httpx.Response(200),
    )
    assert accounts.sign_out()
    assert not accounts.status()[f"connected"]
    assert accounts.status()[f"accounts"][0][f"id"] == f"oaiapp_test"


@pytest.mark.asyncio
async def test_native_messages_tool_roundtrip_and_terminal_events(monkeypatch):
    monkeypatch.setattr(
        model_module.chatgpt_accounts,
        f"access_token",
        lambda: f"oauth",
    )
    events = []
    requests = []

    def transport(request):
        assert request.url == f"https://api.openai.com/v1/responses"
        assert request.headers[f"authorization"] == f"Bearer oauth"
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            headers={f"content-type": f"text/event-stream"},
            text=f"".join(f"data: {json.dumps(e)}\n\n" for e in events),
        )

    original = model_module.AsyncOpenAI
    monkeypatch.setattr(
        model_module,
        f"AsyncOpenAI",
        lambda **kwargs: original(
            **kwargs,
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(transport),
            ),
        ),
    )
    model = model_module.ChatGPTModel(f"account-model")
    history = [
        Msg(
            name=f"system",
            role=f"system",
            content=[TextBlock(text=f"Help.")],
        ),
        Msg(name=f"user", role=f"user", content=[TextBlock(text=f"Weather?")]),
    ]
    tools = [
        {
            f"type": f"function",
            f"function": {
                f"name": f"weather",
                f"parameters": {f"type": f"object", f"properties": {}},
            },
        },
    ]
    events.append(
        {
            f"type": f"response.completed",
            f"response": {
                f"id": f"resp_1",
                f"usage": {f"input_tokens": 10, f"output_tokens": 2},
                f"output": [
                    {
                        f"type": f"function_call",
                        f"call_id": f"call_1",
                        f"name": f"weather",
                        f"arguments": f'{{"city":"Paris"}}',
                    },
                ],
            },
        },
    )
    completed = events[0]
    item = completed[f"response"][f"output"].pop()
    events.insert(
        0,
        {
            f"type": f"response.output_item.done",
            f"output_index": 0,
            f"item": item,
        },
    )
    item[f"id"] = f"fc_1"
    events[:0] = [
        {
            f"type": f"response.output_item.added",
            f"output_index": 0,
            f"item": {**item, f"arguments": f""},
        },
        {
            f"type": f"response.function_call_arguments.delta",
            f"item_id": f"fc_1",
            f"delta": item[f"arguments"],
        },
    ]
    tool_events = list(events)
    chunks = [
        chunk
        async for chunk in await model(
            history,
            tools=tools,
            tool_choice=ToolChoice(mode=f"weather"),
            temperature=1,
            max_output_tokens=32,
            reasoning={f"effort": f"high"},
        )
    ]
    result = chunks[-1]
    assert result.is_last
    streamed_calls = [
        block
        for chunk in chunks
        if not chunk.is_last
        for block in chunk.content
        if block.type == f"tool_call"
    ]
    assert len(streamed_calls) == 1
    assert streamed_calls[0].id == f"call_1"
    assert streamed_calls[0].input == item[f"arguments"]
    assert result.content[0].type == f"tool_call"
    assert result.usage.input_tokens == 10
    assert requests[-1][f"tools"][0][f"type"] == f"namespace"
    assert requests[-1][f"tools"][0][f"description"]
    assert requests[-1][f"tool_choice"] == f"required"
    assert requests[-1][f"reasoning"] == {f"effort": f"high"}
    assert f"temperature" not in requests[-1]
    assert f"max_output_tokens" not in requests[-1]
    assert requests[-1][f"store"] is False and requests[-1][f"stream"] is True
    history.extend(
        [
            Msg(name=f"assistant", role=f"assistant", content=result.content),
            Msg(
                name=f"tool",
                role=f"assistant",
                content=[
                    ToolResultBlock(
                        id=f"call_1",
                        name=f"weather",
                        output=f"Sunny",
                    ),
                ],
            ),
        ],
    )
    events[:] = [
        {
            f"type": f"response.completed",
            f"response": {
                f"id": f"resp_2",
                f"usage": None,
                f"output": [
                    {
                        f"type": f"message",
                        f"content": [
                            {f"type": f"output_text", f"text": f"Sunny."},
                        ],
                    },
                ],
            },
        },
    ]
    text_events = list(events)
    model.stream = False
    result = await model(history, tools=tools)
    assert result.content[0].text == f"Sunny."
    assert any(
        i.get(f"namespace") == f"qwenpaw" for i in requests[-1][f"input"]
    )
    assert requests[-1][f"input"][-1][f"call_id"] == f"call_1"
    model.stream = True

    await _assert_agent_tool_events(
        model,
        history[1],
        events,
        tool_events,
        text_events,
    )
    for ending in (
        [],
        [{f"type": f"response.incomplete"}],
        [
            {
                f"type": f"response.failed",
                f"response": {
                    f"error": {
                        f"code": f"subscription_sharing_usage_limit_exceeded",
                        f"message": f"Plan limit reached.",
                    },
                },
            },
        ],
    ):
        events[:] = ending
        with pytest.raises((RuntimeError, APIError)):
            async for _ in await model(history):
                pass


async def _assert_agent_tool_events(
    model,
    prompt,
    events,
    tool_events,
    text_events,
):
    """Verify the production Agent-to-Envelope lifecycle."""

    async def weather(city: str) -> ToolResponse:
        """Return weather for a city."""
        assert city == f"Paris"
        events[:] = text_events
        return ToolResponse(content=[TextBlock(text=f"Sunny")])

    events[:] = tool_events
    agent = Agent(
        name=f"test",
        system_prompt=f"Help.",
        model=model,
        toolkit=Toolkit(
            tools=[
                FunctionTool(
                    weather,
                    permission=PermissionDecision(
                        behavior=PermissionBehavior.ALLOW,
                        message=f"Read-only test fixture.",
                    ),
                ),
            ],
        ),
        injection_config=InjectionConfig(inject_runtime_state=False),
    )
    envelope = Envelope()
    async for event in agent.reply_stream(inputs=prompt):
        if not isinstance(event, Msg):
            async for _ in envelope.translate_event(event):
                pass
    messages = envelope._response.output
    calls = [m for m in messages if m.type == f"plugin_call"]
    results = [m for m in messages if m.type == f"plugin_call_output"]
    assert len(calls) == len(results) == 1
    call = calls[0].content[0].data
    result = results[0].content[0].data
    assert call[f"call_id"] == result[f"call_id"] == f"call_1"
    assert call[f"arguments"] == tool_events[1][f"delta"]
    assert result[f"state"] == f"success"
    assert f"Sunny" in result[f"output"]


@pytest.mark.asyncio
async def test_account_catalog_does_not_include_api_key_models(monkeypatch):
    monkeypatch.setattr(
        model_module.chatgpt_accounts,
        f"access_token",
        lambda: f"oauth",
    )
    original = httpx.AsyncClient
    monkeypatch.setattr(
        model_module.httpx,
        f"AsyncClient",
        lambda **kwargs: original(
            **kwargs,
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        f"models": [
                            {
                                f"slug": f"account-model",
                                f"display_name": f"Account model",
                                f"visibility": f"list",
                                f"context_window": 272000,
                                f"max_context_window": 872000,
                                f"input_modalities": [f"text", f"image"],
                                f"default_reasoning_level": f"low",
                                f"supported_reasoning_levels": [
                                    {f"effort": f"low"},
                                    {f"effort": f"high"},
                                    {f"effort": f"ultra"},
                                ],
                            },
                            {f"slug": f"hidden", f"visibility": f"hidden"},
                        ],
                    },
                ),
            ),
        ),
    )
    provider = model_module.ChatGPTProvider(
        id=f"openai-chatgpt",
        name=f"ChatGPT",
    )
    provider.discovered_models = await provider.fetch_models()
    assert [m.id for m in provider.discovery_candidates()] == [
        f"account-model",
    ]

    # Old selections retain their identity and use fresh account capabilities.
    provider.models = [
        model_module.ModelInfo(
            id=f"account-model",
            name=f"Old selection",
            max_input_length=200000,
        ),
    ]
    card = provider.model_capabilities(provider.models[0])
    assert card.supports_image is True
    assert card.supports_multimodal is True
    assert card.max_input_length == 272000
    assert card.max_input_length_auto_detected == 872000
    assert card.effective_max_input_length == 272000
    assert card.pricing == {}
    assert provider.resolve_model_info(card.id) == card
    assert card.thinking_control.efforts == [f"low", f"high"]
    assert card.reasoning_effort == f"low"
    assert provider.thinking_control(card.id).kind == f"effort"
    with agent_thinking_level(f"high"):
        runtime = provider.get_chat_model_instance(card.id)
    assert runtime._extra_generate_kwargs[f"reasoning"] == {
        f"effort": f"high",
    }
