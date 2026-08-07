# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches,too-many-statements
"""Phase 3 hierarchical aggregation (macros → supers → root).

Vendored from Qwen-MM-Plugins commit 077aea6
(src/capabilities/video-memory/skill/script/build_memory/build_graph.py,
Phase 3: ``step3_hierarchical_aggregation`` and helpers). License:
Apache-2.0; see backend/vendor/NOTICE.md.
Modifications: orchestration rewritten as ``async`` around an injected
``call_llm(prompt) -> str`` coroutine (the Creator text/VLM backend);
window/parse/fallback logic kept; prints replaced by logging.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from .json_utils import extract_json
from .prompts import (
    HIERARCHICAL_AGGREGATION_PROMPT,
    HIERARCHICAL_AGGREGATION_WINDOW_PROMPT,
    ROOT_SYNTHESIS_PROMPT,
)
from .schema import (
    MacroEvent,
    MacroRelation,
    SuperEvent,
    SuperRelation,
    VideoRoot,
)
from .time_utils import sec_to_time_str, time_str_to_sec

logger = logging.getLogger("creator.vendor.video_memory")

LlmCall = Callable[[str], Awaitable[str]]

AggregationResult = tuple[
    VideoRoot,
    list[SuperEvent],
    list[MacroRelation],
    list[SuperRelation],
]


def _macro_to_dict(m: MacroEvent) -> dict:
    """Convert a MacroEvent to a dict for prompt serialization."""
    return {
        "macro_id": m.macro_id,
        "label": m.label,
        "time_range": [sec_to_time_str(t) for t in m.time_range],
        "summary": m.summary,
        "key_entities": m.key_entities,
        "event_types": m.event_types,
        "ocr_texts": m.ocr_texts,
    }


def _parse_time_range(tr: list) -> list[float]:
    if not tr:
        return [0, 0]
    result = []
    for t in tr:
        if isinstance(t, (int, float)):
            result.append(float(t))
        elif isinstance(t, str):
            result.append(time_str_to_sec(t))
        else:
            result.append(0)
    return result


def _fallback_aggregation(macros: list[MacroEvent]) -> dict:
    chunk_size = max(1, len(macros) // 10)
    supers = []
    for i in range(0, len(macros), chunk_size):
        chunk = macros[i : i + chunk_size]
        sid = f"super_{i // chunk_size:02d}"
        supers.append(
            {
                "super_id": sid,
                "label": f"Phase {i // chunk_size + 1}",
                "description": ", ".join(m.label for m in chunk),
                "sub_macro_ids": [m.macro_id for m in chunk],
                "time_range": [
                    chunk[0].time_range[0],
                    chunk[-1].time_range[1],
                ],
                "key_entities": [],
            },
        )
    return {
        "super_events": supers,
        "macro_relations": [],
        "super_relations": [],
        "root": {
            "title": "Video Summary",
            "description": f"Video with {len(macros)} macro events",
            "themes": [],
            "key_entities": [],
            "emotional_tone": "",
        },
    }


def _parse_window_result(
    agg: dict,
    macros: list[MacroEvent],
    super_counter: int,
) -> tuple[list[SuperEvent], list[MacroRelation], int]:
    """Parse a window aggregation result into SuperEvents and
    MacroRelations."""
    supers = []
    for se in agg.get("super_events", []):
        sid = f"super_{super_counter:02d}"
        super_counter += 1
        supers.append(
            SuperEvent(
                super_id=sid,
                label=se.get("label", ""),
                description=se.get("description", ""),
                sub_macro_ids=se.get("sub_macro_ids", []),
                time_range=_parse_time_range(se.get("time_range", [])),
                key_entities=se.get("key_entities", []),
            ),
        )
        for mid in se.get("sub_macro_ids", []):
            for m in macros:
                if m.macro_id == mid:
                    m.super_id = sid

    macro_rels = [
        MacroRelation(
            source=r["source"],
            target=r["target"],
            type=r["type"],
            reason=r.get("reason", ""),
        )
        for r in agg.get("macro_relations", [])
    ]
    return supers, macro_rels, super_counter


async def aggregate_hierarchy(
    macros: list[MacroEvent],
    call_llm: LlmCall,
    window_size: int = 20,
) -> AggregationResult:
    """Aggregate macros into supers and root using a sliding window.

    For <= window_size macros, uses a single pass (original behavior).
    For > window_size macros, uses sliding windows of window_size macros
    each. The last super_event from each window is dropped and its macros
    become the start of the next window, ensuring boundary continuity.
    After all windows, a root synthesis pass aggregates the super events.
    """
    logger.info(
        "Phase 3: hierarchical aggregation (window_size=%d, macros=%d)",
        window_size,
        len(macros),
    )
    if len(macros) <= window_size:
        return await _single_pass(macros, call_llm)
    return await _sliding_window(macros, call_llm, window_size)


async def _single_pass(
    macros: list[MacroEvent],
    call_llm: LlmCall,
) -> AggregationResult:
    """Original single-pass aggregation for small macro counts."""
    macro_list = [_macro_to_dict(m) for m in macros]
    input_data = json.dumps(macro_list, ensure_ascii=False, indent=2)
    prompt = (
        f"Here are the chronologically ordered Macro events:\n\n"
        f"{input_data}\n\n" + HIERARCHICAL_AGGREGATION_PROMPT
    )

    resp = await call_llm(prompt)
    try:
        agg = extract_json(resp)
    except json.JSONDecodeError:
        logger.warning("aggregation JSON parse failed, using fallback")
        agg = _fallback_aggregation(macros)

    root_data = agg.get("root", {})
    root = VideoRoot(
        title=root_data.get("title", ""),
        description=root_data.get("description", ""),
        themes=root_data.get("themes", []),
        key_entities=root_data.get("key_entities", []),
        emotional_tone=root_data.get("emotional_tone", ""),
    )

    supers = []
    for se in agg.get("super_events", []):
        sid = se.get("super_id", "")
        supers.append(
            SuperEvent(
                super_id=sid,
                label=se.get("label", ""),
                description=se.get("description", ""),
                sub_macro_ids=se.get("sub_macro_ids", []),
                time_range=_parse_time_range(se.get("time_range", [])),
                key_entities=se.get("key_entities", []),
            ),
        )
        for mid in se.get("sub_macro_ids", []):
            for m in macros:
                if m.macro_id == mid:
                    m.super_id = sid

    macro_rels = [
        MacroRelation(
            source=r["source"],
            target=r["target"],
            type=r["type"],
            reason=r.get("reason", ""),
        )
        for r in agg.get("macro_relations", [])
    ]
    super_rels = [
        SuperRelation(
            source=r["source"],
            target=r["target"],
            type=r["type"],
            reason=r.get("reason", ""),
        )
        for r in agg.get("super_relations", [])
    ]
    return root, supers, macro_rels, super_rels


async def _sliding_window(
    macros: list[MacroEvent],
    call_llm: LlmCall,
    window_size: int,
) -> AggregationResult:
    """Sliding window aggregation for large macro counts."""
    all_supers: list[SuperEvent] = []
    all_macro_rels: list[MacroRelation] = []
    super_counter = 0
    macro_ids_by_index = {m.macro_id: i for i, m in enumerate(macros)}

    window_start = 0
    window_num = 0

    while window_start < len(macros):
        window_end = min(window_start + window_size, len(macros))
        window_macros = macros[window_start:window_end]
        is_last_window = window_end >= len(macros)

        window_num += 1
        logger.info(
            "window %d: macros[%d:%d] (%d macros, %s)",
            window_num,
            window_start,
            window_end,
            len(window_macros),
            "final" if is_last_window else "continuing",
        )

        macro_list = [_macro_to_dict(m) for m in window_macros]
        input_data = json.dumps(macro_list, ensure_ascii=False, indent=2)
        prompt = (
            f"Here are the chronologically ordered Macro events "
            f"(window {window_num}, macros {window_start} to "
            f"{window_end - 1}):\n\n"
            f"{input_data}\n\n" + HIERARCHICAL_AGGREGATION_WINDOW_PROMPT
        )

        resp = await call_llm(prompt)
        try:
            agg = extract_json(resp)
        except json.JSONDecodeError:
            logger.warning(
                "window %d: JSON parse failed, using fallback",
                window_num,
            )
            agg = {
                "super_events": [
                    {
                        "super_id": f"super_{super_counter:02d}",
                        "label": f"Window {window_num}",
                        "description": ", ".join(
                            m.label for m in window_macros
                        ),
                        "sub_macro_ids": [m.macro_id for m in window_macros],
                        "time_range": [
                            window_macros[0].time_range[0],
                            window_macros[-1].time_range[1],
                        ],
                        "key_entities": [],
                    },
                ],
                "macro_relations": [],
            }

        window_supers, window_rels, super_counter = _parse_window_result(
            agg,
            macros,
            super_counter,
        )

        if not window_supers:
            logger.info(
                "window %d: no super events returned, advancing",
                window_num,
            )
            window_start = window_end
            continue

        if is_last_window or len(window_supers) <= 1:
            all_supers.extend(window_supers)
            all_macro_rels.extend(window_rels)
            window_start = window_end
        else:
            dropped = window_supers[-1]
            kept = window_supers[:-1]
            all_supers.extend(kept)
            super_counter -= 1

            kept_macro_ids = set()
            for se in kept:
                kept_macro_ids.update(se.sub_macro_ids)
            all_macro_rels.extend(
                r
                for r in window_rels
                if r.source in kept_macro_ids and r.target in kept_macro_ids
            )

            dropped_macro_ids = dropped.sub_macro_ids
            if dropped_macro_ids:
                first_dropped_id = dropped_macro_ids[0]
                if first_dropped_id in macro_ids_by_index:
                    # Rewind to the dropped super's first macro so the next
                    # window re-covers it, but always advance by at least
                    # one — a model that returns sub_macro_ids out of order
                    # could otherwise point back at/behind window_start and
                    # hang the loop.
                    window_start = max(
                        macro_ids_by_index[first_dropped_id],
                        window_start + 1,
                    )
                else:
                    window_start = window_end
            else:
                window_start = window_end

            for mid in dropped_macro_ids:
                for m in macros:
                    if m.macro_id == mid:
                        m.super_id = ""

            logger.info(
                "dropped last super '%s' (%d macros), next window from "
                "macro index %d",
                dropped.label,
                len(dropped_macro_ids),
                window_start,
            )

    logger.info(
        "sliding window done: %d super events from %d windows",
        len(all_supers),
        window_num,
    )

    root, super_rels = await _synthesize_root(all_supers, call_llm)
    return root, all_supers, all_macro_rels, super_rels


async def _synthesize_root(
    supers: list[SuperEvent],
    call_llm: LlmCall,
) -> tuple[VideoRoot, list[SuperRelation]]:
    """Synthesize root summary and super relations from all super events."""
    super_list = []
    for se in supers:
        super_list.append(
            {
                "super_id": se.super_id,
                "label": se.label,
                "description": se.description,
                "time_range": [sec_to_time_str(t) for t in se.time_range],
                "key_entities": se.key_entities,
            },
        )

    input_data = json.dumps(super_list, ensure_ascii=False, indent=2)
    prompt = (
        f"Here are the chronologically ordered Super Events:\n\n"
        f"{input_data}\n\n" + ROOT_SYNTHESIS_PROMPT
    )

    resp = await call_llm(prompt)
    try:
        result = extract_json(resp)
    except json.JSONDecodeError:
        logger.warning("root synthesis JSON parse failed, using fallback")
        result = {
            "root": {
                "title": "Video Summary",
                "description": f"Video with {len(supers)} super events",
                "themes": [],
                "key_entities": [],
                "emotional_tone": "",
            },
            "super_relations": [],
        }

    root_data = result.get("root", {})
    root = VideoRoot(
        title=root_data.get("title", ""),
        description=root_data.get("description", ""),
        themes=root_data.get("themes", []),
        key_entities=root_data.get("key_entities", []),
        emotional_tone=root_data.get("emotional_tone", ""),
    )

    super_rels = [
        SuperRelation(
            source=r["source"],
            target=r["target"],
            type=r["type"],
            reason=r.get("reason", ""),
        )
        for r in result.get("super_relations", [])
    ]

    return root, super_rels
