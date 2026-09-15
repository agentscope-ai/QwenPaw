"""Result reads keep identities and do not confuse live data with storage."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentscope.message import Msg, TextBlock, ThinkingBlock, ToolResultBlock

from qwenpaw.app.chats.replies import ChatReplyView, project_replies


def message(
    text="42", block_id="b", inputs=("first",), phase="final", order=1
):
    return Msg(
        id="m",
        name="assistant",
        role="assistant",
        content=[
            TextBlock(
                id=block_id,
                text=text,
                metadata={
                    "responds_to_input_ids": list(inputs),
                    "run_id": "run",
                    "timeline_order": order,
                    "reply_phase": phase,
                },
            )
        ],
    )


def state(msg):
    return {"agent": {"state": {"context": [msg.model_dump(mode="json")]}}}


def test_equal_answers_are_distinct_and_shared_reply_keeps_all_inputs():
    msg = message(inputs=("a", "b"))
    msg.content.extend(
        message(block_id="next", inputs=("c",), order=2).content
    )
    replies = list(project_replies([msg]).values())
    assert len(replies) == 2
    assert replies[0].input_ids == ("a", "b")
    assert replies[0].identity != replies[1].identity
    assert replies[0].text == replies[1].text


def test_tool_thinking_and_internal_observations_are_not_spoken():
    msg = message()
    msg.content.extend(
        [
            ThinkingBlock(thinking="private"),
            ToolResultBlock(id="tool", name="any-tool", output="raw log"),
        ]
    )
    internal = Msg(
        name="runtime", role="assistant", content=[TextBlock(text="internal")]
    )
    assert len(project_replies([msg, internal])) == 1


def test_reply_projection_cleans_display_artifacts_without_mutating_context():
    msg = message("第一步完成，校验值201。\n⟦ 任务一｜状态：已完成 ⟧")
    raw = msg.content[0].text
    [reply] = project_replies([msg]).values()
    assert reply.text == "第一步完成，校验值201。"
    assert msg.content[0].text == raw
    assert reply.input_ids == ("first",)


def test_live_handoff_needs_equal_readback_and_actual_save():
    view = ChatReplyView()
    current = message("fresh answer")
    view.observe(current)
    assert view.capture(state(current))[0].persisted is False
    view.saved("run")
    assert view.capture(state(message("old answer")))[0].text == "fresh answer"
    assert view._live
    assert view.capture(state(current))[0].persisted is True
    assert not view._live
    assert view.capture(state(current))[0].text == "fresh answer"


@pytest.mark.asyncio
async def test_read_does_not_increment_content_version_or_truncate():
    msg = message("result " * 1000)
    view = ChatReplyView()
    session = SimpleNamespace(
        get_session_state_dict=AsyncMock(return_value=state(msg))
    )
    chat = SimpleNamespace(session_id="s", user_id="u", channel="console")
    first = await view.read(session, chat)
    assert first == await view.read(session, chat)
    assert first[0].text == msg.content[0].text


def test_continuation_message_can_include_blocks_from_an_older_saved_run():
    msg = message()
    continuation = message("new result", "new-block").content[0]
    continuation.metadata["run_id"] = "next-run"
    msg.content.append(continuation)
    view = ChatReplyView()
    view.observe(msg, "next-run")
    view.saved("next-run")
    assert all(reply.persisted for reply in view.capture(state(msg)))
    assert not view._live


def test_separate_messages_with_same_reply_id_keep_every_live_block():
    from agentscope.state import AgentState

    agent = AgentState()
    agent.reply_id = "m"
    view = ChatReplyView()
    for index in range(1, 4):
        agent.context.append(
            Msg(name="user", role="user",
                content=[TextBlock(text=f"input-{index}")])
        )
        agent.append_context(
            "assistant",
            message(str(200 + index), f"b-{index}", (str(index),),
                    order=index).content,
        )
        view.observe(agent.context[-1], "run")
        assert [r.text for r in view.capture({})] == [
            str(200 + i) for i in range(1, index + 1)
        ]
    disk = {"agent": {"state": agent.model_dump(mode="json")}}
    before = view.capture(disk)
    assert not any(r.persisted for r in before)
    view.saved("run")
    after = view.capture(disk)
    assert [(r.identity, r.text) for r in after] == [
        (r.identity, r.text) for r in before
    ]
    assert all(r.persisted for r in after)
    assert not view._live


def test_block_update_and_save_handoff_have_independent_owners():
    view = ChatReplyView()
    first = message("old run", "first")
    second = message("partial", "second", ("next",), order=2)
    second.content[0].metadata["run_id"] = "next-run"
    view.observe(first, "run")
    view.observe(second, "next-run")
    second.content[0].text = "fresh"
    assert [r.text for r in view.capture({})] == ["old run", "fresh"]
    view.saved("run")
    results = view.capture(state(first))
    assert [(r.text, r.persisted) for r in results] == [
        ("old run", True), ("fresh", False)
    ]
    replacement = second.model_copy(deep=True)
    replacement.content[0].text = "final"
    view.observe(replacement, "next-run")
    second.content[0].text = "obsolete object"
    assert view.capture(state(first))[-1].text == "final"
    view.saved("next-run")
    assert view.capture(state(second))[-1].persisted is False
    assert view.capture(state(replacement))[-1].persisted is True
    assert not view._live


def test_cancelled_projection_cannot_remove_other_live_reply_blocks():
    view = ChatReplyView()
    first = message("completed result", "first")
    cancelled = message("internal cancellation", "second", order=2)
    view.observe(first, "run")
    view.observe(cancelled, "next-run")
    cancelled.metadata = {"request_termination": "cancelled"}
    assert [r.text for r in view.capture({})] == ["completed result"]


@pytest.mark.parametrize("code,stage", [
    ("empty_response", "answer_generation"), ("future_error", "unknown"),
])
def test_reply_error_survives_projection_and_stale_disk_handoff(code, stage):
    current = message("请稍后重试", inputs=("failed-input",))
    old_disk = state(current)
    current.content[0].metadata["reply_error"] = code
    raw = current.model_dump(mode="json")
    view = ChatReplyView()
    view.observe(current)
    view.saved("run")
    [reply] = view.capture(old_disk)
    assert reply.public_dict().get("error") == {"code": code, "stage": stage}
    assert not reply.persisted and view._live
    [restored] = view.capture(state(current))
    assert restored.persisted and not view._live
    assert restored.public_dict()["error"] == reply.public_dict()["error"]
    assert current.model_dump(mode="json") == raw
    next_reply = message("成功", "next", ("next-input",), order=2)
    [success] = project_replies([next_reply]).values()
    assert "error" not in success.public_dict()


def test_reply_error_does_not_serialize_runtime_objects():
    msg = message()
    msg.content[0].metadata["reply_error"] = RuntimeError("internal")
    [reply] = project_replies([msg]).values()
    assert "error" not in reply.public_dict()
