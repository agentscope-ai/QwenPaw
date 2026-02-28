# -*- coding: utf-8 -*-
"""Tool message validation and sanitization utilities.

This module ensures tool_use and tool_result messages are properly
paired and ordered to prevent API errors.
"""
import json
import logging

logger = logging.getLogger(__name__)


def extract_tool_ids(msg) -> tuple[set[str], set[str]]:
    """Return (tool_use_ids, tool_result_ids) found in a single message.

    Args:
        msg: A Msg object whose content may contain tool blocks.

    Returns:
        A tuple of two sets: (tool_use IDs, tool_result IDs).
    """
    uses: set[str] = set()
    results: set[str] = set()
    if isinstance(msg.content, list):
        for block in msg.content:
            if isinstance(block, dict) and block.get("id"):
                btype = block.get("type")
                if btype == "tool_use":
                    uses.add(block["id"])
                elif btype == "tool_result":
                    results.add(block["id"])
    return uses, results


def check_valid_messages(messages: list) -> bool:
    """
    Check if the messages are valid by ensuring all tool_use blocks have
    corresponding tool_result blocks.

    Args:
        messages: List of Msg objects to validate.

    Returns:
        bool: True if all tool_use IDs have matching tool_result IDs,
              False otherwise.
    """
    use_ids: set[str] = set()
    result_ids: set[str] = set()
    for msg in messages:
        u, r = extract_tool_ids(msg)
        use_ids |= u
        result_ids |= r
    return use_ids == result_ids


def _reorder_tool_results(msgs: list) -> list:
    """Move tool_result messages right after their corresponding tool_use.

    Handles duplicate tool_call_ids by consuming results FIFO.
    """
    results_by_id: dict[str, list[object]] = {}
    result_msg_ids: set[int] = set()
    for msg in msgs:
        if isinstance(msg.content, list):
            for block in msg.content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_result"
                    and block.get("id")
                ):
                    results_by_id.setdefault(block["id"], []).append(msg)
                    result_msg_ids.add(id(msg))

    consumed: dict[str, int] = {}
    reordered: list = []
    placed: set[int] = set()
    for msg in msgs:
        if id(msg) in result_msg_ids:
            continue
        reordered.append(msg)
        if not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if not (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("id")
            ):
                continue
            bid = block["id"]
            candidates = results_by_id.get(bid, [])
            ci = consumed.get(bid, 0)
            if ci >= len(candidates):
                continue
            rm = candidates[ci]
            consumed[bid] = ci + 1
            if id(rm) not in placed:
                reordered.append(rm)
                placed.add(id(rm))

    return reordered


def _remove_unpaired_tool_messages(msgs: list) -> list:
    """Remove tool_use/tool_result messages that aren't properly paired.

    Each tool_use must be immediately followed by tool_results for all
    its IDs.  Unpaired messages and orphaned results are removed.
    """
    to_remove: set[int] = set()

    i = 0
    while i < len(msgs):
        use_ids, _ = extract_tool_ids(msgs[i])
        if not use_ids:
            i += 1
            continue
        required = set(use_ids)
        j = i + 1
        result_indices: list[int] = []
        while j < len(msgs) and required:
            _, r = extract_tool_ids(msgs[j])
            if not r:
                break
            required -= r
            result_indices.append(j)
            j += 1
        if required:
            to_remove.add(i)
            to_remove.update(result_indices)
            i += 1
        else:
            i = j

    surviving_use_ids: set[str] = set()
    for idx, msg in enumerate(msgs):
        if idx not in to_remove:
            u, _ = extract_tool_ids(msg)
            surviving_use_ids |= u
    for idx, msg in enumerate(msgs):
        if idx in to_remove:
            continue
        _, r = extract_tool_ids(msg)
        if r and not r.issubset(surviving_use_ids):
            to_remove.add(idx)

    return [msg for idx, msg in enumerate(msgs) if idx not in to_remove]


def _dedup_tool_blocks(msgs: list) -> list:
    """Remove duplicate tool_use blocks (same ID) within a single message."""
    changed = False
    result: list = []
    for msg in msgs:
        if not isinstance(msg.content, list):
            result.append(msg)
            continue
        seen_ids: set[str] = set()
        new_blocks: list = []
        deduped = False
        for block in msg.content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("id")
            ):
                if block["id"] in seen_ids:
                    deduped = True
                    continue
                seen_ids.add(block["id"])
            new_blocks.append(block)
        if deduped:
            msg.content = new_blocks
            changed = True
        result.append(msg)
    return result if changed else msgs


