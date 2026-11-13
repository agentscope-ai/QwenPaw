# -*- coding: utf-8 -*-
"""Recover exact legacy boundaries from provider-owned history."""

import json
from importlib import import_module

from ...utils.io_utils import run_sync_io


def _signature(blocks):
    """Compare inputs, final output and ordered tool identities/content."""
    inputs, outputs, tools = [], [], []
    for role, block in blocks:
        kind = block.get("type")
        if kind == "text":
            (inputs if role == "user" else outputs).append(block["text"])
        elif kind == "data":
            data = block.get("data") or {}
            if "arguments" in data:
                arguments = data["arguments"]
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                tools.append((data["call_id"], arguments))
            elif "output" in data:
                tools.append((data["call_id"], data["output"]))
            else:
                return None
        else:
            return None
    if not inputs or not outputs:
        return None
    return inputs, outputs[-1], tools


def recover_qoder_boundaries(catalog, identity):
    """Append only uniquely matched facts; never replay provider context."""
    state = catalog.read_provider_state(**identity)
    binding = state["binding"]
    if not binding or binding.get("provider") != "qoder":
        return
    turns = catalog.read_legacy_turn_blocks(**identity)
    if not turns or all(t in state["boundaries"] for t in turns):
        return
    native = _qoder_lineage(binding["external_session_id"])
    candidates, blocks = [], []
    for message in native:
        if message.parent_tool_use_id:
            continue
        content = message.message.get("content", [])
        if message.type == "user" and isinstance(content, str):
            blocks = [("user", {"type": "text", "text": content})]
            continue
        if not blocks or not isinstance(content, list):
            continue
        for block in content:
            kind = block.get("type")
            if kind == "thinking":
                continue
            if kind == "tool_use":
                block = {
                    "type": "data",
                    "data": {
                        "call_id": block["id"],
                        "arguments": block["input"],
                    },
                }
            elif kind == "tool_result":
                block = {
                    "type": "data",
                    "data": {
                        "call_id": block["tool_use_id"],
                        "output": block.get("content"),
                    },
                }
            blocks.append((message.type, block))
        if message.message.get("stop_reason") == "end_turn":
            candidates.append((_signature(blocks), message.uuid))
            blocks = []
    _record_matches(catalog, identity, state, turns, candidates, "message")


def _qoder_lineage(session_id):
    """Read native ancestry across compaction without changing its context."""
    # Use the installed SDK's path resolution and transcript parser only.
    sdk = import_module("qoder_agent_sdk._internal.sessions")
    if sdk._validate_uuid(session_id) is None:
        raise ValueError("invalid Qoder session ID")
    content = sdk._read_session_file(session_id, None)
    if content is None:
        raise FileNotFoundError("Qoder session history is missing")
    entries = [
        entry
        for entry in sdk._parse_transcript_entries(content)
        if not entry.get("isSidechain") and not entry.get("teamName")
    ]
    ids = {entry["uuid"] for entry in entries}
    for entry in entries:
        if entry.get("subtype") == "compact_boundary":
            parent = entry.get("logicalParentUuid")
            if parent:
                if parent not in ids:
                    raise ValueError("Qoder compaction ancestry is missing")
                entry["parentUuid"] = parent
    return [
        sdk._to_session_message(entry)
        for entry in sdk._build_conversation_chain(entries)
        if entry.get("type") in {"user", "assistant"}
        and not entry.get("isMeta")
        and not entry.get("isCompactSummary")
    ]


def _record_matches(catalog, identity, state, turns, candidates, kind):
    """Persist only unique matches in increasing native history order."""
    binding = state["binding"]
    previous = -1
    matched = []
    for turn_id, local in turns.items():
        inputs = [
            block.get("text", "").strip()
            for role, block in local
            if role == "user" and block.get("type") == "text"
        ]
        if len(inputs) == 1 and inputs[0].split(maxsplit=1)[:1] == [
            "/compact",
        ]:
            continue
        signature = _signature(local)
        matches = [
            i
            for i, (value, _) in enumerate(candidates)
            if signature is not None and value == signature
        ]
        if len(matches) != 1 or matches[0] <= previous:
            continue
        previous = matches[0]
        matched.append((turn_id, candidates[previous][1]))
    for turn_id, boundary_id in matched:
        if turn_id not in state["boundaries"]:
            catalog.record_provider_fact(
                **identity,
                kind="turn_boundary",
                turn_id=turn_id,
                data={
                    **binding,
                    "boundary_kind": kind,
                    "boundary_id": boundary_id,
                },
            )


async def recover_codex_boundaries(catalog, identity, backend_runtime):
    """Match full native turns without resuming or replaying a thread."""
    state = await run_sync_io(catalog.read_provider_state, **identity)
    binding = state["binding"]
    if not binding or binding.get("provider") != "codex":
        return
    turns = await run_sync_io(catalog.read_legacy_turn_blocks, **identity)
    if not turns or all(t in state["boundaries"] for t in turns):
        return
    native_turns = await backend_runtime.call(
        "codex",
        "turn_history",
        **identity,
        external_session_id=binding["external_session_id"],
    )
    candidates = []
    for turn_id, history in native_turns:
        blocks = []
        for entry in history:
            kind = entry.kind.value
            if kind in {"reasoning", "tool_call", "tool_output"}:
                continue
            role = "user" if kind == "user" else "assistant"
            blocks.append((role, {"type": "text", "text": entry.text}))
        candidates.append((_signature(blocks), turn_id))
    # Native thread/read omits stored tools; match unique text boundaries.
    text_turns = {
        turn_id: [
            (role, block)
            for role, block in blocks
            if block.get("type") == "text"
        ]
        for turn_id, blocks in turns.items()
    }
    await run_sync_io(
        _record_matches,
        catalog,
        identity,
        state,
        text_turns,
        candidates,
        "turn",
    )
