# -*- coding: utf-8 -*-
"""Run a batch of tool calls with action-result references and control flow."""

from __future__ import annotations

import asyncio
import ast
import json
import logging
import operator
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agentscope.message import TextBlock
from agentscope.message import ToolResultState
from agentscope.tool import ToolChunk

from ...config.context import get_current_agent_state, get_current_toolkit
from ...runtime.tool_registry import tool_descriptor

logger = logging.getLogger(__name__)

# Maximum number of steps allowed in a single batch.
MAX_BATCH_STEPS = 50
DEFAULT_MAX_EXECUTION_STEPS = 500

# --- Step-reference patterns -----------------------------------------------
# Only the brace-delimited form ${steps.N.path} is recognised.  This avoids
# ambiguity when $-prefixed text appears inside shell commands or other
# mixed-content strings.  N is the action index; in loops, it resolves to that
# action's latest execution result.

_STEP_REF_PATTERN = re.compile(
    r"^\$\{steps\.(\d+)(?:\.([A-Za-z0-9_.-]+))?\}$",
)
_STEP_REF_INLINE_PATTERN = re.compile(
    r"\$\{steps\.(\d+)(?:\.([A-Za-z0-9_.-]+))?\}",
)
_VAR_REF_PATTERN = re.compile(r"^\$\{vars\.([A-Za-z0-9_.-]+)\}$")
_VAR_REF_INLINE_PATTERN = re.compile(r"\$\{vars\.([A-Za-z0-9_.-]+)\}")
_SIMPLE_ASSIGN_PATTERN = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$",
)
_VAR_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_COMPARE_PATTERN = re.compile(r"^(.*?)\s*(==|!=|<=|>=|<|>)\s*(.*?)$")
_Number = int | float
_COMPARE_OPERATORS = {
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    ">": operator.gt,
    "<=": operator.le,
    ">=": operator.ge,
}
_ARITHMETIC_BIN_OPERATORS: dict[
    type[ast.operator],
    Callable[[_Number, _Number], _Number],
] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}
_ARITHMETIC_UNARY_OPERATORS: dict[
    type[ast.unaryop],
    Callable[[_Number], _Number],
] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_ARITHMETIC_TRIGGER_PATTERN = re.compile(r"[+\-*/%()]")
_ARITHMETIC_EXPR_CHARS_PATTERN = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*$|^[A-Za-z0-9_\s.+\-*/%()]+$",
)


# --- Helpers --------------------------------------------------------------


def _json_tool_response(payload: dict[str, Any]) -> ToolChunk:
    """Wrap a JSON-serialisable dict in a single-TextBlock ToolChunk."""
    ok = payload.get("ok", True)
    return ToolChunk(
        state=ToolResultState.SUCCESS if ok else ToolResultState.ERROR,
        content=[
            TextBlock(
                type="text",
                text=json.dumps(payload, ensure_ascii=False),
            ),
        ],
    )


