# -*- coding: utf-8 -*-
"""Hub protocol conversion preserves request bounds and billing usage."""

import pytest

from qwenpaw.providers.adapters.wire_protocol import WireProtocol
from qwenpaw.hub.model_service.api_models import ModelBody


@pytest.mark.parametrize(f"protocol", [f"responses", f"anthropic"])
def test_native_tool_round_trip_and_output_cap(protocol):
    wire = WireProtocol(protocol)
    request = wire.request(
        {
            f"model": f"test",
            f"max_tokens": 32,
            f"stream": False,
            f"messages": [
                {f"role": f"system", f"content": f"stable"},
                {
                    f"role": f"assistant",
                    f"content": None,
                    f"tool_calls": [
                        {
                            f"id": f"call-1",
                            f"type": f"function",
                            f"function": {
                                f"name": f"read",
                                f"arguments": f"{{}}",
                            },
                        },
                    ],
                },
                {
                    f"role": f"tool",
                    f"tool_call_id": f"call-1",
                    f"content": f"ok",
                },
            ],
            f"tools": [
                {
                    f"type": f"function",
                    f"function": {
                        f"name": f"read",
                        f"parameters": {f"type": f"object"},
                    },
                },
            ],
        },
    )
    if protocol == f"responses":
        assert request[f"max_output_tokens"] == 32
        assert request[f"input"][1][f"call_id"] == f"call-1"
        assert request[f"input"][2][f"output"] == f"ok"
    else:
        assert request[f"max_tokens"] == 32
        assert request[f"messages"][0][f"content"][0][f"id"] == f"call-1"
        assert (
            request[f"messages"][1][f"content"][0][f"tool_use_id"] == f"call-1"
        )


def test_anthropic_stream_usage_includes_cache_once():
    wire = WireProtocol(f"anthropic")
    assert (
        wire.event(
            {
                f"type": f"message_start",
                f"message": {
                    f"usage": {
                        f"input_tokens": 10,
                        f"cache_read_input_tokens": 80,
                        f"cache_creation_input_tokens": 20,
                    },
                },
            },
        )
        is None
    )
    event = wire.event(
        {
            f"type": f"message_delta",
            f"delta": {f"stop_reason": f"end_turn"},
            f"usage": {f"output_tokens": 7},
        },
    )
    assert event[f"usage"][f"total_tokens"] == 117
    assert not wire.done
    wire.event({f"type": f"message_stop"})
    assert wire.done


def test_responses_tool_stream_preserves_call_id_and_index():
    wire = WireProtocol(f"responses")
    event = wire.event(
        {
            f"type": f"response.output_item.added",
            f"output_index": 3,
            f"item": {
                f"type": f"function_call",
                f"id": f"item-1",
                f"call_id": f"call-1",
                f"name": f"read",
            },
        },
    )
    call = event[f"choices"][0][f"delta"][f"tool_calls"][0]
    assert call[f"id"] == f"call-1"
    assert call[f"index"] == 0
    event = wire.event(
        {
            f"type": f"response.function_call_arguments.delta",
            f"output_index": 3,
            f"delta": f"{{}}",
        },
    )
    assert event[f"choices"][0][f"delta"][f"tool_calls"][0][f"function"] == {
        f"arguments": f"{{}}",
    }


def test_cache_settings_cannot_override_hub_reservation():
    with pytest.raises(ValueError, match=f"Unsupported cache"):
        ModelBody(
            connection_id=f"c",
            upstream_model=f"m",
            name=f"m",
            input_token_limit=1000,
            cache_settings={f"max_tokens": 1_000_000},
        )


def test_unknown_native_parameter_fails_instead_of_being_dropped():
    with pytest.raises(ValueError, match=f"Unsupported"):
        WireProtocol(f"anthropic").request(
            {
                f"model": f"m",
                f"messages": [],
                f"max_tokens": 32,
                f"arbitrary_connection_override": f"bad",
            },
        )
