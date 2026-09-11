# -*- coding: utf-8 -*-
# pylint: disable=too-many-branches
"""Data structures for Hierarchical Graph Memory.

Vendored from Qwen-MM-Plugins commit 077aea6
(src/capabilities/video-memory/skill/script/build_memory/schema.py).
License: Apache-2.0; see backend/vendor/NOTICE.md.
Modifications: dropped the legacy ``hierarchical_graph_final.json`` loader;
``load`` split into ``from_payload`` + file IO so merged in-memory graphs
(Creator multi-source memory) reuse the same parser.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class MicroEvent:
    event_id: str
    event_type: str
    time_range: list[float]
    subject: str
    object: str
    action: str
    description: str
    macro_id: str = ""


@dataclass
class Entity:
    entity_id: str
    name: str | None
    entity_type: str
    attributes: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    visual_grounding: dict[str, Any] = field(default_factory=dict)
    macro_id: str = ""


@dataclass
class Edge:
    source_id: str
    target_id: str
    relation_label: str
    relation_type: str
    description: str = ""


@dataclass
class OnScreenText:
    text_id: str
    text: str
    time_range: list[float] = field(default_factory=list)
    description: str = ""
    macro_id: str = ""


@dataclass
class Subgraph:
    macro_id: str
    micro_events: list[MicroEvent] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    on_screen_texts: list[OnScreenText] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


@dataclass
class MacroEvent:
    macro_id: str
    label: str
    time_range: list[float]
    summary: str = ""
    key_entities: list[dict[str, str]] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)
    ocr_texts: list[str] = field(default_factory=list)
    dense_description: str = ""
    asr_text: str = ""
    subgraph: Subgraph | None = None
    super_id: str = ""


@dataclass
class SuperEvent:
    super_id: str
    label: str
    description: str = ""
    sub_macro_ids: list[str] = field(default_factory=list)
    time_range: list[float] = field(default_factory=list)
    key_entities: list[dict[str, str]] = field(default_factory=list)


@dataclass
class VideoRoot:
    title: str = ""
    description: str = ""
    themes: list[str] = field(default_factory=list)
    key_entities: list[str] = field(default_factory=list)
    emotional_tone: str = ""


@dataclass
class MacroRelation:
    source: str
    target: str
    type: str
    reason: str


@dataclass
class SuperRelation:
    source: str
    target: str
    type: str
    reason: str


@dataclass
class HierarchicalGraphMemory:
    video_key: str = ""
    video_path: str = ""
    root: VideoRoot = field(default_factory=VideoRoot)
    super_events: list[SuperEvent] = field(default_factory=list)
    macro_events: list[MacroEvent] = field(default_factory=list)
    macro_relations: list[MacroRelation] = field(default_factory=list)
    super_relations: list[SuperRelation] = field(default_factory=list)

    def save(self, path: str):
        # Atomic write: a reader sees the file only once complete.
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str) -> HierarchicalGraphMemory:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_payload(data)

    @classmethod
    def from_payload(cls, data: dict) -> HierarchicalGraphMemory:
        mem = cls()
        mem.video_key = data.get("video_key", "")
        mem.video_path = data.get("video_path", "")

        r = data.get("root", {})
        mem.root = VideoRoot(
            title=r.get("title", ""),
            description=r.get("description", ""),
            themes=r.get("themes", []),
            key_entities=r.get("key_entities", []),
            emotional_tone=r.get("emotional_tone", ""),
        )

        for se in data.get("super_events", []):
            mem.super_events.append(
                SuperEvent(
                    super_id=se["super_id"],
                    label=se["label"],
                    description=se.get("description", ""),
                    sub_macro_ids=se.get("sub_macro_ids", []),
                    time_range=se.get("time_range", []),
                    key_entities=se.get("key_entities", []),
                ),
            )

        for me in data.get("macro_events", []):
            sg_data = me.get("subgraph")
            sg = None
            if sg_data:
                on_screen_texts = []
                for t in sg_data.get("on_screen_texts", []):
                    on_screen_texts.append(
                        OnScreenText(
                            text_id=t.get("text_id", ""),
                            text=t.get("text", ""),
                            time_range=t.get("time_range", []),
                            description=t.get("description", ""),
                            macro_id=me["macro_id"],
                        ),
                    )
                sg = Subgraph(
                    macro_id=sg_data.get("macro_id", me["macro_id"]),
                    micro_events=[
                        MicroEvent(**e)
                        for e in sg_data.get("micro_events", [])
                    ],
                    entities=[
                        Entity(**e) for e in sg_data.get("entities", [])
                    ],
                    on_screen_texts=on_screen_texts,
                    edges=[Edge(**e) for e in sg_data.get("edges", [])],
                )
            mem.macro_events.append(
                MacroEvent(
                    macro_id=me["macro_id"],
                    label=me["label"],
                    time_range=me.get("time_range", []),
                    summary=me.get("summary", ""),
                    key_entities=me.get("key_entities", []),
                    event_types=me.get("event_types", []),
                    ocr_texts=me.get("ocr_texts", []),
                    dense_description=me.get("dense_description", ""),
                    asr_text=me.get("asr_text", ""),
                    subgraph=sg,
                    super_id=me.get("super_id", ""),
                ),
            )

        for mr in data.get("macro_relations", []):
            mem.macro_relations.append(MacroRelation(**mr))
        for sr in data.get("super_relations", []):
            mem.super_relations.append(SuperRelation(**sr))

        return mem

    def get_all_nodes(self) -> list[dict]:
        """Get all entity, event, OCR, and ASR nodes for embedding."""
        nodes = []
        for me in self.macro_events:
            if not me.subgraph:
                continue
            for ent in me.subgraph.entities:
                nodes.append(
                    {
                        "node_id": ent.entity_id,
                        "node_type": "entity",
                        "text": f"{ent.name or ''}: {ent.description}",
                        "macro_id": me.macro_id,
                    },
                )
            for ev in me.subgraph.micro_events:
                nodes.append(
                    {
                        "node_id": ev.event_id,
                        "node_type": "event",
                        "text": f"{ev.action}: {ev.description}",
                        "macro_id": me.macro_id,
                    },
                )
            for ocr in me.subgraph.on_screen_texts:
                nodes.append(
                    {
                        "node_id": ocr.text_id,
                        "node_type": "on_screen_text",
                        "text": f"{ocr.text}: {ocr.description}",
                        "macro_id": me.macro_id,
                    },
                )
        for me in self.macro_events:
            if not me.asr_text:
                continue
            text = me.asr_text.strip()
            if len(text) < 3:
                continue
            chunks: list[str] = []
            current = ""
            sentences = re.split(r"(?<=[.!?。！？\n])\s*", text)
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                if current and len(current) + len(sent) > 500:
                    chunks.append(current)
                    current = sent
                else:
                    current = (
                        (current + " " + sent).strip() if current else sent
                    )
            if current:
                chunks.append(current)
            for idx, chunk in enumerate(chunks):
                if len(chunk) < 3:
                    continue
                nodes.append(
                    {
                        "node_id": f"asr_{me.macro_id}_{idx:03d}",
                        "node_type": "asr_text",
                        "text": chunk,
                        "macro_id": me.macro_id,
                    },
                )
        return nodes
