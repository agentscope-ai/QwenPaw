# -*- coding: utf-8 -*-
"""Tests for the Gemini native-provider thought_signature relay.

Gemini thinking models (3.x, and 2.5 with thinking) return a
``thought_signature`` on every ``functionCall`` part and require it to be
echoed back on the same part in subsequent requests.  AgentScope stashes
the signature into the tool-call block id but never relays it, so QwenPaw
adds a capture/persist/relay pipeline for the native Gemini provider,
mirroring the existing OpenAI-compatible path.
"""
# pylint: disable=redefined-outer-name,unused-argument,protected-access
from __future__ import annotations

import asyncio
import base64
import copy
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from agentscope.message import Msg

import qwenpaw.providers.gemini_provider as gemini_provider_module
from qwenpaw.providers.capping_formatter import _CappingGeminiFormatter
from qwenpaw.providers.gemini_provider import GeminiProvider
from qwenpaw.utils.tool_call_extra import (
    collect_transient_tool_call_extras,
    persist_tool_call_extras,
    tool_call_extras_for_provider,
)

PROVIDER_ID = "gemini"


def _make_provider(**overrides) -> GeminiProvider:
    config = {
        "id": "gemini",
        "name": "Gemini",
        "base_url": "https://generativelanguage.googleapis.com",
        "api_key": "gem-test",
        "chat_model": "GeminiChatModel",
    }
    config.update(overrides)
    return GeminiProvider(**config)


def _make_model(monkeypatch) -> SimpleNamespace:
    """Build a compat model instance with a stubbed genai client."""
    fake_client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace()))

    def create_client(**kwargs):  # pylint: disable=unused-variable
        return fake_client

    monkeypatch.setattr(gemini_provider_module.genai, "Client", create_client)
    return _make_provider().get_chat_model_instance("gemini-2.5-flash")


def _fc_part(name: str, sig: bytes | None, fc_id: str | None = None):
    return SimpleNamespace(
        text=None,
        thought=False,
        function_call=SimpleNamespace(
            id=fc_id,
            name=name,
            args={"city": "SF"},
        ),
        thought_signature=sig,
    )


def _text_part(text: str, thought: bool = False):
    return SimpleNamespace(
        text=text,
        thought=thought,
        function_call=None,
        thought_signature=None,
    )


def _chunk(parts) -> SimpleNamespace:
    return SimpleNamespace(
        response_id=None,
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))],
        usage_metadata=None,
    )


async def _astream(*chunks):
    for chunk in chunks:
        yield chunk


def _assistant_msg(tool_blocks: list) -> Msg:
    return Msg(
        name="assistant",
        role="assistant",
        content=tool_blocks,
        metadata={},
    )


def _user_msg(text: str) -> Msg:
    return Msg(
        name="user",
        role="user",
        content=[{"type": "text", "text": text}],
        metadata={},
    )


def _block_get(block, key, default=None):
    """Attribute access that works for both dict and Pydantic blocks."""
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def test_stream_captures_and_attaches_thought_signature(
    monkeypatch,
) -> None:
    model = _make_model(monkeypatch)
    start = datetime.now()
    stream = _astream(_chunk([_fc_part("get_weather", b"sig-one")]))

    async def run():
        blocks = []
        async for delta in model._parse_stream_response(start, stream):
            blocks.extend(delta.content)
        return blocks

    blocks = asyncio.run(run())

    assert len(blocks) == 1
    record = collect_transient_tool_call_extras(blocks)
    assert list(record) == [base64.b64encode(b"sig-one").decode("ascii")]
    sig_id = base64.b64encode(b"sig-one").decode("ascii")
    assert record[sig_id]["provider_id"] == PROVIDER_ID
    assert record[sig_id]["extra_content"] == {
        "thought_signature": sig_id,
    }


