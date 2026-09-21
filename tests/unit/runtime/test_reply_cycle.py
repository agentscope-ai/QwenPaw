"""Contracts for the run-local reply-cycle identity model."""

import pytest

from qwenpaw.runtime.reply_cycle import ReplyCycleContext


def test_consumed_batch_activates_one_revision_with_last_input_as_group():
    context = ReplyCycleContext("run-1", "input-a")

    snapshot = context.activate(["input-b", "input-c"])

    assert snapshot.run_id == "run-1"
    assert snapshot.group_id == "input-c"
    assert snapshot.revision == 2
    assert snapshot.responds_to_input_ids == ("input-b", "input-c")
    assert snapshot.metadata() == {
        "run_id": "run-1",
        "timeline_group_id": "input-c",
        "timeline_revision": 2,
        "responds_to_input_ids": ["input-b", "input-c"],
    }


def test_steer_extends_active_task_reply_ownership():
    context = ReplyCycleContext("run-1", "task")
    context.start_inputs(("task",))

    snapshot = context.extend_for_steer(("correction", "status-query"))

    assert snapshot.group_id == "status-query"
    assert snapshot.responds_to_input_ids == (
        "task",
        "correction",
        "status-query",
    )
    context.finish_reply("completed")
    assert context.terminated_input_ids("completed") == (
        "task",
        "correction",
        "status-query",
    )


@pytest.mark.asyncio
async def test_visible_occurrences_get_independent_authoritative_orders():
    orders = iter((4, 7))

    async def reserve_order():
        return next(orders)

    context = ReplyCycleContext("run-1", "input-a", reserve_order)

    first = await context.start_occurrence()
    second = await context.start_occurrence()

    assert first.group_id == second.group_id == "input-a"
    assert first.metadata()["timeline_order"] == 4
    assert second.metadata()["timeline_order"] == 7
    assert "timeline_order" not in context.snapshot.metadata()


@pytest.mark.asyncio
async def test_new_reply_cycle_requires_a_new_visible_occurrence():
    async def reserve_order():
        return 9

    context = ReplyCycleContext("run-1", "input-a", reserve_order)
    await context.start_occurrence()

    snapshot = context.activate(["input-b", "input-c"])

    assert snapshot.group_id == "input-c"
    assert context.output_snapshot is snapshot
    occurrence = await context.ensure_occurrence()
    assert occurrence.metadata()["timeline_order"] == 9


@pytest.mark.asyncio
async def test_tool_call_owner_does_not_move_with_later_revision():
    async def reserve_order():
        return 11

    context = ReplyCycleContext("run-1", "input-a", reserve_order)
    await context.start_occurrence()
    owner = context.bind_call("call-a")

    context.activate(["input-b"])

    assert context.owner_of_call("call-a") is owner
    assert owner.group_id == "input-a"
    assert owner.metadata()["timeline_order"] == 11
    assert context.snapshot.group_id == "input-b"


@pytest.mark.parametrize("run_id,input_id", [("", "a"), ("r", "")])
def test_identity_rejects_empty_values(run_id, input_id):
    with pytest.raises(ValueError):
        ReplyCycleContext(run_id, input_id)


def test_input_lifecycle_preserves_steered_work_and_settles_once():
    events = []
    context = ReplyCycleContext("run", "first", on_input_state=events.append)
    context.start_inputs(("first",))
    context.accept_input("correction")
    context.activate(("correction",))
    assert not any(event.status == "completed" for event in events)
    context.finish_reply("completed")
    assert events[-1].input_ids == ("first", "correction")
    assert events[-1].status == "completed"
    context.accept_input("next")
    context.activate(("next",))
    context.finish_run("cancelled")
    assert events[-1].input_ids == ("next",)
    count = len(events)
    context.finish_run("cancelled")
    assert len(events) == count


def test_waiting_reply_is_not_completed_by_run_eof():
    events = []
    context = ReplyCycleContext("run", "first", on_input_state=events.append)
    context.start_inputs(("first",))
    context.finish_reply("waiting")
    context.finish_run("completed")
    assert events[-1].status == "waiting"


def test_waiting_input_ownership_round_trips_to_new_run():
    events = []
    first = ReplyCycleContext("first", "original")
    first.start_inputs(("original",))
    first.finish_reply("waiting")
    second = ReplyCycleContext(
        "second", "approval", on_input_state=events.append
    )
    second.start_inputs(("approval",))
    second.resume_inputs(first.waiting_inputs())
    assert events[-1].resumed_from == "first"
    assert events[-1].input_ids == ("original",)
    second.finish_reply("completed")
    assert set(events[-1].input_ids) == {"approval", "original"}
    assert not second.waiting_inputs()
