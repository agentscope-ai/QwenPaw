# -*- coding: utf-8 -*-
"""Focused reliability tests for the embedded Auto-Dream workflow."""
# pylint: disable=protected-access

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from reme.components.runtime_context import RuntimeContext
from reme.schema import DreamState, Response
from reme.steps.evolve.dream.finish import DreamFinishStep

from qwenpaw.agents.memory.reme_dream import (
    QwenPawDreamFinishStep,
    QwenPawDreamIntegrateStep,
    classify_dream_status,
)
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


def _state(unit_name: str = "unit") -> SimpleNamespace:
    return SimpleNamespace(
        hint="",
        units=[
            {
                "name": unit_name,
                "bucket": "wiki",
                "summary": "summary",
                "paths": ["daily/2026-08-09.md"],
            },
        ],
        integrate_results=[],
        nodes_created=[],
        nodes_updated=[],
        failed_units=[],
        failed_paths=[],
        errors=[],
    )


def _valid_result() -> dict:
    return {
        "result": '{"action":"CREATE","target_path":"digest/wiki/unit.md"}',
    }


class _ReplyWrapper:
    def __init__(self, replies, on_call=None):
        self.replies = iter(replies)
        self.calls = []
        self.on_call = on_call

    async def reply(self, message, **kwargs):
        self.calls.append((message, kwargs))
        if self.on_call:
            self.on_call(len(self.calls))
        return next(self.replies)


@pytest.mark.asyncio
async def test_invalid_schema_retries_once_and_recovers(tmp_path):
    state = _state()
    wrapper = _ReplyWrapper([{"result": "{}"}, _valid_result()])
    step = QwenPawDreamIntegrateStep(name="integrate")
    step.agent_wrapper = wrapper

    await step._integrate_one(
        state,
        state.units[0],
        1,
        tmp_path,
        "digest",
    )

    assert len(wrapper.calls) == 2
    assert wrapper.calls[1][1]["job_tools"] == [
        "node_search",
        "read",
        "frontmatter_read",
        "write",
        "edit",
        "frontmatter_update",
    ]
    assert len(state.integrate_results) == 1
    assert state.failed_units == []


@pytest.mark.asyncio
async def test_retry_is_read_only_when_first_attempt_wrote_a_file(tmp_path):
    state = _state()

    def write_on_first_call(call_number):
        if call_number == 1:
            target = tmp_path / "digest" / "wiki" / "unit.md"
            target.parent.mkdir(parents=True)
            target.write_text("already written", encoding="utf-8")

    wrapper = _ReplyWrapper(
        [{"result": "{}"}, _valid_result()],
        write_on_first_call,
    )
    step = QwenPawDreamIntegrateStep(name="integrate")
    step.agent_wrapper = wrapper

    await step._integrate_one(state, state.units[0], 1, tmp_path, "digest")

    assert len(wrapper.calls) == 2
    assert wrapper.calls[1][1]["job_tools"] == [
        "node_search",
        "read",
        "frontmatter_read",
    ]
    assert (tmp_path / "digest" / "wiki" / "unit.md").read_text(
        encoding="utf-8",
    ) == "already written"
    assert len(state.integrate_results) == 1


@pytest.mark.asyncio
async def test_invalid_schema_is_failed_after_one_retry(tmp_path):
    state = _state()
    wrapper = _ReplyWrapper([{"result": "{}"}, {"result": "[]"}])
    step = QwenPawDreamIntegrateStep(name="integrate")
    step.agent_wrapper = wrapper

    await step._integrate_one(state, state.units[0], 1, tmp_path, "digest")

    assert len(wrapper.calls) == 2
    assert state.integrate_results == []
    assert len(state.failed_units) == 1
    assert state.failed_paths == ["daily/2026-08-09.md"]


@pytest.mark.asyncio
async def test_successful_unit_is_idempotent(tmp_path):
    state = _state()
    state.integrate_results.append(
        {
            "unit": "unit",
            "bucket": "wiki",
            "paths": ["daily/2026-08-09.md"],
            "action": "CREATE",
            "target_path": "digest/wiki/unit.md",
        },
    )
    wrapper = _ReplyWrapper([_valid_result()])
    step = QwenPawDreamIntegrateStep(name="integrate")
    step.agent_wrapper = wrapper

    await step._integrate_one(state, state.units[0], 1, tmp_path, "digest")

    assert not wrapper.calls
    assert len(state.integrate_results) == 1


def test_dream_status_distinguishes_partial_and_full_failure():
    partial = _state()
    partial.integrate_results.append({"unit": "ok"})
    partial.failed_units.append({"name": "failed"})
    assert classify_dream_status(partial) == "partial"

    failed = _state()
    failed.failed_units.append({"name": "failed"})
    assert classify_dream_status(failed) == "error"


@pytest.mark.asyncio
async def test_finish_step_persists_partial_status(monkeypatch):
    state = DreamState(
        integrate_results=[{"unit": "ok"}],
        failed_units=[{"name": "failed"}],
    )
    context = RuntimeContext(dream=state.model_dump())

    async def fake_parent_execute(self):
        self.context.response.answer = "AutoDream completed"
        self.context.response.success = False
        return self.context.response

    monkeypatch.setattr(DreamFinishStep, "execute", fake_parent_execute)
    step = QwenPawDreamFinishStep(name="finish")
    step.context = context

    await step.execute()

    assert context.response.metadata["dream_status"] == "partial"
    assert context.response.success is False
    assert context.response.answer.startswith("Status: partial")


@pytest.mark.asyncio
async def test_inbox_and_dream_treat_partial_as_warning(monkeypatch):
    manager = object.__new__(ReMeLightMemoryManager)
    manager.agent_id = "agent-1"
    manager.get_memory_config = lambda: SimpleNamespace(
        inbox_push_enabled=True,
        auto_dream_inbox_push_enabled=True,
    )
    event = {"id": "event-1", "status": "partial"}
    append = AsyncMock(return_value=event)
    monkeypatch.setattr(
        "qwenpaw.agents.memory.reme_light_memory_manager.append_inbox_event",
        append,
    )
    response = Response(
        answer="Status: partial",
        success=False,
        metadata={"dream_status": "partial"},
    )

    assert await manager._append_reme_job_result_to_inbox(
        "auto_dream",
        response=response,
        kwargs={},
    )
    assert append.await_args.kwargs["status"] == "partial"
    assert append.await_args.kwargs["severity"] == "warning"

    manager._run_reme_job = AsyncMock(return_value=response)
    await manager.dream()
    manager._run_reme_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_dream_raises_for_full_failure():
    manager = object.__new__(ReMeLightMemoryManager)
    response = Response(
        answer="Status: error",
        success=False,
        metadata={"dream_status": "error"},
    )
    manager._run_reme_job = AsyncMock(return_value=response)

    with pytest.raises(RuntimeError, match="Status: error"):
        await manager.dream()