def test_stream_alignment_with_mixed_signatures(monkeypatch) -> None:
    """One part with a signature, one without: only the right block
    receives the transient extra, and both blocks keep the right ids."""
    model = _make_model(monkeypatch)
    start = datetime.now()
    stream = _astream(
        _chunk(
            [
                _fc_part("alpha", b"sig-a"),
                _fc_part("beta", None, fc_id="functions.beta:0"),
            ],
        ),
    )

    async def run():
        blocks = []
        async for delta in model._parse_stream_response(start, stream):
            blocks.extend(delta.content)
        return blocks

    blocks = asyncio.run(run())

    assert len(blocks) == 2
    record = collect_transient_tool_call_extras(blocks)
    assert len(record) == 1
    assert base64.b64encode(b"sig-a").decode("ascii") in record
    # The non-signature block must NOT have been annotated.
    assert _block_get(blocks[1], "id") == "functions.beta:0"


def test_stream_without_signature_leaves_blocks_untouched(monkeypatch):
    model = _make_model(monkeypatch)
    start = datetime.now()
    stream = _astream(_chunk([_text_part("hello")]))

    async def run():
        blocks = []
        async for delta in model._parse_stream_response(start, stream):
            blocks.extend(delta.content)
        return blocks

    blocks = asyncio.run(run())

    assert len(blocks) == 1
    assert collect_transient_tool_call_extras(blocks) == {}


def test_completion_captures_thought_signature(monkeypatch) -> None:
    model = _make_model(monkeypatch)
    start = datetime.now()
    response = SimpleNamespace(
        response_id=None,
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[
                        _text_part("thinking", thought=True),
                        _fc_part("get_weather", b"sig-done"),
                    ],
                ),
            ),
        ],
        usage_metadata=None,
    )

    result = model._parse_completion_response(start, response)
    blocks = [
        b
        for b in result.content
        if _block_get(b, "type") == "tool_call"
    ]
    assert len(blocks) == 1
    record = collect_transient_tool_call_extras(blocks)
    assert record == {
        base64.b64encode(b"sig-done").decode("ascii"): {
            "provider_id": PROVIDER_ID,
            "extra_content": {
                "thought_signature": base64.b64encode(
                    b"sig-done",
                ).decode("ascii"),
            },
        },
    }


def test_persist_and_replay_roundtrip(monkeypatch) -> None:
    """attach -> collect -> persist to Msg.metadata -> formatter relay."""
    model = _make_model(monkeypatch)
    start = datetime.now()
    stream = _astream(_chunk([_fc_part("get_weather", b"sig-rt")]))

    async def run():
        blocks = []
        async for delta in model._parse_stream_response(start, stream):
            blocks.extend(delta.content)
        return blocks

    blocks = asyncio.run(run())

    extras = collect_transient_tool_call_extras(blocks)
    msg = _assistant_msg(copy.deepcopy([b for b in blocks]))
    persist_tool_call_extras(msg, extras)

    provider = tool_call_extras_for_provider(msg, PROVIDER_ID)
    assert provider, "extras must survive persistence under provider id"

    fmt = _CappingGeminiFormatter(
        thought_signature_provider_id=PROVIDER_ID,
    )
    wire = asyncio.run(
        fmt.format(
            [
                _user_msg("weather?"),
                msg,
                _user_msg("go"),
            ],
        ),
    )

    model_turns = [m for m in wire if m.get("role") == "model"]
    assert len(model_turns) == 1
    part = model_turns[0]["parts"][0]
    expected = base64.b64encode(b"sig-rt").decode("ascii")
    assert part["thought_signature"] == expected
    assert part["function_call"]["id"] == expected


def test_relay_fifo_for_repeated_tool_ids() -> None:
    """Two assistant messages reusing one tool id must replay their
    signatures in message order."""

    def _sig_msg(sig: bytes):
        tid = base64.b64encode(sig).decode("ascii")
        block = {
            "type": "tool_call",
            "id": tid,
            "name": "get_weather",
            "input": '{"city": "SF"}',
        }
        msg = _assistant_msg([copy.deepcopy(block)])
        persist_tool_call_extras(
            msg,
            {
                tid: {
                    "provider_id": PROVIDER_ID,
                    "extra_content": {"thought_signature": tid},
                },
            },
        )
        return msg, tid

    msg1, tid1 = _sig_msg(b"first-sig")
    msg2, tid2 = _sig_msg(b"second-sig")

    fmt = _CappingGeminiFormatter(
        thought_signature_provider_id=PROVIDER_ID,
    )
    wire = asyncio.run(
        fmt.format(
            [
                _user_msg("q"),
                msg1,
                msg2,
            ],
        ),
    )
    model_turns = [m for m in wire if m.get("role") == "model"]
    assert len(model_turns) == 2
    assert model_turns[0]["parts"][0]["thought_signature"] == tid1
    assert model_turns[1]["parts"][0]["thought_signature"] == tid2


