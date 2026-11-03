# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Memory query surfaces, segmentation, and new renderers (WT-A3)."""

from __future__ import annotations

import io
import json

import numpy as np
import pytest
from PIL import Image

from vendor.media_toolkit.renderers import (
    SUPPORTED_EXTENSIONS,
    get_renderer,
    renderer_module_name,
)
from vendor.media_toolkit.video_memory.embeddings import EmbeddingIndex
from vendor.media_toolkit.video_memory.schema import HierarchicalGraphMemory
from vendor.media_toolkit.video_memory.segmentation import (
    compute_cut_scores,
    decode_jpeg_to_hls,
    find_optimal_threshold,
    plan_segments,
)
from vendor.media_toolkit.video_memory.toolkit import MemoryToolkit

pytestmark = pytest.mark.unit

# Two-scene fixture; second asr_text is space-separated for BM25 tokens.
_GRAPH_JSON = """
{"video_key": "index-1", "video_path": "/tmp/video.mp4",
 "root": {"title": "Fixture Video", "description": "two-scene fixture", "themes": ["fixture"], "key_entities": ["orange cat"], "emotional_tone": "calm"},
 "super_events": [{"super_id": "super_00", "label": "whole video", "description": "everything", "sub_macro_ids": ["macro_0000", "macro_0001"], "time_range": [0.0, 620.0], "key_entities": [{"name": "orange cat", "type": "PERSON"}]}],
 "macro_events": [
  {"macro_id": "macro_0000", "label": "scene_0000", "time_range": [0.0, 300.0], "summary": "cat explores the garden pond", "super_id": "super_00",
   "asr_text": "今天天气不错。 小猫来到池塘边喝水。",
   "subgraph": {"macro_id": "macro_0000",
    "micro_events": [{"event_id": "ev_001", "event_type": "action", "time_range": [12.0, 30.0], "subject": "cat", "object": "pond", "action": "approaches the pond", "description": "the cat walks to the pond edge", "macro_id": "macro_0000"}],
    "entities": [{"entity_id": "ent_001", "name": "orange cat", "entity_type": "PERSON", "description": "orange tabby cat wearing a camera", "visual_grounding": {"distinctive_features": ["orange fur"]}, "macro_id": "macro_0000"}],
    "on_screen_texts": [{"text_id": "ocr_001", "text": "Team Blue 12 : 8 Team Red", "time_range": [20.0, 40.0], "description": "scoreboard overlay"}],
    "edges": [{"source_id": "ent_001", "target_id": "ev_001", "relation_label": "PERFORMS", "relation_type": "SEMANTIC"},
              {"source_id": "ev_001", "target_id": "ent_001", "relation_label": "CAUSES", "relation_type": "CAUSAL"}]}},
  {"macro_id": "macro_0001", "label": "scene_0001", "time_range": [300.0, 620.0], "summary": "decisive teamfight at the dragon pit", "super_id": "super_00",
   "asr_text": "这一波 团战 打得非常精彩 蓝色方 完成 零换五",
   "subgraph": {"macro_id": "macro_0001",
    "micro_events": [{"event_id": "ev_101", "event_type": "teamfight", "time_range": [320.0, 360.0], "subject": "team blue", "object": "dragon pit", "action": "starts the decisive teamfight", "description": "five members collapse on the dragon pit", "macro_id": "macro_0001"}]}}]}
"""


def build_fixture_memory() -> HierarchicalGraphMemory:
    return HierarchicalGraphMemory.from_payload(json.loads(_GRAPH_JSON))


def build_fixture_index(memory: HierarchicalGraphMemory):
    nodes = memory.get_all_nodes()
    # Deterministic orthogonal embeddings: one hot per node index.
    vectors = np.eye(len(nodes), dtype=np.float32)
    index = EmbeddingIndex()
    index.build(nodes, vectors)
    return index, nodes, vectors


@pytest.fixture(name="toolkit")
def toolkit_fixture() -> MemoryToolkit:
    memory = build_fixture_memory()
    index, _, _ = build_fixture_index(memory)
    return MemoryToolkit(memory, index)


