# -*- coding: utf-8 -*-
"""Mail F1 exploration mode activation tool."""
from __future__ import annotations

import logging

from agentscope.message import TextBlock
from agentscope.message import ToolResultState
from agentscope.tool import ToolChunk

from ...config.context import (
    activate_f1_for_session,
    get_current_session_id,
)
from ...runtime.tool_registry import tool_descriptor

logger = logging.getLogger(__name__)


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="ActivateF1ExplorationMode",
    ui_description=(
        "Activate F1 exploration mode for step-by-step mail approval"
    ),
    ui_icon="🔍",
)
async def activate_f1_exploration_mode() -> ToolChunk:
    """Activate F1 exploration mode. Call this when an email cannot be
    classified by the triage tree (MAIL_TRIAGE.md) and you need to
    attempt handling it with per-tool user approval.

    After activation, work in two phases: first ANALYZE the email from
    the recipient's (user's) perspective — its intent and how the user
    would handle it — and output a brief plan; then ACT step by step,
    stating a one-sentence reason before each tool call. The SYSTEM
    automatically intercepts every tool call (mail read/write, file
    ops, browser use, shell, etc.) and shows your reason and action to
    the user for approval, for the remainder of this request.

    IMPORTANT: Do NOT ask the user for approval yourself in your chat
    output. Just call the tools you need as usual; approval is handled
    automatically by the system. If the user approves, the tool returns
    its normal result; if the user denies, the tool returns a denial
    message and you should retry with a different approach.

    Returns:
        `ToolChunk`: Confirmation that F1 mode is now active.
    """
    # The session_id ContextVar is set in PRE_DISPATCH (before the tool
    # coordinator spawns per-tool tasks), so it is readable here even
    # though this coroutine runs in its own asyncio task.
    session_id = get_current_session_id()
    if not session_id:
        logger.warning(
            "activate_f1_exploration_mode: no session_id in context; "
            "F1 mode NOT activated.",
        )
        return ToolChunk(
            is_last=True,
            state=ToolResultState.SUCCESS,
            content=[
                TextBlock(
                    type="text",
                    text=(
                        "Failed to activate F1 Exploration Mode: the current "
                        "request has no session_id, so the step-by-step "
                        "approval state could not be registered. Apply the "
                        "strictest safety standard yourself, and do not "
                        "perform any action if uncertain."
                    ),
                ),
            ],
        )
    activate_f1_for_session(session_id)
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[
            TextBlock(
                type="text",
                text=(
                    "F1 Exploration Mode is active. Work as follows:\n"
                    "1. Analyze first: read the entire email from the "
                    "recipient's (user's) perspective, determine the email's "
                    "intent and how the user would handle it, and provide a "
                    "brief analysis and handling plan.\n"
                    "2. Then act: before each tool call, state the reason in "
                    "one sentence (for example, \"I want to read the email's "
                    'details more carefully"), then call the tool directly.\n'
                    "The system automatically intercepts every tool call and "
                    "shows your reason and proposed action to the user for "
                    "approval. If approved, the tool executes; if denied, "
                    "try a different approach. Do not ask the user for "
                    "approval yourself in the conversation."
                ),
            ),
        ],
    )