def test_relay_is_noop_without_provider_id() -> None:
    tid = base64.b64encode(b"sig-x").decode("ascii")
    msg = _assistant_msg(
        [
            {
                "type": "tool_call",
                "id": tid,
                "name": "get_weather",
                "input": "{}",
            },
        ],
    )
    persist_tool_call_extras(
        msg,
        {
            tid: {
                "provider_id": PROVIDER_ID,
                "extra_content": {"thought_signature": tid},
            },
        },
    )
    fmt = _CappingGeminiFormatter()  # provider id unset
    wire = asyncio.run(fmt.format([msg]))
    model_turns = [m for m in wire if m.get("role") == "model"]
    assert len(model_turns) == 1
    assert "thought_signature" not in model_turns[0]["parts"][0]


def test_relay_ignores_other_provider_extras() -> None:
    tid = base64.b64encode(b"sig-y").decode("ascii")
    msg = _assistant_msg(
        [
            {
                "type": "tool_call",
                "id": tid,
                "name": "get_weather",
                "input": "{}",
            },
        ],
    )
    persist_tool_call_extras(
        msg,
        {
            tid: {
                "provider_id": "openai",
                "extra_content": {"thought_signature": tid},
            },
        },
    )
    fmt = _CappingGeminiFormatter(
        thought_signature_provider_id=PROVIDER_ID,
    )
    wire = asyncio.run(fmt.format([msg]))
    model_turns = [m for m in wire if m.get("role") == "model"]
    assert len(model_turns) == 1
    assert "thought_signature" not in model_turns[0]["parts"][0]


def test_relayed_signature_reaches_wire_json(monkeypatch) -> None:
    """End-to-end: the SDK must serialize the relayed signature as
    ``thoughtSignature`` (base64) on the functionCall part."""
    from google.genai import _api_client

    tid = base64.b64encode(b"wire-sig").decode("ascii")
    msg = _assistant_msg(
        [
            {
                "type": "tool_call",
                "id": tid,
                "name": "get_weather",
                "input": '{"city": "SF"}',
            },
        ],
    )
    persist_tool_call_extras(
        msg,
        {
            tid: {
                "provider_id": PROVIDER_ID,
                "extra_content": {"thought_signature": tid},
            },
        },
    )
    fmt = _CappingGeminiFormatter(
        thought_signature_provider_id=PROVIDER_ID,
    )
    wire = asyncio.run(
        fmt.format(
            [
                _user_msg("weather?"),
                msg,
                _user_msg("go"),
            ],
        ),
    )

    captured: dict = {}

    async def fake_async_request(
        self,
        http_request,
        http_options=None,
        stream=False,
    ):
        captured["body"] = http_request.data
        raise RuntimeError("STOP_BEFORE_NETWORK")

    monkeypatch.setattr(
        _api_client.BaseApiClient,
        "_async_request",
        fake_async_request,
    )
    from google import genai

    client = genai.Client(api_key="dummy-key")

    async def call():
        try:
            await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=wire,
            )
        except RuntimeError as exc:
            assert "STOP_BEFORE_NETWORK" in str(exc)

    asyncio.run(call())
    body = captured["body"]
    if isinstance(body, bytes):
        body = json.loads(body)
    elif isinstance(body, str):
        body = json.loads(body)
    model_turns = [m for m in body["contents"] if m.get("role") == "model"]
    assert len(model_turns) == 1
    part = model_turns[0]["parts"][0]
    assert part["thoughtSignature"] == tid
    assert part["functionCall"]["id"] == tid

