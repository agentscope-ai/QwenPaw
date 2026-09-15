import json

import pytest

from qwenpaw.runtime.input_context import ChatInputContext


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
        "other-query", "Other task's question", target="future-0", context_only=True
    )
    value = json.loads(context.capture(("correction",)))
    assert [(r["source_id"], r["kind"]) for r in value["inputs"]] == [
        ("s1", "related_input"),
        ("s2", "active_input"),
        ("s3", "user_update"),
    ]
    assert "future job" not in str(value)
    assert "Do not run again" not in context.capture(("future-0",))
    assert context.capture(("unknown",)) == ""


def test_capture_cutoff_and_replays_cannot_replace_words():
    context = setup_context()
    context.register("s3", "Do not run again", target="task-a", context_only=True)
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
    assert context.capture(("new",)) == ""


def test_long_update_is_complete_and_bind_is_immutable():
    context = setup_context()
    text = "Background. " * 600 + "Do not rerun."
    context.register("long", text, target="task-a", context_only=True)
    assert json.loads(context.capture(("correction",)))["inputs"][-1]["text"] == text
    with pytest.raises(ValueError):
        context.bind("correction", "s1")
    assert (
        json.loads(context.capture(("correction",)))["inputs"][1]["source_id"] == "s2"
    )


def test_repeated_words_have_independent_identities_and_unknown_target_is_not_global():
    context = setup_context()
    for identity in ("s3", "s4"):
        context.register(identity, "Do not rerun", target="task-a", context_only=True)
    context.register(
        "unknown", "Unresolved constraint", target="unresolved:task", context_only=True
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
    assert context.capture(("new",)) == ""