def _extract_text(response: ToolChunk) -> str:
    """Extract text from the first TextBlock in a ToolChunk.

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


def _extract_files_info(blocks: list[Any]) -> list[dict[str, str]]:
    """Extract file URL/name from DataBlocks for the step result."""
    files: list[dict[str, str]] = []
    for block in blocks:
        if isinstance(block, dict):
            btype = block.get("type", "")
            source = block.get("source")
            name = block.get("name", "")
        else:
            btype = getattr(block, "type", "")
            source = getattr(block, "source", None)
            name = getattr(block, "name", "")
        if btype != "data" or source is None:
            continue
        if isinstance(source, dict):
            url = source.get("url", "")
        else:
            url = getattr(source, "url", "")
        if url:
            files.append({"url": str(url), "name": str(name) or ""})
    return files


def _response_payload(response: ToolChunk) -> dict[str, Any]:
    """Convert a ToolChunk into a normalised result dict.

    The ``ok`` field is inferred from:
    - The response ``state`` (ERROR / DENIED → not ok).
    - JSON responses with an explicit ``ok`` field (``browser_use``,
      ``desktop_screenshot``).
    - Plain-text error prefixes (``Error:``, ``Command failed``).
    - Exceptions caught in ``_call_tool`` (already ``ok: False``).

    The original content blocks are preserved under ``_raw_blocks``
    (an internal key that avoids colliding with tool payloads that
    contain their own ``content`` field).
    """
    resp_state = getattr(response, "state", None)
    is_error_state = resp_state in (
        ToolResultState.ERROR,
        ToolResultState.DENIED,
    )

    text = _extract_text(response)
    content = list(response.content or [])

    # Try JSON first — some tools return structured JSON with ``ok``.
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            if "ok" not in payload:
                payload["ok"] = not is_error_state and "error" not in payload
            elif is_error_state:
                payload["ok"] = False
            payload["_raw_blocks"] = content
            return payload
        return {
            "ok": not is_error_state,
            "value": payload,
            "_raw_blocks": content,
        }
    except (json.JSONDecodeError, TypeError):
        pass

    # Plain-text response — check state and known error patterns.
    if is_error_state or _is_error_text(text):
        return {"ok": False, "error": text, "_raw_blocks": content}
    return {"ok": True, "text": text, "_raw_blocks": content}


# --- Step-reference resolution --------------------------------------------


def resolve_step_refs(
    value: Any,
    results: list[dict[str, Any]],
    variables: dict[str, Any] | None = None,
) -> Any:
    """Recursively resolve ``${steps...}`` and ``${vars...}`` references."""
    if isinstance(value, dict):
        return {
            key: resolve_step_refs(item, results, variables)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [resolve_step_refs(item, results, variables) for item in value]
    if isinstance(value, str):
        return _resolve_ref_string(value, results, variables or {})
    return value


def _resolve_ref_string(
    value: str,
    results: list[dict[str, Any]],
    variables: dict[str, Any],
) -> Any:
    """Resolve ``${steps...}`` and ``${vars...}`` placeholders in a string."""
    # Exact match – return the raw resolved value (preserves type).
    match = _STEP_REF_PATTERN.match(value)
    if match:
        return _lookup_step_ref(
            match.group(1),
            match.group(2),
            results,
            value,
        )

    var_match = _VAR_REF_PATTERN.match(value)
    if var_match:
        return _lookup_var(var_match.group(1), variables, value)

    def _replace_step(match_obj: re.Match[str]) -> str:
        resolved = _lookup_step_ref(
            match_obj.group(1),
            match_obj.group(2),
            results,
            value,
        )
        return _stringify_resolved_value(resolved)

    def _replace_var(match_obj: re.Match[str]) -> str:
        resolved = _lookup_var(match_obj.group(1), variables, value)
        return _stringify_resolved_value(resolved)

    value = _STEP_REF_INLINE_PATTERN.sub(_replace_step, value)
    return _VAR_REF_INLINE_PATTERN.sub(_replace_var, value)


def _lookup_step_ref(
    step_index_text: str,
    path: str | None,
    results: list[dict[str, Any]],
    original: str,
) -> Any:
    """Look up the latest result for one action-index reference."""
    step_index = int(step_index_text)
    current: Any = next(
        (
            result
            for result in reversed(results)
            if result.get("step") == step_index
        ),
        None,
    )
    if current is None:
        raise ValueError(f"Step reference has no result: {original}")
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


def _stringify_resolved_value(resolved: Any) -> str:
    """Convert a resolved placeholder value into inline string form."""
    return (
        resolved
        if isinstance(resolved, str)
        else json.dumps(
            resolved,
            ensure_ascii=False,
        )
    )


def _lookup_var(
    path: str,
    variables: dict[str, Any],
    original: str,
) -> Any:
    """Look up one runtime variable reference."""
    current: Any = variables
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"Missing var reference: {original}")
        current = current[part]
    return current


def _build_label_map(actions: list[dict[str, Any]]) -> dict[str, int]:
    """Collect label targets and validate duplicates."""
    labels: dict[str, int] = {}
    for index, step in enumerate(actions):
        if not isinstance(step, dict):
            continue
        tool_name = str(
            step.get("tool_name") or step.get("tool") or "",
        ).strip()
        if tool_name != "label":
            continue
        arguments = step.get("arguments") or step.get("args") or {}
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        name = str(arguments.get("name") or "").strip()
        if not name:
            raise ValueError("label step requires arguments.name")
        if name in labels:
            raise ValueError(f"Duplicate label: {name}")
        labels[name] = index
    return labels


def _parse_scalar(value: Any) -> Any:
    """Parse simple bool/int string values while preserving other values."""
    if not isinstance(value, str):
        return value
    text = value.strip()
    lower = text.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return text


def _resolve_token(
    token: str,
    results: list[dict[str, Any]],
    variables: dict[str, Any],
) -> Any:
    """Resolve one expression token from vars, steps, or scalar literals."""
    stripped = token.strip()
    if not stripped:
        raise ValueError("expression is invalid")
    if _VAR_NAME_PATTERN.fullmatch(stripped):
        if stripped in variables:
            return variables[stripped]
        parsed = _parse_scalar(stripped)
        if parsed != stripped:
            return parsed
        raise ValueError(f"Undefined variable: {stripped}")
    resolved = _resolve_ref_string(stripped, results, variables)
    return _parse_scalar(resolved)


def _coerce_bool(value: Any, original: str) -> bool:
    """Convert one resolved condition value into a boolean."""
    value = _parse_scalar(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    raise ValueError(f"Unsupported condition: {original}")


def _evaluate_condition(
    condition: str,
    results: list[dict[str, Any]],
    variables: dict[str, Any],
) -> bool:
    """Evaluate a simple goto condition without eval/exec."""
    text = condition.strip()
    match = _COMPARE_PATTERN.match(text)
    if not match:
        return _coerce_bool(
            _resolve_token(text, results, variables),
            condition,
        )

    left = _resolve_token(match.group(1), results, variables)
    right = _resolve_token(match.group(3), results, variables)
    try:
        return _COMPARE_OPERATORS[match.group(2)](left, right)
    except TypeError as exc:
        raise ValueError(f"Unsupported condition: {condition}") from exc


def _evaluate_arithmetic_expr(
    expr: str,
    variables: dict[str, Any],
) -> int | float:
    """Evaluate a restricted numeric expression without eval/exec."""

    def _eval_node(node: ast.AST) -> int | float:
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError("unknown variable in arithmetic")
            value = variables[node.id]
            if isinstance(value, bool) or not isinstance(value, int | float):
                raise ValueError("arithmetic variables must be numeric")
            return value
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                raise ValueError("boolean is not supported in arithmetic")
            if isinstance(node.value, int | float):
                return node.value
            raise ValueError("only numeric literals are supported")
        if isinstance(node, ast.BinOp):
            bin_op_func = _ARITHMETIC_BIN_OPERATORS.get(type(node.op))
            if bin_op_func is None:
                raise ValueError("unsupported arithmetic operator")
            return bin_op_func(_eval_node(node.left), _eval_node(node.right))
        if isinstance(node, ast.UnaryOp):
            unary_op_func = _ARITHMETIC_UNARY_OPERATORS.get(type(node.op))
            if unary_op_func is None:
                raise ValueError("unsupported arithmetic operator")
            return unary_op_func(_eval_node(node.operand))
        raise ValueError("unsupported arithmetic expression")

    try:
        tree = ast.parse(expr, mode="eval")
        return _eval_node(tree)
    except ZeroDivisionError as exc:
        raise ValueError("division by zero in set_var expression") from exc
    except (SyntaxError, ValueError) as exc:
        raise ValueError(
            "set_var requires a valid numeric expression",
        ) from exc


def _evaluate_set_var_expr(
    expr: str,
    results: list[dict[str, Any]],
    variables: dict[str, Any],
) -> tuple[str, Any]:
    """Evaluate a simple set_var assignment expression."""
    match = _SIMPLE_ASSIGN_PATTERN.match(expr or "")
    if not match:
        raise ValueError("set_var requires a simple assignment expression")

    name = match.group(1)
    rhs = match.group(2).strip()
    resolved = _resolve_ref_string(rhs, results, variables)
    if not isinstance(resolved, str):
        return name, resolved

    resolved = resolved.strip()
    parsed = _parse_scalar(resolved)
    if not isinstance(parsed, str):
        return name, parsed
    if _STEP_REF_PATTERN.match(rhs) or _VAR_REF_PATTERN.match(rhs):
        return name, resolved
    if not _ARITHMETIC_TRIGGER_PATTERN.search(resolved):
        return name, _resolve_token(resolved, results, variables)
    if not _ARITHMETIC_EXPR_CHARS_PATTERN.fullmatch(resolved):
        return name, resolved
    return name, _evaluate_arithmetic_expr(resolved, variables)


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
) -> ToolChunk:
    """Call a registered tool function by name via the current Toolkit.

    Uses ``Toolkit.call_tool`` so that permission checking (including
    ``PolicyGuardedTool.check_permissions``), tool-group activation
    guards, and state injection all apply — the same pipeline as a
    normal agent tool call.
    """
    from agentscope.message import ToolCallBlock

    toolkit = get_current_toolkit()
    if toolkit is None:
        return _json_tool_response(
            {"ok": False, "error": "No toolkit available in current context"},
        )

    agent_state = get_current_agent_state()
    if agent_state is None:
        return _json_tool_response(
            {
                "ok": False,
                "error": "No agent state available in current context",
            },
        )

    tool_call = ToolCallBlock(
        id=f"batch_{uuid.uuid4().hex[:8]}",
        name=tool_name,
        input=json.dumps(arguments, ensure_ascii=False),
    )

    tool_stream = None
    try:
        response: ToolChunk | None = None
        tool_stream = toolkit.call_tool(tool_call, agent_state)
        async for chunk in tool_stream:
            response = chunk
            # An INTERRUPTED chunk is terminal: keep it as the response and
            # stop consuming so a later chunk can't overwrite the signal.
            # (Post-loop callers detect interruption via ``response.state``.)
            if getattr(chunk, "state", None) == ToolResultState.INTERRUPTED:
                break
        if response is None:
            return _json_tool_response(
                {
                    "ok": False,
                    "error": f"Tool {tool_name} returned no response",
                },
            )
        return response
    except asyncio.CancelledError:
        if tool_stream is not None:
            await tool_stream.aclose()
        raise
    except Exception as exc:  # pylint: disable=broad-except
        return _json_tool_response(
            {"ok": False, "error": f"{type(exc).__name__}: {exc}"},
        )


async def _wait_after_step(step: dict[str, Any]) -> None:
    """Apply an action's optional post-step wait."""
    wait = float(step.get("wait") or 0)
    if wait > 0:
        await asyncio.sleep(wait)


