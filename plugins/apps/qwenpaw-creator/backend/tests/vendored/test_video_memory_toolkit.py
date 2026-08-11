# -*- coding: utf-8 -*-
"""Locks the 9 memory query surfaces over a prebuilt graph fixture."""
from __future__ import annotations

import numpy as np
import pytest

from vendor.media_toolkit.video_memory.embeddings import EmbeddingIndex
from vendor.media_toolkit.video_memory.schema import (
    Edge,
    Entity,
    HierarchicalGraphMemory,
    MacroEvent,
    MacroRelation,
    MicroEvent,
    OnScreenText,
    Subgraph,
    SuperEvent,
    SuperRelation,
    VideoRoot,
)
from vendor.media_toolkit.video_memory.toolkit import MemoryToolkit


def build_fixture_memory() -> HierarchicalGraphMemory:
    subgraph_a = Subgraph(
        macro_id="macro_0000",
        micro_events=[
            MicroEvent(
                event_id="ev_001",
                event_type="action",
                time_range=[12.0, 30.0],
                subject="cat",
                object="pond",
                action="approaches the pond",
                description="the cat walks to the pond edge",
                macro_id="macro_0000",
            ),
        ],
        entities=[
            Entity(
                entity_id="ent_001",
                name="orange cat",
                entity_type="PERSON",
                description="orange tabby cat wearing a camera",
                visual_grounding={"distinctive_features": ["orange fur"]},
                macro_id="macro_0000",
            ),
        ],
        on_screen_texts=[
            OnScreenText(
                text_id="ocr_001",
                text="Team Blue 12 : 8 Team Red",
                time_range=[20.0, 40.0],
                description="scoreboard overlay",
                macro_id="macro_0000",
            ),
        ],
        edges=[
            Edge(
                source_id="ent_001",
                target_id="ev_001",
                relation_label="PERFORMS",
                relation_type="SEMANTIC",
            ),
            Edge(
                source_id="ev_001",
                target_id="ent_001",
                relation_label="CAUSES",
                relation_type="CAUSAL",
            ),
        ],
    )
    subgraph_b = Subgraph(
        macro_id="macro_0001",
        micro_events=[
            MicroEvent(
                event_id="ev_101",
                event_type="teamfight",
                time_range=[320.0, 360.0],
                subject="team blue",
                object="dragon pit",
                action="starts the decisive teamfight",
                description="five members collapse on the dragon pit",
                macro_id="macro_0001",
            ),
        ],
        entities=[],
        on_screen_texts=[],
        edges=[],
    )
    macros = [
        MacroEvent(
            macro_id="macro_0000",
            label="scene_0000",
            time_range=[0.0, 300.0],
            summary="cat explores the garden pond",
            asr_text="今天天气不错。 小猫来到池塘边喝水。",
            subgraph=subgraph_a,
            super_id="super_00",
        ),
        MacroEvent(
            macro_id="macro_0001",
            label="scene_0001",
            time_range=[300.0, 620.0],
            summary="decisive teamfight at the dragon pit",
            # Space-separated so BM25 tokenization also works without the
            # dense embedding backend (CJK runs are single tokens).
            asr_text="这一波 团战 打得非常精彩 蓝色方 完成 零换五",
            subgraph=subgraph_b,
            super_id="super_00",
        ),
    ]
    return HierarchicalGraphMemory(
        video_key="index-1",
        video_path="/tmp/video.mp4",
        root=VideoRoot(
            title="Fixture Video",
            description="two-scene fixture",
            themes=["fixture"],
            key_entities=["orange cat"],
            emotional_tone="calm",
        ),
        super_events=[
            SuperEvent(
                super_id="super_00",
                label="whole video",
                description="everything",
                sub_macro_ids=["macro_0000", "macro_0001"],
                time_range=[0.0, 620.0],
                key_entities=[{"name": "orange cat", "type": "PERSON"}],
            ),
        ],
        macro_events=macros,
        macro_relations=[
            MacroRelation(
                source="macro_0000",
                target="macro_0001",
                type="ENABLES",
                reason="fixture",
            ),
        ],
        super_relations=[
            SuperRelation(
                source="super_00",
                target="super_00",
                type="LEADS_TO",
                reason="fixture",
            ),
        ],
    )


