# -*- coding: utf-8 -*-
"""Translate engine SSE stream frames into AgentScope events.

The engine emits ``stream_objects`` frames (object: response / message /
content / artifact.registered / followup.generated / segment / biz_event /
task_status / error).  The bridge re-emits them as AgentScope block events
so QwenPaw's Envelope → channel rendering pipeline delivers them over any
configured channel unchanged.

Loop semantics ported from the engine's own channel consumer
(``qwenpaw_data.host.core.channels.base``): only ``message``/``reasoning``
assistant messages are whitelisted for text deltas (``plugin_call`` frames
carry tool payloads, not prose), and a completed ``plugin_call`` carrying an
``ask_user_question`` call pauses the turn for clarification.
"""

from __future__ import annotations

import base64
import json
import logging
import posixpath
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
)

from agentscope.event import (
    DataBlockDeltaEvent,
    DataBlockEndEvent,
    DataBlockStartEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
    ThinkingBlockDeltaEvent,
    ThinkingBlockEndEvent,
    ThinkingBlockStartEvent,
)

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


@dataclass
class ClarificationRequest:
    """A pending ask_user_question extracted from a plugin_call frame."""

    clarification_id: str
    title: str
    # [{question, description, multi_select, options: [{label, description}]}]
    questions: List[Dict[str, Any]]


@dataclass
class TurnResult:
    """Mutable summary of one bridged turn, filled while translating."""

    status: str = ""
    answer_text: List[str] = field(default_factory=list)
    clarification: Optional[ClarificationRequest] = None
    followups: List[str] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    failure_message: str = ""
    last_seq: int = -1

    @property
    def answer(self) -> str:
        return "".join(self.answer_text)


# pylint: disable=too-many-return-statements,too-many-branches
def parse_clarification(
    frame: Dict[str, Any],
) -> Optional[ClarificationRequest]:
    """Extract an ask_user_question group from a completed plugin_call.

    Mirrors the engine console's parser: the frame's first ``data``
    content block must carry ``name == "ask_user_question"`` with JSON
    ``arguments`` of shape ``{title, questions: [...]}``.
    """
    if frame.get("type") != "plugin_call":
        return None
    if frame.get("status") != "completed":
        return None
    data = None
    for item in frame.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "data":
            data = item.get("data")
            break
    if not isinstance(data, dict):
        return None
    if data.get("name") != "ask_user_question":
        return None
    call_id = data.get("call_id")
    if not isinstance(call_id, str):
        return None
    arguments = data.get("arguments")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except ValueError:
            return None
    if not isinstance(arguments, dict):
        return None
    raw_questions = arguments.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        return None
    questions: List[Dict[str, Any]] = []
    for question in raw_questions:
        if not isinstance(question, dict):
            return None
        text = question.get("question")
        options = question.get("options")
        if not isinstance(text, str) or not isinstance(options, list):
            return None
        normalized_options = []
        for option in options:
            if not isinstance(option, dict) or not isinstance(
                option.get("label"),
                str,
            ):
                return None
            normalized_options.append(
                {
                    "label": option["label"],
                    "description": option.get("description") or "",
                },
            )
        questions.append(
            {
                "question": text,
                "description": question.get("description") or "",
                "multi_select": bool(question.get("multiSelect")),
                "options": normalized_options,
            },
        )
    return ClarificationRequest(
        clarification_id=call_id,
        title=str(arguments.get("title") or ""),
        questions=questions,
    )


def render_clarification_text(request: ClarificationRequest) -> str:
    """Render an ask_user_question group as a numbered-choice text prompt."""
    lines: List[str] = []
    if request.title:
        lines.append(f"❓ {request.title}")
    for q_index, question in enumerate(request.questions, start=1):
        prefix = f"{q_index}. " if len(request.questions) > 1 else ""
        lines.append(f"{prefix}{question['question']}")
        if question.get("description"):
            lines.append(f"   {question['description']}")
        for o_index, option in enumerate(question["options"], start=1):
            desc = option.get("description") or ""
            suffix = f" — {desc}" if desc else ""
            lines.append(f"   {o_index}) {option['label']}{suffix}")
        if question.get("multi_select"):
            lines.append("   （可多选，如：1,3；也可直接回复自定义内容）")
    lines.append("请回复选项编号或直接输入答案。")
    return "\n".join(lines)


