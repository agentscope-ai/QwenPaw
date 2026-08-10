# -*- coding: utf-8 -*-
"""Build the canonical response messages for one artifact manifest."""

from __future__ import annotations

import json
import uuid
from typing import Any

from ..schemas import (
    ContentType,
    DataContent,
    FunctionCall,
    FunctionCallOutput,
    Message,
    MessageType,
    Role,
    RunStatus,
)


def build_artifact_messages(
    manifest: dict[str, Any],
) -> tuple[Message, Message]:
    """Return one completed internal tool call and result pair."""
    call_id = f"workspace_artifacts_{uuid.uuid4().hex}"
    call_message = Message(
        id=f"msg_{uuid.uuid4().hex}",
        type=MessageType.PLUGIN_CALL,
        role=Role.ASSISTANT,
        content=[],
        status=RunStatus.Completed,
    )
    call_message.name = "assistant"
    call_message.object = "message"
    call_content = DataContent(
        type=ContentType.DATA,
        data=FunctionCall(
            call_id=call_id,
            name="workspace_artifacts",
            arguments="{}",
        ).model_dump(),
        delta=False,
        index=0,
    )
    call_content.msg_id = call_message.id
    call_message.content.append(call_content)

    output_message = Message(
        id=f"msg_{uuid.uuid4().hex}",
        type=MessageType.PLUGIN_CALL_OUTPUT,
        role=Role.TOOL,
        content=[],
        status=RunStatus.Completed,
    )
    output_message.name = "assistant"
    output_message.object = "message"
    output_content = DataContent(
        type=ContentType.DATA,
        data=FunctionCallOutput(
            call_id=call_id,
            name="workspace_artifacts",
            output=json.dumps(manifest, ensure_ascii=False),
        ).model_dump(),
        delta=False,
        index=0,
    )
    output_content.msg_id = output_message.id
    output_message.content.append(output_content)
    return call_message, output_message


__all__ = ["build_artifact_messages"]
