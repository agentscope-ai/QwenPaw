# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Exercise ReMe proposals against host archives and atomic commits."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock, ToolCallBlock, ToolResultBlock

from qwenpaw.agents.context import jev
from qwenpaw.agents.context.jev import JEV_COMPACTED, JevCompactor
from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.manager import ScrollContextManager
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.config.config import AgentProfileConfig, JevCompactConfig


def make_agent():
    config = AgentProfileConfig(id="agent", name="Agent")
    config.running.light_context_config.jev_compact_config = JevCompactConfig(
        enabled=True,
        preserve_recent_messages=0,
        preview_chars=20,
    )
    context = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(text="Earlier task")],
        ),
    ]
    for index in range(3):
        context.append(
            Msg(
                name="assistant",
                role="assistant",
                content=[
                    ToolCallBlock(
                        id=f"c{index}",
                        name="read_file",
                        input='{"file_path":"a"}',
                        state="finished",
                    ),
                    ToolResultBlock(
                        id=f"c{index}",
                        name="read_file",
                        output="original evidence " * 300,
                        state="success",
                    ),
                ],
            ),
        )
    context.extend(
        [
            Msg(
                name="user",
                role="user",
                content=[TextBlock(text="Current task")],
            ),
            Msg(
                name="assistant",
                role="assistant",
                content=[
                    ToolCallBlock(
                        id="active",
                        name="read_file",
                        input="{}",
                        state="finished",
                    ),
                    ToolResultBlock(
                        id="active",
                        name="read_file",
                        output="active evidence " * 300,
                        state="success",
                    ),
                ],
            ),
        ],
    )
    agent = SimpleNamespace(
        _agent_config=config,
        _model_session_id="session",
        state=SimpleNamespace(context=context, summary=None),
        model=SimpleNamespace(context_size=100000),
        context_config=SimpleNamespace(trigger_ratio=0.8),
        offloader=SimpleNamespace(
            offload_tool_result=AsyncMock(return_value="/tmp/source.txt"),
        ),
    )

    async def prepare():
        return {
            "messages": [
                m.model_dump(mode="json") for m in agent.state.context
            ],
            "tools": [],
        }

    async def count(**kwargs):
        return len(json.dumps(kwargs))

    agent._prepare_model_input = prepare
    agent.model.count_tokens = count
    return agent


@pytest.fixture
def model(monkeypatch):
    async def decide(**kwargs):
        return SimpleNamespace(
            content={
                key: SimpleNamespace(type="binary_answer", probability=0.01)
                for key in kwargs["questions"]
            },
            usage=None,
        )

    model = AsyncMock(side_effect=decide)
    model.client = SimpleNamespace(aclose=AsyncMock())
    monkeypatch.setattr(
        jev,
        "create_decision_model_async",
        AsyncMock(return_value=model),
    )
    return model


