# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name,unused-argument
"""Exercise ReMe proposals against host archives and atomic commits."""

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock, ToolCallBlock, ToolResultBlock

from qwenpaw.agents.context import decision_compaction
from qwenpaw.agents.context.decision_compaction import DecisionCompactor
from qwenpaw.agents.context.types import (
    DECISION_COMPACTED,
    DecisionCompactionResult,
)
from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.manager import ScrollContextManager
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.agents.offloader import QwenPawOffloader
from qwenpaw.config.config import AgentProfileConfig, DecisionCompactConfig


def _tool_message(
    call_id,
    evidence="original evidence ",
    tool_input='{"file_path":"a"}',
):
    return Msg(
        name="assistant",
        role="assistant",
        content=[
            ToolCallBlock(
                id=call_id,
                name="read_file",
                input=tool_input,
                state="finished",
            ),
            ToolResultBlock(
                id=call_id,
                name="read_file",
                output=evidence * 300,
                state="success",
            ),
        ],
    )


def make_agent():
    config = AgentProfileConfig(id="agent", name="Agent")
    config.running.light_context_config.decision_compact_config = (
        DecisionCompactConfig(
            enabled=True,
            preserve_recent_messages=0,
            preview_chars=20,
        )
    )
    context = [
        Msg(
            name="user",
            role="user",
            content=[TextBlock(text="Earlier task")],
        ),
        *(_tool_message(f"c{index}") for index in range(3)),
        Msg(
            name="user",
            role="user",
            content=[TextBlock(text="Current task")],
        ),
        _tool_message("active", "active evidence ", tool_input="{}"),
    ]
    agent = object.__new__(QwenPawAgent)
    agent.__dict__.update(
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
        decision_compaction,
        "create_decision_model_async",
        AsyncMock(return_value=model),
    )
    return model


async def compact(compactor, agent, *, refs=None):
    kwargs = await agent._prepare_model_input()
    tokens = await agent.model.count_tokens(**kwargs)
    return await compactor.compact(
        agent,
        tokens=tokens,
        source_refs=refs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["drain", "client"])
async def test_close_finishes_after_repeated_cancellation(model, phase):
    """Drain and close the borrowed client before shutdown finishes."""
    compactor = DecisionCompactor()
    component = await compactor._decision_component(make_agent())
    entered, release = asyncio.Event(), asyncio.Event()

    async def wait(**_kwargs):
        entered.set()
        await release.wait()

    request = None
    if phase == "drain":
        model.side_effect = wait
        request = asyncio.create_task(
            component(
                state="test",
                questions={"q": {"type": "binary", "instructions": "test"}},
            ),
        )
        await entered.wait()
    else:
        model.client.aclose.side_effect = wait
    closing = asyncio.create_task(compactor.close())
    if phase == "client":
        await entered.wait()
    for _ in range(2):
        await asyncio.sleep(0)
        closing.cancel()
        await asyncio.sleep(0)
        assert not closing.done()
    release.set()
    if request is not None:
        await request
    with pytest.raises(asyncio.CancelledError):
        await closing
    model.client.aclose.assert_awaited_once()
    assert compactor._model is compactor._component is None


@pytest.mark.asyncio
async def test_failed_client_close_can_be_retried(model):
    compactor = DecisionCompactor()
    await compactor._decision_component(make_agent())
    model.client.aclose.side_effect = [RuntimeError("close failed"), None]
    with pytest.raises(RuntimeError, match="close failed"):
        await compactor.close()
    assert compactor._model is model
    await compactor.close()
    assert model.client.aclose.await_count == 2
    assert compactor._model is compactor._component is None


