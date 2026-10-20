import json

import pytest
from agentscope.message import Msg, TextBlock, ToolCallBlock, ToolResultBlock

from qwenpaw.runtime.reply_cycle import set_reply_block_metadata
from qwenpaw.runtime.tool_execution_context import (
    project_tool_execution_context,
)


def recorded_step(
    input_id="input-a", call_id="write-a", state="success", run_id="run-a"
):
    call = ToolCallBlock(
        id=call_id,
        name="write_file",
        input=json.dumps({"file_path": "验证.txt", "content": "完成"}),
        state="finished",
    )
    result = ToolResultBlock(
        id=call_id, name="write_file", output="File written", state=state
    )
    message = Msg(name="assistant", role="assistant", content=[call, result])
    set_reply_block_metadata(
        message, call, {"run_id": run_id, "responds_to_input_ids": [input_id]}
    )
    return message


@pytest.mark.parametrize(
    "state,succeeded",
    [
        ("success", True),
        ("error", False),
        ("denied", False),
        ("interrupted", False),
        ("running", None),
    ],
)
def test_result_state_wins_over_finished_call_and_success_sounding_text(
    state, succeeded
):
    message = recorded_step(state=state)
    receipt = project_tool_execution_context([message], ("input-a",))[
        "observed_tool_steps"
    ][0]
    assert receipt["execution_status"] == state
    assert receipt["succeeded"] is succeeded
    assert receipt["arguments"]["content"] == "完成"


def test_saved_history_reload_preserves_owner_during_new_request():
    message = recorded_step()
    # The containing message's latest reply owner is deliberately different.
    message.metadata.update(run_id="run-b", responds_to_input_ids=["input-b"])
    restored = Msg.model_validate_json(message.model_dump_json())
    receipt = project_tool_execution_context([restored], ("input-b",))[
        "observed_tool_steps"
    ][0]
    assert receipt["input_ids"] == ["input-a"]
    assert receipt["run_id"] == "run-a"
    assert receipt["succeeded"] is True


def test_explicit_repeat_with_same_arguments_is_an_independent_step():
    first = recorded_step()
    repeat = recorded_step("input-b", "write-b", "running", "run-b")
    steps = project_tool_execution_context([first, repeat], ("input-b",))[
        "observed_tool_steps"
    ]
    assert [(s["input_ids"], s["succeeded"]) for s in steps] == [
        (["input-a"], True),
        (["input-b"], None),
    ]


def test_late_result_keeps_original_input_and_does_not_change_history():
    original = recorded_step()
    late = Msg(
        name="assistant", role="assistant", content=[original.content.pop()]
    )
    set_reply_block_metadata(
        late, "write-a", original.metadata["qwenpaw_reply_blocks"]["write-a"]
    )
    new = recorded_step("input-b", "write-b", "running")
    messages = [original, new, late]
    before = [m.model_dump_json() for m in messages]
    steps = project_tool_execution_context(messages, ("input-b",))[
        "observed_tool_steps"
    ]
    assert steps[0]["input_ids"] == ["input-a"]
    assert steps[0]["succeeded"] is True
    assert steps[1]["succeeded"] is None
    assert [m.model_dump_json() for m in messages] == before


@pytest.mark.parametrize("damage", ["owner", "name", "order", "duplicate"])
def test_ambiguous_evidence_cannot_create_success_receipt(damage):
    message = recorded_step()
    result = Msg(
        name="assistant", role="assistant", content=[message.content.pop()]
    )
    set_reply_block_metadata(
        result,
        "write-a",
        {"run_id": "run-a", "responds_to_input_ids": ["input-a"]},
    )
    messages = [message, result]
    if damage == "owner":
        set_reply_block_metadata(
            result,
            "write-a",
            {"run_id": "run-a", "responds_to_input_ids": ["input-b"]},
        )
    elif damage == "name":
        result.content[0].name = "other_tool"
    elif damage == "order":
        messages.reverse()
    elif damage == "duplicate":
        messages.insert(1, message.model_copy(deep=True))
    view = project_tool_execution_context(messages, ("input-a",))
    assert view["observed_tool_steps"] == []
    assert view["tool_step_coverage"]["ambiguous_calls"] == 1


def test_missing_evidence_after_compaction_never_implies_success():
    message = recorded_step()
    result_only = message.model_copy(update={"content": [message.content[1]]})
    view = project_tool_execution_context([result_only], ("input-a",))
    assert view["observed_tool_steps"] == []
    assert view["tool_step_coverage"]["results_without_calls"] == 1
    call_only = message.model_copy(update={"content": [message.content[0]]})
    step = project_tool_execution_context([call_only], ("input-a",))[
        "observed_tool_steps"
    ][0]
    assert step["execution_status"] == "unknown"
    assert step["succeeded"] is None
    # Legacy message-level ownership alone cannot prove block ownership.
    message.metadata = {
        "run_id": "run-a",
        "responds_to_input_ids": ["input-a"],
    }
    view = project_tool_execution_context([message], ("input-a",))
    assert view["observed_tool_steps"] == []
    assert view["tool_step_coverage"]["unassociated_blocks"] == 2


def test_reused_call_ids_in_distinct_runs_never_share_result():
    old = recorded_step()
    new = recorded_step("input-b", run_id="run-b")
    new.content.pop()
    steps = project_tool_execution_context([old, new], ("input-b",))[
        "observed_tool_steps"
    ]
    assert [s["succeeded"] for s in steps] == [True, None]


def test_budget_prioritizes_current_steps_and_discloses_omissions():
    current = recorded_step()
    current.content[0].input = json.dumps({"content": "X" * 10000})
    current.content[1].output = [TextBlock(text="Y" * 10000)]
    others = [recorded_step(f"old-{i}", f"old-{i}") for i in range(60)]
    view = project_tool_execution_context([current, *others], ("input-a",))
    step = view["observed_tool_steps"][0]
    assert step["input_ids"] == ["input-a"]
    assert step["arguments_truncated"] and step["result_truncated"]
    assert "arguments" not in step
    assert view["tool_step_coverage"]["omitted_steps"] > 0
    assert len(json.dumps(view, ensure_ascii=False)) < 18000