async def compact(compactor, agent, *, target=100000, refs=None):
    kwargs = await agent._prepare_model_input()
    tokens = await agent.model.count_tokens(**kwargs)
    return await compactor.compact(
        agent,
        target=target,
        tokens=tokens,
        source_refs=refs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("scroll", [False, True])
async def test_real_reme_compacts_only_archived_completed_results(
    model,
    scroll,
):
    agent = make_agent()
    before = [m.model_dump(mode="json") for m in agent.state.context]
    refs = (
        {f"c{i}": f"recall_history(tool_call_id='c{i}')" for i in range(3)}
        if scroll
        else None
    )
    compactor = JevCompactor()
    assert await compact(compactor, agent, refs=refs)
    assert agent.state.context[-1].model_dump(mode="json") == before[-1]
    for msg in agent.state.context[1:4]:
        assert msg.content[1].metadata[JEV_COMPACTED]
        assert "Recover from:" in msg.content[1].output
        assert (
            msg.content[0].model_dump(mode="json")
            == before[agent.state.context.index(msg)]["content"][0]
        )
    assert agent.offloader.offload_tool_result.await_count == (
        0 if scroll else 3
    )
    # Repeated passes skip previously compacted results.
    calls = model.await_count
    assert not await compact(compactor, agent, refs=refs)
    assert model.await_count == calls
    await compactor.close()
    model.client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_partial_savings_continue_existing_pipeline(model):
    agent = make_agent()
    before = agent.state.context
    compactor = JevCompactor()
    assert not await compact(compactor, agent, target=1)
    assert agent.state.context is not before
    assert agent.state.context[1].content[1].metadata[JEV_COMPACTED]
    await compactor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    ["archive", "model", "count", "no_savings", "timeout", "cancel"],
)
async def test_failures_and_cancellation_preserve_original_context(
    model,
    failure,
):
    agent = make_agent()
    cfg = agent._agent_config.running.light_context_config.jev_compact_config
    before = agent.state.context
    snapshot = [m.model_dump(mode="json") for m in before]
    if failure == "archive":
        agent.offloader.offload_tool_result.side_effect = OSError("disk full")
    elif failure == "model":
        model.side_effect = RuntimeError("provider unavailable")
    elif failure == "count":
        agent.model.count_tokens = AsyncMock(
            side_effect=RuntimeError("count failed"),
        )
    elif failure == "no_savings":
        agent.model.count_tokens = AsyncMock(return_value=1000000)
    elif failure in {"timeout", "cancel"}:

        async def wait(**_kwargs):
            if failure == "cancel":
                raise asyncio.CancelledError()
            await asyncio.Event().wait()

        model.side_effect = wait
        cfg.total_timeout_seconds = 0.02
    compactor = JevCompactor()
    if failure == "cancel":
        cfg.total_timeout_seconds = 30
        started = asyncio.Event()

        async def wait_for_cancel(**_kwargs):
            started.set()
            await asyncio.Event().wait()

        model.side_effect = wait_for_cancel
        task = asyncio.create_task(
            compactor.compact(agent, target=10, tokens=100000),
        )
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        assert not await compactor.compact(agent, target=10, tokens=100000)
    assert agent.state.context is before
    assert [m.model_dump(mode="json") for m in before] == snapshot
    await compactor.close()


@pytest.mark.asyncio
async def test_default_disabled_does_not_create_component_or_model(model):
    agent = object.__new__(QwenPawAgent)
    agent._agent_config = AgentProfileConfig(id="agent", name="Agent")
    assert not await agent._try_jev_compact(target=10, tokens=100000)
    jev.create_decision_model_async.assert_not_awaited()
    assert not hasattr(agent, "_jev_compactor")


@pytest.mark.asyncio
async def test_scroll_durability_and_recovery_use_original_rows(
    model,
    tmp_path,
):
    agent = make_agent()
    history = HistoryStore(tmp_path / "history.db")
    manager = ScrollContextManager(
        history=history,
        session_id="session",
        agent_id="agent",
    )
    assert await manager._persist_guarded_async(agent)
    refs = {
        tcid: f"recall_history(op='recall_tool', tool_call_id={tcid!r})"
        for tcid in manager._seq_by_tcid
    }
    originals = history.contents_by_seqs(set(manager._seq_by_tcid.values()))
    compactor = JevCompactor()
    assert await compact(compactor, agent, refs=refs)
    assert await manager._persist_guarded_async(agent)
    assert (
        history.contents_by_seqs(set(manager._seq_by_tcid.values()))
        == originals
    )
    assert manager._is_folded_stub(agent.state.context[1].content[1])
    restored = manager._durable_folded_result_contents(
        agent.state.context[1:4],
    )
    for msg in agent.state.context[1:4]:
        seq = manager._seq_by_tcid[msg.content[1].id]
        assert restored[(msg.id, 0)] == originals[seq]
    await compactor.close()
    history.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    ["user_text", "call_id", "reference", "stale"],
)
async def test_invalid_or_stale_proposals_never_commit(
    model,
    monkeypatch,
    mutation,
):
    from reme.steps.compaction.compact_context import CompactContextStep

    agent = make_agent()
    before = agent.state.context
    execute = CompactContextStep.execute

    async def tamper(step):
        response = await execute(step)
        if mutation == "user_text":
            response.answer["messages"][0]["content"][0]["text"] = "changed"
        elif mutation == "call_id":
            response.answer["messages"][1]["content"][0]["id"] = "changed"
        elif mutation == "reference":
            response.answer["decisions"][0]["source_ref"] = "wrong source"
        else:
            agent.state.context.append(
                Msg(
                    name="user",
                    role="user",
                    content=[TextBlock(text="new input")],
                ),
            )
        return response

    monkeypatch.setattr(CompactContextStep, "execute", tamper)
    compactor = JevCompactor()
    assert not await compact(compactor, agent)
    assert agent.state.context is before
    if mutation == "stale":
        assert agent.state.context[-1].content[0].text == "new input"
    await compactor.close()


