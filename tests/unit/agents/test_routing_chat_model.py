# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,unused-argument,use-implicit-booleaness-not-comparison  # noqa: E501
"""Unit tests for the local/cloud chat-model router."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from qwenpaw.agents.routing_chat_model import (
    RoutingChatModel,
    RoutingDecision,
    RoutingEndpoint,
    RoutingPolicy,
)
from qwenpaw.config.config import AgentsLLMRoutingConfig


def _endpoint(provider_id="local-prov", model_name="local-model"):
    """An endpoint whose model is an AsyncMock so calls are awaitable."""
    model = AsyncMock()
    model.return_value = "response-from-" + provider_id
    return RoutingEndpoint(
        provider_id=provider_id,
        model_name=model_name,
        model=model,
        formatter=MagicMock(),
        formatter_family=type(MagicMock()),
    )


def _router(local_mode="local_first", **kwargs):
    cfg = AgentsLLMRoutingConfig(mode=local_mode)
    local = _endpoint("local-prov", "local-model")
    cloud = _endpoint("cloud-prov", "cloud-model")
    model = RoutingChatModel(
        local_endpoint=local,
        cloud_endpoint=cloud,
        routing_cfg=cfg,
    )
    return model, local, cloud


class TestRoutingDecision:
    def test_defaults_to_an_empty_reason_list(self):
        decision = RoutingDecision(route="local")
        assert decision.reasons == []

    def test_two_decisions_do_not_share_one_reason_list(self):
        first = RoutingDecision(route="local")
        second = RoutingDecision(route="cloud")
        first.reasons.append("x")
        assert second.reasons == []


class TestRoutingPolicy:
    def test_local_first_mode_routes_local(self):
        policy = RoutingPolicy(AgentsLLMRoutingConfig(mode="local_first"))
        decision = policy.decide()
        assert decision.route == "local"
        assert decision.reasons == ["mode:local_first"]

    def test_cloud_first_mode_routes_cloud(self):
        policy = RoutingPolicy(AgentsLLMRoutingConfig(mode="cloud_first"))
        decision = policy.decide()
        assert decision.route == "cloud"
        assert decision.reasons == ["mode:cloud_first"]

    def test_default_mode_is_local_first(self):
        policy = RoutingPolicy(AgentsLLMRoutingConfig())
        assert policy.decide().route == "local"

    def test_a_config_object_without_mode_falls_back_to_local(self):
        """getattr() default guards a partially-populated config."""
        policy = RoutingPolicy(object())
        assert policy.decide().route == "local"
        assert policy.decide().reasons == ["mode:local_first"]

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"text": "hello"},
            {"channel": "dingtalk"},
            {"tools_available": False},
            {"text": "x", "channel": "y", "tools_available": True},
        ],
    )
    def test_request_signals_do_not_change_the_route(self, kwargs):
        """The policy documents smarter switching as not implemented."""
        policy = RoutingPolicy(AgentsLLMRoutingConfig(mode="local_first"))
        assert policy.decide(**kwargs).route == "local"

    def test_cloud_first_ignores_request_signals_too(self):
        policy = RoutingPolicy(AgentsLLMRoutingConfig(mode="cloud_first"))
        assert (
            policy.decide(text="heavy", tools_available=False).route == "cloud"
        )


class TestRouterConstruction:
    def test_exposes_both_endpoints(self):
        model, local, cloud = _router()
        assert model.local_endpoint is local
        assert model.cloud_endpoint is cloud

    def test_keeps_the_routing_config(self):
        model, _, _ = _router()
        assert model.routing_cfg.mode == "local_first"

    def test_builds_a_policy_from_the_config(self):
        model, _, _ = _router()
        assert isinstance(model.policy, RoutingPolicy)
        assert model.policy.cfg is model.routing_cfg

    def test_base_class_model_name_is_routing(self):
        model, _, _ = _router()
        assert model.model == "routing"

    def test_stream_flag_follows_the_local_endpoint(self):
        local = _endpoint()
        local.model.stream = False
        cloud = _endpoint("cloud-prov", "cloud-model")
        model = RoutingChatModel(
            local_endpoint=local,
            cloud_endpoint=cloud,
            routing_cfg=AgentsLLMRoutingConfig(),
        )
        assert model.stream is False

    def test_stream_defaults_to_true_when_the_endpoint_omits_it(self):
        """A bare endpoint exercises every getattr() default in __init__."""
        # spec=["__call__"] keeps the model awaitable while making
        # stream/credential/parameters genuinely absent (plain AsyncMock
        # auto-creates any attribute, so getattr() would never fall back).
        bare = AsyncMock(spec=["__call__"])
        local = RoutingEndpoint(
            provider_id="bare-prov",
            model_name="bare-model",
            model=bare,
            formatter=MagicMock(),
            formatter_family=type(MagicMock()),
        )
        model = RoutingChatModel(
            local_endpoint=local,
            cloud_endpoint=_endpoint("cloud-prov", "cloud-model"),
            routing_cfg=AgentsLLMRoutingConfig(),
        )

        assert model.stream is True

    def test_parameters_fall_back_to_the_base_class_default(self):
        from agentscope.model import ChatModelBase

        bare = AsyncMock(spec=["__call__"])
        local = RoutingEndpoint(
            provider_id="bare-prov",
            model_name="bare-model",
            model=bare,
            formatter=MagicMock(),
            formatter_family=type(MagicMock()),
        )
        model = RoutingChatModel(
            local_endpoint=local,
            cloud_endpoint=_endpoint("cloud-prov", "cloud-model"),
            routing_cfg=AgentsLLMRoutingConfig(),
        )

        assert isinstance(model.parameters, ChatModelBase.Parameters)

    def test_credential_defaults_to_none_when_the_endpoint_has_none(self):
        bare = AsyncMock(spec=["__call__"])
        local = RoutingEndpoint(
            provider_id="bare-prov",
            model_name="bare-model",
            model=bare,
            formatter=MagicMock(),
            formatter_family=type(MagicMock()),
        )
        model = RoutingChatModel(
            local_endpoint=local,
            cloud_endpoint=_endpoint("cloud-prov", "cloud-model"),
            routing_cfg=AgentsLLMRoutingConfig(),
        )

        assert model.credential is None


class TestRouterDispatch:
    async def test_local_first_calls_the_local_endpoint(self):
        model, local, cloud = _router("local_first")

        result = await model([{"role": "user", "content": "hi"}])

        assert result == "response-from-local-prov"
        local.model.assert_awaited_once()
        cloud.model.assert_not_awaited()

    async def test_cloud_first_calls_the_cloud_endpoint(self):
        model, local, cloud = _router("cloud_first")

        result = await model([{"role": "user", "content": "hi"}])

        assert result == "response-from-cloud-prov"
        cloud.model.assert_awaited_once()
        local.model.assert_not_awaited()

    async def test_forwards_messages_tools_and_tool_choice(self):
        model, local, _ = _router("local_first")
        messages = [{"role": "user", "content": "hi"}]
        tools = [{"name": "search"}]

        await model(messages, tools=tools, tool_choice="required")

        kwargs = local.model.await_args.kwargs
        assert kwargs["messages"] is messages
        assert kwargs["tools"] is tools
        assert kwargs["tool_choice"] == "required"

    async def test_drops_the_agentscope_1x_structured_model_kwarg(self):
        """A leftover 1.x kwarg must not reach the 2.0 endpoint."""
        model, local, _ = _router("local_first")

        await model(
            [{"role": "user", "content": "hi"}],
            structured_model=MagicMock(),
        )

        assert "structured_model" not in local.model.await_args.kwargs

    async def test_passes_through_unknown_kwargs(self):
        model, local, _ = _router("local_first")

        await model([{"role": "user", "content": "hi"}], temperature=0.3)

        assert local.model.await_args.kwargs["temperature"] == 0.3

    async def test_tools_default_to_none(self):
        model, local, _ = _router("local_first")

        await model([{"role": "user", "content": "hi"}])

        assert local.model.await_args.kwargs["tools"] is None

    async def test_only_user_text_is_collected_for_the_policy(self):
        """System and assistant turns must not feed the routing text."""
        model, _, _ = _router("local_first")
        captured = {}

        def fake_decide(**kwargs):
            captured.update(kwargs)
            return RoutingDecision(route="local", reasons=["mode:local_first"])

        model.policy.decide = fake_decide

        await model(
            [
                {"role": "system", "content": "sys prompt"},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "reply"},
                {"role": "user", "content": "second"},
            ],
        )

        assert captured["text"] == "first second"

    async def test_non_string_content_is_ignored_when_joining(self):
        """A list-of-blocks message must not blow up the join."""
        model, _, _ = _router("local_first")
        captured = {}

        def fake_decide(**kwargs):
            captured.update(kwargs)
            return RoutingDecision(route="local", reasons=["mode:local_first"])

        model.policy.decide = fake_decide

        await model(
            [
                {"role": "user", "content": [{"type": "image"}]},
                {"role": "user", "content": "real text"},
            ],
        )

        assert captured["text"] == "real text"

    async def test_missing_content_key_is_tolerated(self):
        model, _, _ = _router("local_first")
        captured = {}

        def fake_decide(**kwargs):
            captured.update(kwargs)
            return RoutingDecision(route="local", reasons=["mode:local_first"])

        model.policy.decide = fake_decide

        await model([{"role": "user"}])

        assert captured["text"] == ""

    async def test_tools_availability_is_reported_to_the_policy(self):
        model, _, _ = _router("local_first")
        captured = {}

        def fake_decide(**kwargs):
            captured.update(kwargs)
            return RoutingDecision(route="local", reasons=["mode:local_first"])

        model.policy.decide = fake_decide

        await model([{"role": "user", "content": "hi"}])
        assert captured["tools_available"] is False

        await model([{"role": "user", "content": "hi"}], tools=[])
        assert captured["tools_available"] is True