def _step_error(
    step: int | None,
    error: str,
    tool_name: str | None = None,
) -> dict[str, Any]:
    """Build a standard per-step error result."""
    result: dict[str, Any] = {"ok": False, "error": error}
    if step is not None:
        result["step"] = step
    if tool_name:
        result["tool_name"] = tool_name
    return result


async def _append_error_and_should_stop(
    results: list[dict[str, Any]],
    error: dict[str, Any],
    step: dict[str, Any],
    stop: bool,
) -> bool:
    """Append an error and return whether execution should stop."""
    results.append(error)
    if stop:
        return True
    await _wait_after_step(step)
    return False


# --- Step execution loop --------------------------------------------------


async def _run_steps(  # pylint: disable=too-many-branches,too-many-statements
    actions: list[dict[str, Any]],
    stop_on_error: bool = True,
    maxstep: int = DEFAULT_MAX_EXECUTION_STEPS,
) -> tuple[list[dict[str, Any]], list[Any], list[Any] | None]:
    """Execute a list of actions with simple control flow support."""
    results: list[dict[str, Any]] = []
    all_content_blocks: list[Any] = []
    last_text_block: Any | None = None
    variables: dict[str, Any] = {}

    try:
        label_map = _build_label_map(actions)
    except ValueError as exc:
        return [{"ok": False, "error": str(exc)}], [], None

    pc = 0
    execution_count = 0

    while pc < len(actions):
        execution_count += 1
        if execution_count > maxstep:
            results.append(
                _step_error(
                    pc,
                    f"Exceeded maximum execution steps ({maxstep})",
                ),
            )
            break

        index = pc
        step = actions[index]

        if not isinstance(step, dict):
            results.append(_step_error(index, "step must be an object"))
            break

        last_text_block = None

        tool_name = str(
            step.get("tool_name") or step.get("tool") or "",
        ).strip()
        if not tool_name:
            results.append(_step_error(index, "step must include tool_name"))
            break

        if tool_name == "run_tool_batch":
            results.append(
                _step_error(
                    index,
                    "Recursive run_tool_batch is not allowed",
                    tool_name,
                ),
            )
            break

        arguments = step.get("arguments") or step.get("args") or {}
        if not isinstance(arguments, dict):
            results.append(
                _step_error(index, "arguments must be an object", tool_name),
            )
            break

        step_stop = step.get("stop_on_error", stop_on_error)

        if tool_name != "set_var":
            try:
                arguments = resolve_step_refs(arguments, results, variables)
            except ValueError as exc:
                if await _append_error_and_should_stop(
                    results,
                    _step_error(index, str(exc), tool_name),
                    step,
                    step_stop,
                ):
                    break
                pc += 1
                continue

        if tool_name == "label":
            name = str(arguments.get("name") or "").strip()
            if not name:
                results.append(
                    _step_error(
                        index,
                        "label step requires arguments.name",
                        tool_name,
                    ),
                )
                break
            results.append(
                {
                    "step": index,
                    "tool_name": tool_name,
                    "ok": True,
                    "label": name,
                },
            )
            await _wait_after_step(step)
            pc += 1
            continue

        if tool_name == "goto":
            label = str(arguments.get("label") or "").strip()
            if not label:
                results.append(
                    _step_error(
                        index,
                        "goto step requires arguments.label",
                        tool_name,
                    ),
                )
                break
            if label not in label_map:
                results.append(
                    _step_error(index, f"Unknown label: {label}", tool_name),
                )
                break
            condition = arguments.get("condition")
            try:
                should_jump = (
                    True
                    if condition in (None, "")
                    else _evaluate_condition(
                        str(condition),
                        results,
                        variables,
                    )
                )
            except ValueError as exc:
                if await _append_error_and_should_stop(
                    results,
                    _step_error(index, str(exc), tool_name),
                    step,
                    step_stop,
                ):
                    break
                pc += 1
                continue
            results.append(
                {
                    "step": index,
                    "tool_name": tool_name,
                    "ok": True,
                    "label": label,
                    "jumped": should_jump,
                },
            )
            await _wait_after_step(step)
            pc = label_map[label] if should_jump else pc + 1
            continue

        if tool_name == "set_var":
            expr = str(arguments.get("expr") or "").strip()
            if not expr:
                results.append(
                    _step_error(
                        index,
                        "set_var step requires arguments.expr",
                        tool_name,
                    ),
                )
                break
            try:
                var_name, var_value = _evaluate_set_var_expr(
                    expr,
                    results,
                    variables,
                )
            except ValueError as exc:
                if await _append_error_and_should_stop(
                    results,
                    _step_error(index, str(exc), tool_name),
                    step,
                    step_stop,
                ):
                    break
                pc += 1
                continue
            variables[var_name] = var_value
            results.append(
                {
                    "step": index,
                    "tool_name": tool_name,
                    "ok": True,
                    "name": var_name,
                    "value": var_value,
                },
            )
            await _wait_after_step(step)
            pc += 1
            continue

        response = await _call_tool(tool_name, arguments)
        if getattr(response, "state", None) == ToolResultState.INTERRUPTED:
            break
        result = _response_payload(response)

        step_content = result.pop("_raw_blocks", [])
        non_text_blocks: list[Any] = []
        current_text_block: Any | None = None
        for block in step_content:
            block_type = (
                block.get("type", "")
                if isinstance(block, dict)
                else getattr(block, "type", "")
            )
            if block_type == "text" and current_text_block is None:
                current_text_block = block
            else:
                non_text_blocks.append(block)

        last_text_block = current_text_block
        all_content_blocks.extend(non_text_blocks)

        files_info = _extract_files_info(non_text_blocks)
        if files_info:
            result["files"] = files_info

        results.append(
            {"step": index, "tool_name": tool_name, **result},
        )

        if not result.get("ok", True) and step_stop:
            break

        await _wait_after_step(step)

        pc += 1

    return results, all_content_blocks, last_text_block


