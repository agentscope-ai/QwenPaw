# -*- coding: utf-8 -*-
# pylint: disable=redefined-outer-name,protected-access,unused-argument
"""A4-PR1: pre-send window budget guard (design §3 案A) + empty-reply
fallback (design §3 案C-1).

Case A: ``compress()`` must not let an input through silently when it fits
the raw window yet leaves no room for the declared output cap (incident:
196,602-token prompt → provider truncation → 200 OK + completion_tokens=0).
Case C-1: a zero-meaningful-block reply must retry once through context
recovery, then surface a visible bilingual warning instead of an empty
message.

Design §5 test cases 1, 2, 3, 4, 5, 6, 9, 11. All provider traffic is
faked — no network, no real LLM.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from agentscope.agent import Agent
from agentscope.event import TextBlockStartEvent
from agentscope.message import (
    AssistantMsg,
    Msg,
    TextBlock,
    ThinkingBlock,
    ToolCallBlock,
)
from agentscope.model import ChatModelBase

from qwenpaw.agents.context.scroll.history import HistoryStore
from qwenpaw.agents.context.scroll.manager import ScrollContextManager
from qwenpaw.agents.context.types import ContextWindowUnfitError
from qwenpaw.agents.react_agent import QwenPawAgent
from qwenpaw.constant import (
    LOOP_CONTINUATION_MESSAGE_TAG,
    QWENPAW_MESSAGE_TAG_KEY,
)
from qwenpaw.loop.gates import StopAction

# -- fakes: scroll manager ---------------------------------------------------
#
# Window math for the default fakes: context_size=1000 →
# output_reserve=min(4096, int(1000*0.05))=50 → effective_hard_limit=950,
# trigger=0.8*1000=800, reserve=0.1*1000=100.


class _FakeModel:
    """Constant token count; the chat call must never happen in these tests."""

    def __init__(
        self,
        tokens: int,
        context_size: int = 1000,
        max_tokens: int | None = None,
    ) -> None:
        self._tokens = tokens
        self.context_size = context_size
        self.parameters = SimpleNamespace(max_tokens=max_tokens)
        self.count_calls = 0
        self.chat_calls = 0

    async def count_tokens(self, *args: Any, **kwargs: Any) -> int:
        self.count_calls += 1
        return self._tokens

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.chat_calls += 1
        raise AssertionError("provider called with an oversized prompt")


class _FakeConfig:
    trigger_ratio = 0.8
    reserve_ratio = 0.1


class _FakeState:
    def __init__(self, context: list[Msg]) -> None:
        self.context = context


class _FakeAgent:
    """Minimal stand-in exposing the AS-2.0 surface the manager touches."""

    def __init__(self, context: list[Msg], model: _FakeModel) -> None:
        self.state = _FakeState(context)
        self.model = model
        self.context_config = _FakeConfig
        self.omitted_thinking_ids: set[str] = set()

    async def _prepare_model_input(self) -> dict:
        return {"tools": []}

    async def _split_context_for_compression(
        self,
        reserve: float,
        tools: Any,
    ) -> tuple:
        return (self.state.context[:-1], self.state.context[-1:])

    def _set_formatter_thinking_omit_ids(self, block_ids: set[str]) -> bool:
        self.omitted_thinking_ids = set(block_ids)
        return True


def _user_msg(text: str = "big request") -> Msg:
    return Msg(
        name="user",
        role="user",
        content=[TextBlock(type="text", text=text)],
    )


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    h = HistoryStore(tmp_path / "history.db")
    yield h
    h.close()


def _make_manager(store: HistoryStore) -> ScrollContextManager:
    return ScrollContextManager(history=store, session_id="s1", agent_id="ag1")


# -- 案A: pre-send window budget (design §5 cases 1-6, 9) --------------------


@pytest.mark.asyncio
async def test_precheck_rejects_oversized_input_without_provider_call(
    store: HistoryStore,
) -> None:
    """案A-1: input over the hard budget is refused before any provider call."""
    mgr = _make_manager(store)
    model = _FakeModel(990)
    agent = _FakeAgent([_user_msg()], model)

    with pytest.raises(ContextWindowUnfitError) as excinfo:
        await mgr.compress(agent)

    assert excinfo.value.tokens == 990
    assert excinfo.value.hard_limit == 950
    assert "CONTEXT_UNFIT" in str(excinfo.value)
    assert model.chat_calls == 0


@pytest.mark.asyncio
async def test_precheck_passes_under_budget(store: HistoryStore) -> None:
    """案A-2: under budget, the pipeline behaves as before (no new raise)."""
    mgr = _make_manager(store)
    model = _FakeModel(900)
    agent = _FakeAgent([_user_msg()], model)

    await mgr.compress(agent)

    assert model.chat_calls == 0


@pytest.mark.asyncio
async def test_precheck_uses_requested_max_tokens_in_budget(
    store: HistoryStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """案A-3: a declared output cap tightens the budget and forces the path."""
    mgr = _make_manager(store)
    model = _FakeModel(850, max_tokens=200)  # budget = 1000 - 200 = 800
    agent = _FakeAgent([_user_msg()], model)
    pre_fold = AsyncMock(return_value=(0, 850))
    monkeypatch.setattr(mgr, "_batch_fold_completed_tool_results", pre_fold)

    with pytest.raises(ContextWindowUnfitError) as excinfo:
        await mgr.compress(agent)

    assert excinfo.value.tokens == 850
    assert excinfo.value.hard_limit == 800
    pre_fold.assert_not_awaited()  # forced path skips the lighter pre-fold
    assert model.chat_calls == 0


@pytest.mark.asyncio
async def test_below_trigger_no_declared_cap_passes_through(
    store: HistoryStore,
) -> None:
    """案A-4 (pins current behavior): no declared cap below trigger →
    silent pass-through, the residual 案B gap (count_tokens undercounts),
    which PR1 documents but does not close."""
    mgr = _make_manager(store)
    model = _FakeModel(750)
    agent = _FakeAgent([_user_msg()], model)

    await mgr.compress(agent)

    assert model.chat_calls == 0
    assert agent.state.context[0].get_text_content() == "big request"


@pytest.mark.asyncio
async def test_below_trigger_over_hard_budget_forces_and_rejects(
    store: HistoryStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """案A-5 (the fix): below trigger but over the capped budget → forced
    compaction, and a visible CONTEXT_UNFIT raise when it cannot fit."""
    mgr = _make_manager(store)
    model = _FakeModel(750, max_tokens=300)  # budget = 1000 - 300 = 700
    agent = _FakeAgent([_user_msg()], model)
    pre_fold = AsyncMock(return_value=(0, 750))
    monkeypatch.setattr(mgr, "_batch_fold_completed_tool_results", pre_fold)

    with pytest.raises(ContextWindowUnfitError) as excinfo:
        await mgr.compress(agent)

    assert excinfo.value.tokens == 750
    assert excinfo.value.hard_limit == 700
    pre_fold.assert_not_awaited()
    assert model.chat_calls == 0


@pytest.mark.asyncio
async def test_output_reserve_config_defaults_unchanged(
    store: HistoryStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """案A-6: the configured reserve defaults (5%, capped at 4096) and the
    persist-failure raise are untouched by the new gate."""
    mgr = _make_manager(store)
    model = _FakeModel(193_000, context_size=196_608)
    agent = _FakeAgent([_user_msg()], model)
    monkeypatch.setattr(
        mgr,
        "_persist_guarded_async",
        AsyncMock(return_value=False),
    )

    with pytest.raises(ContextWindowUnfitError) as excinfo:
        await mgr.compress(agent)

    expected_reserve = min(4096, max(1, int(196_608 * 0.05)))
    assert excinfo.value.tokens == 193_000
    assert excinfo.value.hard_limit == 196_608 - expected_reserve == 192_512


def test_unfit_error_message_carries_numbers_for_visible_channel() -> None:
    """案A-9: the error text carries both numbers, which the console channel's
    top-level ``except Exception → print_error(str(e))`` prints into the room
    (no src/ catch point swallows it)."""
    message = str(ContextWindowUnfitError(tokens=990, hard_limit=950))
    assert "CONTEXT_UNFIT" in message
    assert "990" in message
    assert "950" in message


# -- 案C-1: empty-reply fallback (design §5 case 11) -------------------------


class _AgentModel(ChatModelBase):
    def __init__(self) -> None:
        super().__init__(
            credential=None,
            model="test-model",
            parameters=ChatModelBase.Parameters(),
            stream=False,
            context_size=32_768,
        )


def _bare_agent(
    context: list[Msg],
    context_manager: Any = None,
) -> QwenPawAgent:
    """Build a minimal agent without running heavy __init__."""
    agent = object.__new__(QwenPawAgent)
    agent.name = "QwenPaw"
    agent.model = _AgentModel()
    agent.state = SimpleNamespace(context=list(context), cur_iter=0)
    agent._context_manager = context_manager
    agent._empty_reply_retried = False

    async def _noop() -> None:
        return None

    async def _stop_result(_final_msg: Any) -> Any:
        return SimpleNamespace(
            action=StopAction.BYPASS,
            final_message=None,
            reason="",
            continuation_message=None,
            continuation_metadata=None,
        )

    agent._inject_pending_hints = _noop
    agent._model_rejects_media = lambda: False
    agent._run_stop_handlers = _stop_result
    return agent


@pytest.mark.asyncio
async def test_empty_reply_retries_once_then_surfaces_visible_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """案C-1: empty reply → one context-recovery retry → visible bilingual
    warning on the second empty reply."""
    user = _user_msg()
    recover = AsyncMock(return_value=True)
    agent = _bare_agent(
        [user],
        SimpleNamespace(recover_from_context_overflow=recover),
    )

    async def fake_base_reasoning(self, tool_choice=None):
        del tool_choice
        yield TextBlockStartEvent(reply_id="r1", block_id="b1")
        yield AssistantMsg("agent", content=[TextBlock(type="text", text="")])

    monkeypatch.setattr(Agent, "_reasoning", fake_base_reasoning)
    monkeypatch.setattr(
        "qwenpaw.loop.gates.runner.check_pending_gates",
        lambda _agent: None,
    )

    # Pass 1: retry silently through context recovery; no Msg leaves.
    first = [evt async for evt in agent._reasoning()]
    assert not [evt for evt in first if isinstance(evt, Msg)]
    assert recover.await_count == 1
    retry = agent.state.context[-1]
    assert retry.role == "user"
    assert retry.get_text_content() == "Response was empty; retrying."
    assert (
        retry.metadata[QWENPAW_MESSAGE_TAG_KEY]
        == LOOP_CONTINUATION_MESSAGE_TAG
    )
    assert agent._empty_reply_retried is True

    # Pass 2: second empty reply → flag reset, visible bilingual warning.
    second = [evt async for evt in agent._reasoning()]
    messages = [evt for evt in second if isinstance(evt, Msg)]
    assert len(messages) == 1
    assert messages[0].role == "assistant"
    text = messages[0].get_text_content()
    assert "empty response" in text.lower()
    assert "空响应" in text
    assert recover.await_count == 1  # exactly one retry, total
    assert agent._empty_reply_retried is False
    assert len(agent.state.context) == 2  # no extra message appended


@pytest.mark.asyncio
async def test_empty_reply_gate_allows_tool_call_and_thinking_replies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """案C-1: tool-call-only and thinking-only replies are meaningful and
    pass through untouched (the pending retry flag is reset, not honored)."""
    user = _user_msg()
    agent = _bare_agent([user])
    agent._empty_reply_retried = True

    async def tool_call_reasoning(self, tool_choice=None):
        del tool_choice
        yield TextBlockStartEvent(reply_id="r1", block_id="b1")
        yield AssistantMsg(
            "agent",
            content=[
                ToolCallBlock(
                    type="tool_call",
                    id="c1",
                    name="grep",
                    input="{}",
                ),
            ],
        )

    monkeypatch.setattr(Agent, "_reasoning", tool_call_reasoning)
    monkeypatch.setattr(
        "qwenpaw.loop.gates.runner.check_pending_gates",
        lambda _agent: None,
    )

    outputs = [evt async for evt in agent._reasoning()]
    messages = [evt for evt in outputs if isinstance(evt, Msg)]
    assert len(messages) == 1
    assert [block.type for block in messages[0].content] == ["tool_call"]
    assert len(agent.state.context) == 1  # no continuation appended
    assert agent._empty_reply_retried is False

    # Thinking-only reply: also meaningful.
    agent2 = _bare_agent([user])
    agent2._empty_reply_retried = True

    async def thinking_reasoning(self, tool_choice=None):
        del tool_choice
        yield TextBlockStartEvent(reply_id="r2", block_id="b2")
        yield AssistantMsg(
            "agent",
            content=[ThinkingBlock(thinking="hmm")],
        )

    monkeypatch.setattr(Agent, "_reasoning", thinking_reasoning)
    outputs2 = [evt async for evt in agent2._reasoning()]
    messages2 = [evt for evt in outputs2 if isinstance(evt, Msg)]
    assert len(messages2) == 1
    assert [block.type for block in messages2[0].content] == ["thinking"]
    assert agent2._empty_reply_retried is False
