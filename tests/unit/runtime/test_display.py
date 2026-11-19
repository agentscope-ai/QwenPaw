# -*- coding: utf-8 -*-
"""Verify that display projection preserves runtime events and their scope."""

import pytest

from qwenpaw.runtime.display import AssistantDisplayStream
from qwenpaw.schemas import Message, MessageType, Role, RunStatus, TextContent


@pytest.mark.parametrize(
    "status",
    [RunStatus.Completed, RunStatus.Failed, RunStatus.Cancelled],
)
def test_releases_only_the_terminal_assistant_snapshot(status):
    display = AssistantDisplayStream()
    draft = Message(
        role=Role.ASSISTANT,
        content=[TextContent(text="private prefix")],
    )
    [projected] = display.project(draft)
    assert projected.content[0].text == ""
    delta = TextContent(text="private prefix", msg_id=draft.id, delta=True)
    assert display.project(delta)[0].text == ""
    assert display.project(delta)[0].delta is True

    terminal = draft.model_copy(
        update={
            "status": status,
            "content": [
                TextContent(text="private prefix", index=0),
                TextContent(text="</think>answer", index=2),
            ],
        },
    )
    released, snapshot = display.project(terminal)
    assert (
        released.msg_id,
        released.index,
        released.delta,
        released.text,
    ) == (
        draft.id,
        2,
        True,
        "answer",
    )
    assert [block.text for block in snapshot.content] == ["", "answer"]
    assert terminal.content[1].text == "</think>answer"
    assert draft.content[0].text == delta.text == "private prefix"


@pytest.mark.parametrize(
    ("role", "kind"),
    [
        (Role.USER, MessageType.MESSAGE),
        (Role.ASSISTANT, MessageType.REASONING),
    ],
)
def test_non_reply_text_passes_through_unchanged(role, kind):
    display = AssistantDisplayStream()
    message = Message(role=role, type=kind)
    assert display.project(message) == [message]
    content = TextContent(text="<think>literal</think>", msg_id=message.id)
    assert display.project(content) == [content]
    message.content.append(content)
    assert display.project(message.completed()) == [message]