def test_summary_and_super_events(toolkit: MemoryToolkit) -> None:
    summary = toolkit.get_summary()
    assert summary["title"] == "Fixture Video"
    assert summary["themes"] == ["fixture"]
    supers = toolkit.get_super_events()
    assert [item["super_id"] for item in supers] == ["super_00"]
    assert supers[0]["num_macros"] == 2
    assert supers[0]["time_range"] == "00:00:00-00:10:20"
    assert supers[0]["key_entities"] == ["orange cat"]


def test_get_macro_events_all_and_super_filter(toolkit: MemoryToolkit) -> None:
    ids = [item["macro_id"] for item in toolkit.get_macro_events()]
    assert ids == ["macro_0000", "macro_0001"]
    assert len(toolkit.get_macro_events(super_id="super_00")) == 2
    assert "error" in toolkit.get_macro_events(super_id="super_99")


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


def test_search_nodes_dense_and_bm25(toolkit: MemoryToolkit):
    nodes = toolkit.memory.get_all_nodes()
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
    # Without an embedding the search falls back to BM25.
    sparse = toolkit.search_nodes("teamfight dragon", top_k=3)
    assert sparse["results"][0]["node_id"] == "macro_0001:ev_101"


def test_enumerate_events_time_ordered(toolkit: MemoryToolkit) -> None:
    result = toolkit.enumerate_events("cat teamfight", min_cosine=0.0)
    starts = [item["time_range"] for item in result["matches"]]
    assert result["total_matches"] == len(result["matches"]) > 0
    assert starts == sorted(starts)


def test_search_ocr_and_asr_text(toolkit: MemoryToolkit) -> None:
    matches = toolkit.search_ocr_text("Team Blue scoreboard")
    assert matches[0]["macro_id"] == "macro_0000"
    assert "Team Blue" in matches[0]["text"]
    # The ASR keyword fallback works without any embedding index.
    keyword = MemoryToolkit(build_fixture_memory(), None)
    hits = keyword.search_asr_text("团战 零换五")
    assert hits[0]["macro_id"] == "macro_0001"
    assert hits[0]["time_range"] == "00:05:00-00:10:20"


def test_search_by_time_overlap(toolkit: MemoryToolkit) -> None:
    hits = toolkit.search_by_time(start_sec=310.0, end_sec=400.0)
    assert [item["macro_id"] for item in hits] == ["macro_0001"]
    assert hits[0]["super_event"] == "whole video"
    assert len(toolkit.search_by_time(start_sec=0.0, end_sec=620.0)) == 2


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
    assert {"一换", "换三", "asphalt"} <= set(tokens)
    # Mixed digit/CJK runs keep matchable bigrams too.
    assert "0换" in _tokenize("打出了一波0换3")


def test_short_chinese_phrase_gets_exact_bm25_hit() -> None:
    # Regression: a whole commentary sentence used to collapse into one
    # opaque token, so exact short phrases missed BM25 entirely and RRF
    # surfaced arbitrary zero-score candidates.
    texts = [
        "张飞也没一波一换三，AG要尝试打终结的。",
        "现在整体的野射对位上面双方都有领先。",
        "这场比赛打得非常精彩，值得回看。",
        "赛后采访回顾第一局的关键团战细节。",
    ]
    nodes = []
    for i, text in enumerate(texts):
        node = {"node_id": f"asr_{i}", "node_type": "asr_text"}
        nodes.append(node | {"macro_id": f"macro_{i:04d}", "text": text})
    index = EmbeddingIndex()
    index.build(nodes, None)
    hits = index.search("一换三", top_k=4)
    assert hits[0]["node_id"] == "asr_0"
    # Upstream f9d5741: nodes absent from both the dense and the sparse
    # rank lists are dropped, so zero-score candidates never appear.
    assert len(hits) == 1