def build_fixture_index(
    memory: HierarchicalGraphMemory,
) -> tuple[EmbeddingIndex, list[dict], np.ndarray]:
    nodes = memory.get_all_nodes()
    # Deterministic orthogonal-ish embeddings: one hot per node index.
    vectors = np.eye(len(nodes), dtype=np.float32)
    index = EmbeddingIndex()
    index.build(nodes, vectors)
    return index, nodes, vectors


@pytest.fixture(name="toolkit")
def toolkit_fixture() -> MemoryToolkit:
    memory = build_fixture_memory()
    index, _, _ = build_fixture_index(memory)
    return MemoryToolkit(memory, index)


def test_get_summary(toolkit: MemoryToolkit) -> None:
    summary = toolkit.get_summary()
    assert summary["title"] == "Fixture Video"
    assert summary["themes"] == ["fixture"]


def test_get_super_events(toolkit: MemoryToolkit) -> None:
    supers = toolkit.get_super_events()
    assert len(supers) == 1
    assert supers[0]["super_id"] == "super_00"
    assert supers[0]["num_macros"] == 2
    assert supers[0]["time_range"] == "00:00:00-00:10:20"
    assert supers[0]["key_entities"] == ["orange cat"]


def test_get_macro_events_all_and_super_filter(
    toolkit: MemoryToolkit,
) -> None:
    all_macros = toolkit.get_macro_events()
    assert [item["macro_id"] for item in all_macros] == [
        "macro_0000",
        "macro_0001",
    ]
    filtered = toolkit.get_macro_events(super_id="super_00")
    assert len(filtered) == 2
    missing = toolkit.get_macro_events(super_id="super_99")
    assert "error" in missing


def test_get_subgraph_structure(toolkit: MemoryToolkit) -> None:
    subgraph = toolkit.get_subgraph("macro_0000")
    assert subgraph["macro_id"] == "macro_0000"
    assert subgraph["entities"][0]["entity_id"] == "macro_0000:ent_001"
    assert subgraph["entities"][0]["visual_features"] == ["orange fur"]
    assert subgraph["events"][0]["event_id"] == "macro_0000:ev_001"
    assert subgraph["ocr_texts"][0]["text"].startswith("Team Blue")
    # Only the high-value CAUSAL edge survives the relation filter.
    assert len(subgraph["key_relations"]) == 1
    assert subgraph["key_relations"][0]["type"] == "CAUSAL"
    assert "error" in toolkit.get_subgraph("macro_9999")


def test_search_nodes_dense_ranking(toolkit: MemoryToolkit) -> None:
    memory = toolkit.memory
    nodes = memory.get_all_nodes()
    target = next(
        i for i, node in enumerate(nodes) if node["node_id"] == "ev_101"
    )
    query_embedding = np.eye(len(nodes), dtype=np.float32)[target]
    result = toolkit.search_nodes(
        "teamfight",
        top_k=3,
        query_embedding=query_embedding,
    )
    top = result["results"][0]
    assert top["node_id"] == "macro_0001:ev_101"
    assert top["parent_macro"]["macro_id"] == "macro_0001"


def test_search_nodes_without_embedding_falls_back_to_bm25(
    toolkit: MemoryToolkit,
) -> None:
    result = toolkit.search_nodes("teamfight dragon", top_k=3)
    assert result["results"]
    assert result["results"][0]["node_id"] == "macro_0001:ev_101"


def test_enumerate_events_time_ordered(toolkit: MemoryToolkit) -> None:
    result = toolkit.enumerate_events("cat teamfight", min_cosine=0.0)
    starts = [item["time_range"] for item in result["matches"]]
    assert result["total_matches"] == len(result["matches"]) > 0
    assert starts == sorted(starts)