def _remove_invalid_tool_blocks(msgs: list) -> list:
    """Remove tool_use/tool_result blocks with invalid id/name.

    A valid tool_use block must have:
    - Non-empty, non-None id
    - Non-empty, non-None name

    A valid tool_result block must have:
    - Non-empty, non-None id

    Args:
        msgs: List of Msg objects to validate.

    Returns:
        List of Msg objects with invalid tool blocks removed.
    """
    changed = False
    result: list = []

    for msg in msgs:
        if not isinstance(msg.content, list):
            result.append(msg)
            continue

        new_blocks: list = []
        removed = False

        for block in msg.content:
            if not isinstance(block, dict):
                new_blocks.append(block)
                continue

            block_type = block.get("type")

            # Validate tool_use and tool_result blocks
            if block_type in ("tool_use", "tool_result"):
                block_id = block.get("id")
                block_name = block.get("name")

                # Check if id is valid (not None, not empty string)
                if not block_id:
                    logger.warning(
                        "Removing %s with invalid id: id=%r, name=%r",
                        block_type,
                        block_id,
                        block_name,
                    )
                    removed = True
                    continue

                # For tool_use, also check name is non-empty
                if block_type == "tool_use" and not block_name:
                    logger.warning(
                        "Removing tool_use with invalid name: id=%r, name=%r",
                        block_id,
                        block_name,
                    )
                    removed = True
                    continue

            new_blocks.append(block)

        if removed:
            msg.content = new_blocks
            changed = True

        result.append(msg)

    return result if changed else msgs


def _repair_empty_tool_inputs(
    msgs: list,
) -> list:
    """Repair tool_use blocks with empty input but valid raw_input.

    This fixes a bug in AgentScope 1.0.16dev where stream_tool_parsing
    may fail to parse arguments correctly, leaving input={} while
    raw_input contains valid JSON.

    Args:
        msgs: List of Msg objects to repair.

    Returns:
        List of Msg objects with repaired tool_use blocks.
    """
    # pylint: disable=too-many-nested-blocks
    changed = False
    result: list = []

    for msg in msgs:
        if not isinstance(msg.content, list):
            result.append(msg)
            continue

        new_blocks: list = []
        repaired = False

        for block in msg.content:
            if not isinstance(block, dict):
                new_blocks.append(block)
                continue

            # Check if this is a tool_use with empty input but valid raw_input
            if block.get("type") == "tool_use":
                input_field = block.get("input", {})
                raw_input = block.get("raw_input", "")

                # If input is empty but raw_input has content, try to parse
                if not input_field and raw_input and raw_input != "{}":
                    try:
                        parsed = json.loads(raw_input)
                        if isinstance(parsed, dict) and parsed:
                            # Success! Update the input field
                            block["input"] = parsed
                            repaired = True
                            logger.info(
                                "Repaired tool_use input from raw_input: "
                                "id=%s, name=%s, keys=%s",
                                block.get("id"),
                                block.get("name"),
                                list(parsed.keys()),
                            )
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(
                            "Failed to repair tool_use input from raw_input: "
                            "id=%s, name=%s, error=%s",
                            block.get("id"),
                            block.get("name"),
                            e,
                        )

            new_blocks.append(block)

        if repaired:
            msg.content = new_blocks
            changed = True

        result.append(msg)

    return result if changed else msgs


def _sanitize_tool_messages(msgs: list) -> list:
    """Ensure tool_use/tool_result messages are properly paired and ordered.

    Returns the original list unchanged if no fix is needed.
    """
    # First, repair tool_use blocks with empty input but valid raw_input
    msgs = _repair_empty_tool_inputs(msgs)
    # Then, remove invalid tool blocks (empty id, None name, etc.)
    msgs = _remove_invalid_tool_blocks(msgs)
    # Finally, remove duplicate tool blocks
    msgs = _dedup_tool_blocks(msgs)

    pending: dict[str, int] = {}
    needs_fix = False
    for msg in msgs:
        msg_uses, msg_results = extract_tool_ids(msg)
        for rid in msg_results:
            if pending.get(rid, 0) <= 0:
                needs_fix = True
                break
            pending[rid] -= 1
            if pending[rid] == 0:
                del pending[rid]
        if needs_fix:
            break
        if pending and not msg_results:
            needs_fix = True
            break
        for uid in msg_uses:
            pending[uid] = pending.get(uid, 0) + 1
    if not needs_fix and not pending:
        return msgs

    logger.debug("Sanitizing tool messages: fixing order/pairing issues")
    return _remove_unpaired_tool_messages(_reorder_tool_results(msgs))


def _truncate_text(text: str, max_length: int) -> str:
    """Truncate text to max length, keeping head and tail portions.

    Args:
        text: The text to truncate
        max_length: Maximum allowed length

    Returns:
        Truncated text with middle replaced by [...truncated...]
    """
    text = str(text) if text else ""
    if not text:
        return text

    if len(text) <= max_length:
        return text

    half_length = max_length // 2
    truncated_chars = len(text) - max_length
    logger.info(
        "Text truncated: original %d chars, kept head %d + tail %d, "
        "removed %d chars.",
        len(text),
        half_length,
        half_length,
        truncated_chars,
    )
    return (
        f"{text[:half_length]}\n\n[...truncated {truncated_chars} "
        f"chars...]\n\n{text[-half_length:]}"
    )