@pytest.mark.asyncio
async def test_cancellation_during_host_count_rolls_back(model):
    agent = make_agent()
    before = agent.state.context
    agent.model.count_tokens = AsyncMock(side_effect=asyncio.CancelledError())
    compactor = JevCompactor()
    with pytest.raises(asyncio.CancelledError):
        await compactor.compact(agent, target=1, tokens=100000)
    assert agent.state.context is before
    await compactor.close()


@pytest.mark.asyncio
async def test_scroll_dispatch_runs_jev_before_existing_folding(
    model,
    tmp_path,
):
    from types import MethodType

    agent = make_agent()
    agent.model.context_size = 12000
    agent.context_config.reserve_ratio = 0.1
    agent._try_jev_compact = MethodType(QwenPawAgent._try_jev_compact, agent)
    history = HistoryStore(tmp_path / "history.db")
    manager = ScrollContextManager(
        history=history,
        session_id="session",
        agent_id="agent",
    )
    manager._batch_fold_completed_tool_results = AsyncMock(
        side_effect=AssertionError("JEV should relieve pressure first"),
    )
    await manager.compress(agent)
    assert agent.state.context[1].content[1].metadata[JEV_COMPACTED]
    manager._batch_fold_completed_tool_results.assert_not_awaited()
    agent.offloader.offload_tool_result.assert_not_awaited()
    await agent._jev_compactor.close()
    history.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("forced", [False, True])
async def test_native_dispatch_preserves_manual_compact(
    model,
    monkeypatch,
    forced,
):
    from agentscope.agent import Agent

    fake = make_agent()
    agent = object.__new__(QwenPawAgent)
    agent.__dict__.update(vars(fake))
    agent._context_manager = None
    agent._get_active_formatter = lambda: None
    agent.model.context_size = 12000
    fallback = AsyncMock()
    monkeypatch.setattr(Agent, "_compress_context_impl", fallback)
    cfg = SimpleNamespace(trigger_ratio=0.000001 if forced else 0.8)
    await agent._compress_context_impl(cfg)
    assert fallback.await_count == (1 if forced else 0)
    if forced:
        jev.create_decision_model_async.assert_not_awaited()
    else:
        assert agent.state.context[1].content[1].metadata[JEV_COMPACTED]
        await agent._jev_compactor.close()


@pytest.mark.asyncio
async def test_synthetic_continuation_does_not_expose_active_turn(model):
    from qwenpaw.constant import (
        LOOP_CONTINUATION_MESSAGE_TAG,
        QWENPAW_MESSAGE_TAG_KEY,
    )

    agent = make_agent()
    active = agent.state.context[-1].model_dump(mode="json")
    agent.state.context.append(
        Msg(
            name="user",
            role="user",
            content=[TextBlock(text="Continue")],
            metadata={QWENPAW_MESSAGE_TAG_KEY: LOOP_CONTINUATION_MESSAGE_TAG},
        ),
    )
    compactor = JevCompactor()
    assert await compact(compactor, agent)
    assert agent.state.context[-2].model_dump(mode="json") == active
    await compactor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("scroll", [False, True])
async def test_memory_middleware_detects_jev_without_message_eviction(
    model,
    scroll,
):
    from qwenpaw.agents.middlewares import MemoryMiddleware

    agent = make_agent()
    if scroll:
        agent._context_manager = SimpleNamespace(
            last_compress={"evicted": 0, "folded": 0},
        )
    before = MemoryMiddleware._compression_state(agent)
    compactor = JevCompactor()
    assert await compact(compactor, agent)
    assert before[1] == tuple(msg.id for msg in agent.state.context)
    assert MemoryMiddleware._did_compress_context(agent, before)
    assert not MemoryMiddleware._did_compress_context(
        agent,
        MemoryMiddleware._compression_state(agent),
    )
    await compactor.close()
