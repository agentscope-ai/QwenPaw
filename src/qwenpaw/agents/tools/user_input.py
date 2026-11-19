# -*- coding: utf-8 -*-
"""Tool for asking the Web/console user structured questions."""
from __future__ import annotations

import json
import logging
from uuid import UUID
from typing import Any

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse
from pydantic import ValidationError

from ...config.context import get_current_request_context
from ...runtime.tool_registry import tool_descriptor
from ...user_input.schemas import UserInputQuestion
from ...user_input.service import get_user_input_service

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 300.0
_MAX_TIMEOUT_SECONDS = 1800.0


def _response(payload: dict[str, Any]) -> ToolResponse:
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(payload, ensure_ascii=False, indent=2),
            ),
        ],
    )


def _normalize_kind(raw: Any, allow_custom: bool) -> str:
    value = str(raw or "").strip().lower().replace("-", "_")
    if value in {"text", "input", "freeform", "free_text", "textarea"}:
        return "free_text"
    if allow_custom:
        return "choice_with_custom"
    if value in {"single_choice", "select", "radio", "choice"}:
        return "single_choice"
    return "choice_with_custom"


def _normalize_options(raw_options: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_options, list):
        return []
    normalized = []
    for index, item in enumerate(raw_options):
        if isinstance(item, str):
            label = item.strip()
            if not label:
                continue
            normalized.append(
                {
                    "label": label,
                    "value": label,
                    "recommended": (
                        "默认" in label
                        or "推荐" in label
                        or "recommended" in label.lower()
                        or index == 0
                    ),
                },
            )
        elif isinstance(item, dict):
            label = str(item.get("label") or item.get("text") or "").strip()
            value = str(item.get("value") or label).strip()
            if not label or not value:
                continue
            normalized.append(
                {
                    "label": label,
                    "value": value,
                    "description": item.get("description"),
                    "recommended": bool(item.get("recommended", False)),
                },
            )
    return normalized