@pytest.mark.asyncio
@pytest.mark.parametrize("scroll", [False, True])
async def test_real_reme_compacts_only_archived_completed_results(
    model,
    scroll,
):
    agent = make_agent()
    original = agent.state.context
    before = [m.model_dump(mode="json") for m in agent.state.context]
    refs = (
        {f"c{i}": f"recall_history(tool_call_id='c{i}')" for i in range(3)}
        if scroll
        else None
    )
    compactor = DecisionCompactor()
    result = await compact(compactor, agent, refs=refs)
    assert result.changed
    assert agent.state.context is not original
    assert agent._decision_compaction_revision == 1
    assert result.tokens_after == await agent.model.count_tokens(
        **await agent._prepare_model_input(),
    )
    assert agent.state.context[-1].model_dump(mode="json") == before[-1]
    for msg in agent.state.context[1:4]:
        assert msg.content[1].metadata[DECISION_COMPACTED]
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
    repeated = await compact(compactor, agent, refs=refs)
    assert not repeated.changed
    assert repeated.tokens_after == result.tokens_after
    assert model.await_count == calls
    await compactor.close()
    model.client.aclose.assert_awaited_once()


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
    context_config = agent._agent_config.running.light_context_config
    cfg = context_config.decision_compact_config
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
    elif failure == "timeout":

        async def wait(**_kwargs):
            await asyncio.Event().wait()

        model.side_effect = wait
        cfg.total_timeout_seconds = 0.02
    compactor = DecisionCompactor()
    if failure == "cancel":
        cfg.total_timeout_seconds = 30
        started = asyncio.Event()

        async def wait_for_cancel(**_kwargs):
            started.set()
            await asyncio.Event().wait()

        model.side_effect = wait_for_cancel
        task = asyncio.create_task(
            compactor.compact(agent, tokens=100000),
        )
        await asyncio.wait_for(started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await compactor.compact(agent, tokens=100000)
        assert result == DecisionCompactionResult(
            changed=False,
            tokens_after=100000,
        )
    assert agent.state.context is before
    assert [m.model_dump(mode="json") for m in before] == snapshot
    await compactor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    ["keep", "model_error"],
)
async def test_native_retries_reuse_archives(model, tmp_path, outcome):
    agent = make_agent()
    original = agent.state.context
    agent.offloader = QwenPawOffloader(
        str(tmp_path / "dialog"),
        str(tmp_path / "results"),
    )
    if outcome == "keep":

        async def keep(**kwargs):
            return SimpleNamespace(
                content={
                    key: SimpleNamespace(
                        type="binary_answer",
                        probability=0.99,
                    )
                    for key in kwargs["questions"]
                },
                usage=None,
            )

        model.side_effect = keep
    else:
        model.side_effect = RuntimeError("provider unavailable")

    for _ in range(2):
        compactor = DecisionCompactor()
        try:
            assert not (await compact(compactor, agent)).changed
            assert agent.state.context is original
            assert len(list((tmp_path / "results").glob("*.txt"))) == 3
        finally:
            await compactor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("automatic", "decision"),
    [(False, False), (False, True), (True, False)],
)
async def test_disabled_compaction_does_not_create_component_or_model(
    model,
    automatic,
    decision,
):
    agent = object.__new__(QwenPawAgent)
    agent._agent_config = AgentProfileConfig(id="agent", name="Agent")
    config = agent._agent_config.running.light_context_config
    config.context_compact_config.enabled = automatic
    config.decision_compact_config.enabled = decision
    result = await agent.try_decision_compact(tokens=100000)
    assert result == DecisionCompactionResult(
        changed=False,
        tokens_after=100000,
    )
    decision_compaction.create_decision_model_async.assert_not_awaited()
    assert not hasattr(agent, "_decision_compactor")


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
    compactor = DecisionCompactor()
    assert (await compact(compactor, agent, refs=refs)).changed
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
    from reme.steps.compaction import CompactContextStep

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
    compactor = DecisionCompactor()
    assert not (await compact(compactor, agent)).changed
    assert agent.state.context is before
    if mutation == "stale":
        assert agent.state.context[-1].content[0].text == "new input"
    await compactor.close()


@pytest.mark.asyncio
async def test_cancellation_during_host_count_rolls_back(model):
    agent = make_agent()
    before = agent.state.context
    agent.model.count_tokens = AsyncMock(side_effect=asyncio.CancelledError())
    compactor = DecisionCompactor()
    with pytest.raises(asyncio.CancelledError):
        await compactor.compact(agent, tokens=100000)
    assert agent.state.context is before
    await compactor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("fits_budget", [False, True])
