# -*- coding: utf-8 -*-
"""Interactive choice card tool for chat interface.

Presents an interactive selection card to the user in the chat UI,
supporting fixed buttons and editable text input options.
The tool blocks until the user confirms their selection.
"""

import asyncio
import json
import logging
from typing import List

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from copaw.app.interaction import (
    InteractionManager,
    current_session_id,
)

logger = logging.getLogger(__name__)

_INTERACTION_TIMEOUT = 600  # 10 minutes


def _make_error(msg: str) -> ToolResponse:
    return ToolResponse(content=[TextBlock(type="text", text=msg)])


def _validate_options(
    raw: str,
) -> tuple[List[dict] | None, ToolResponse | None]:
    """Parse and validate the options JSON string.

    Returns (parsed_options, None) on success, or (None, error_response)
    on failure.
    """
    try:
        parsed: List[dict] = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, _make_error(
            "Error: 'options' parameter must be a valid "
            "JSON string representing a list of option objects.",
        )

    for i, opt in enumerate(parsed):
        if not isinstance(opt, dict):
            return None, _make_error(
                f"Error: Option at index {i} is not a dict.",
            )
        if opt.get("type") not in ("fixed", "editable"):
            return None, _make_error(
                f"Error: Option at index {i} must have "
                f'"type" set to "fixed" or "editable".',
            )
        if not opt.get("label"):
            return None, _make_error(
                f"Error: Option at index {i} must have "
                f'a non-empty "label".',
            )

    return parsed, None


async def interactive_choice(
    text: str,
    options: str,
) -> ToolResponse:
    """Display an interactive selection card to the user in the chat
    interface and wait for their response. The card contains descriptive
    text (supports Markdown) and a list of selectable options.

    This tool will block until the user makes a selection and confirms.

    Args:
        text (`str`):
            Descriptive text displayed at the top of the card.
            Supports full Markdown syntax including headings, lists,
            bold, code blocks, tables, etc.
        options (`str`):
            A JSON-encoded list of option objects. Each object must have:
            - "type" (str): Either "fixed" (a preset button) or
              "editable" (a button that reveals a text input field).
            - "label" (str): For "fixed" type, the button display text.
              For "editable" type, the placeholder hint text
              (e.g. "其他，请手动输入").

            Example:
            [
              {"type": "fixed", "label": "方案一"},
              {"type": "fixed", "label": "方案二"},
              {"type": "editable", "label": "其他，请手动输入"}
            ]

    Returns:
        `ToolResponse`:
            The user's selection result. For fixed buttons: "用户选择的
            是{label}". For editable buttons: "用户选择的是其他，补充内
            容为{user_input}".
    """
    parsed_options, err = _validate_options(options)
    if err is not None:
        return err

    session_id = current_session_id.get()
    if session_id is None:
        logger.warning(
            "interactive_choice called without session context; "
            "returning card data without waiting for user input",
        )
        payload = json.dumps(
            {"text": text, "options": parsed_options},
            ensure_ascii=False,
        )
        return ToolResponse(
            content=[TextBlock(type="text", text=payload)],
        )

    interaction = InteractionManager.create(session_id)
    try:
        await asyncio.wait_for(
            interaction.event.wait(),
            timeout=_INTERACTION_TIMEOUT,
        )
    except asyncio.TimeoutError:
        return ToolResponse(
            content=[
                TextBlock(
                    type="text",
                    text="用户未在规定时间内做出选择，交互超时。",
                ),
            ],
        )
    finally:
        InteractionManager.cleanup(session_id)

    result = interaction.result or "用户未做出选择"
    return ToolResponse(
        content=[TextBlock(type="text", text=result)],
    )