def _normalize_question(item: dict[str, Any], index: int) -> dict[str, Any]:
    """Accept both QwenPaw and claw-code-like question shapes."""
    allow_custom = bool(item.get("allow_custom", True))
    question_id = str(
        item.get("id")
        or item.get("name")
        or item.get("key")
        or f"question_{index + 1}",
    ).strip()
    question_text = str(
        item.get("question")
        or item.get("label")
        or item.get("title")
        or question_id,
    ).strip()
    options = _normalize_options(item.get("options"))
    kind = _normalize_kind(item.get("kind") or item.get("type"), allow_custom)
    if kind == "single_choice" and allow_custom:
        kind = "choice_with_custom"
    if kind == "choice_with_custom" and not options:
        kind = "free_text"

    return {
        "id": question_id,
        "question": question_text,
        "kind": kind,
        "options": options,
        "placeholder": item.get("placeholder") or item.get("hint"),
        "required": bool(item.get("required", True)),
        "default_value": item.get("default_value") or item.get("default"),
    }


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="AskUserInput",
    ui_description="Ask the user a structured clarification question",
    ui_icon="❔",
)
async def ask_user_input(
    questions: list[dict[str, Any]] | None = None,
    title: str | None = None,
    timeout_seconds: float | None = None,
    sample_artifact_id: str | None = None,
) -> ToolResponse:
    """Ask the user for structured input and wait for their answer.

    Use this tool only when missing information would materially change the
    task outcome. Prefer offering a recommended default option when the user
    can safely proceed without specifying every detail.

    For PPT sample approval, first send the sample image with send_file_to_user.
    Ask one question with id sample_approval and pass the artifact UUID from its
    download URL. On continuation reuse the same artifact and original answer.
    A revised image must be sent and reviewed separately.

    Args:
        questions: Questions to show in the Web/console input panel. Each
            question may use either QwenPaw shape
            ``{id, question, kind, options}`` or claw-code-like shape
            ``{name, label, type, options}``. For choice questions, provide
            two to four concrete options; the UI appends a custom-answer
            choice.
        title: Optional panel title.
        timeout_seconds: Optional maximum wait time; defaults to 300 seconds.
    """
    from ...app.agent_context import (
        get_current_agent_id,
        get_current_root_session_id,
        get_current_session_id,
    )

    ctx = get_current_request_context() or {}
    channel = str(ctx.get("channel") or "")
    if channel and channel != "console":
        return _response(
            {
                "status": "unavailable",
                "reason": (
                    "Structured user input is only available in the "
                    "Web/console channel. Ask the user directly in text."
                ),
                "answers": {},
            },
        )

    session_id = str(ctx.get("session_id") or get_current_session_id() or "")
    if not session_id:
        return _response(
            {
                "status": "unavailable",
                "reason": "No active session is available for user input.",
                "answers": {},
            },
        )

    if not questions:
        return _response(
            {
                "status": "error",
                "reason": (
                    "The 'questions' argument is required. Provide a list of "
                    "question objects, e.g. {name, label, type, options}."
                ),
                "answers": {},
            },
        )

    try:
        normalized = [
            _normalize_question(item, index)
            for index, item in enumerate(questions)
            if isinstance(item, dict)
        ]
        parsed_questions = [UserInputQuestion(**item) for item in normalized]
    except (TypeError, ValidationError) as exc:
        return _response(
            {
                "status": "error",
                "reason": f"Invalid questions payload: {exc}",
                "answers": {},
            },
        )
    if not parsed_questions:
        return _response(
            {
                "status": "error",
                "reason": "At least one question is required.",
                "answers": {},
            },
        )

    timeout = float(timeout_seconds or _DEFAULT_TIMEOUT_SECONDS)
    timeout = max(1.0, min(timeout, _MAX_TIMEOUT_SECONDS))
    root_session_id = str(
        ctx.get("root_session_id") or get_current_root_session_id() or session_id,
    )
    user_id = str(ctx.get("user_id") or "default")
    agent_id = str(ctx.get("agent_id") or get_current_agent_id())

    from ...runtime_status.scope import execution_user_id

    svc = get_user_input_service()
    sample_scope = None
    if len(parsed_questions) == 1 and parsed_questions[0].id == "sample_approval":
        from ...identity.runtime import is_multi_user_enabled
        from ...access.agent_repository import agent_database_id

        if is_multi_user_enabled():
            try:
                sample_scope = dict(owner=UUID(str(execution_user_id(ctx))), agent=agent_database_id(agent_id),
                                    chat=UUID(str(ctx.get("conversation_id"))), artifact=UUID(str(sample_artifact_id)))
            except ValueError:
                return _response({"status": "sample_required", "answers": {},
                                  "reason": "先发送本会话的样稿图片，再传入下载链接中的 sample_artifact_id。"})
            # 复用的答复只覆盖这一份图片的制作决定，不复用模型自定义的问题和权限。
            parsed_questions = [UserInputQuestion(
                id="sample_approval", question="是否确认这份样稿，并按它制作剩余页面？",
                kind="single_choice", options=[
                    {"label": "确认并生成", "value": "确认并生成"},
                    {"label": "调整样稿", "value": "调整样稿"},
                ],
            )]
            title = "确认 PPT 样稿"
    request_args = dict(
        session_id=session_id,
        root_session_id=root_session_id,
        user_id=user_id,
        channel="console",
        agent_id=agent_id,
        title=title,
        recipient_user_id=execution_user_id(ctx),
        questions=parsed_questions,
        timeout_seconds=timeout,
    )
    if sample_scope is not None:
        try:
            return _response(await svc.ask_about_sample(sample_scope, **request_args))
        except ValueError as exc:
            return _response({"status": "unavailable", "reason": str(exc), "answers": {}})
    pending = await svc.create_pending(**request_args)
    logger.info(
        "ask_user_input waiting: request_id=%s session=%s questions=%d",
        pending.request_id[:8],
        session_id[:8],
        len(parsed_questions),
    )
    result = await svc.wait_for_result(pending.request_id, timeout)
    return _response(result.model_dump())
