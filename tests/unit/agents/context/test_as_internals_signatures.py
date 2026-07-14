# -*- coding: utf-8 -*-
"""Signature smoke test for the AgentScope 2.0 private internals the scroll
manager depends on.

AgentScope 2.0 is alpha. The scroll context manager calls two underscore
methods on the agent via :mod:`qwenpaw.agents.context.scroll._as_internals`.
If a future AgentScope release renames them or changes their parameters, these
tests fail loudly here — instead of the manager silently breaking inside
``compress()`` at runtime. When they fail, update ``_as_internals`` (and these
assertions) together.
"""
import inspect

from agentscope.agent import Agent

from qwenpaw.agents.context.scroll import _as_internals


def test_prepare_model_input_still_exists_and_is_async():
    method = getattr(Agent, "_prepare_model_input", None)
    assert (
        method is not None
    ), "AgentScope Agent lost `_prepare_model_input`; update _as_internals."
    assert inspect.iscoroutinefunction(method)
    # The adapter calls it with no arguments beyond self.
    assert list(inspect.signature(method).parameters) == ["self"]


def test_split_context_for_compression_signature_unchanged():
    method = getattr(Agent, "_split_context_for_compression", None)
    assert method is not None, (
        "AgentScope Agent lost `_split_context_for_compression`; "
        "update _as_internals."
    )
    assert inspect.iscoroutinefunction(method)
    # The adapter calls it positionally as (reserve_tokens, tools).
    assert list(inspect.signature(method).parameters) == [
        "self",
        "to_reserved_tokens",
        "tools",
    ]


async def test_adapter_forwards_to_the_wrapped_methods():
    """The adapter is a pure pass-through to the agent's private methods."""
    seen: dict = {}

    class FakeAgent:
        async def _prepare_model_input(self):
            seen["prepare"] = True
            return {"tools": ["t"]}

        async def _split_context_for_compression(self, reserve, tools):
            seen["split"] = (reserve, tools)
            return (["compress"], ["reserve"])

    agent = FakeAgent()
    assert await _as_internals.prepare_model_input(agent) == {"tools": ["t"]}
    assert await _as_internals.split_for_compression(
        agent,
        0.1,
        ["t"],
    ) == (["compress"], ["reserve"])
    assert seen == {"prepare": True, "split": (0.1, ["t"])}


async def test_split_for_compression_keeps_tool_messages_with_assistant():
    class FakeAgent:
        async def _split_context_for_compression(self, reserve, tools):
            _ = (reserve, tools)
            # Simulate a split that cuts right after the assistant message,
            # leaving the tool responses in the reserved list.

            class Msg:
                def __init__(self, role, content):
                    self.role = role
                    self.content = content

            to_compress = [
                Msg("user", "hi"),
                Msg("assistant", "call tool"),
            ]
            to_reserve = [
                Msg("tool", "result A"),
                Msg("tool", "result B"),
                Msg("assistant", "final answer"),
            ]
            return (to_compress, to_reserve)

    agent = FakeAgent()
    to_compress, to_reserve = await _as_internals.split_for_compression(
        agent,
        0.1,
        ["t"],
    )

    # Move assistant message to start of reserve list to pair with tool
    assert len(to_compress) == 1
    assert to_compress[0].role == "user"

    assert len(to_reserve) == 4
    assert to_reserve[0].role == "assistant"
    assert to_reserve[1].role == "tool"
    assert to_reserve[2].role == "tool"
    assert to_reserve[3].role == "assistant"
