# -*- coding: utf-8 -*-
"""Merge per-video graph memories into one combined graph payload.

Vendored from Qwen-MM-Plugins commit 077aea6
(src/capabilities/video-memory/skill/script/build_memory/merge_memories.py).
License: Apache-2.0; see backend/vendor/NOTICE.md.
Modifications: CLI entry point, ``*.memory`` directory scanning and
embeddings-file IO are removed (the Creator source-memory service owns
artifact discovery, caching and index construction); the pure functions
keep the upstream semantics — ID prefixing across every graph surface,
mechanical root synthesis and embedding-node ID rewriting.
"""

from __future__ import annotations

from typing import Any


def prefix_graph_payload(data: dict, prefix: str) -> None:
    """Prefix every node/relation ID inside one graph payload in place."""
    p = f"{prefix}_"

    for se in data.get("super_events", []):
        se["super_id"] = p + str(se["super_id"])
        se["sub_macro_ids"] = [
            p + str(mid) for mid in se.get("sub_macro_ids", [])
        ]

    for me in data.get("macro_events", []):
        me["macro_id"] = p + str(me["macro_id"])
        me["super_id"] = (
            p + str(me.get("super_id", "")) if me.get("super_id") else ""
        )
        sg = me.get("subgraph")
        if sg:
            sg["macro_id"] = p + str(sg.get("macro_id", ""))
            for e in sg.get("micro_events", []):
                e["event_id"] = p + str(e.get("event_id", ""))
                e["macro_id"] = (
                    p + str(e.get("macro_id", "")) if e.get("macro_id") else ""
                )
            for e in sg.get("entities", []):
                e["entity_id"] = p + str(e.get("entity_id", ""))
                e["macro_id"] = (
                    p + str(e.get("macro_id", "")) if e.get("macro_id") else ""
                )
            for edge in sg.get("edges", []):
                edge["source_id"] = p + str(edge.get("source_id", ""))
                edge["target_id"] = p + str(edge.get("target_id", ""))
            for txt in sg.get("on_screen_texts", []):
                txt["text_id"] = p + str(txt.get("text_id", ""))
                txt["macro_id"] = (
                    p + str(txt.get("macro_id", ""))
                    if txt.get("macro_id")
                    else ""
                )

    for mr in data.get("macro_relations", []):
        mr["source"] = p + str(mr["source"])
        mr["target"] = p + str(mr["target"])

    for sr in data.get("super_relations", []):
        sr["source"] = p + str(sr["source"])
        sr["target"] = p + str(sr["target"])


def prefix_index_nodes(nodes: list[dict], prefix: str) -> None:
    """Prefix embedding-index node IDs to match a prefixed graph."""
    p = f"{prefix}_"
    for node in nodes:
        node["node_id"] = p + str(node.get("node_id", ""))
        if node.get("macro_id"):
            node["macro_id"] = p + str(node["macro_id"])


def merged_graph_payload(
    sources: list[tuple[str, dict]],
    merged_key: str = "merged",
) -> dict:
    """Concatenate already-prefixed graph payloads into one payload.

    ``sources`` is a list of ``(prefix, payload)`` pairs whose payloads
    have been rewritten by :func:`prefix_graph_payload`. The root is a
    mechanical synthesis (titles/themes/entities union), mirroring the
    upstream merge script.
    """
    merged: dict[str, Any] = {
        "video_key": merged_key,
        "video_path": "",
        "root": {
            "title": "",
            "description": "",
            "themes": [],
            "key_entities": [],
            "emotional_tone": "",
        },
        "super_events": [],
        "macro_events": [],
        "macro_relations": [],
        "super_relations": [],
    }

    titles: list[str] = []
    all_themes: set[str] = set()
    all_entities: set[str] = set()

    for prefix, data in sources:
        merged["super_events"].extend(data.get("super_events", []))
        merged["macro_events"].extend(data.get("macro_events", []))
        merged["macro_relations"].extend(data.get("macro_relations", []))
        merged["super_relations"].extend(data.get("super_relations", []))

        root = data.get("root", {})
        if root.get("title"):
            titles.append(f"{prefix}: {root['title']}")
        all_themes.update(root.get("themes", []))
        all_entities.update(str(e) for e in root.get("key_entities", []))

    merged["root"]["title"] = f"Merged memory: {len(sources)} sources"
    merged["root"]["description"] = "; ".join(titles[:20])
    if len(titles) > 20:
        merged["root"]["description"] += f" ... and {len(titles) - 20} more"
    merged["root"]["themes"] = sorted(all_themes)[:50]
    merged["root"]["key_entities"] = sorted(all_entities)[:100]
    return merged