def _build_batch_response(
    actions: list[dict[str, Any]],
    results: list[dict[str, Any]],
    all_content_blocks: list[Any],
    *,
    last_only: bool = False,
    last_text_block: Any | None = None,
) -> ToolChunk:
    """Build the final ToolChunk for a batch run."""
    completed = sum(1 for r in results if r.get("ok", False))
    failed = next((r for r in results if not r.get("ok", False)), None)
    all_ok = failed is None and completed == len(results)

    if last_only and results:
        payload = {
            "ok": all_ok,
            "total": len(actions),
            "completed": completed,
            "last_step_result": results[-1],
        }
    else:
        payload = {
            "ok": all_ok,
            "total": len(actions),
            "completed": completed,
            "results": results,
        }

    if failed and "error" in failed:
        payload["error"] = failed["error"]

    state = ToolResultState.SUCCESS if all_ok else ToolResultState.ERROR
    summary = TextBlock(
        type="text",
        text=json.dumps(payload, ensure_ascii=False, default=str),
    )
    if not last_only:
        return ToolChunk(
            state=state,
            content=[summary, *all_content_blocks],
        )

    content: list[Any] = [summary]
    if _should_include_last_text_block(last_text_block, results):
        content.append(last_text_block)
    content.extend(all_content_blocks)
    return ToolChunk(state=state, content=content)


