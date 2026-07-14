# -*- coding: utf-8 -*-
"""Tool message validation and sanitization utilities.

This module ensures tool_call/tool_result messages are properly
paired and ordered to prevent API errors.

Supports both dict blocks (1.x ``type="tool_use"``) and Pydantic
``ToolCallBlock``/``ToolResultBlock`` objects (2.0 ``type="tool_call"``).
"""
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_json_decoder = json.JSONDecoder()

_TOOL_CALL_TYPES = ("tool_use", "tool_call")
_TOOL_RESULT_TYPES = ("tool_result",)


def _block_attr(block: Any, key: str, default: Any = None) -> Any:
    """Read *key* from a dict or Pydantic block."""
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _is_tool_call(block: Any) -> bool:
    return _block_attr(block, "type") in _TOOL_CALL_TYPES


def _is_tool_result(block: Any) -> bool:
    return _block_attr(block, "type") in _TOOL_RESULT_TYPES


def extract_tool_ids(msg) -> tuple[set[str], set[str]]:
    """Return (tool_call_ids, tool_result_ids) found in a single message.

    Args:
        msg: A Msg object whose content may contain tool blocks.

    Returns:
        A tuple of two sets: (tool_call IDs, tool_result IDs).
    """
    uses: set[str] = set()
    results: set[str] = set()
    if isinstance(msg.content, list):
        for block in msg.content:
            bid = _block_attr(block, "id")
            if not bid:
                continue
            if _is_tool_call(block):
                uses.add(bid)
            elif _is_tool_result(block):
                results.add(bid)
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
            # Keep a message that carries its own tool_call in place (e.g. an
            # AgentScope 2.0 self-paired assistant msg
            # [text, tool_call, tool_result]); only standalone tool_result
            # messages are movable. Skipping a self-carrying msg here would
            # drop it, since its own tool_call can never re-insert it.
            has_own_call = any(
                _is_tool_call(block) and _block_attr(block, "id")
                for block in msg.content
            )
            if has_own_call:
                continue
            for block in msg.content:
                if _is_tool_result(block) and _block_attr(block, "id"):
                    results_by_id.setdefault(
                        _block_attr(block, "id"),
                        [],
                    ).append(msg)
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
            if not (_is_tool_call(block) and _block_attr(block, "id")):
                continue
            bid = _block_attr(block, "id")
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
        use_ids, own_results = extract_tool_ids(msgs[i])
        if not use_ids:
            i += 1
            continue
        # A self-paired message satisfies (some of) its own tool_calls with the
        # tool_results in the same message; only the remainder must be covered
        # by following messages.
        required = set(use_ids) - own_results
        j = i + 1
        result_indices: list[int] = []
        while j < len(msgs) and required:
            uj, r = extract_tool_ids(msgs[j])
            if not r:
                break
            # A following message that also carries tool_calls (e.g. another
            # self-paired turn) is not a result-provider for this one; stop
            # rather than consuming it.
            if uj:
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
        u, r = extract_tool_ids(msg)
        # A tool_result is paired if some surviving tool_call uses its id --
        # including a tool_call in the same (self-paired) message.
        if r and not r.issubset(surviving_use_ids | u):
            to_remove.add(idx)

    return [msg for idx, msg in enumerate(msgs) if idx not in to_remove]


