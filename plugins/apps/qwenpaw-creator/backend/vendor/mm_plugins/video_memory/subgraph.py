# -*- coding: utf-8 -*-
"""Phase 2 subgraph extraction: prompt context and response parsing.

Vendored from Qwen-MM-Plugins commit 077aea6
(src/capabilities/video-memory/skill/script/build_memory/build_graph.py,
Phase 2: ``_extract_one_subgraph``). License: Apache-2.0; see
backend/vendor/NOTICE.md.
Modifications: video clipping/upload and the VLM HTTP call are removed
(the Creator ``creator_vlm_model`` backend performs the call); only the
segment context construction and the response→schema conversion with
relative→absolute time shifting are kept.
"""

from __future__ import annotations

from .schema import (
    Edge,
    Entity,
    MacroEvent,
    MicroEvent,
    OnScreenText,
    Subgraph,
)
from .time_utils import sec_to_time_str, time_str_to_sec


def build_segment_context(macro: MacroEvent) -> str:
    """Build the per-segment context prefix for the subgraph prompt."""
    start, end = macro.time_range
    duration = end - start
    context = (
        f"Video segment: {macro.label}\n"
        f"Absolute time in full video: {sec_to_time_str(start)} to "
        f"{sec_to_time_str(end)} (duration: {duration:.0f}s)\n"
        f"IMPORTANT: All time_range values in your output must be RELATIVE "
        f"to this segment — second 0 is the start of this clip, second "
        f"{duration:.0f} is the end. Do NOT use absolute video timestamps.\n"
    )
    if macro.asr_text:
        context += (
            f"\nAudio transcript (ASR) for this segment:\n{macro.asr_text}\n"
        )
    context += "\n"
    return context


def _to_float(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return time_str_to_sec(v)
    return 0.0


def apply_subgraph_payload(
    macro: MacroEvent,
    sg_data: dict,
    index: int = 0,
) -> MacroEvent:
    """Convert one parsed VLM subgraph payload onto ``macro`` in place.

    Relative segment timestamps are shifted to absolute video seconds.
    """
    start, end = macro.time_range

    events = []
    for e in sg_data.get("micro_events", []):
        tr = e.get("time_range", [start, end])
        if isinstance(tr, list) and len(tr) == 2:
            tr = [_to_float(tr[0]) + start, _to_float(tr[1]) + start]
        events.append(
            MicroEvent(
                event_id=e.get("event_id", f"ev_{index}"),
                event_type=e.get("event_type", ""),
                time_range=tr,
                subject=e.get("subject", ""),
                object=e.get("object", ""),
                action=e.get("action", ""),
                description=e.get("description", ""),
                macro_id=macro.macro_id,
            ),
        )

    entities = []
    for e in sg_data.get("entities", []):
        vg = e.get("visual_grounding", {})
        if isinstance(vg, dict) and "primary_time_sec" in vg:
            vg["primary_time_sec"] = _to_float(vg["primary_time_sec"]) + start
        entities.append(
            Entity(
                entity_id=e.get("entity_id", f"ent_{index}"),
                name=e.get("name"),
                entity_type=e.get("entity_type", "OBJECT"),
                attributes=e.get("attributes", {}),
                description=e.get("description", ""),
                visual_grounding=vg if isinstance(vg, dict) else {},
                macro_id=macro.macro_id,
            ),
        )

    edges = []
    for e in sg_data.get("edges", []):
        edges.append(
            Edge(
                source_id=str(e.get("source_id", "")),
                target_id=str(e.get("target_id", "")),
                relation_label=e.get("relation_label", ""),
                relation_type=e.get("relation_type", ""),
                description=e.get("description", ""),
            ),
        )

    on_screen_texts = []
    for t in sg_data.get("on_screen_texts", []):
        tr = t.get("time_range", [start, end])
        if isinstance(tr, list) and len(tr) == 2:
            tr = [_to_float(tr[0]) + start, _to_float(tr[1]) + start]
        on_screen_texts.append(
            OnScreenText(
                text_id=t.get("text_id", f"ocr_{index}"),
                text=t.get("text", ""),
                time_range=tr,
                description=t.get("description", ""),
                macro_id=macro.macro_id,
            ),
        )

    macro.subgraph = Subgraph(
        macro_id=macro.macro_id,
        micro_events=events,
        entities=entities,
        on_screen_texts=on_screen_texts,
        edges=edges,
    )
    macro.key_entities = [
        {"name": e.name or e.entity_id, "type": e.entity_type}
        for e in entities[:10]
    ]
    macro.event_types = list({e.event_type for e in events if e.event_type})
    macro.ocr_texts = [t.text for t in on_screen_texts]
    return macro