async def test_scroll_compacts_before_existing_folding(
    model,
    tmp_path,
    monkeypatch,
    fits_budget,
):
    agent = make_agent()
    agent.model.context_size = 12000 if fits_budget else 100
    agent.context_config.reserve_ratio = 0.1
    count = agent.model.count_tokens
    agent.model.count_tokens = AsyncMock(wraps=count)
    history = HistoryStore(tmp_path / "history.db")
    manager = ScrollContextManager(
        history=history,
        session_id="session",
        agent_id="agent",
    )
    assert await manager._persist_guarded_async(agent)
    folded = agent.state.context[3].content[1]
    folded.metadata[DECISION_COMPACTED] = True
    folded.output = "previous preview"
    manager._seq_by_tcid["evicted"] = 999999
    read_contents = history.contents_by_seqs
    loop_thread = threading.get_ident()

    def checked_read(seqs):
        assert threading.get_ident() != loop_thread
        assert 999999 not in seqs
        assert manager._seq_by_tcid[folded.id] not in seqs
        return read_contents(seqs)

    monkeypatch.setattr(history, "contents_by_seqs", checked_read)
    manager._batch_fold_completed_tool_results = AsyncMock(
        side_effect=(
            AssertionError(
                "Decision model should relieve pressure first",
            )
            if fits_budget
            else RuntimeError("Continue existing folding")
        ),
    )
    manager._live_tokens = AsyncMock(
        side_effect=AssertionError("Committed previews are already counted"),
    )
    if fits_budget:
        await manager.compress(agent)
        manager._batch_fold_completed_tool_results.assert_not_awaited()
    else:
        with pytest.raises(RuntimeError, match="Continue existing folding"):
            await manager.compress(agent)
        assert manager._batch_fold_completed_tool_results.await_args.kwargs[
            "tokens"
        ] == await count(**agent.model.count_tokens.await_args.kwargs)
    assert agent.state.context[1].content[1].metadata[DECISION_COMPACTED]
    assert agent.model.count_tokens.await_count == 2
    agent.offloader.offload_tool_result.assert_not_awaited()
    await agent._decision_compactor.close()
    history.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("forced", "context_size"),
    [(False, 12000), (False, 100), (True, 12000)],
)
async def test_native_dispatch_preserves_manual_compact(
    model,
    monkeypatch,
    forced,
    context_size,
):
    from agentscope.agent import Agent

    fake = make_agent()
    agent = object.__new__(QwenPawAgent)
    agent.__dict__.update(vars(fake))
    agent._context_manager = None
    agent._get_active_formatter = lambda: None
    agent.model.context_size = context_size
    fallback = AsyncMock()
    monkeypatch.setattr(Agent, "_compress_context_impl", fallback)
    cfg = SimpleNamespace(trigger_ratio=0.000001 if forced else 0.8)
    await agent._compress_context_impl(cfg)
    assert fallback.await_count == (1 if forced or context_size == 100 else 0)
    if forced:
        decision_compaction.create_decision_model_async.assert_not_awaited()
    else:
        assert agent.state.context[1].content[1].metadata[DECISION_COMPACTED]
        await agent._decision_compactor.close()


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
    compactor = DecisionCompactor()
    assert (await compact(compactor, agent)).changed
    assert agent.state.context[-2].model_dump(mode="json") == active
    await compactor.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("scroll", [False, True])
async def test_memory_middleware_detects_compaction_without_eviction(
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
    compactor = DecisionCompactor()
    assert (await compact(compactor, agent)).changed
    assert before[1] == tuple(msg.id for msg in agent.state.context)
    assert MemoryMiddleware._did_compress_context(agent, before)
    assert not MemoryMiddleware._did_compress_context(
        agent,
        MemoryMiddleware._compression_state(agent),
    )
    await compactor.close()