def _dedup_tool_blocks(msgs: list) -> list:
    """Remove duplicate tool_use/tool_result blocks sharing the same ID.

    For both tool_call and tool_result blocks, if multiple blocks across
    all messages share the same ID, only the first occurrence is kept.
    Messages whose content becomes empty after dedup are dropped entirely.
    """
    changed = False
    result: list = []
    seen_call_ids: set[str] = set()
    seen_result_ids: set[str] = set()
    for msg in msgs:
        if not isinstance(msg.content, list):
            result.append(msg)
            continue
        new_blocks: list = []
        deduped = False
        for block in msg.content:
            bid = _block_attr(block, "id")
            if bid and _is_tool_call(block):
                if bid in seen_call_ids:
                    logger.debug(
                        "Dropping duplicate tool_call block id=%s",
                        bid,
                    )
                    deduped = True
                    continue
                seen_call_ids.add(bid)
            elif bid and _is_tool_result(block):
                if bid in seen_result_ids:
                    logger.debug(
                        "Dropping duplicate tool_result block id=%s",
                        bid,
                    )
                    deduped = True
                    continue
                seen_result_ids.add(bid)
            new_blocks.append(block)
        if deduped:
            changed = True
            if not new_blocks:
                continue
            msg.content = new_blocks
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
            block_type = _block_attr(block, "type")

            if _is_tool_call(block) or _is_tool_result(block):
                block_id = _block_attr(block, "id")
                block_name = _block_attr(block, "name")

                if not block_id:
                    logger.warning(
                        "Removing %s with invalid id: id=%r, name=%r",
                        block_type,
                        block_id,
                        block_name,
                    )
                    removed = True
                    continue

                if _is_tool_call(block) and not block_name:
                    logger.warning(
                        "Removing %s with invalid name: id=%r, name=%r",
                        block_type,
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
            if _is_tool_call(block):
                input_field = _block_attr(block, "input", {})
                raw_input = _block_attr(block, "raw_input", "")

                if not input_field and raw_input and raw_input != "{}":
                    try:
                        raw_str = (
                            raw_input
                            if isinstance(raw_input, str)
                            else str(raw_input)
                        )
                        try:
                            parsed = json.loads(raw_str)
                        except json.JSONDecodeError:
                            start = json.decoder.WHITESPACE.match(
                                raw_str,
                                0,
                            ).end()
                            parsed, _ = _json_decoder.raw_decode(
                                raw_str,
                                start,
                            )
                        if isinstance(parsed, dict) and parsed:
                            # All agentscope 2.0 formatters expect
                            # ToolCallBlock.input to be a JSON string
                            # (Anthropic/Gemini do json.loads on their side).
                            # Use json.dumps for both dict and Pydantic blocks
                            # so the downstream pipeline is consistent.
                            input_str = json.dumps(parsed, ensure_ascii=False)
                            if isinstance(block, dict):
                                block["input"] = input_str
                            else:
                                block.input = input_str
                            repaired = True
                            logger.info(
                                "Repaired tool input from raw_input: "
                                "id=%s, name=%s, keys=%s",
                                _block_attr(block, "id"),
                                _block_attr(block, "name"),
                                list(parsed.keys()),
                            )
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(
                            "Failed to repair tool input from raw_input: "
                            "id=%s, name=%s, error=%s",
                            _block_attr(block, "id"),
                            _block_attr(block, "name"),
                            e,
                        )

            new_blocks.append(block)

        if repaired:
            msg.content = new_blocks
            changed = True

        result.append(msg)

    return result if changed else msgs


# pylint: disable=too-many-branches
def _coerce_tool_inputs_to_json(msgs: list) -> list:
    """Ensure every tool_call block's ``input`` field is a valid JSON string.

    The DashScope (and other OpenAI-compatible) APIs reject requests where
    ``function.arguments`` is not valid JSON.  This can happen when a
    historical session stored a ``ToolCallBlock`` whose ``input`` field was
    saved as a non-JSON value (e.g. an empty string ``""``, or a bare dict),
    or is missing entirely.

    Coercion rules:
    * Already-valid JSON string → keep as-is.
    * ``dict`` / ``list`` → ``json.dumps``.
    * Empty string ``""`` → ``"{}"`` (treat as no-args call).
    * Non-empty non-JSON string (e.g. truncated streaming artefact) →
      **drop the block** so ``_remove_unpaired_tool_messages`` can clean up
      the orphaned tool_result.  Replacing with ``{}`` would cause the tool
      to be called with wrong/empty arguments, which is worse.
    """
    for msg in msgs:
        if not isinstance(getattr(msg, "content", None), list):
            continue

        new_blocks: list = []
        changed_this_msg = False

        for block in msg.content:
            if not _is_tool_call(block):
                new_blocks.append(block)
                continue

            # Legacy dict blocks go through _coerce_block on load and also
            # always carry "input". Fall back to "" just in case so
            # downstream code stays safe.
            raw = _block_attr(block, "input", "")

            drop_block = False
            coerced_input: str = raw if isinstance(raw, str) else "{}"

            if isinstance(raw, str):
                try:
                    json.loads(raw)
                    coerced_input = raw  # already a valid JSON string
                except (json.JSONDecodeError, ValueError) as exc:
                    if raw == "":
                        coerced_input = "{}"
                    else:
                        # Some models (e.g. DeepSeek-V4-Flash) append garbage
                        # after valid JSON for no-param tool calls: "{
                        # }trailing" json.loads raises "Extra data" but
                        # raw_decode can recover the leading valid object.
                        try:
                            start = json.decoder.WHITESPACE.match(
                                raw,
                                0,
                            ).end()
                            recovered, _ = _json_decoder.raw_decode(
                                raw,
                                start,
                            )
                            if not isinstance(recovered, dict):
                                raise json.JSONDecodeError(
                                    "recovered value is not a JSON object",
                                    raw,
                                    0,
                                ) from exc
                            coerced_input = json.dumps(
                                recovered,
                                ensure_ascii=False,
                            )
                            logger.info(
                                "tool_call input had trailing garbage; "
                                "recovered via raw_decode: id=%r, name=%r",
                                _block_attr(block, "id"),
                                _block_attr(block, "name"),
                            )
                        except (json.JSONDecodeError, ValueError):
                            logger.warning(
                                "tool_call input is not valid JSON; "
                                "dropping block: id=%r, name=%r, "
                                "input_preview=%s",
                                _block_attr(block, "id"),
                                _block_attr(block, "name"),
                                repr(raw[:120]),
                            )
                            drop_block = True
            elif isinstance(raw, (dict, list)):
                coerced_input = json.dumps(raw, ensure_ascii=False)
            else:
                # None / bytes / int / … → treat as empty.
                coerced_input = "{}"

            if drop_block:
                changed_this_msg = True
                continue  # omit from new_blocks

            if coerced_input != raw:
                if isinstance(block, dict):
                    block["input"] = coerced_input
                else:
                    block.input = coerced_input
                changed_this_msg = True

            new_blocks.append(block)

        if changed_this_msg:
            msg.content = new_blocks

    return msgs


def _sanitize_tool_messages(msgs: list) -> list:
    """Ensure tool_use/tool_result messages are properly paired and ordered.

    Returns the original list unchanged if no fix is needed.
    """
    # First, repair tool_use blocks with empty input but valid raw_input
    msgs = _repair_empty_tool_inputs(msgs)
    # Coerce all tool_call input fields to valid JSON strings so that
    # providers (DashScope, OpenAI, etc.) do not reject the request.
    msgs = _coerce_tool_inputs_to_json(msgs)
    # Then, remove invalid tool blocks (empty id, None name, etc.)
    msgs = _remove_invalid_tool_blocks(msgs)
    # Finally, remove duplicate tool blocks
    msgs = _dedup_tool_blocks(msgs)

    pending: dict[str, int] = {}
    needs_fix = False
    for msg in msgs:
        msg_uses, msg_results = extract_tool_ids(msg)
        # Process uses BEFORE results so that intra-message pairs
        # (AgentScope 2.0 style: tool_call + tool_result in the same
        # assistant message) are correctly matched.
        for uid in msg_uses:
            pending[uid] = pending.get(uid, 0) + 1
        for rid in msg_results:
            if pending.get(rid, 0) <= 0:
                needs_fix = True
                break
            pending[rid] -= 1
            if pending[rid] == 0:
                del pending[rid]
        if needs_fix:
            break
        if pending and not msg_results and not msg_uses:
            needs_fix = True
            break
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
