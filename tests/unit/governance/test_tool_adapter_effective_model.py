# -*- coding: utf-8 -*-
"""The guarded tool wrapper publishes the turn's serving model."""

# pylint: disable=protected-access,redefined-outer-name

import inspect
from types import SimpleNamespace

import pytest

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.config.context import (
    get_current_effective_model,
    scoped_effective_model,
)
from qwenpaw.governance.tool_adapter import (
    PolicyGuardedTool,
    _policy_tool_call,
)

VISION_SLOT = ModelSlotConfig(provider_id="p", model="vision-pro")
PARENT_SLOT = ModelSlotConfig(provider_id="p", model="parent")


@pytest.fixture
def recording_call(monkeypatch):
    """Record the effective model visible to the wrapped tool."""
    seen: list[object] = []

    async def fake_call(_tool, *_args, **_kwargs):
        seen.append(get_current_effective_model())
        return "ok"

    from agentscope.tool import FunctionTool

    monkeypatch.setattr(FunctionTool, "__call__", fake_call)
    return seen


@pytest.mark.asyncio
async def test_policy_call_scopes_model_for_one_tool_call(recording_call):
    tool = SimpleNamespace(
        _qp_sandbox_mode=False,
        _qp_request_context={"effective_model": VISION_SLOT},
    )

    assert await _policy_tool_call(tool, "arg") == "ok"
    assert recording_call == [VISION_SLOT]
    assert get_current_effective_model() is None


@pytest.mark.asyncio
async def test_nested_scope_is_restored_after_the_call(recording_call):
    tool = SimpleNamespace(
        _qp_sandbox_mode=False,
        _qp_request_context={"effective_model": VISION_SLOT},
    )

    with scoped_effective_model(PARENT_SLOT):
        await _policy_tool_call(tool)
        assert get_current_effective_model() == PARENT_SLOT

    assert recording_call == [VISION_SLOT]


@pytest.mark.asyncio
async def test_missing_slot_keeps_the_outer_scope(recording_call):
    tool = SimpleNamespace(_qp_sandbox_mode=False, _qp_request_context={})

    with scoped_effective_model(PARENT_SLOT):
        await _policy_tool_call(tool)

    assert recording_call == [PARENT_SLOT]


@pytest.mark.asyncio
async def test_async_generator_tool_keeps_scope_during_iteration():
    """Streaming tools run their body after __call__ returns."""
    seen: list[object] = []

    async def streaming_tool():
        seen.append(get_current_effective_model())
        yield "first"
        seen.append(get_current_effective_model())
        yield "second"

    tool = PolicyGuardedTool(
        streaming_tool,
        governor=None,
        request_context={"effective_model": VISION_SLOT},
    )

    stream = await _policy_tool_call(tool)
    assert inspect.isasyncgen(stream)

    chunks = [chunk async for chunk in stream]

    assert len(chunks) == 2
    assert seen == [VISION_SLOT, VISION_SLOT]
    assert get_current_effective_model() is None