def _should_include_last_text_block(
    last_text_block: Any | None,
    results: list[dict[str, Any]],
) -> bool:
    if last_text_block is None or not results:
        return False

    last_block_text = _block_text(last_text_block)
    if not isinstance(last_block_text, str):
        return False

    return not _last_step_result_contains_text(results[-1], last_block_text)


def _block_text(block: Any) -> Any:
    return (
        block.get("text")
        if isinstance(block, dict)
        else getattr(block, "text", None)
    )


def _last_step_result_contains_text(
    last_step_result: dict[str, Any],
    text: str,
) -> bool:
    if last_step_result.get("text") == text:
        return True

    try:
        parsed_text = json.loads(text)
        if parsed_text == last_step_result.get("value"):
            return True
        return parsed_text == {
            key: value
            for key, value in last_step_result.items()
            if key not in {"step", "tool_name"}
        }
    except (json.JSONDecodeError, TypeError):
        return False


def _prepare_batch_inputs(
    actions: list[dict[str, Any]] | str | None,
    file_path: str,
    args: dict[str, Any] | str | None,
    maxstep: int,
) -> tuple[list[dict[str, Any]], int]:
    if file_path and actions:
        raise ValueError("Provide either 'actions' or 'file_path', not both")

    resolved_args = _coerce_batch_args(args)
    resolved_actions = _coerce_batch_actions(actions)
    if file_path:
        resolved_actions = _load_actions_from_file(file_path, resolved_args)

    return (
        _validate_batch_actions(resolved_actions),
        _validate_maxstep(maxstep),
    )


