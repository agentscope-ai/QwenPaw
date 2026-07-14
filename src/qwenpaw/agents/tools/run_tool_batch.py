# -*- coding: utf-8 -*-
"""Run a batch of tool calls sequentially with step-result references."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import get_current_toolkit

logger = logging.getLogger(__name__)

# Maximum number of steps allowed in a single batch.
MAX_BATCH_STEPS = 50

# --- Step-reference patterns -----------------------------------------------
# Only the brace-delimited form ${steps.N.path} is recognised.  This avoids
# ambiguity when $-prefixed text appears inside shell commands or other
# mixed-content strings.

_STEP_REF_PATTERN = re.compile(
    r"^\$\{steps\.(\d+)(?:\.([A-Za-z0-9_.-]+))?\}$",
)
_STEP_REF_INLINE_PATTERN = re.compile(
    r"\$\{steps\.(\d+)(?:\.([A-Za-z0-9_.-]+))?\}",
)


# --- Helpers --------------------------------------------------------------


def _json_tool_response(payload: dict[str, Any]) -> ToolResponse:
    """Wrap a JSON-serialisable dict in a single-TextBlock ToolResponse."""
    return ToolResponse(
        content=[
            TextBlock(
                type="text",
                text=json.dumps(payload, ensure_ascii=False),
            ),
        ],
    )


def _extract_text(response: ToolResponse) -> str:
    """Extract text from the first TextBlock in a ToolResponse.

    Some tools (``view_image``, ``send_file``, etc.) return an
    ``ImageBlock`` / ``FileBlock`` / ``VideoBlock`` before the
    ``TextBlock``.  We scan all blocks to find the first one whose
    ``type`` is ``"text"``.
    """
    for block in response.content or []:
        block_type = (
            block.get("type", "")
            if isinstance(block, dict)
            else getattr(block, "type", "")
        )
        if block_type == "text":
            return (
                block.get("text", "")
                if isinstance(block, dict)
                else getattr(block, "text", "")
            )
    return ""


# Error prefixes/patterns used by built-in tools (plain-text responses).
# Covers:
#   file_io / file_search / view_media / send_file / get_current_time
#       / delegate_external_agent          →  "Error: ..."
#   agent_management (chat/submit/check)   →  "ERROR: ..."
#   shell (non-zero exit)                  →  "Command failed ..."
_ERROR_PREFIXES = (
    "error:",  # covers "Error:" and "ERROR:" (case-insensitive)
    "command failed ",  # shell non-zero exit code
)


def _is_error_text(text: str) -> bool:
    """Heuristically detect error responses from plain-text tools."""
    lower = text.lower()
    return any(lower.startswith(p) for p in _ERROR_PREFIXES)


def _response_payload(response: ToolResponse) -> dict[str, Any]:
    """Convert a ToolResponse into a normalised result dict.

    The ``ok`` field is inferred from:
    - JSON responses with an explicit ``ok`` field (``browser_use``,
      ``desktop_screenshot``).
    - Plain-text error prefixes (``Error:``, ``Command failed``).
    - Exceptions caught in ``_call_tool`` (already ``ok: False``).

    The original content blocks are preserved under ``_raw_blocks``
    (an internal key that avoids colliding with tool payloads that
    contain their own ``content`` field).
    """
    text = _extract_text(response)
    content = list(response.content or [])

    # Try JSON first — some tools return structured JSON with ``ok``.
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            if "ok" not in payload:
                payload["ok"] = "error" not in payload
            payload["_raw_blocks"] = content
            return payload
        return {"ok": True, "value": payload, "_raw_blocks": content}
    except (json.JSONDecodeError, TypeError):
        pass

    # Plain-text response — check for known error patterns.
    if _is_error_text(text):
        return {"ok": False, "error": text, "_raw_blocks": content}
    return {"ok": True, "text": text, "_raw_blocks": content}


# --- Step-reference resolution --------------------------------------------


def resolve_step_refs(
    value: Any,
    results: list[dict[str, Any]],
) -> Any:
    """Recursively resolve ``$steps.<index>.<path>`` references."""
    if isinstance(value, dict):
        return {
            key: resolve_step_refs(item, results)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [resolve_step_refs(item, results) for item in value]
    if isinstance(value, str):
        return _resolve_step_ref_string(value, results)
    return value


def _resolve_step_ref_string(
    value: str,
    results: list[dict[str, Any]],
) -> Any:
    """Resolve ``${steps}`` placeholders in a single string value."""
    # Exact match – return the raw resolved value (preserves type).
    match = _STEP_REF_PATTERN.match(value)
    if match:
        return _lookup_step_ref(
            match.group(1),
            match.group(2),
            results,
            value,
        )

    # Inline match – substitute into the surrounding string.
    def _replace(match_obj: re.Match[str]) -> str:
        resolved = _lookup_step_ref(
            match_obj.group(1),
            match_obj.group(2),
            results,
            value,
        )
        return (
            resolved
            if isinstance(resolved, str)
            else json.dumps(
                resolved,
                ensure_ascii=False,
            )
        )

    return _STEP_REF_INLINE_PATTERN.sub(_replace, value)


def _lookup_step_ref(
    step_index_text: str,
    path: str | None,
    results: list[dict[str, Any]],
    original: str,
) -> Any:
    """Look up one step-result reference."""
    step_index = int(step_index_text)
    if step_index >= len(results):
        raise ValueError(f"Step reference out of range: {original}")
    current: Any = results[step_index]
    if not path:
        return current
    for part in path.split("."):
        if isinstance(current, list):
            if not part.isdigit():
                raise ValueError(
                    f"Invalid list index in step reference: {original}",
                )
            idx = int(part)
            if idx >= len(current):
                raise ValueError(
                    f"List index out of range in step reference: {original}",
                )
            current = current[idx]
        elif isinstance(current, dict):
            if part not in current:
                raise ValueError(
                    f"Missing key '{part}' in step reference: {original}",
                )
            current = current[part]
        else:
            raise ValueError(
                f"Cannot resolve step reference: {original}",
            )
    return current


# --- Batch file loading & $args resolution --------------------------------

# Only the brace-delimited form ${args.name} is recognised.
_ARG_REF_PATTERN = re.compile(r"^\$\{args\.([A-Za-z0-9_.-]+)\}$")
_ARG_REF_INLINE_PATTERN = re.compile(r"\$\{args\.([A-Za-z0-9_.-]+)\}")


def _load_batch_file(file_path: str) -> list[dict[str, Any]]:
    """Load actions from a JSON batch file.

    The file may be a plain JSON array of actions, or an object with an
    ``actions`` key.  ``file_path`` must be an absolute path.

    Raises ``ValueError`` on any validation failure.
    """
    path_text = (file_path or "").strip()
    if not path_text:
        raise ValueError("file_path is required")

    path = Path(path_text).expanduser().resolve()

    if not path.is_file():
        raise ValueError(f"Batch file not found: {path}")
    if path.suffix.lower() != ".json":
        raise ValueError("file_path must point to a .json file")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON at {path}: {exc}") from exc

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        actions = data.get("actions")
        if isinstance(actions, list):
            return actions
    raise ValueError(
        "Batch JSON must be an array of actions or an object "
        "with an 'actions' array",
    )


def _resolve_args(value: Any, args: dict[str, Any]) -> Any:
    """Recursively replace ``${args.<name>}`` placeholders in actions."""
    if isinstance(value, dict):
        return {k: _resolve_args(v, args) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_args(v, args) for v in value]
    if isinstance(value, str):
        # Exact match — return the raw value (preserves type).
        match = _ARG_REF_PATTERN.match(value)
        if match:
            return _lookup_arg(match.group(1), args)
        # Inline — substitute into the string.

        def _replace(m: re.Match[str]) -> str:
            resolved = _lookup_arg(m.group(1), args)
            return (
                resolved
                if isinstance(resolved, str)
                else json.dumps(
                    resolved,
                    ensure_ascii=False,
                )
            )

        return _ARG_REF_INLINE_PATTERN.sub(_replace, value)
    return value


def _lookup_arg(path: str, args: dict[str, Any]) -> Any:
    """Walk a dotted path into the args dict."""
    current: Any = args
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"Missing arg: $args.{path}")
        current = current[part]
    return current


# --- Single-step execution ------------------------------------------------


async def _call_tool(
    tool_name: str,
    arguments: dict[str, Any],
) -> ToolResponse:
    """Call a registered tool function by name via the current Toolkit.

    Uses ``Toolkit.call_tool_function`` so that ToolGuard interception,
    preset kwargs, postprocess hooks, and group-activity checks all
    apply — the same pipeline as a normal agent tool call.
    """
    toolkit = get_current_toolkit()
    if toolkit is None:
        return _json_tool_response(
            {"ok": False, "error": "No toolkit available in current context"},
        )

    if tool_name not in toolkit.tools:
        return _json_tool_response(
            {
                "ok": False,
                "error": f"Unknown tool: {tool_name}",
                "available": sorted(toolkit.tools.keys()),
            },
        )

    tool_call = {"name": tool_name, "input": arguments}
    try:
        response: ToolResponse | None = None
        async for chunk in await toolkit.call_tool_function(tool_call):
            response = chunk
        if response is None:
            return _json_tool_response(
                {
                    "ok": False,
                    "error": f"Tool {tool_name} returned no response",
                },
            )
        return response
    except Exception as exc:  # pylint: disable=broad-except
        return _json_tool_response(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
        )


# --- Step execution loop --------------------------------------------------


async def _run_steps(  # pylint: disable=too-many-branches
    actions: list[dict[str, Any]],
    stop_on_error: bool = True,
) -> tuple[list[dict[str, Any]], list[Any]]:
    """Execute a list of actions sequentially.

    Returns ``(results, all_content_blocks)`` — the per-step result
    dicts and the accumulated raw content blocks from every step.
    """
    results: list[dict[str, Any]] = []
    all_content_blocks: list[Any] = []

    for index, step in enumerate(actions):
        # --- Validate step structure (always fatal) ---
        if not isinstance(step, dict):
            results.append(
                {
                    "step": index,
                    "ok": False,
                    "error": "step must be an object",
                },
            )
            break

        tool_name = str(
            step.get("tool_name") or step.get("tool") or "",
        ).strip()
        if not tool_name:
            results.append(
                {
                    "step": index,
                    "ok": False,
                    "error": "step must include tool_name",
                },
            )
            break

        # Prevent recursive batch calls.
        if tool_name == "run_tool_batch":
            results.append(
                {
                    "step": index,
                    "tool_name": tool_name,
                    "ok": False,
                    "error": "Recursive run_tool_batch is not allowed",
                },
            )
            break

        arguments = step.get("arguments") or step.get("args") or {}
        if not isinstance(arguments, dict):
            results.append(
                {
                    "step": index,
                    "tool_name": tool_name,
                    "ok": False,
                    "error": "arguments must be an object",
                },
            )
            break

        step_stop = step.get("stop_on_error", stop_on_error)

        # --- Resolve $steps references ---
        try:
            arguments = resolve_step_refs(arguments, results)
        except ValueError as exc:
            results.append(
                {
                    "step": index,
                    "tool_name": tool_name,
                    "ok": False,
                    "error": str(exc),
                },
            )
            if step_stop:
                break
            continue

        # --- Execute ---
        response = await _call_tool(tool_name, arguments)
        result = _response_payload(response)

        step_content = result.pop("_raw_blocks", [])
        all_content_blocks.extend(step_content)

        results.append(
            {"step": index, "tool_name": tool_name, **result},
        )

        if not result.get("ok", True) and step_stop:
            break

        # Optional wait between steps.
        wait = float(step.get("wait") or 0)
        if wait > 0:
            await asyncio.sleep(wait)

    return results, all_content_blocks


def _build_batch_response(
    actions: list[dict[str, Any]],
    results: list[dict[str, Any]],
    all_content_blocks: list[Any],
    *,
    last_only: bool = False,
) -> ToolResponse:
    """Build the final ToolResponse for a batch run."""
    completed = sum(1 for r in results if r.get("ok", False))
    all_ok = completed == len(actions)

    if last_only and results:
        payload = {
            "ok": all_ok,
            "total": len(actions),
            "completed": completed,
            "result": results[-1],
        }
    else:
        payload = {
            "ok": all_ok,
            "total": len(actions),
            "completed": completed,
            "results": results,
        }

    summary = TextBlock(
        type="text",
        text=json.dumps(payload, ensure_ascii=False),
    )
    return ToolResponse(content=[summary, *all_content_blocks])


# --- Main entry point -----------------------------------------------------


async def run_tool_batch(  # pylint: disable=too-many-return-statements
    actions: list[dict[str, Any]] | None = None,
    file_path: str = "",
    args: dict[str, Any] | None = None,
    stop_on_error: bool = True,
    last_only: bool = False,
) -> ToolResponse:
    """Execute a batch of tool calls from a JSON file.

    Load actions from a JSON batch file and execute them sequentially.
    The JSON file should contain an ``actions`` array (or be a plain
    array). Each action object contains:

    - ``tool_name`` (str): Name of a registered tool function.
    - ``arguments`` (dict): Keyword arguments for the tool.
    - ``stop_on_error`` (bool, optional): Override per-step.
    - ``wait`` (float, optional): Seconds to sleep after this step.

    Use ``${args.<name>}`` placeholders in argument values for parts
    that vary at runtime. Use ``${steps.<index>.<path>}`` to reference
    earlier steps' output. The brace-delimited syntax is required so
    that placeholders are unambiguous inside mixed-content strings
    (e.g. shell commands).

    Example::

        run_tool_batch(
            file_path="/absolute/path/to/batch.json",
            args={"file_path": "/app/config.yaml", "pattern": "database"},
        )

    Args:
        file_path: Absolute path to a JSON batch file.
        args: Values to substitute ``${args.<name>}`` placeholders
            in the batch file.
        stop_on_error: Default stop-on-error behaviour for all steps.
        last_only: If true, only return the last step's result instead
            of all steps. Useful when only the final output matters.

    Returns:
        ToolResponse containing a JSON summary TextBlock followed by
        all content blocks collected from each step's ToolResponse
        (ImageBlock, FileBlock, VideoBlock, etc.).
    """
    # --- Resolve actions source ---
    if file_path and actions:
        return _json_tool_response(
            {
                "ok": False,
                "error": "Provide either 'actions' or 'file_path', not both",
            },
        )

    # Coerce args from JSON string if the model serialised it as text.
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return _json_tool_response(
                {
                    "ok": False,
                    "error": "args must be an object or JSON string",
                },
            )
    if args is not None and not isinstance(args, dict):
        return _json_tool_response(
            {"ok": False, "error": "args must be an object"},
        )

    # Coerce actions from JSON string if needed.
    if isinstance(actions, str):
        try:
            actions = json.loads(actions)
        except (json.JSONDecodeError, TypeError):
            pass

    if file_path:
        try:
            actions = _load_batch_file(file_path)
        except ValueError as exc:
            return _json_tool_response({"ok": False, "error": str(exc)})
        # Substitute $args placeholders if provided.
        if args:
            try:
                actions = _resolve_args(actions, args)
            except ValueError as exc:
                return _json_tool_response({"ok": False, "error": str(exc)})

    if not isinstance(actions, list) or not actions:
        return _json_tool_response(
            {
                "ok": False,
                "error": (
                    "actions must be a non-empty list, or provide "
                    "file_path to load from a JSON file"
                ),
            },
        )

    if len(actions) > MAX_BATCH_STEPS:
        return _json_tool_response(
            {
                "ok": False,
                "error": (
                    f"Too many steps ({len(actions)}). "
                    f"Maximum allowed is {MAX_BATCH_STEPS}."
                ),
            },
        )

    # --- Execute ---
    results, all_content_blocks = await _run_steps(actions, stop_on_error)
    return _build_batch_response(
        actions,
        results,
        all_content_blocks,
        last_only=last_only,
    )