def is_image_artifact(name: str) -> bool:
    return posixpath.splitext(name)[1].lower() in _IMAGE_EXTS


def artifact_media_type(name: str) -> str:
    return _IMAGE_MEDIA_TYPES.get(
        posixpath.splitext(name)[1].lower(),
        "application/octet-stream",
    )


def _end_block(block_id: str, kind: str, *, reply_id: str) -> Any:
    if kind == "reasoning":
        return ThinkingBlockEndEvent(reply_id=reply_id, block_id=block_id)
    return TextBlockEndEvent(reply_id=reply_id, block_id=block_id)


def _close_blocks(
    open_blocks: Dict[str, str],
    *,
    reply_id: str,
) -> List[Any]:
    """Close and remove every currently open text or reasoning block."""
    events = [
        _end_block(block_id, kind, reply_id=reply_id)
        for block_id, kind in open_blocks.items()
    ]
    open_blocks.clear()
    return events


# pylint: disable=too-many-branches,too-many-statements
async def translate_frames(  # noqa: C901, PLR0912
    frames: AsyncIterator[Dict[str, Any]],
    result: TurnResult,
    *,
    reply_id: str,
) -> AsyncIterator[Any]:
    """Consume engine frames, yield AgentScope events, fill ``result``.

    Ends on a terminal ``response`` frame, on clarification detection
    (the engine keeps the chat open waiting for the answer, but the
    QwenPaw turn must end so the user's next message can carry it), or
    when the frame stream is exhausted.
    """
    # msg_id → "message" | "reasoning"; populated by message_start frames
    whitelist: Dict[str, str] = {}
    open_blocks: Dict[str, str] = {}

    async for frame in frames:
        seq = frame.get("sequence_number")
        if isinstance(seq, int):
            result.last_seq = max(result.last_seq, seq)
        obj = frame.get("object")

        if obj == "message":
            status = frame.get("status")
            mtype = frame.get("type")
            msg_id = frame.get("id") or ""
            if status == "in_progress" and mtype in ("message", "reasoning"):
                if msg_id:
                    whitelist[msg_id] = mtype
            elif status == "completed" and mtype in (
                "message",
                "reasoning",
            ):
                whitelist.pop(msg_id, None)
                kind = open_blocks.pop(msg_id, None)
                if kind is not None:
                    yield _end_block(msg_id, kind, reply_id=reply_id)
            elif status == "completed" and mtype == "plugin_call":
                clarification = parse_clarification(frame)
                if clarification is not None:
                    result.clarification = clarification
                    for event in _close_blocks(
                        open_blocks,
                        reply_id=reply_id,
                    ):
                        yield event
                    block_id = f"clarify-{clarification.clarification_id}"
                    text = render_clarification_text(clarification)
                    yield TextBlockStartEvent(
                        reply_id=reply_id,
                        block_id=block_id,
                    )
                    yield TextBlockDeltaEvent(
                        reply_id=reply_id,
                        block_id=block_id,
                        delta=text,
                    )
                    yield TextBlockEndEvent(
                        reply_id=reply_id,
                        block_id=block_id,
                    )
                    result.status = "clarification"
                    return

        elif obj == "content":
            if frame.get("type") != "text":
                continue
            msg_id = frame.get("msg_id") or ""
            mtype = whitelist.get(msg_id)
            if not mtype:
                continue
            text = frame.get("text") or ""
            if frame.get("delta"):
                if not text:
                    continue
                if mtype == "reasoning":
                    if msg_id not in open_blocks:
                        open_blocks[msg_id] = mtype
                        yield ThinkingBlockStartEvent(
                            reply_id=reply_id,
                            block_id=msg_id,
                        )
                    yield ThinkingBlockDeltaEvent(
                        reply_id=reply_id,
                        block_id=msg_id,
                        delta=text,
                    )
                else:
                    if msg_id not in open_blocks:
                        open_blocks[msg_id] = mtype
                        yield TextBlockStartEvent(
                            reply_id=reply_id,
                            block_id=msg_id,
                        )
                    result.answer_text.append(text)
                    yield TextBlockDeltaEvent(
                        reply_id=reply_id,
                        block_id=msg_id,
                        delta=text,
                    )
            else:
                # Full (non-delta) content: emit as one block if the
                # stream never produced deltas for this msg_id (e.g.
                # non-streamed replay), otherwise just close the block.
                if mtype == "reasoning":
                    whitelist.pop(msg_id, None)
                    kind = open_blocks.pop(msg_id, None)
                    if kind is not None:
                        yield _end_block(msg_id, kind, reply_id=reply_id)
                    continue
                if msg_id not in open_blocks:
                    if not text:
                        whitelist.pop(msg_id, None)
                        continue
                    open_blocks[msg_id] = mtype
                    yield TextBlockStartEvent(
                        reply_id=reply_id,
                        block_id=msg_id,
                    )
                    result.answer_text.append(text)
                    yield TextBlockDeltaEvent(
                        reply_id=reply_id,
                        block_id=msg_id,
                        delta=text,
                    )
                whitelist.pop(msg_id, None)
                kind = open_blocks.pop(msg_id)
                yield _end_block(msg_id, kind, reply_id=reply_id)

        elif obj == "artifact.registered":
            artifact = frame.get("artifact")
            if isinstance(artifact, dict) and artifact.get("path"):
                if not any(
                    existing.get("path") == artifact["path"]
                    for existing in result.artifacts
                ):
                    result.artifacts.append(artifact)

        elif obj == "followup.generated":
            followup = frame.get("followup")
            if isinstance(followup, dict):
                questions = followup.get("questions")
                if isinstance(questions, list):
                    result.followups = [str(q) for q in questions if q]

        elif obj == "error":
            result.status = "failed"
            result.failure_message = str(frame.get("message") or "")

        elif obj == "response":
            status = frame.get("status")
            if status in ("completed", "failed", "cancelled"):
                result.status = status or ""
                if status == "failed":
                    error = frame.get("error")
                    if isinstance(error, dict):
                        result.failure_message = str(
                            error.get("message") or "",
                        )
                for event in _close_blocks(open_blocks, reply_id=reply_id):
                    yield event
                return

    for event in _close_blocks(open_blocks, reply_id=reply_id):
        yield event
    if not result.status:
        result.status = "completed"