# ── video memory segmentation ────────────────────────────────────────────
def _frame(color: tuple[int, int, int]) -> np.ndarray:
    image = Image.new("RGB", (32, 18), color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    hls = decode_jpeg_to_hls(buffer.getvalue())
    assert hls is not None
    return hls


def test_cut_scores_spike_on_scene_change() -> None:
    red = _frame((200, 30, 30))
    blue = _frame((30, 30, 200))
    cut_times, cut_scores = compute_cut_scores(
        [(0.0, red), (4.0, red), (8.0, blue), (12.0, blue)],
    )
    assert cut_times == [4.0, 8.0, 12.0]
    assert cut_scores[1] > cut_scores[0] * 10
    assert cut_scores[1] > cut_scores[2] * 10


_PLAN_KW = {"min_scene_sec": 30.0, "max_scene_sec": 300.0, "threshold": 20.0}


def test_plan_segments_covers_range_min_scene_and_max_split() -> None:
    # One strong cut at 100s; weak noise elsewhere.
    cut_times = [float(t) for t in range(4, 300, 4)]
    cut_scores = [40.0 if t == 100 else 1.0 for t in cut_times]
    segments = plan_segments(
        cut_times,
        cut_scores,
        start_sec=0.0,
        end_sec=300.0,
        **_PLAN_KW,
    )
    assert segments[0][0] == 0.0 and segments[-1][1] == 300.0
    # Contiguous coverage without gaps.
    for left, right in zip(segments, segments[1:]):
        assert left[1] == right[0]
    assert any(abs(start - 100.0) < 1e-6 for start, _ in segments)
    assert all(end - start >= 30.0 - 1e-6 for start, end in segments)
    # Without cuts, overlong stretches are still split to max_scene_sec.
    splits = plan_segments([], [], start_sec=0.0, end_sec=1200.0, **_PLAN_KW)
    assert splits[0][0] == 0.0 and splits[-1][1] == 1200.0
    assert all(end - start <= 300.0 + 1e-6 for start, end in splits)
    assert len(splits) >= 4


def test_find_optimal_threshold_targets_median_duration() -> None:
    cut_times = [float(t) for t in range(10, 1200, 10)]
    cut_scores = [30.0 if t % 120 == 0 else 5.0 for t in cut_times]
    threshold = find_optimal_threshold(
        cut_times,
        cut_scores,
        0.0,
        1200.0,
        30.0,
        300.0,
    )
    # Only the strong cuts (every 120s) produce a median close to the
    # (min+max)/2 target, so the search must keep the 30-point cuts.
    assert 5.0 < threshold <= 30.0


# ── geo/drawio/model3d/latex renderers (WT-A3) ───────────────────────────
def test_new_extensions_are_registered() -> None:
    modules = {
        "geo": [".geojson", ".kml", ".shp"],
        "drawio": [".drawio"],
        "model3d": [".obj", ".stl", ".glb", ".gltf", ".ply"],
        "latex": [".tex"],
    }
    for module, exts in modules.items():
        for ext in exts:
            assert ext in SUPPORTED_EXTENSIONS
            assert renderer_module_name(ext) == module, ext


def _blocks_by_type(blocks):
    grouped: dict[str, list] = {}
    for block in blocks:
        grouped.setdefault(block.get("type"), []).append(block)
    return grouped


def test_geo_renders_a_geojson_feature_collection(tmp_path) -> None:
    pytest.importorskip("geopandas")

    def feature(name: str, population: int, lon: float, lat: float) -> dict:
        return {
            "type": "Feature",
            "properties": {"name": name, "population": population},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        }

    payload = {
        "type": "FeatureCollection",
        "features": [
            feature("上海", 24_870_000, 121.47, 31.23),
            feature("北京", 21_540_000, 116.40, 39.90),
        ],
    }
    path = tmp_path / "cities.geojson"
    path.write_text(json.dumps(payload), encoding="utf-8")

    blocks = get_renderer(".geojson")(str(path))
    grouped = _blocks_by_type(blocks)
    assert grouped["meta"][0]["format"] == "gis"
    assert grouped["image"], "GIS render must produce a map image"
    assert grouped["image"][0]["image"].size[0] > 0
    assert "2 features" in grouped["full_text"][0]["text"]


def test_model3d_renders_canonical_views(tmp_path) -> None:
    trimesh = pytest.importorskip("trimesh")
    path = tmp_path / "box.stl"
    trimesh.creation.box(extents=(1.0, 2.0, 3.0)).export(str(path))

    blocks = get_renderer(".stl")(str(path))
    grouped = _blocks_by_type(blocks)
    assert grouped["meta"][0]["format"] == "model3d"
    assert len(grouped["image"]) == 3, "one image per canonical view"
    assert "8 vertices" in grouped["full_text"][0]["text"]