def _coerce_batch_args(
    args: dict[str, Any] | str | None,
) -> dict[str, Any] | None:
    if isinstance(args, str):
        try:
            resolved_args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("args must be an object or JSON string") from None
    else:
        resolved_args = args

    if resolved_args is not None and not isinstance(resolved_args, dict):
        raise ValueError("args must be an object")
    return resolved_args


def _coerce_batch_actions(
    actions: list[dict[str, Any]] | str | None,
) -> Any:
    if not isinstance(actions, str):
        return actions

    try:
        return json.loads(actions)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("actions string is not valid JSON") from None


def _load_actions_from_file(
    file_path: str,
    args: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    actions = _load_batch_file(file_path)
    if not args:
        return actions

    return _resolve_args(actions, args)


def _validate_batch_actions(actions: Any) -> list[dict[str, Any]]:
    if not isinstance(actions, list) or not actions:
        raise ValueError(
            "actions must be a non-empty list, or provide "
            "file_path to load from a JSON file",
        )

    if len(actions) > MAX_BATCH_STEPS:
        raise ValueError(
            f"Too many steps ({len(actions)}). "
            f"Maximum allowed is {MAX_BATCH_STEPS}.",
        )

    return actions


def _validate_maxstep(maxstep: int) -> int:
    try:
        resolved_maxstep = int(maxstep)
    except (TypeError, ValueError):
        raise ValueError("maxstep must be a positive integer") from None
    if resolved_maxstep <= 0:
        raise ValueError("maxstep must be a positive integer")

    return resolved_maxstep


# --- Main entry point -----------------------------------------------------


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="RunToolBatch",
)
async def run_tool_batch(  # pylint: disable=too-many-return-statements
    actions: list[dict[str, Any]] | str | None = None,
    file_path: str = "",
    args: dict[str, Any] | str | None = None,
    stop_on_error: bool = True,
    last_only: bool = False,
    maxstep: int = DEFAULT_MAX_EXECUTION_STEPS,
) -> ToolChunk:
    """Execute a batch of tool calls from a JSON file.

    Load actions from a JSON batch file and execute them sequentially.
    The JSON file should contain an ``actions`` array (or be a plain
    array). Each action object contains:

    - ``tool_name`` (str): Name of a registered tool function.
      ``run_tool_batch`` also supports these built-in control-flow tools:

      - ``label``
        - ``name`` (str, required): Label name used as a jump target.

      - ``goto``
        - ``label`` (str, required): Target label name.
        - ``condition`` (str, optional): Simple condition expression.
          If omitted or empty, jump unconditionally. Supported forms include
          ``true``, ``false``, ``1>2``, ``i<5``,
          ``${vars.i}<${steps.0.value}``.

      - ``set_var``
        - ``expr`` (str, required): Simple assignment expression used
          to update runtime variables. The right-hand side is intended
          for scalar values and restricted arithmetic expressions only,
          such as ``i=0``, ``i=i+1``, ``i=${vars.i}+1``,
          ``i=(${vars.i}+1)*2``. It is not a general string-templating
          assignment language.

    - ``arguments`` (dict): Keyword arguments for the tool.
    - ``stop_on_error`` (bool, optional): Override per-step.
    - ``wait`` (float, optional): Seconds to sleep after this step.

    Use ``${args.<name>}`` placeholders in argument values for parts
    that vary at runtime. Use ``${steps.<index>.<path>}`` to reference
    an action by its zero-based position in the batch JSON, not by the
    execution count. If a loop jumps back to the same action, that action
    keeps the same ``steps.<index>`` reference; it resolves to that
    action's most recent execution result. Use ``${vars.<name>}`` to
    reference runtime variables created by ``set_var``. The brace-delimited
    syntax is required so that placeholders are unambiguous inside
    mixed-content strings (e.g. shell commands).

    Combine ``set_var``, ``goto``, and ``label`` to build loops — for
    example, iterating over a dynamic list, retrying until a condition
    is met, or coordinating multiple variables in a single pass.

    Once a batch script is stable, set ``last_only=True`` to return only
    the final step's result and reduce token consumption. To make the
    most of this mode, consolidate useful output into a file or place a
    summary step at the end of the actions list.

    Usage::

        run_tool_batch(
            file_path="path/to/example.json",
            args={"folder": "/data/reports"},
            last_only=True,
        )

    Example — find PDFs and send each to the user
    (``path/to/example.json``)::

        {
          "actions": [
            {
              "tool_name": "execute_shell_command",
              "arguments": {
                "command": "find ${args.folder} -name '*.pdf' | sort"
              }
            },
            {
              "tool_name": "execute_shell_command",
              "arguments": {
                "command": "echo '${steps.0.text}' | wc -l | tr -d ' '"
              }
            },
            {"tool_name": "set_var",
             "arguments": {"expr": "total=${steps.1.value}"}},
            {"tool_name": "set_var",
             "arguments": {"expr": "i=1"}},
            {"tool_name": "label",
             "arguments": {"name": "next_pdf"}},
            {
              "tool_name": "execute_shell_command",
              "arguments": {
                "command": "echo '${steps.0.text}' | sed -n '${vars.i}p'"
              }
            },
            {
              "tool_name": "send_file_to_user",
              "arguments": {
                "file_path": "${steps.5.text}"
              }
            },
            {"tool_name": "set_var",
             "arguments": {"expr": "i=${vars.i}+1"}},
            {
              "tool_name": "goto",
              "arguments": {
                "label": "next_pdf",
                "condition": "${vars.i}<=${vars.total}"
              }
            }
          ]
        }

    Args:
        file_path: Absolute path to a JSON batch file.
        args: Values to substitute ``${args.<name>}`` placeholders
            in the batch file.
        stop_on_error: Default stop-on-error behaviour for all steps.
        last_only: If true, return a compact summary with ``ok`` and
            ``last_step_result``, plus non-duplicated last text content
            and all non-text blocks. Use this when the workflow is
            stable to reduce token usage while preserving success/failure
            status.
        maxstep: Maximum number of executed steps after control-flow
            jumps are applied. This prevents infinite loops. Defaults to
            500.

    Returns:
        ToolChunk containing a JSON summary TextBlock followed by
        all content blocks collected from each step's ToolChunk
        (ImageBlock, FileBlock, VideoBlock, etc.).
    """
    try:
        actions, maxstep = _prepare_batch_inputs(
            actions,
            file_path,
            args,
            maxstep,
        )
    except ValueError as exc:
        return _json_tool_response({"ok": False, "error": str(exc)})

    # --- Execute ---
    results, all_content_blocks, last_text_block = await _run_steps(
        actions,
        stop_on_error,
        maxstep=maxstep,
    )
    return _build_batch_response(
        actions,
        results,
        all_content_blocks,
        last_only=last_only,
        last_text_block=last_text_block,
    )
