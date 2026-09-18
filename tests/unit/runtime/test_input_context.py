import json

import pytest

from qwenpaw.runtime.input_context import ChatInputContext
from qwenpaw.runtime.reply_cycle import InputStateEvent


def setup_context():
    context = ChatInputContext()
    context.register("s1", "Run task two and print 3002")
    context.bind("task-a", "s1")
    context.register("s2", "Correction: 302", target="task-a")
    context.bind("correction", "s2")
    return context


def test_updates_are_ordered_scoped_and_do_not_release_other_work():
    context = setup_context()
    for i in range(10):
        context.register_execution(f"future-{i}", f"Run future job {i}")
    context.register(
        "s3",
        "Do not run again; report actual output",
        target="task-a",
        context_only=True,
    )
    context.register(
        "other-query",
        "Other task's question",
        target="future-0",
        context_only=True,
    )
    value = json.loads(context.capture(("correction",)))
    assert [(r["source_id"], r["kind"]) for r in value["inputs"]] == [
        ("s1", "related_input"),
        ("s2", "active_input"),
        ("s3", "user_update"),
    ]
    assert "future job" not in str(value["inputs"])
    assert len(value["readonly_requests"]) == 10
    assert value["active_input_ids"] == ["correction"]
    assert "Do not run again" not in context.capture(("future-0",))
    assert context.capture(("unknown",)) == ""


def test_capture_cutoff_and_replays_cannot_replace_words():
    context = setup_context()
    context.register(
        "s3", "Do not run again", target="task-a", context_only=True
    )
    first = context.capture(("correction",))
    context.register("s3", "MUTATED REPLAY", context_only=True)
    assert context.capture(("correction",)) == first
    context.register(
        "s4", "New words after capture", target="task-a", context_only=True
    )
    assert "New words" not in first
    second = json.loads(context.capture(("correction",)))
    assert second["through_order"] == 4
    assert second["inputs"][-1]["text"] == "New words after capture"


def test_context_only_never_becomes_an_execution_input():
    context = ChatInputContext()
    context.register("query", "What happened?", context_only=True)
    assert context.capture(()) == ""
    # A later unrelated task does not inherit an old untargeted query.
    context.register_execution("new", "New work")
    assert "What happened?" not in context.capture(("new",))


def test_long_update_is_complete_and_bind_is_immutable():
    context = setup_context()
    text = "Background. " * 600 + "Do not rerun."
    context.register("long", text, target="task-a", context_only=True)
    assert (
        json.loads(context.capture(("correction",)))["inputs"][-1]["text"]
        == text
    )
    with pytest.raises(ValueError):
        context.bind("correction", "s1")
    assert (
        json.loads(context.capture(("correction",)))["inputs"][1]["source_id"]
        == "s2"
    )


def test_repeated_words_have_independent_ids_and_unknown_target_is_local():
    context = setup_context()
    for identity in ("s3", "s4"):
        context.register(
            identity, "Do not rerun", target="task-a", context_only=True
        )
    context.register(
        "unknown",
        "Unresolved constraint",
        target="unresolved:task",
        context_only=True,
    )
    rows = json.loads(context.capture(("correction",)))["inputs"]
    assert [r["source_id"] for r in rows] == ["s1", "s2", "s3", "s4"]


def test_constraint_is_not_lost_when_router_calls_it_a_followup():
    context = setup_context()
    context.register("s3", "Do not rerun", target="task-a")
    value = json.loads(context.capture(("correction",)))
    assert value["inputs"][-1] == {
        "source_id": "s3",
        "order": 3,
        "kind": "related_input",
        "text": "Do not rerun",
    }


def test_global_updates_apply_only_to_tasks_already_present():
    context = setup_context()
    context.register("s3", "Do not rerun anything", context_only=True)
    context.register_execution("new", "New unrelated work")
    assert "Do not rerun anything" in context.capture(("task-a",))
    assert "Do not rerun anything" in context.capture(("correction",))
    value = json.loads(context.capture(("new",)))
    assert [row["source_id"] for row in value["inputs"]] == ["new"]
    assert "Do not rerun anything" not in str(value)


