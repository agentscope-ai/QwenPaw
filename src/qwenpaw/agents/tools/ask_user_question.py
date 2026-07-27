# -*- coding: utf-8 -*-
"""AskUserQuestion tool for structured user interaction.

This tool allows the agent to ask the user structured questions
with options (single/multi select) or free text input. The tool
blocks until the user responds or timeout is reached.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from agentscope.message import TextBlock
from agentscope.tool import ToolChunk
from agentscope.message import ToolResultState

from ...app.agent_context import (
    get_current_session_id,
    get_current_agent_id,
    get_current_channel,
)
from ...runtime.tool_registry import tool_descriptor

logger = logging.getLogger(__name__)


# Sentinel prefix used by ``_parse_questions_json`` to flag JSON-level
# failures (malformed payload, code fence pollution, etc.). Schema-level
# failures (missing field, wrong type) do NOT carry this prefix.
# ``ask_user_question`` uses the prefix to decide whether to attach a
# copy-pasteable example to the error response: JSON errors benefit from
# one, schema errors do not.
_JSON_ERROR_PREFIX = "[json] "


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="AskUserQuestion",
    default_policy="allow",
    policy_reason="Interactive tool that blocks until the user answers; "
    "every call must be approved by the user.",
    ui_description="Ask the user structured questions and wait for answers",
    ui_icon="❓",
)
async def ask_user_question(
    questions: str,
) -> ToolChunk:
    """Ask the user structured questions and BLOCK until they respond.

    WHEN TO USE — only when you cannot proceed without the user's input:
    - The request is ambiguous and a wrong guess would waste effort
      (e.g. unclear scope, conflicting requirements).
    - A decision must be made that materially changes the outcome
      (e.g. which library, which approach, whether to overwrite data).
    - You need preferences or information that only the user has
      (e.g. target environment, personal taste, credentials policy).

    WHEN NOT TO USE — do NOT interrupt the user for things you can
    resolve yourself:
    - Facts available in the codebase, files, or via other tools
      (search or read first; ask only as a last resort).
    - Trivial choices where any reasonable option works — just pick
      one and mention it in your reply.
    - Informational progress updates; this tool blocks, so every call
    costs the user an interaction. Prefer doing over asking.

    QUESTION TYPES:
    - SINGLE_SELECT / MULTI_SELECT: present concrete options; the user
      can always pick 'Other' to type a custom answer, so options do
      not need to be exhaustive.
    - TEXT_INPUT: open-ended answers (names, paths, free-form specs).
    You may ask 1-4 related questions in a single call.

    OPTION DESIGN:
    - Put your recommended option first and append '(Recommended)' to
      its label, with a short reason in its description.
    - Keep options mutually exclusive; use MULTI_SELECT when they are
      not.

    Args:
        questions (`str`):
            MUST be a JSON array string of question objects. Each item
            is an object with:
            - question_type (str): "SINGLE_SELECT", "MULTI_SELECT", or
              "TEXT_INPUT"
            - prompt (str): The question text to display
            - options (array of strings, optional): Required for SELECT
              types. Example: ["Option A", "Option B", "Option C"]
            Required structure:
            [
                {
                    "question_type":
                        "SINGLE_SELECT|MULTI_SELECT|TEXT_INPUT" (required),
                    "prompt": "question text" (required, non-empty),
                    "options": ["a", "b"] (required for SELECT types,
                        optional for TEXT_INPUT)
                }
            ]
            Common mistakes to AVOID:
            - Forgetting options for SELECT types
            - Using wrong question_type spelling
            - Empty prompt string

            Pass a JSON string like:
            ``[{"question_type": "SINGLE_SELECT", "prompt": "Choose one:",
            "options": ["A", "B"]}]``

    Returns:
        `ToolChunk`:
            The user's answers to all questions, or error/status message.
    """
    # Lazy imports: avoid a circular dependency with the questionnaires
    # module, which itself imports from app.agent_context.
    from ...app.questionnaires.service import get_question_service
    from ...app.questionnaires.models import Question, QuestionType

    parsed_questions = _parse_questions_json(questions)
    if isinstance(parsed_questions, str):
        # JSON-level errors (syntax / extraction failure) carry an example
        # so the agent can self-correct on the next turn; schema-level
        # errors (missing field, wrong type) do not — the message itself
        # already pinpoints the problem and a 25-line example would be
        # pure noise.
        if parsed_questions.startswith(_JSON_ERROR_PREFIX):
            return _make_error_with_example(parsed_questions)
        return _make_error(parsed_questions)

    # ``session_id`` is the single key under which the Future is parked
    # in QuestionService; the frontend resolves it using the same id
    # (``window.currentSessionId``), so they must agree byte-for-byte.
    session_id = str(get_current_session_id() or "")
    if not session_id:
        # Without a session context we cannot park the coroutine safely —
        # fail loud instead of silently losing the question.
        return _make_error(
            "Error: AskUserQuestion requires a session context.",
        )
    agent_id = str(get_current_agent_id() or "")
    channel = str(get_current_channel() or "")

    service = get_question_service()
    try:
        result = await service.create_and_wait(
            parsed_questions,
            session_id=session_id,
            agent_id=agent_id,
            channel=channel,
        )
    except asyncio.CancelledError:
        # The user aborted the tool invocation (e.g. clicked "Stop").
        # Mark the questionnaire ``interrupted`` so the suspended coroutine
        # is released with a structured payload instead of a hard cancel.
        logger.info(
            "Caught CancelledError for session %s, marking interrupted",
            session_id,
        )
        result = await service.interrupt(session_id)
        return _build_tool_chunk(result)
    except Exception as e:
        logger.exception("AskUserQuestion failed")
        return _make_error(f"Error: Failed to process question - {e!s}")

    # ``answers`` only carries ``question_index`` (a number) which the LLM
    # cannot map back to the original prompt — rehydrate the question text
    # so the next model step sees a self-contained ``{question, answer}``
    # list.
    answers = result.get("answers", [])
    enriched = []
    for a in answers:
        idx = a.get("question_index", -1)
        prompt = (
            parsed_questions[idx].prompt
            if 0 <= idx < len(parsed_questions)
            else f"Q{idx}"
        )
        entry: dict[str, Any] = {"question": prompt, "answer": a.get("answer")}
        sup = a.get("supplementary_input", "")
        if sup:
            entry["supplementary_input"] = sup
        enriched.append(entry)
    result["answers"] = enriched

    # Return structured JSON (not human-readable text): the frontend
    # ToolCard parses ``answers[]`` for per-question rendering, and the
    # LLM reads JSON just as easily as prose.
    return _build_tool_chunk(result)


def _build_tool_chunk(result: dict[str, Any]) -> ToolChunk:
    """Wrap a questionnaire result dict into a successful ``ToolChunk``."""
    result_json = json.dumps(result, ensure_ascii=False, indent=2)
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=result_json)],
    )


def _parse_questions_json(
    questions: str | list | None,
) -> "list[Question] | str":  # noqa: F821 (Question lives in models)
    """Parse the ``questions`` tool argument.

    Tolerant of common LLM JSON pollution: outer quotes, leading/trailing
    prose, markdown code fences. Returns the parsed ``Question`` list on
    success, or an error message string suitable for echoing back to the
    agent.

    Args:
        questions: A JSON string, an already-decoded list, or ``None``.

    Returns:
        ``list[Question]`` on success; ``str`` error message on failure.
        String errors raised by JSON-level failures
        (i.e. ``_extract_json_array``) are tagged with the
        ``_JSON_ERROR_PREFIX`` sentinel so the caller
        can decide whether to attach an example. Schema-level errors are
        returned as plain strings.
    """
    from ...app.questionnaires.models import Question, QuestionType

    if questions is None:
        return "Error: questions is required."

    if isinstance(questions, list):
        questions_list = questions
    elif isinstance(questions, str):
        questions_list = _extract_json_array(questions)
        if isinstance(questions_list, str):
            # Already tagged by ``_extract_json_array``.
            return questions_list
    else:
        return (
            f"Error: 'questions' must be a JSON string or array, "
            f"got {type(questions).__name__}."
        )

    if not isinstance(questions_list, list):
        return "Error: 'questions' must be a JSON array."

    if len(questions_list) == 0:
        return "Error: questions list cannot be empty."

    parsed_questions: list[Question] = []
    for i, q_input in enumerate(questions_list):
        if not isinstance(q_input, dict):
            return (
                f"Error: question {i} must be an object, "
                f"got {type(q_input).__name__}."
            )

        question_type = q_input.get("question_type")
        prompt = q_input.get("prompt")

        if not question_type:
            return f"Error: question {i} missing 'question_type'."
        if not prompt:
            return f"Error: question {i} missing 'prompt'."

        try:
            q_type = QuestionType(question_type)
        except ValueError:
            valid_types = [t.value for t in QuestionType]
            return (
                f"Error: invalid question_type '{question_type}'. "
                f"Valid types: {valid_types}"
            )

        options = _normalize_options(q_input.get("options"))

        if q_type in (QuestionType.SINGLE_SELECT, QuestionType.MULTI_SELECT):
            if not options:
                return (
                    f"Error: question {i} ({q_type.value}) requires "
                    f"'options' list with at least one option."
                )

        parsed_questions.append(
            Question(
                question_type=q_type,
                prompt=prompt,
                options=options,
            )
        )

    return parsed_questions


def _extract_json_array(raw: str) -> list | str:
    """Recover the outermost JSON array from a possibly polluted string.

    Strategies, tried in order:
      1. ``json.loads`` directly.
      2. Strip an outer pair of matching quotes and retry.
      3. Slice the substring between the first ``[`` and last ``]``.
      4. Strip markdown code fences (`` ```json ... ``` ``) and retry.

    All failure returns carry the ``_JSON_ERROR_PREFIX`` sentinel so the
    caller can route them through ``_make_error_with_example`` rather
    than the noisier plain-error path.

    Args:
        raw: The raw string from the LLM.

    Returns:
        The parsed list, or a ``[json] Error: ...`` string when all
        strategies fail.
    """
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        return f"{_JSON_ERROR_PREFIX}'questions' must be a JSON array."
    except json.JSONDecodeError:
        pass

    stripped = raw.strip()
    if (stripped.startswith('"') and stripped.endswith('"')) or (
        stripped.startswith("'") and stripped.endswith("'")
    ):
        stripped = stripped[1:-1]
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                return [parsed]
            return f"{_JSON_ERROR_PREFIX}'questions' must be a JSON array."
        except json.JSONDecodeError:
            pass

    start = stripped.find("[")
    end = stripped.rfind("]")
    if start != -1 and end != -1 and start < end:
        try:
            parsed = json.loads(stripped[start : end + 1])
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    cleaned = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
    except json.JSONDecodeError:
        pass

    return f"{_JSON_ERROR_PREFIX}Invalid JSON in 'questions': {raw[:200]}"


def _normalize_options(options: Any) -> list[str]:
    """Coerce ``options`` into ``list[str]`` regardless of LLM quirks.

    The LLM sometimes hands us a dict (e.g. ``{"0": "红", "1": "蓝"}``)
    instead of a list; flattening ``values()`` keeps the contract
    uniform and avoids surprises downstream.
    """
    if options is None:
        return []
    if isinstance(options, list):
        return [str(opt) for opt in options]
    if isinstance(options, dict):
        return [str(v) for v in options.values()]
    return [str(options)]


def _make_error(text: str) -> ToolChunk:
    """Build a failure ``ToolChunk``.

    ``ToolResultState.ERROR`` (not ``SUCCESS``) is intentional: it makes
    the coordinator mark ``end_state = "error"``, and the agent
    framework recognises the failure so the LLM doesn't loop on the
    same malformed input forever.
    """
    return ToolChunk(
        is_last=True,
        state=ToolResultState.ERROR,
        content=[TextBlock(type="text", text=text)],
    )


def _make_error_with_example(error_msg: str) -> ToolChunk:
    """Failure ``ToolChunk`` with a copy-pasteable, language-agnostic example.

    Echoing a working payload alongside the error lets the agent
    self-correct on the next turn without us having to chase the model.

    The example uses ``<...>`` placeholders for free-form text and keeps
    explanations in English (the dominant pre-training language for
    JSON syntax); the model is then free to fill the placeholders in
    whichever language the surrounding conversation uses. Keeping
    Chinese here would only fit Chinese-prompt agents and bias the
    next regeneration toward Chinese even when the user is in EN.
    """
    example = """Example payload (replace placeholders, keep JSON structure):

[
  {
    "question_type": "SINGLE_SELECT",
    "prompt": "<your question text>",
    "options": ["<option 1>", "<option 2>"]
  },
  {
    "question_type": "MULTI_SELECT",
    "prompt": "<your question text>",
    "options": ["<option 1>", "<option 2>"]
  },
  {
    "question_type": "TEXT_INPUT",
    "prompt": "<your question text>"
  }
]

Supported question_type values:
- SINGLE_SELECT: single-choice; ``options`` is REQUIRED and must
  contain at least one entry.
- MULTI_SELECT: multi-choice; ``options`` is REQUIRED and must contain
  at least one entry.
- TEXT_INPUT: free-text; ``options`` must be omitted or empty.

The whole value of ``questions`` MUST be a JSON array (start with ``[``
and end with ``]``). Make sure the JSON is syntactically valid before
sending it again."""
    error_text = f"{error_msg}\n\n{example}"
    return _make_error(error_text)
