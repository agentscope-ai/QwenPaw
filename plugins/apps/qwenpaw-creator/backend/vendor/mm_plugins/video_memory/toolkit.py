# -*- coding: utf-8 -*-
"""Retrieval toolkit over Hierarchical Graph Memory.

Vendored from Qwen-MM-Plugins commit 077aea6
(src/capabilities/video-memory/qwen_mm_plugins_video_memory/toolkit.py plus
the query logic of loader.py). License: Apache-2.0; see
backend/vendor/NOTICE.md.
Modifications: the EgoLife multi-day time system and the time-cutoff
support are removed (Creator sources use plain single-video timelines);
methods return Python objects instead of JSON strings; dense lookups take
a precomputed query embedding produced by the Creator embedding client.
"""

from __future__ import annotations

import numpy as np

from .embeddings import EmbeddingIndex
from .schema import HierarchicalGraphMemory


def sec_to_time_str(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _entity_names(key_entities: list) -> list[str]:
    """Entity display names, tolerating both the {"name": ...} dicts the
    build emits and the bare strings an LLM occasionally returns for a
    key_entities list instead."""
    return [
        e.get("name", "") if isinstance(e, dict) else str(e)
        for e in key_entities
    ]


def time_val_to_sec(val) -> float:
    """Convert a time_range element (float or string) to float seconds."""
    if isinstance(val, (int, float)):
        return float(val)
    if not isinstance(val, str):
        return 0.0
    import re

    m = re.search(r"(\d{1,2}):(\d{2}):(\d{2})$", val.strip())
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
    return 0.0


class MemoryToolkit:
    """Retrieval methods over a loaded HierarchicalGraphMemory."""

    def __init__(
        self,
        memory: HierarchicalGraphMemory,
        index: EmbeddingIndex | None = None,
    ):
        self.memory = memory
        self.index = index
        self._macro_map = {m.macro_id: m for m in memory.macro_events}
        self._super_map = {s.super_id: s for s in memory.super_events}
        self._node_map: dict[str, dict] = {}
        self._edge_map: dict[str, list[dict]] = {}
        self._build_edge_index()

    def _fmt_tr(self, tr) -> str | None:
        if not tr or len(tr) < 2:
            return None
        if isinstance(tr[0], str):
            return f"{tr[0]}-{tr[1]}"
        return f"{sec_to_time_str(tr[0])}-{sec_to_time_str(tr[1])}"

    @staticmethod
    def _prefixed(macro_id: str, node_id: str) -> str:
        return f"{macro_id}:{node_id}"

    def _build_edge_index(self):
        for me in self.memory.macro_events:
            if not me.subgraph:
                continue
            mid = me.macro_id
            for ent in me.subgraph.entities:
                self._node_map[self._prefixed(mid, ent.entity_id)] = {
                    "type": "Entity",
                    "macro_id": mid,
                    "name": ent.name,
                    "entity_type": ent.entity_type,
                    "description": ent.description,
                }
            for ev in me.subgraph.micro_events:
                self._node_map[self._prefixed(mid, ev.event_id)] = {
                    "type": "Event",
                    "macro_id": mid,
                    "action": ev.action,
                    "description": ev.description,
                    "time_range": ev.time_range,
                }
            for ocr in me.subgraph.on_screen_texts:
                self._node_map[self._prefixed(mid, ocr.text_id)] = {
                    "type": "OCRText",
                    "macro_id": mid,
                    "name": ocr.text,
                    "description": ocr.description,
                    "time_range": ocr.time_range,
                }
            for edge in me.subgraph.edges:
                src = self._prefixed(mid, edge.source_id)
                tgt = self._prefixed(mid, edge.target_id)
                self._edge_map.setdefault(src, []).append(
                    {
                        "target_id": tgt,
                        "relation_label": edge.relation_label,
                        "relation_type": edge.relation_type,
                        "description": edge.description,
                        "direction": "outgoing",
                    },
                )
                self._edge_map.setdefault(tgt, []).append(
                    {
                        "source_id": src,
                        "relation_label": edge.relation_label,
                        "relation_type": edge.relation_type,
                        "description": edge.description,
                        "direction": "incoming",
                    },
                )
        for rel in self.memory.macro_relations:
            self._edge_map.setdefault(rel.source, []).append(
                {
                    "target_id": rel.target,
                    "relation_label": rel.type,
                    "relation_type": "CAUSAL",
                    "description": rel.reason,
                    "direction": "outgoing",
                },
            )
        for rel in self.memory.super_relations:
            self._edge_map.setdefault(rel.source, []).append(
                {
                    "target_id": rel.target,
                    "relation_label": rel.type,
                    "relation_type": "PROGRESSION",
                    "description": rel.reason,
                    "direction": "outgoing",
                },
            )

    # ------------------------------------------------------------------
    def _get_neighbor_info(self, prefixed: str) -> list[dict]:
        """Build neighbor list for ego graph."""
        related = self._edge_map.get(prefixed, [])
        if not related:
            return []
        neighbors = []
        for rel in related:
            tid = rel.get("target_id") or rel.get("source_id", "")
            tnode = self._node_map.get(tid, {})
            nb_name = tnode.get("name") or tnode.get("action", "")
            nb_etype = tnode.get("entity_type", "")
            label = (
                f"{nb_etype}: {nb_name}"
                if nb_etype and nb_name
                else (nb_name or tid)
            )
            neighbors.append(
                {
                    "node_id": tid,
                    "node_type": tnode.get("type", ""),
                    "label": label,
                    "description": tnode.get("description", ""),
                    "direction": rel.get("direction", ""),
                    "relation_type": rel["relation_type"],
                    "relation_label": rel["relation_label"],
                },
            )
        return neighbors

    def get_summary(self) -> dict:
        r = self.memory.root
        return {
            "title": r.title,
            "description": r.description,
            "themes": r.themes,
            "key_entities": r.key_entities,
            "emotional_tone": r.emotional_tone,
        }

    def get_super_events(self) -> list[dict]:
        result = []
        for se in self.memory.super_events:
            visible_macros = [
                mid for mid in se.sub_macro_ids if mid in self._macro_map
            ]
            if not visible_macros:
                continue
            result.append(
                {
                    "super_id": se.super_id,
                    "label": se.label,
                    "time_range": self._fmt_tr(se.time_range),
                    "key_entities": _entity_names(se.key_entities),
                    "description": se.description or "",
                    "num_macros": len(visible_macros),
                },
            )
        return result

    def get_macro_events(
        self,
        super_id: str = "",
        macro_ids: list[str] | None = None,
    ) -> list[dict] | dict:
        if macro_ids:
            macro_list = macro_ids
        elif super_id:
            se = self._super_map.get(super_id)
            if not se:
                return {"error": f"Super event {super_id} not found"}
            macro_list = se.sub_macro_ids
        else:
            macro_list = [me.macro_id for me in self.memory.macro_events]

        macros = []
        for mid in macro_list:
            me = self._macro_map.get(mid)
            if not me:
                continue
            macros.append(
                {
                    "macro_id": me.macro_id,
                    "label": me.label,
                    "time_range": self._fmt_tr(me.time_range),
                    "key_entities": _entity_names(me.key_entities),
                    "summary": me.summary,
                },
            )
        return macros

    def get_subgraph(self, macro_id: str) -> dict:
        me = self._macro_map.get(macro_id)
        if not me:
            return {"error": f"Macro event {macro_id} not found"}
        if not me.subgraph:
            return {"error": f"No subgraph for {macro_id}"}

        sg = me.subgraph
        result = {
            "macro_id": macro_id,
            "label": me.label,
            "time_range": self._fmt_tr(me.time_range),
            "description": me.summary,
            "entities": [],
            "events": [],
            "ocr_texts": [],
            "key_relations": [],
        }
        for ent in sg.entities:
            entry = {
                "entity_id": self._prefixed(macro_id, ent.entity_id),
                "name": ent.name,
                "entity_type": ent.entity_type,
                "description": ent.description,
            }
            if ent.attributes:
                entry["attributes"] = ent.attributes
            if ent.visual_grounding:
                feats = ent.visual_grounding.get("distinctive_features")
                if feats:
                    entry["visual_features"] = feats
            result["entities"].append(entry)
        for ev in sg.micro_events:
            result["events"].append(
                {
                    "event_id": self._prefixed(macro_id, ev.event_id),
                    "time_range": self._fmt_tr(ev.time_range),
                    "action": ev.action,
                    "description": ev.description,
                },
            )
        for ocr in sg.on_screen_texts:
            result["ocr_texts"].append(
                {
                    "text_id": self._prefixed(macro_id, ocr.text_id),
                    "text": ocr.text,
                    "description": ocr.description,
                    "time_range": self._fmt_tr(ocr.time_range),
                },
            )
        # Relation types the build pipeline actually emits (see build
        # prompt): SEMANTIC, CAUSAL, TEMPORAL, HIERARCHICAL, SPATIAL,
        # IDENTITY. Keep the high-signal ones for key_relations; selected
        # SEMANTIC links are still surfaced via HIGH_VALUE_LABELS below.
        high_value_types = {"CAUSAL", "SPATIAL"}
        high_value_labels = {"USES_TOOL", "RECEIVES", "CONTEXT_FOR"}
        for edge in sg.edges:
            rtype = edge.relation_type or ""
            rlabel = edge.relation_label or ""
            if (
                rtype not in high_value_types
                and rlabel not in high_value_labels
            ):
                continue
            src_prefixed = self._prefixed(macro_id, edge.source_id)
            tgt_prefixed = self._prefixed(macro_id, edge.target_id)
            src_node = self._node_map.get(src_prefixed, {})
            tgt_node = self._node_map.get(tgt_prefixed, {})
            result["key_relations"].append(
                {
                    "source": src_prefixed,
                    "source_label": src_node.get("name")
                    or src_node.get("action", ""),
                    "target": tgt_prefixed,
                    "target_label": tgt_node.get("name")
                    or tgt_node.get("action", ""),
                    "label": rlabel,
                    "type": rtype,
                    "description": edge.description or "",
                },
            )
        return result

    def search_nodes(
        self,
        query: str,
        top_k: int = 10,
        node_types: list[str] | None = None,
        query_embedding: np.ndarray | None = None,
    ) -> dict:
        if self.index is None:
            return {"error": "Embedding index not available"}
        if node_types is None:
            node_types = ["entity", "event"]
        results = self.index.search(
            query,
            top_k=top_k * 2,
            node_types=node_types,
            query_embedding=query_embedding,
        )
        output = []
        for r in results:
            node_id = r["node_id"]
            orig_id = node_id
            if node_id.startswith("slot") and "_" in node_id:
                orig_id = node_id.split("_", 1)[1]

            macro_id = r.get("macro_id", "")
            prefixed = self._prefixed(macro_id, orig_id) if macro_id else ""
            node_info = (
                self._node_map.get(prefixed) if prefixed else None
            ) or {}
            if not macro_id:
                macro_id = node_info.get("macro_id", "")
                if macro_id:
                    prefixed = self._prefixed(macro_id, orig_id)
                    node_info = self._node_map.get(prefixed, {})

            macro = self._macro_map.get(macro_id)

            node_type = node_info.get("type") or r.get("node_type", "unknown")
            name_or_action = node_info.get("name") or node_info.get(
                "action",
                "",
            )
            desc = node_info.get("description", "")
            tr = self._fmt_tr(node_info.get("time_range"))

            entry = {
                "node_id": prefixed or orig_id,
                "node_type": node_type,
                "label": name_or_action,
                "description": desc if desc != name_or_action else "",
                "time_range": tr,
                "score": round(r["score"], 4),
                "parent_macro": {
                    "macro_id": macro_id,
                    "label": macro.label if macro else "",
                }
                if macro_id
                else None,
                "neighbors": self._get_neighbor_info(prefixed)
                if prefixed
                else [],
            }
            output.append(entry)
            if len(output) >= top_k:
                break
        return {"results": output}

    def enumerate_events(
        self,
        query: str,
        min_cosine: float = 0.5,
        max_results: int = 120,
        node_types: list[str] | None = None,
        query_embedding: np.ndarray | None = None,
    ) -> dict:
        """Exhaustive time-ordered match list for counting/enumeration
        questions."""
        if self.index is None:
            return {"error": "Embedding index not available"}
        if node_types is None:
            node_types = ["event"]
        max_results = min(max_results, 300)
        results = self.index.search(
            query,
            top_k=max_results * 3,
            node_types=node_types,
            query_embedding=query_embedding,
        )

        dense_available = any(r.get("cosine") for r in results)
        entries = []
        seen = set()
        for r in results:
            if dense_available and r.get("cosine", 0.0) < min_cosine:
                continue
            node_id = r["node_id"]
            orig_id = (
                node_id.split("_", 1)[1]
                if node_id.startswith("slot") and "_" in node_id
                else node_id
            )
            macro_id = r.get("macro_id", "")
            prefixed = self._prefixed(macro_id, orig_id) if macro_id else ""
            node_info = (
                self._node_map.get(prefixed) if prefixed else None
            ) or {}
            macro = self._macro_map.get(macro_id)
            key = prefixed or orig_id
            if key in seen:
                continue
            seen.add(key)
            tr = node_info.get("time_range")
            start = tr[0] if isinstance(tr, (list, tuple)) and tr else None
            entries.append(
                {
                    "node_id": key,
                    "label": node_info.get("name")
                    or node_info.get("action")
                    or r.get("text", "")[:80],
                    "time_range": self._fmt_tr(tr),
                    "_start": start if start is not None else float("inf"),
                    "cosine": r.get("cosine", 0.0),
                    "macro_id": macro_id,
                    "macro_label": macro.label if macro else "",
                },
            )
            if len(entries) >= max_results:
                break
        entries.sort(key=lambda e: e["_start"])
        for e in entries:
            e.pop("_start", None)
        return {
            "query": query,
            "total_matches": len(entries),
            "note": (
                "Time-ordered candidate instances. Some may be duplicates "
                "of the same real-world occurrence (adjacent time ranges) "
                "or false positives — verify borderline ones against the "
                "original footage before finalizing a count."
            ),
            "matches": entries,
        }

    def search_ocr_text(
        self,
        query: str,
        top_k: int = 10,
        query_embedding: np.ndarray | None = None,
    ) -> list[dict]:
        if self.index is not None:
            results = self.index.search(
                query,
                top_k=top_k * 2,
                node_types=["on_screen_text"],
                query_embedding=query_embedding,
            )
            if results:
                output = []
                for r in results:
                    node_id = r.get("node_id", "")
                    macro_id = r.get("macro_id", "")
                    macro = self._macro_map.get(macro_id)
                    orig_id = node_id
                    if node_id.startswith("slot") and "_" in node_id:
                        orig_id = node_id.split("_", 1)[1]
                    prefixed = (
                        self._prefixed(macro_id, orig_id) if macro_id else ""
                    )
                    node_info = self._node_map.get(prefixed, {})
                    output.append(
                        {
                            "node_id": node_id,
                            "text": r.get("text", ""),
                            "description": node_info.get("description", ""),
                            "time_range": self._fmt_tr(
                                node_info.get("time_range"),
                            ),
                            "score": round(r["score"], 4),
                            "macro_id": macro_id,
                            "macro_label": macro.label if macro else "",
                        },
                    )
                    if len(output) >= top_k:
                        break
                if output:
                    return output

        query_lower = query.lower()
        matches = []
        for me in self.memory.macro_events:
            if not me.subgraph:
                continue
            for ocr in me.subgraph.on_screen_texts:
                text = ocr.text or ""
                desc = ocr.description or ""
                combined = f"{text} {desc}".lower()
                score = sum(
                    1 for word in query_lower.split() if word in combined
                )
                if score > 0:
                    matches.append(
                        {
                            "text": text,
                            "description": desc,
                            "time_range": self._fmt_tr(ocr.time_range),
                            "macro_id": me.macro_id,
                            "macro_label": me.label,
                            "score": score,
                        },
                    )
        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches[:top_k]

    def search_asr_text(
        self,
        query: str,
        top_k: int = 10,
        query_embedding: np.ndarray | None = None,
    ) -> list[dict]:
        if self.index is not None:
            results = self.index.search(
                query,
                top_k=top_k * 2,
                node_types=["asr_text"],
                query_embedding=query_embedding,
            )
            if results:
                output = []
                for r in results:
                    node_id = r.get("node_id", "")
                    macro_id = r.get("macro_id", "")
                    macro = self._macro_map.get(macro_id)
                    output.append(
                        {
                            "node_id": node_id,
                            "text": r.get("text", ""),
                            "time_range": self._fmt_tr(macro.time_range)
                            if macro
                            else "",
                            "score": round(r["score"], 4),
                            "macro_id": macro_id,
                            "macro_label": macro.label if macro else "",
                        },
                    )
                    if len(output) >= top_k:
                        break
                if output:
                    return output

        query_lower = query.lower()
        matches = []
        for me in self.memory.macro_events:
            asr = me.asr_text or ""
            if not asr:
                continue
            asr_lower = asr.lower()
            score = sum(1 for word in query_lower.split() if word in asr_lower)
            if score > 0:
                matches.append(
                    {
                        "text": asr[:500],
                        "time_range": self._fmt_tr(me.time_range),
                        "macro_id": me.macro_id,
                        "macro_label": me.label,
                        "score": score,
                    },
                )
        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches[:top_k]

    def search_by_time(
        self,
        start_sec: float = 0,
        end_sec: float = 600,
    ) -> list[dict]:
        results = []
        for me in self.memory.macro_events:
            if not me.time_range or len(me.time_range) < 2:
                continue
            ms = time_val_to_sec(me.time_range[0])
            me_end = time_val_to_sec(me.time_range[1])
            if ms <= end_sec and me_end >= start_sec:
                se = self._super_map.get(me.super_id)
                results.append(
                    {
                        "macro_id": me.macro_id,
                        "label": me.label,
                        "time_range": self._fmt_tr(me.time_range),
                        "key_entities": _entity_names(me.key_entities),
                        "super_event": se.label if se else "",
                    },
                )
        return results