async def emit_artifacts(
    artifacts: List[Dict[str, Any]],
    *,
    reply_id: str,
    fetch: Callable[[str], Awaitable[bytes]],
) -> AsyncIterator[Any]:
    """Emit image artifacts as data blocks and others as a text notice."""
    notices: List[str] = []
    for artifact in artifacts:
        name = str(artifact.get("name") or "")
        path = str(artifact.get("path") or "")
        if is_image_artifact(name):
            try:
                raw = await fetch(path)
            except Exception:
                logger.warning(
                    "bridge: artifact download failed: %s",
                    path,
                    exc_info=True,
                )
                notices.append(name)
                continue
            block_id = f"artifact-{path}"
            media_type = artifact_media_type(name)
            yield DataBlockStartEvent(
                reply_id=reply_id,
                block_id=block_id,
                media_type=media_type,
            )
            yield DataBlockDeltaEvent(
                reply_id=reply_id,
                block_id=block_id,
                data=base64.b64encode(raw).decode("ascii"),
                media_type=media_type,
            )
            yield DataBlockEndEvent(
                reply_id=reply_id,
                block_id=block_id,
            )
        else:
            notices.append(name)
    if notices:
        listed = "、".join(notices)
        text = f"📎 已生成文件：{listed}（请在控制台查看下载）"
        block_id = "artifact-notices"
        yield TextBlockStartEvent(reply_id=reply_id, block_id=block_id)
        yield TextBlockDeltaEvent(
            reply_id=reply_id,
            block_id=block_id,
            delta=text,
        )
        yield TextBlockEndEvent(reply_id=reply_id, block_id=block_id)


def render_followups_text(questions: List[str]) -> str:
    lines = ["💡 您可以继续问："]
    for index, question in enumerate(questions, start=1):
        lines.append(f"{index}. {question}")
    return "\n".join(lines)