def test_search_ocr_text(toolkit: MemoryToolkit) -> None:
    matches = toolkit.search_ocr_text("Team Blue scoreboard")
    assert matches
    assert matches[0]["macro_id"] == "macro_0000"
    assert "Team Blue" in matches[0]["text"]


def test_search_asr_text_keyword_fallback() -> None:
    memory = build_fixture_memory()
    toolkit = MemoryToolkit(memory, None)
    matches = toolkit.search_asr_text("团战 零换五")
    assert matches
    assert matches[0]["macro_id"] == "macro_0001"
    assert matches[0]["time_range"] == "00:05:00-00:10:20"


def test_search_by_time_overlap(toolkit: MemoryToolkit) -> None:
    hits = toolkit.search_by_time(start_sec=310.0, end_sec=400.0)
    assert [item["macro_id"] for item in hits] == ["macro_0001"]
    assert hits[0]["super_event"] == "whole video"
    both = toolkit.search_by_time(start_sec=0.0, end_sec=620.0)
    assert len(both) == 2


def test_graph_and_index_round_trip(tmp_path) -> None:
    memory = build_fixture_memory()
    index, nodes, _ = build_fixture_index(memory)
    graph_path = tmp_path / "graph_memory.json"
    npz_path = tmp_path / "embeddings.npz"
    memory.save(str(graph_path))
    index.save(str(npz_path))

    loaded_memory = HierarchicalGraphMemory.load(str(graph_path))
    assert len(loaded_memory.macro_events) == 2
    assert loaded_memory.macro_events[0].subgraph is not None
    assert loaded_memory.get_all_nodes() == nodes

    loaded_index = EmbeddingIndex()
    loaded_index.load(str(npz_path))
    assert loaded_index.embeddings is not None
    assert loaded_index.embeddings.shape == (len(nodes), len(nodes))
    toolkit = MemoryToolkit(loaded_memory, loaded_index)
    assert toolkit.search_asr_text("零换五")[0]["macro_id"] == "macro_0001"


def test_asr_nodes_are_chunked_for_embedding() -> None:
    memory = build_fixture_memory()
    memory.macro_events[0].asr_text = "很长的句子。" * 200
    nodes = memory.get_all_nodes()
    asr_nodes = [n for n in nodes if n["node_type"] == "asr_text"]
    assert len(asr_nodes) >= 3
    assert all(len(n["text"]) <= 520 for n in asr_nodes)


def test_cjk_tokenizer_emits_character_bigrams() -> None:
    from vendor.media_toolkit.video_memory.embeddings import _tokenize

    tokens = _tokenize("张飞也没一波一换三 asphalt road")
    assert "一换" in tokens
    assert "换三" in tokens
    assert "asphalt" in tokens
    # Mixed digit/CJK runs keep matchable bigrams too.
    assert "0换" in _tokenize("打出了一波0换3")


def test_short_chinese_phrase_gets_exact_bm25_hit() -> None:
    # Regression: a whole commentary sentence used to collapse into one
    # opaque token, so exact short phrases missed BM25 entirely and RRF
    # surfaced arbitrary zero-score candidates.
    index = EmbeddingIndex()
    nodes = [
        {
            "node_id": f"asr_{i}",
            "node_type": "asr_text",
            "macro_id": f"macro_{i:04d}",
            "text": text,
        }
        for i, text in enumerate(
            [
                "张飞也没一波一换三，AG要尝试打终结的。",
                "现在整体的野射对位上面双方都有领先。",
                "这场比赛打得非常精彩，值得回看。",
                "赛后采访回顾第一局的关键团战细节。",
            ],
        )
    ]
    index.build(nodes, None)
    hits = index.search("一换三", top_k=4)
    assert hits[0]["node_id"] == "asr_0"
    # Upstream f9d5741: a node absent from both the dense and the sparse
    # rank lists is dropped entirely instead of carrying default-rank RRF
    # credit, so the zero-score candidates no longer appear at all.
    assert len(hits) == 1