def test_source_binding_late_events_and_retry_keep_original_words():
    context = ChatInputContext()
    context.register_execution("apple", "Run apple")
    context.register("spoken-banana", "Run banana")
    context.set_admission("spoken-banana", "preparing")
    prepared = json.loads(context.capture(("apple",)))["readonly_requests"][0]
    assert prepared["admission_status"] == "preparing"
    assert prepared["input_status"] is None
    context.observe_state(InputStateEvent("run-1", ("attempt-1",), "queued"))
    assert (
        json.loads(context.capture(("apple",)))["coverage"][
            "unbound_execution_inputs"
        ]
        == 1
    )
    context.bind("attempt-1", "spoken-banana")
    context.set_admission("attempt-1", "admitted")
    context.observe_state(InputStateEvent("run-1", ("attempt-1",), "failed"))
    context.set_admission("spoken-banana", "preparing")
    context.bind("attempt-2", "spoken-banana")
    retry = json.loads(context.capture(("apple",)))["readonly_requests"][0]
    assert retry["source_id"] == "spoken-banana"
    assert retry["request_excerpt"] == "Run banana"
    assert retry["previous_attempts"] == 1
    assert retry["execution_input_id"] == "attempt-2"
    assert retry["admission_status"] == "preparing"
    assert retry["input_status"] is None
    context.set_admission("attempt-2", "rejected")
    context.observe_state(
        InputStateEvent("run-1", ("attempt-1",), "completed")
    )
    rejected = json.loads(context.capture(("apple",)))["readonly_requests"][0]
    assert rejected["admission_status"] == "rejected"
    assert rejected["input_status"] is None
    assert context.state("attempt-1").status == "failed"


def test_projection_is_run_fenced_and_terminal_states_do_not_reopen():
    context = ChatInputContext()
    context.observe_state(InputStateEvent("run-1", ("input",), "waiting"))
    context.observe_state(InputStateEvent("run-2", ("input",), "processing"))
    assert context.state("input").run_id == "run-1"
    context.observe_state(
        InputStateEvent("run-2", ("input",), "processing", "run-1")
    )
    context.observe_state(InputStateEvent("run-1", ("input",), "completed"))
    context.observe_state(InputStateEvent("run-2", ("input",), "queued"))
    assert context.state("input").status == "processing"
    context.observe_state(InputStateEvent("run-2", ("input",), "cancelled"))
    context.observe_state(
        InputStateEvent("run-3", ("input",), "processing", "run-2")
    )
    assert context.state("input").status == "cancelled"
    assert context.state("input").run_id == "run-2"


def test_overview_is_bounded_prioritizes_live_work_and_preserves_constraints():
    context = ChatInputContext()
    context.register_execution("apple", "Run apple")
    context.register_execution("banana", "Run banana" + "x" * 500)
    context.observe_state(InputStateEvent("run", ("banana",), "queued"))
    for index in range(1000):
        identity = f"old-{index}"
        context.register_execution(identity, "old " * 500)
        context.observe_state(InputStateEvent("old", (identity,), "completed"))
    for index in range(40):
        context.register(f"received-{index}", "Unrouted input")
    constraint = "Background. " * 2000 + "Do not rerun any task."
    context.register("query", constraint, context_only=True)
    raw = context.capture(("apple",))
    view = json.loads(raw)
    assert len(view["readonly_requests"]) == 32
    banana = next(
        r for r in view["readonly_requests"] if r["source_id"] == "banana"
    )
    assert banana["input_status"] == "queued"
    assert banana["excerpt_truncated"] is True
    assert len(banana["request_excerpt"]) == 160
    assert view["inputs"][-1]["text"] == constraint
    assert view["active_input_ids"] == ["apple"]
    assert view["coverage"]["omitted_other_requests"] == 1009
    assert view["coverage"]["other_status_counts"] == {
        "completed": 1000,
        "received": 40,
        "queued": 1,
    }
    assert context.capture(("apple",)) == raw  # Capture is read-only.


def test_closed_view_ignores_late_writes_and_never_leaks_to_another_chat():
    context = setup_context()
    context.close()
    context.register_execution("late", "Late words")
    context.observe_state(InputStateEvent("late-run", ("late",), "processing"))
    context.set_admission("late", "admitted")
    assert context.capture(("late",)) == ""
    assert context.state("late") is None
    assert ChatInputContext().capture(("task-a",)) == ""
