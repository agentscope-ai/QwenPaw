# -*- coding: utf-8 -*-
"""Behavioural tests for the Hub model-service wire protocol.

``qwenpaw.hub.model_service.protocol`` is the only place that decides
what a member's Chat Completions body may ask for, what the server
sends upstream instead, and what of the upstream answer may be echoed
back.  ``qwenpaw.hub.model_service.runtime_policy`` decides which model
routes a member API may not reach at all.  Both are module-level pure
functions with no persisted state, so they are driven directly.

The thinking-control leg of ``upstream_payload`` resolves a provider
through ``model_provider``, which reads the packaged provider catalog;
that lookup is stubbed here so the assertions stay about this module's
translation rules rather than about catalog contents.
"""
# pylint: disable=redefined-outer-name,unused-argument
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from qwenpaw.hub.model_service import protocol as pr
from qwenpaw.hub.model_service import runtime_policy as rp

MODEL = {
    "upstream_model": "qwen-max",
    "output_limit_field": "max_tokens",
}
CONNECTION: dict[str, Any] = {"provider_id": "dashscope", "id": "c1"}


def _body(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": "alias-1", "messages": []}
    payload.update(overrides)
    return payload


def _provider(
    *,
    supports: bool = True,
    controls: dict[str, Any] | None = None,
) -> MagicMock:
    """Stub the provider that ``model_provider`` would resolve."""
    provider = MagicMock(name="ProviderStub")
    provider.supports_agent_thinking.return_value = supports
    provider.get_agent_thinking_kwargs.return_value = dict(controls or {})
    return provider


# ---------------------------------------------------------------------------
# usage_tokens
# ---------------------------------------------------------------------------


class TestUsageTokens:
    def test_sums_prompt_and_completion(self) -> None:
        payload = {"usage": {"prompt_tokens": 3, "completion_tokens": 4}}
        assert pr.usage_tokens(payload) == 7

    def test_zeros_are_a_real_total_not_absence(self) -> None:
        payload = {"usage": {"prompt_tokens": 0, "completion_tokens": 0}}
        assert pr.usage_tokens(payload) == 0

    def test_no_usage_key_is_none(self) -> None:
        assert pr.usage_tokens({}) is None

    @pytest.mark.parametrize("usage", [None, 7, "3", [1, 2]])
    def test_non_dict_usage_is_none(self, usage: Any) -> None:
        assert pr.usage_tokens({"usage": usage}) is None

    @pytest.mark.parametrize(
        "usage",
        [
            {"prompt_tokens": 3},
            {"completion_tokens": 4},
            {"prompt_tokens": None, "completion_tokens": 4},
            {"prompt_tokens": 3, "completion_tokens": None},
        ],
    )
    def test_incomplete_usage_is_none(self, usage: dict) -> None:
        assert pr.usage_tokens({"usage": usage}) is None

    def test_negative_usage_is_none(self) -> None:
        payload = {"usage": {"prompt_tokens": -1, "completion_tokens": 4}}
        assert pr.usage_tokens(payload) is None

    @pytest.mark.parametrize(
        "value",
        [True, False, 1.0, "3", [3]],
    )
    def test_non_int_usage_is_none(self, value: Any) -> None:
        """``type(value) is not int`` excludes bool and float too.

        A bool total would silently charge 0 or 1 token, so the strict
        type test is the point of the assertion.
        """
        usage = {"prompt_tokens": value, "completion_tokens": 4}
        assert pr.usage_tokens({"usage": usage}) is None

    def test_unrelated_keys_do_not_count(self) -> None:
        usage = {
            "prompt_tokens": 2,
            "completion_tokens": 5,
            "total_tokens": 999,
            "cached": 1,
        }
        assert pr.usage_tokens({"usage": usage}) == 7


# ---------------------------------------------------------------------------
# safe_payload
# ---------------------------------------------------------------------------


class TestSafePayload:
    def test_keeps_only_protocol_output_fields(self) -> None:
        payload = {
            "id": "i",
            "object": "chat.completion.chunk",
            "created": 1,
            "choices": [{"delta": {"content": "hi"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            "model": "upstream-name",
            "reasoning_content": "SECRET",
            "messages": [{"role": "user"}],
            "system_fingerprint": "fp",
        }
        assert pr.safe_payload(payload, "alias-1") == {
            "id": "i",
            "object": "chat.completion.chunk",
            "created": 1,
            "choices": [{"delta": {"content": "hi"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            "model": "alias-1",
        }

    def test_upstream_model_name_is_never_leaked(self) -> None:
        payload = {"model": "vendor/internal-alias", "choices": []}
        assert pr.safe_payload(payload, "public-alias")["model"] == (
            "public-alias"
        )

    def test_empty_payload_still_carries_the_alias(self) -> None:
        assert pr.safe_payload({}, "alias-1") == {"model": "alias-1"}

    def test_upstream_error_is_not_forwarded(self) -> None:
        payload = {"error": {"message": "upstream blew up"}}
        with pytest.raises(ValueError, match="Upstream stream error"):
            pr.safe_payload(payload, "alias-1")

    def test_error_key_wins_even_beside_valid_fields(self) -> None:
        payload = {"id": "i", "choices": [], "error": "bad"}
        with pytest.raises(ValueError):
            pr.safe_payload(payload, "alias-1")


# ---------------------------------------------------------------------------
# validate_request
# ---------------------------------------------------------------------------


class TestValidateRequestShape:
    @pytest.mark.parametrize("body", ["x", 7, None, [], ()])
    def test_non_dict_body_is_422(self, body: Any) -> None:
        with pytest.raises(HTTPException) as excinfo:
            pr.validate_request(body)
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == "Unsupported model request fields"

    @pytest.mark.parametrize(
        "extra",
        ["api_base", "base_url", "api_key", "http_client", "extra_headers"],
    )
    def test_connection_override_is_rejected(self, extra: str) -> None:
        """A member must not be able to redirect the gateway upstream."""
        with pytest.raises(HTTPException) as excinfo:
            pr.validate_request(_body(**{extra: "http://evil.example/v1"}))
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == "Unsupported model request fields"

    def test_minimal_body_is_accepted(self) -> None:
        assert pr.validate_request(_body()) is None

    @pytest.mark.parametrize(
        "field",
        [
            "model",
            "messages",
            "stream",
            "stream_options",
            "tools",
            "tool_choice",
            "parallel_tool_calls",
            "temperature",
            "top_p",
            "stop",
            "seed",
            "response_format",
            "frequency_penalty",
            "presence_penalty",
            "max_tokens",
            "max_completion_tokens",
            "n",
            "hub_thinking_level",
        ],
    )
    def test_every_allowlisted_field_alone_is_supported(
        self,
        field: str,
    ) -> None:
        body = {"model": "alias-1", "messages": [], field: None}
        try:
            pr.validate_request(body)
        except HTTPException as exc:
            # Only a field-level rule may complain, never the allowlist.
            assert exc.detail != "Unsupported model request fields"


class TestValidateRequestThinkingLevel:
    @pytest.mark.parametrize(
        "level",
        ["inherit", "off", "low", "medium", "high"],
    )
    def test_documented_levels_are_accepted(self, level: str) -> None:
        body = _body(hub_thinking_level=level)
        assert pr.validate_request(body) is None

    @pytest.mark.parametrize("level", ["ultra", "", "LOW", 1, None, True])
    def test_anything_else_is_422(self, level: Any) -> None:
        with pytest.raises(HTTPException) as excinfo:
            pr.validate_request(_body(hub_thinking_level=level))
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == "Invalid Hub thinking level"


class TestValidateRequestCoreFields:
    @pytest.mark.parametrize("model", [1, None, [], {}])
    def test_model_must_be_a_string(self, model: Any) -> None:
        with pytest.raises(HTTPException) as excinfo:
            pr.validate_request(_body(model=model))
        assert excinfo.value.detail == "Invalid Chat Completions request"

    @pytest.mark.parametrize("messages", ["x", 1, None, {}])
    def test_messages_must_be_a_list(self, messages: Any) -> None:
        with pytest.raises(HTTPException) as excinfo:
            pr.validate_request(_body(messages=messages))
        assert excinfo.value.detail == "Invalid Chat Completions request"

    @pytest.mark.parametrize("n", [0, 2, -1, "1", None, [1], {}])
    def test_n_must_be_exactly_one(self, n: Any) -> None:
        """Fan-out multiplies organization cost, so it is pinned to 1."""
        with pytest.raises(HTTPException) as excinfo:
            pr.validate_request(_body(n=n))
        assert excinfo.value.detail == "Invalid Chat Completions request"

    def test_n_one_is_accepted(self) -> None:
        assert pr.validate_request(_body(n=1)) is None

    def test_n_is_compared_numerically_not_by_type(self) -> None:
        """Observed behaviour, pinned so a change is a visible decision.

        ``n`` is checked with ``!= 1``, so ``1.0`` passes, while
        ``stream`` and the output limits use ``type(...) is ...`` and
        reject their float/bool look-alikes.  ``1.0`` still means one
        completion, so the laxer check is not a cost hole.
        """
        assert pr.validate_request(_body(n=1.0)) is None
        assert pr.validate_request(_body(n=True)) is None

    @pytest.mark.parametrize("stream", ["yes", 1, 0, None, "false"])
    def test_stream_must_be_a_real_bool(self, stream: Any) -> None:
        with pytest.raises(HTTPException) as excinfo:
            pr.validate_request(_body(stream=stream))
        assert excinfo.value.detail == "Invalid Chat Completions request"

    @pytest.mark.parametrize("stream", [True, False])
    def test_bool_stream_is_accepted(self, stream: bool) -> None:
        assert pr.validate_request(_body(stream=stream)) is None


class TestValidateRequestOutputLimits:
    def test_no_limit_returns_none(self) -> None:
        assert pr.validate_request(_body()) is None

    def test_null_limit_is_ignored(self) -> None:
        body = _body(max_tokens=None, max_completion_tokens=None)
        assert pr.validate_request(body) is None

    def test_single_limit_is_returned(self) -> None:
        assert pr.validate_request(_body(max_completion_tokens=77)) == 77

    def test_smallest_of_two_limits_wins(self) -> None:
        body = _body(max_tokens=50, max_completion_tokens=20)
        assert pr.validate_request(body) == 20

    def test_smallest_of_two_limits_wins_the_other_way(self) -> None:
        body = _body(max_tokens=12, max_completion_tokens=900)
        assert pr.validate_request(body) == 12

    def test_limit_of_one_is_valid(self) -> None:
        assert pr.validate_request(_body(max_tokens=1)) == 1

    @pytest.mark.parametrize("value", [0, -3])
    def test_non_positive_limit_is_422(self, value: int) -> None:
        with pytest.raises(HTTPException) as excinfo:
            pr.validate_request(_body(max_tokens=value))
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == (
            "Output limit must be a positive integer"
        )

    @pytest.mark.parametrize("value", [1.5, "20", True, [20]])
    def test_non_int_limit_is_422(self, value: Any) -> None:
        with pytest.raises(HTTPException) as excinfo:
            pr.validate_request(_body(max_tokens=value))
        assert excinfo.value.detail == (
            "Output limit must be a positive integer"
        )

    def test_a_bad_limit_is_caught_whichever_field_holds_it(self) -> None:
        body = _body(max_tokens=10, max_completion_tokens=-1)
        with pytest.raises(HTTPException):
            pr.validate_request(body)


# ---------------------------------------------------------------------------
# upstream_payload
# ---------------------------------------------------------------------------


class TestUpstreamPayloadRouting:
    def test_model_alias_is_replaced_by_the_upstream_id(self) -> None:
        out = pr.upstream_payload(_body(), MODEL, 100, CONNECTION)
        assert out["model"] == "qwen-max"

    def test_server_owns_the_output_bound(self) -> None:
        out = pr.upstream_payload(
            _body(max_tokens=999999),
            MODEL,
            100,
            CONNECTION,
        )
        assert out["max_tokens"] == 100

    def test_both_client_limit_fields_are_dropped(self) -> None:
        body = _body(max_tokens=999, max_completion_tokens=888)
        out = pr.upstream_payload(body, MODEL, 100, CONNECTION)
        assert out == {
            "model": "qwen-max",
            "messages": [],
            "max_tokens": 100,
        }

    def test_the_configured_limit_field_is_used(self) -> None:
        model = {
            "upstream_model": "gpt-x",
            "output_limit_field": "max_completion_tokens",
        }
        out = pr.upstream_payload(_body(), model, 55, CONNECTION)
        assert out["max_completion_tokens"] == 55
        assert "max_tokens" not in out

    def test_client_stream_options_are_replaced(self) -> None:
        body = _body(stream_options={"include_usage": False})
        out = pr.upstream_payload(body, MODEL, 10, CONNECTION)
        assert "stream_options" not in out

    def test_streaming_forces_usage_reporting(self) -> None:
        out = pr.upstream_payload(_body(stream=True), MODEL, 10, CONNECTION)
        assert out["stream"] is True
        assert out["stream_options"] == {"include_usage": True}

    def test_non_streaming_gets_no_stream_options(self) -> None:
        out = pr.upstream_payload(_body(), MODEL, 10, CONNECTION)
        assert "stream_options" not in out

    def test_other_body_fields_pass_through(self) -> None:
        body = _body(
            tools=[{"type": "function"}],
            tool_choice="auto",
            temperature=0.2,
            top_p=0.9,
            stop=["\n"],
            seed=5,
            response_format={"type": "text"},
            frequency_penalty=0.1,
            presence_penalty=0.2,
            parallel_tool_calls=False,
        )
        out = pr.upstream_payload(body, MODEL, 10, CONNECTION)
        for key in (
            "tools",
            "tool_choice",
            "temperature",
            "top_p",
            "stop",
            "seed",
            "response_format",
            "frequency_penalty",
            "presence_penalty",
            "parallel_tool_calls",
        ):
            assert out[key] == body[key]

    def test_input_body_is_not_mutated(self) -> None:
        body = _body(hub_thinking_level="high", max_tokens=7)
        snapshot = dict(body)
        pr.upstream_payload(body, MODEL, 100, CONNECTION)
        assert body == snapshot


class TestUpstreamPayloadThinking:
    def test_inherit_level_never_resolves_a_provider(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        resolver = MagicMock(name="model_provider")
        monkeypatch.setattr(pr, "model_provider", resolver)
        out = pr.upstream_payload(
            _body(hub_thinking_level="inherit"),
            MODEL,
            100,
            CONNECTION,
        )
        resolver.assert_not_called()
        assert out == {
            "model": "qwen-max",
            "messages": [],
            "max_tokens": 100,
        }

    def test_absent_level_defaults_to_inherit(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        resolver = MagicMock(name="model_provider")
        monkeypatch.setattr(pr, "model_provider", resolver)
        pr.upstream_payload(_body(), MODEL, 100, CONNECTION)
        resolver.assert_not_called()

    def test_unsupported_model_is_422(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            pr,
            "model_provider",
            lambda model, connection: _provider(supports=False),
        )
        with pytest.raises(HTTPException) as excinfo:
            pr.upstream_payload(
                _body(hub_thinking_level="high"),
                MODEL,
                100,
                CONNECTION,
            )
        assert excinfo.value.status_code == 422
        assert excinfo.value.detail == (
            "Model does not support thinking control"
        )

    def test_provider_is_asked_about_the_upstream_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        provider = _provider(controls={"reasoning_effort": "high"})
        monkeypatch.setattr(
            pr,
            "model_provider",
            lambda model, connection: provider,
        )
        pr.upstream_payload(
            _body(hub_thinking_level="high"),
            MODEL,
            7,
            CONNECTION,
        )
        provider.supports_agent_thinking.assert_called_once_with("qwen-max")
        provider.get_agent_thinking_kwargs.assert_called_once_with(
            "qwen-max",
            "high",
        )

    def test_thinking_enable_is_renamed_for_the_wire(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            pr,
            "model_provider",
            lambda model, connection: _provider(
                controls={"thinking_enable": True, "thinking_budget": 4096},
            ),
        )
        out = pr.upstream_payload(
            _body(hub_thinking_level="high"),
            MODEL,
            999999,
            CONNECTION,
        )
        assert out["enable_thinking"] is True
        assert "thinking_enable" not in out
        assert out["thinking_budget"] == 4096

    def test_thinking_budget_is_clamped_to_the_output_cap(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The budget may never exceed what the gateway already capped."""
        monkeypatch.setattr(
            pr,
            "model_provider",
            lambda model, connection: _provider(
                controls={"thinking_enable": True, "thinking_budget": 32768},
            ),
        )
        out = pr.upstream_payload(
            _body(hub_thinking_level="high"),
            MODEL,
            100,
            CONNECTION,
        )
        assert out["thinking_budget"] == 100

    def test_a_smaller_budget_is_left_alone(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            pr,
            "model_provider",
            lambda model, connection: _provider(
                controls={"thinking_budget": 16},
            ),
        )
        out = pr.upstream_payload(
            _body(hub_thinking_level="low"),
            MODEL,
            100,
            CONNECTION,
        )
        assert out["thinking_budget"] == 16

    def test_disable_thinking_writes_both_wire_shapes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            pr,
            "model_provider",
            lambda model, connection: _provider(
                controls={"disable_thinking": True},
            ),
        )
        out = pr.upstream_payload(
            _body(hub_thinking_level="off"),
            MODEL,
            100,
            CONNECTION,
        )
        assert out["enable_thinking"] is False
        assert out["thinking"] == {"type": "disabled"}
        assert "disable_thinking" not in out

    def test_extra_body_is_flattened_into_the_payload(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            pr,
            "model_provider",
            lambda model, connection: _provider(
                controls={
                    "extra_body": {"enable_search": True},
                    "reasoning_effort": "low",
                },
            ),
        )
        out = pr.upstream_payload(
            _body(hub_thinking_level="low"),
            MODEL,
            100,
            CONNECTION,
        )
        assert out["enable_search"] is True
        assert "extra_body" not in out
        assert out["reasoning_effort"] == "low"

    def test_unknown_control_keys_are_forwarded(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            pr,
            "model_provider",
            lambda model, connection: _provider(
                controls={"thinking_config": {"budget": 8}},
            ),
        )
        out = pr.upstream_payload(
            _body(hub_thinking_level="medium"),
            MODEL,
            100,
            CONNECTION,
        )
        assert out["thinking_config"] == {"budget": 8}

    def test_thinking_leg_runs_before_stream_options(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            pr,
            "model_provider",
            lambda model, connection: _provider(
                controls={"thinking_enable": True, "thinking_budget": 64},
            ),
        )
        out = pr.upstream_payload(
            _body(hub_thinking_level="high", stream=True),
            MODEL,
            100,
            CONNECTION,
        )
        assert out["stream_options"] == {"include_usage": True}
        assert out["enable_thinking"] is True
        assert out["thinking_budget"] == 64


# ---------------------------------------------------------------------------
# runtime_policy.require_model_route
# ---------------------------------------------------------------------------


class TestRequireModelRoute:
    @pytest.mark.parametrize(
        "path",
        [
            "/hub/model-runtime",
            "/hub/model-runtime/",
            "/hub/model-runtime/tokens",
            "hub/model-runtime/x",
        ],
    )
    def test_runtime_token_routes_are_not_found(self, path: str) -> None:
        """404 rather than 403: their existence is not disclosed."""
        with pytest.raises(HTTPException) as excinfo:
            rp.require_model_route(path)
        assert excinfo.value.status_code == 404
        assert excinfo.value.detail == "Not found"

    @pytest.mark.parametrize(
        "path",
        [
            "/models/hub-managed",
            "/models/hub-managed/m1",
            "/models/custom-providers/hub-managed",
            "/models/custom-providers/hub-managed/m1",
        ],
    )
    def test_managed_model_routes_are_forbidden(self, path: str) -> None:
        with pytest.raises(HTTPException) as excinfo:
            rp.require_model_route(path)
        assert excinfo.value.status_code == 403
        assert excinfo.value.detail == "Organization models are managed"

    @pytest.mark.parametrize(
        "path",
        [
            "/models/openai",
            "/models/custom-providers/openai",
            "/hub/users",
            "/hub/settings",
            "/hub/model-runtimeX",
            "/x/hub/model-runtime",
            "/models/hub-managed-x",
            "",
            "/",
        ],
    )
    def test_member_routes_pass(self, path: str) -> None:
        assert rp.require_model_route(path) is None
