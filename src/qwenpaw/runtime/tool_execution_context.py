"""Read-only tool observations derived from the retained, persisted history.

No execution cache is maintained: reloads and history edits use the same source
of truth. Missing or ambiguous evidence never becomes a successful receipt.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from agentscope.message import Msg, ToolCallBlock, ToolResultBlock

from .reply_cycle import reply_block_metadata

_DETAIL_LIMIT = 2048
_STEPS_LIMIT = 32
_TOTAL_LIMIT = 16384


def _owner(message: Msg, block: Any) -> tuple[str, tuple[str, ...]] | None:
    # Message-level ownership can change while earlier tools are still running.
    # Never use it to attribute an old block to the latest input.
    metadata = reply_block_metadata(message, block)
    run = metadata.get("run_id")
    inputs = metadata.get("responds_to_input_ids")
    if not isinstance(run, str) or not run or not isinstance(inputs, list):
        return None
    if not inputs or any(not isinstance(i, str) or not i for i in inputs):
        return None
    return run, tuple(inputs)


def _details(step: dict, call: ToolCallBlock, result: Any) -> None:
    if len(call.input) <= _DETAIL_LIMIT:
        try:
            step["arguments"] = json.loads(call.input)
        except (ValueError, TypeError):
            step["arguments_text"] = call.input
    else:
        step["arguments_excerpt"] = call.input[:_DETAIL_LIMIT]
        step["arguments_truncated"] = True
    if result is None:
        return
    output = result.output
    text = (
        output
        if isinstance(output, str)
        else "\n".join(b.text for b in output if b.type == "text")
    )
    step["result"] = text[:_DETAIL_LIMIT]
    step["result_truncated"] = len(text) > _DETAIL_LIMIT
    step["nontext_result_omitted"] = not isinstance(output, str) and any(
        b.type != "text" for b in output
    )


def project_tool_execution_context(
    messages: list[Msg], active_input_ids: tuple[str, ...]
) -> dict[str, Any]:
    """Associate observations by run, call ID, name, order and block ownership.

    The scope is retained model history, not all actions ever executed. Prefer
    current-input observations within the bounded view, then recent old ones
    (which remain useful when the user explicitly requests a repeat).
    """
    calls: dict[tuple[str, str], list] = defaultdict(list)
    results: dict[tuple[str, str], list] = defaultdict(list)
    unassociated = 0
    for mi, message in enumerate(messages):
        if message.role != "assistant":
            continue
        for bi, block in enumerate(message.content):
            if not isinstance(block, (ToolCallBlock, ToolResultBlock)):
                continue
            owner = _owner(message, block)
            if owner is None:
                unassociated += 1
                continue
            target = calls if isinstance(block, ToolCallBlock) else results
            target[owner[0], block.id].append(((mi, bi), block, owner[1]))

    observations = []
    ambiguous = 0
    for key, entries in calls.items():
        outputs = results.get(key, [])
        if len(entries) != 1 or len(outputs) > 1:
            ambiguous += 1
            continue
        position, call, inputs = entries[0]
        result = None
        if outputs:
            result_position, result, result_inputs = outputs[0]
            if (
                result_position <= position
                or result.name != call.name
                or result_inputs != inputs
            ):
                ambiguous += 1
                continue
        state = str(result.state) if result is not None else "unknown"
        step = {
            "source": (
                "recorded_tool_call_and_result"
                if result is not None
                else "recorded_tool_call"
            ),
            "run_id": key[0],
            "input_ids": list(inputs),
            "tool_call_id": call.id,
            "tool_name": call.name,
            "execution_status": state,
            "succeeded": (
                True
                if state == "success"
                else (
                    False
                    if state in {"error", "denied", "interrupted"}
                    else None
                )
            ),
        }
        _details(step, call, result)
        observations.append((position, step))

    active = set(active_input_ids)
    observations.sort(
        key=lambda row: (
            bool(active.intersection(row[1]["input_ids"])),
            row[0],
        ),
        reverse=True,
    )
    selected = []
    used = 0
    for position, step in observations:
        size = len(json.dumps(step, ensure_ascii=False))
        if len(selected) < _STEPS_LIMIT and used + size <= _TOTAL_LIMIT:
            selected.append((position, step))
            used += size
    selected.sort(key=lambda row: row[0])
    return {
        "observed_tool_steps": [step for _, step in selected],
        "tool_step_coverage": {
            "scope": "retained_model_history",
            "included_steps": len(selected),
            "omitted_steps": len(observations) - len(selected),
            "ambiguous_calls": ambiguous,
            "unassociated_blocks": unassociated,
            "results_without_calls": sum(
                len(rows) for key, rows in results.items() if key not in calls
            ),
        },
    }
