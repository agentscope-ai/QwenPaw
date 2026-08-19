# -*- coding: utf-8 -*-
"""Unit tests for KB memory search scope filtering and tagging."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from agentscope.message import ToolResultState
from qwenpaw.agents.memory.reme_light_memory_manager import (
    ReMeLightMemoryManager,
)


def _manager() -> ReMeLightMemoryManager:
    # Bypass __init__ (would try to import ReMe).
    mgr = object.__new__(ReMeLightMemoryManager)
    return mgr


def _chunk_text(chunk) -> str:
    return chunk.content[0].text


def _answer_with_sections() -> str:
    return (
        "========== knowledge/wiki/gmv.md:1-3 [0.9] ==========\n"
        "GMV body\n"
        "========== digest/foo.md:1-2 [0.8] ==========\n"
        "digest body\n"
        "========== knowledge/_inbox/draft.md:1-2 [0.7] ==========\n"
        "inbox body\n"
    )


def test_path_scope_tag_classifies_paths():
    mgr = _manager()
    assert (
        mgr._path_scope_tag(
            "knowledge/wiki/a.md",
            knowledge_dir="knowledge",
            daily_dir="memory",
            digest_dir="digest",
        )
        == "knowledge"
    )
    assert (
        mgr._path_scope_tag(
            "knowledge/_inbox/x.md",
            knowledge_dir="knowledge",
            daily_dir="memory",
            digest_dir="digest",
        )
        == "inbox"
    )
    assert (
        mgr._path_scope_tag(
            "digest/node.md",
            knowledge_dir="knowledge",
            daily_dir="memory",
            digest_dir="digest",
        )
        == "agent"
    )
    assert (
        mgr._path_scope_tag(
            "knowledge/_audit/2026-08-13_gmv_1.md",
            knowledge_dir="knowledge",
            daily_dir="memory",
            digest_dir="digest",
        )
        == "excluded"
    )
    assert (
        mgr._path_scope_tag(
            "knowledge/KB.md",
            knowledge_dir="knowledge",
            daily_dir="memory",
            digest_dir="digest",
        )
        == "excluded"
    )


def test_filter_scope_knowledge_drops_agent_inbox_and_audit():
    mgr = _manager()
    response = SimpleNamespace(
        success=True,
        answer=_answer_with_sections()
        + "========== knowledge/_audit/r.md:1-1 [0.6] ==========\naudit\n"
        + "========== knowledge/KB.md:1-1 [0.5] ==========\nmeta\n",
        metadata={
            "results": [
                {"path": "knowledge/wiki/gmv.md", "start_line": 1, "end_line": 3},
                {"path": "digest/foo.md", "start_line": 1, "end_line": 2},
                {
                    "path": "knowledge/_inbox/draft.md",
                    "start_line": 1,
                    "end_line": 2,
                },
                {"path": "knowledge/_audit/r.md", "start_line": 1, "end_line": 1},
                {"path": "knowledge/KB.md", "start_line": 1, "end_line": 1},
            ],
        },
    )
    mgr._filter_search_response_by_scope(
        response,
        scope="knowledge",
        knowledge_dir="knowledge",
        daily_dir="memory",
        digest_dir="digest",
        tag=False,
    )
    paths = [r["path"] for r in response.metadata["results"]]
    assert paths == ["knowledge/wiki/gmv.md"]
    assert "digest/foo.md" not in response.answer
    assert "_inbox" not in response.answer
    assert "_audit" not in response.answer
    assert "KB.md" not in response.answer
    assert "knowledge/wiki/gmv.md" in response.answer
    # Untagged: header still starts with ==========
    assert response.answer.lstrip().startswith("==========")


def test_tag_after_filter_keeps_parseable_headers():
    mgr = _manager()
    answer = (
        "========== knowledge/wiki/gmv.md:1-3 [0.9] ==========\n"
        "GMV body\n"
        "========== digest/foo.md:1-2 [0.8] ==========\n"
        "digest body\n"
    )
    tagged = mgr._tag_answer_by_scope(
        answer,
        scope="all",
        knowledge_dir="knowledge",
        daily_dir="memory",
        digest_dir="digest",
        add_labels=True,
    )
    assert "source: [knowledge]" in tagged
    assert "source: [digest]" in tagged
    # Headers remain parseable for rerank reconstruction.
    sections = mgr._parse_answer_into_sections(tagged)
    assert "knowledge/wiki/gmv.md:1-3" in sections
    assert "digest/foo.md:1-2" in sections


def test_list_memory_tools_gated_by_agent_type(monkeypatch):
    mgr = _manager()
    mgr.agent_id = "a1"

    def fake_load(agent_id: str):
        cfg = MagicMock()
        cfg.agent_type = agent_type
        return cfg

    agent_type = "default"
    monkeypatch.setattr(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        fake_load,
    )
    tools = mgr.list_memory_tools()
    assert [t.__name__ for t in tools] == ["memory_search"]

    agent_type = "business_analysis"
    tools = mgr.list_memory_tools()
    names = [t.__name__ for t in tools]
    assert names == ["memory_search", "save_to_knowledge"]


def test_apply_knowledge_watch_only_for_ba():
    from qwenpaw.agents.agent_types import (
        BUSINESS_ANALYSIS_AGENT_TYPE,
        DEFAULT_AGENT_TYPE,
    )
    from qwenpaw.agents.memory.reme_config import build_reme_app_config
    from qwenpaw.config.config import AgentProfileConfig

    default_cfg = AgentProfileConfig(
        id="d",
        name="D",
        agent_type=DEFAULT_AGENT_TYPE,
    )
    ba_cfg = AgentProfileConfig(
        id="b",
        name="B",
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    default_reme = build_reme_app_config(
        working_dir="/tmp/ws",
        agent_config=default_cfg,
    )
    ba_reme = build_reme_app_config(
        working_dir="/tmp/ws",
        agent_config=ba_cfg,
    )
    # default: no knowledge mount in watch list
    default_watch = default_reme["jobs"]["index_update_loop"]["watch_dirs"]
    assert not any(str(p).endswith("/knowledge") for p in default_watch)
    # BA: absolute knowledge mount path in watch list (not the literal "knowledge"
    # name nor the broken "knowledge_dir" config key).
    # BA: absolute published-bucket paths, not the whole knowledge mount.
    ba_watch = ba_reme["jobs"]["index_update_loop"]["watch_dirs"]
    normalized = [str(p).replace("\\", "/") for p in ba_watch]
    assert any(p.endswith("/ws/knowledge/business/wiki") for p in normalized), ba_watch
    assert not any(p.endswith("/ws/knowledge") for p in normalized)
    assert "knowledge" not in ba_watch
    assert "knowledge_dir" not in ba_watch
    reindex_watch = [
        str(p).replace("\\", "/") for p in ba_reme["jobs"]["reindex"]["watch_dirs"]
    ]
    assert any(p.endswith("/ws/knowledge/business/wiki") for p in reindex_watch)
    sync_watch = [
        str(p).replace("\\", "/") for p in ba_reme["jobs"]["index_sync"]["watch_dirs"]
    ]
    assert any(p.endswith("/ws/knowledge/test/test_cases") for p in sync_watch)


def test_knowledge_watch_resolves_to_mount_dir(tmp_path):
    """End-to-end: ReMe ApplicationConfig + watch_rules resolve to knowledge/."""
    from pathlib import Path

    from qwenpaw.agents.agent_types import BUSINESS_ANALYSIS_AGENT_TYPE
    from qwenpaw.agents.memory.reme_config import build_reme_app_config
    from qwenpaw.config.config import AgentProfileConfig

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "knowledge").mkdir()  # simulate mount

    cfg = AgentProfileConfig(
        id="ba",
        name="BA",
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    reme_cfg = build_reme_app_config(
        working_dir=str(workspace),
        agent_config=cfg,
    )

    # ReMe's ApplicationContext would parse this into ApplicationConfig,
    # which drops unknown keys (extra="ignore"). Simulate that.
    from reme.schema.application_config import ApplicationConfig
    from reme.steps.index._watch_rules import build_watch_rules

    app_config = ApplicationConfig(**reme_cfg)
    watch_dirs = reme_cfg["jobs"]["index_update_loop"]["watch_dirs"]
    rules = build_watch_rules(
        app_config,
        Path(workspace),
        watch_dirs=watch_dirs,
        watch_suffixes=["md"],
    )
    rule_paths = {str(Path(r.path)).replace("\\", "/") for r in rules}
    wiki = str(workspace / "knowledge" / "business" / "wiki").replace("\\", "/")
    mount = str(workspace / "knowledge").replace("\\", "/")
    assert wiki in rule_paths
    assert mount not in rule_paths
    assert str(workspace / "knowledge_dir") not in rule_paths


def test_custom_knowledge_dir_name_watches_correctly(tmp_path):
    """Custom mount name flows through to watch_dirs."""
    from pathlib import Path

    from qwenpaw.agents.agent_types import BUSINESS_ANALYSIS_AGENT_TYPE
    from qwenpaw.agents.memory.reme_config import build_reme_app_config
    from qwenpaw.config.config import AgentProfileConfig

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "biz_kb").mkdir()

    cfg = AgentProfileConfig(
        id="ba",
        name="BA",
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    cfg.running.reme_light_memory_config.knowledge_dir_name = "biz_kb"
    reme_cfg = build_reme_app_config(
        working_dir=str(workspace),
        agent_config=cfg,
    )
    mount_wiki = str(workspace / "biz_kb" / "business" / "wiki")
    watch = reme_cfg["jobs"]["index_update_loop"]["watch_dirs"]
    assert mount_wiki in watch or any(
        str(p).replace("\\", "/").endswith("/biz_kb/business/wiki") for p in watch
    )
    assert str(workspace / "biz_kb") not in watch

    from reme.schema.application_config import ApplicationConfig
    from reme.steps.index._watch_rules import build_watch_rules

    app_config = ApplicationConfig(**reme_cfg)
    watch_dirs = reme_cfg["jobs"]["index_update_loop"]["watch_dirs"]
    rules = build_watch_rules(
        app_config,
        Path(workspace),
        watch_dirs=watch_dirs,
        watch_suffixes=["md"],
    )
    paths = {str(Path(r.path)).replace("\\", "/") for r in rules}
    wiki = str(workspace / "biz_kb" / "business" / "wiki").replace("\\", "/")
    assert wiki in paths
    assert str(workspace / "biz_kb").replace("\\", "/") not in paths


def test_junction_watch_indexes_knowledge_relative_paths(tmp_path, monkeypatch):
    """Init scan through a real junction/symlink yields knowledge/... paths.

    This is the critical invariant for scope tagging: ``_path_scope_tag``
    classifies a search result as ``knowledge`` only when the indexed path
    starts with ``knowledge/``. ``collect_existing`` walks ``rule.path``
    (the mount) with ``rglob`` and stores ``p.absolute()`` — which must keep
    the junction prefix (not resolve to the shared KB target). A plain-dir
    test cannot catch a junction-resolving regression, so create a real link.
    """
    import os
    import sys
    from pathlib import Path

    from qwenpaw.agents.knowledge.mount import ensure_knowledge_mount
    from qwenpaw.agents.knowledge.store import ensure_kb
    from reme.steps.index._watch_rules import build_watch_rules, collect_existing

    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    ensure_kb("shared_idx_kb")
    shared_root = tmp_path / "knowledge_bases" / "shared_idx_kb"
    (shared_root / "wiki").mkdir(parents=True, exist_ok=True)
    (shared_root / "wiki" / "gmv.md").write_text("# GMV\n", encoding="utf-8")

    workspace = tmp_path / "ws"
    workspace.mkdir()
    try:
        mount = ensure_knowledge_mount(workspace, "shared_idx_kb")
    except Exception as exc:  # pragma: no cover - platform without link support
        pytest.skip(f"cannot create knowledge mount on this platform: {exc}")

    # The mount must be a link, not a plain dir, for this test to be meaningful.
    assert mount.is_symlink() or (
        sys.platform == "win32" and mount.exists()
    ), "mount was not created as a link"

    # Build watch rules the same way _apply_knowledge_watch does: absolute path.
    mount_abs = str(workspace / "knowledge")
    rules = build_watch_rules(
        app_config=object(),  # absolute paths bypass getattr(app_config, ...)
        workspace_path=Path(workspace),
        watch_dirs=[mount_abs],
        watch_suffixes=["md"],
    )
    existing = collect_existing(rules, recursive=True)
    indexed_paths = list(existing.keys())
    assert indexed_paths, "collect_existing found no files through the mount"
    # Paths must be under the workspace/knowledge prefix (junction-relative),
    # NOT under the real shared KB target — otherwise scope tagging breaks.
    rel = Path(indexed_paths[0]).absolute().relative_to(workspace).as_posix()
    assert rel.startswith("knowledge/"), (
        f"indexed path {indexed_paths[0]} is not knowledge-relative; "
        f"scope tagging would misclassify it. relative={rel}"
    )
    assert "knowledge_bases" not in indexed_paths[0], (
        f"junction was resolved to the real target: {indexed_paths[0]}"
    )


# ---------------------------------------------------------------------------
# Node-level recall (memory_search(recall="node"))
# ---------------------------------------------------------------------------

def _node_mem_cfg():
    return SimpleNamespace(
        knowledge_dir_name="knowledge",
        daily_dir="memory",
        digest_dir="digest",
        knowledge_search_default="knowledge",
    )


def _node_manager(captured, *, hits, success=True, answer=""):
    mgr = _manager()
    response = SimpleNamespace(success=success, answer=answer, metadata={"hits": hits})
    captured.setdefault("calls", [])

    async def _fake_run(name, **kwargs):
        captured["name"] = name
        captured["kwargs"] = kwargs
        captured["calls"].append({"name": name, "kwargs": dict(kwargs)})
        return response

    mgr._run_reme_job = _fake_run  # type: ignore[method-assign]
    return mgr


def test_node_recall_uses_knowledge_prefix_for_knowledge_scope():
    import asyncio

    captured: dict = {}
    mgr = _node_manager(
        captured,
        hits=[{"path": "knowledge/wiki/gmv.md", "name": "GMV", "description": "d", "score": 0.9}],
    )
    out = asyncio.run(
        mgr._memory_search_nodes(
            query="gmv",
            max_results=5,
            scope="knowledge",
            kb_enabled=True,
            mem_cfg=_node_mem_cfg(),
        )
    )
    assert captured["name"] == "node_search"
    from qwenpaw.agents.knowledge.store import knowledge_published_path_prefixes
    assert captured["kwargs"]["prefixes"] == knowledge_published_path_prefixes("knowledge")
    text = _chunk_text(out)
    assert "knowledge/wiki/gmv.md" in text
    assert "name: GMV" in text
    assert "description: d" in text
    assert "[0.9000]" in text
    assert "(source: knowledge)" in text
    assert "read_file" in text


def test_node_recall_uses_digest_prefix_for_agent_scope():
    import asyncio

    captured: dict = {}
    mgr = _node_manager(
        captured,
        hits=[{"path": "digest/notes.md", "name": "N", "description": "x", "score": 0.5}],
    )
    asyncio.run(
        mgr._memory_search_nodes(
            query="q",
            max_results=3,
            scope="agent",
            kb_enabled=True,
            mem_cfg=_node_mem_cfg(),
        )
    )
    assert captured["kwargs"]["prefixes"] == ["digest/"]


def test_node_recall_all_scope_combines_digest_and_knowledge_prefixes():
    import asyncio

    captured: dict = {}
    mgr = _node_manager(captured, hits=[])
    asyncio.run(
        mgr._memory_search_nodes(
            query="q",
            max_results=3,
            scope="all",
            kb_enabled=True,
            mem_cfg=_node_mem_cfg(),
        )
    )
    from qwenpaw.agents.knowledge.store import knowledge_published_path_prefixes

    prefix_calls = [c["kwargs"]["prefixes"] for c in captured["calls"]]
    assert ["digest/"] in prefix_calls
    assert knowledge_published_path_prefixes("knowledge") in prefix_calls


def test_node_recall_default_agent_all_scope_is_digest_only():
    import asyncio

    captured: dict = {}
    mgr = _node_manager(captured, hits=[])
    asyncio.run(
        mgr._memory_search_nodes(
            query="q",
            max_results=3,
            scope="all",
            kb_enabled=False,
            mem_cfg=_node_mem_cfg(),
        )
    )
    assert captured["kwargs"]["prefixes"] == ["digest/"]


def test_node_recall_excludes_inbox_nodes():
    import asyncio

    captured: dict = {}
    mgr = _node_manager(
        captured,
        hits=[
            {"path": "knowledge/_inbox/draft.md", "name": "Draft", "description": "d", "score": 0.95},
            {"path": "knowledge/wiki/policy.md", "name": "Policy", "description": "p", "score": 0.4},
        ],
    )
    out = asyncio.run(
        mgr._memory_search_nodes(
            query="q",
            max_results=5,
            scope="knowledge",
            kb_enabled=True,
            mem_cfg=_node_mem_cfg(),
        )
    )
    text = _chunk_text(out)
    assert "_inbox/draft.md" not in text
    assert "knowledge/wiki/policy.md" in text


def test_node_recall_empty_hits_returns_no_memory_results():
    import asyncio

    from qwenpaw.agents.memory.reme_light_memory_manager import NO_MEMORY_RESULTS

    captured: dict = {}
    mgr = _node_manager(captured, hits=[])
    out = asyncio.run(
        mgr._memory_search_nodes(
            query="q",
            max_results=5,
            scope="knowledge",
            kb_enabled=True,
            mem_cfg=_node_mem_cfg(),
        )
    )
    assert _chunk_text(out) == NO_MEMORY_RESULTS


def test_node_recall_empty_hits_appends_inbox_hint():
    import asyncio

    from qwenpaw.agents.memory.reme_light_memory_manager import NO_MEMORY_RESULTS

    captured: dict = {}
    mgr = _node_manager(captured, hits=[])
    mem = _node_mem_cfg()
    mem.knowledge_base_id = "kb_hint"
    with patch(
        "qwenpaw.agents.knowledge.dream.list_inbox_items",
        return_value=[SimpleNamespace(), SimpleNamespace()],
    ):
        out = asyncio.run(
            mgr._memory_search_nodes(
                query="q",
                max_results=5,
                scope="knowledge",
                kb_enabled=True,
                mem_cfg=mem,
            )
        )
    text = _chunk_text(out)
    assert NO_MEMORY_RESULTS in text
    assert "2 pending _inbox" in text


def test_node_recall_reme_not_started_returns_error():
    import asyncio

    mgr = _manager()

    async def _none_run(name, **kwargs):
        return None

    mgr._run_reme_job = _none_run  # type: ignore[method-assign]
    out = asyncio.run(
        mgr._memory_search_nodes(
            query="q",
            max_results=5,
            scope="knowledge",
            kb_enabled=True,
            mem_cfg=_node_mem_cfg(),
        )
    )
    assert out.state == ToolResultState.ERROR


def test_memory_search_recall_node_routes_to_node_search():
    """End-to-end: memory_search(recall='node') bypasses the chunk pipeline."""
    import asyncio

    from qwenpaw.agents.agent_types import BUSINESS_ANALYSIS_AGENT_TYPE
    from qwenpaw.agents.knowledge.store import knowledge_published_path_prefixes

    captured: dict = {}
    mgr = _manager()
    mgr.agent_id = "biz-1"

    response = SimpleNamespace(
        success=True, answer="", metadata={"hits": [{"path": "knowledge/wiki/gmv.md", "name": "GMV", "description": "d", "score": 0.9}]},
    )

    async def _fake_run(name, **kwargs):
        captured["name"] = name
        captured["kwargs"] = kwargs
        return response

    mgr._run_reme_job = _fake_run  # type: ignore[method-assign]

    cfg = MagicMock()
    cfg.agent_type = BUSINESS_ANALYSIS_AGENT_TYPE
    cfg.running.reme_light_memory_config = _node_mem_cfg()

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        return_value=cfg,
    ):
        out = asyncio.run(mgr.memory_search("gmv", recall="node", scope="knowledge", bucket="all"))

    assert captured["name"] == "node_search"
    assert captured["kwargs"]["prefixes"] == knowledge_published_path_prefixes("knowledge")
    assert "name: GMV" in _chunk_text(out)


def test_memory_search_recall_invalid_falls_back_to_chunk():
    """An unknown recall value normalizes to 'chunk' (the default path)."""
    import asyncio

    from qwenpaw.agents.agent_types import DEFAULT_AGENT_TYPE

    captured: dict = {}
    mgr = _manager()
    mgr.agent_id = "d-1"

    response = SimpleNamespace(success=True, answer="chunk-result", metadata={})

    async def _fake_run(name, **kwargs):
        captured["name"] = name
        return response

    mgr._run_reme_job = _fake_run  # type: ignore[method-assign]
    mgr._get_reranker_config = lambda: None  # type: ignore[method-assign]

    cfg = MagicMock()
    cfg.agent_type = DEFAULT_AGENT_TYPE
    cfg.running.reme_light_memory_config = _node_mem_cfg()

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        return_value=cfg,
    ):
        out = asyncio.run(mgr.memory_search("q", recall="weird"))

    # Chunk path uses "search", not "node_search".
    assert captured["name"] == "search"
    assert _chunk_text(out) == "chunk-result"


# ---------------------------------------------------------------------------
# System-prompt guidance for the recall parameter
# ---------------------------------------------------------------------------

def test_memory_guidance_includes_recall_section_for_kb_agents():
    from qwenpaw.agents.memory.prompts import build_memory_guidance_prompt

    zh = build_memory_guidance_prompt(
        language="zh", daily_dir="memory", knowledge_enabled=True, knowledge_dir="knowledge",
    )
    en = build_memory_guidance_prompt(
        language="en", daily_dir="memory", knowledge_enabled=True, knowledge_dir="knowledge",
    )
    # Both languages document the two recall modes and the rule of thumb.
    for text in (zh, en):
        assert "recall" in text
        assert "chunk" in text
        assert "node" in text
        assert "bucket" in text
        assert "read_file" in text
    # ZH carries the scenario cues; EN carries the rule-of-thumb phrasing.
    assert "盘点" in zh
    assert "引用内容" in zh
    assert "what we have" in en
    assert "what it says" in en
    # The knowledge_dir placeholder must be substituted, not left bare.
    assert "{knowledge_dir}" not in zh
    assert "{knowledge_dir}" not in en
    assert "knowledge" in zh
    assert "knowledge" in en


def test_memory_guidance_omits_recall_section_for_default_agents():
    from qwenpaw.agents.memory.prompts import build_memory_guidance_prompt

    base = build_memory_guidance_prompt(
        language="en", daily_dir="memory", knowledge_enabled=False,
    )
    # Default agents have no KB / node recall; the chunk-only base guidance
    # must not advertise a recall parameter it cannot meaningfully use.
    assert "recall" not in base


def test_merge_dual_quota_keeps_both_sides():
    mgr = _manager()
    knowledge = [{"path": f"knowledge/business/wiki/{i}.md"} for i in range(5)]
    agent = [{"path": f"digest/{i}.md"} for i in range(5)]
    merged = mgr._merge_dual_quota(knowledge, agent, 5)
    k_count = sum(1 for r in merged if r["path"].startswith("knowledge/"))
    a_count = sum(1 for r in merged if r["path"].startswith("digest/"))
    assert len(merged) == 5
    assert k_count == 3
    assert a_count == 2


def test_merge_dual_quota_knowledge_floor_at_small_cap():
    """cap=2: knowledge takes both seats so digest cannot crowd the KB."""
    mgr = _manager()
    knowledge = [{"path": f"knowledge/business/wiki/{i}.md"} for i in range(3)]
    agent = [{"path": f"digest/{i}.md"} for i in range(3)]
    merged = mgr._merge_dual_quota(knowledge, agent, 2)
    assert [r["path"] for r in merged] == [
        "knowledge/business/wiki/0.md",
        "knowledge/business/wiki/1.md",
    ]


def test_merge_dual_quota_fills_from_knowledge_when_agent_short():
    mgr = _manager()
    knowledge = [{"path": f"knowledge/x/{i}.md"} for i in range(5)]
    merged = mgr._merge_dual_quota(knowledge, [{"path": "digest/a.md"}], 5)
    assert len(merged) == 5
    k_count = sum(1 for r in merged if r["path"].startswith("knowledge/"))
    a_count = sum(1 for r in merged if r["path"].startswith("digest/"))
    assert k_count == 4
    assert a_count == 1
    assert merged[3]["path"] == "digest/a.md"
    assert merged[4]["path"].startswith("knowledge/")


def test_chunk_search_knowledge_scope_passes_published_prefixes():
    import asyncio

    from qwenpaw.agents.agent_types import BUSINESS_ANALYSIS_AGENT_TYPE
    from qwenpaw.agents.knowledge.store import knowledge_published_path_prefixes

    captured: dict = {}
    mgr = _manager()
    mgr.agent_id = "ba-1"
    mgr._get_reranker_config = lambda: None  # type: ignore[method-assign]

    response = SimpleNamespace(
        success=True,
        answer="========== knowledge/business/wiki/gmv.md:1-2 [0.9] ==========\nGMV",
        metadata={"results": [{"path": "knowledge/business/wiki/gmv.md", "start_line": 1, "end_line": 2, "text": "GMV"}]},
    )

    async def _fake_run(name, **kwargs):
        captured["name"] = name
        captured["kwargs"] = kwargs
        return response

    mgr._run_reme_job = _fake_run  # type: ignore[method-assign]
    cfg = MagicMock()
    cfg.agent_type = BUSINESS_ANALYSIS_AGENT_TYPE
    cfg.running.reme_light_memory_config = _node_mem_cfg()

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        return_value=cfg,
    ):
        asyncio.run(mgr.memory_search("gmv", scope="knowledge", bucket="all", max_results=3))

    assert captured["name"] == "search"
    assert captured["kwargs"]["search_filter"]["prefixes"] == (
        knowledge_published_path_prefixes("knowledge")
    )


def test_chunk_search_all_scope_runs_dual_search():
    import asyncio

    from qwenpaw.agents.agent_types import BUSINESS_ANALYSIS_AGENT_TYPE
    from qwenpaw.agents.knowledge.store import knowledge_published_path_prefixes

    captured: dict = {"calls": []}
    mgr = _manager()
    mgr.agent_id = "ba-1"
    mgr._get_reranker_config = lambda: None  # type: ignore[method-assign]

    k_resp = SimpleNamespace(
        success=True,
        answer="========== knowledge/business/wiki/gmv.md:1-2 [0.9] ==========\nGMV",
        metadata={
            "results": [
                {
                    "path": "knowledge/business/wiki/gmv.md",
                    "start_line": 1,
                    "end_line": 2,
                    "text": "GMV",
                },
            ],
        },
    )
    a_resp = SimpleNamespace(
        success=True,
        answer="========== digest/notes.md:1-2 [0.8] ==========\nnote",
        metadata={
            "results": [
                {
                    "path": "digest/notes.md",
                    "start_line": 1,
                    "end_line": 2,
                    "text": "note",
                },
            ],
        },
    )

    async def _fake_run(name, **kwargs):
        captured["calls"].append({"name": name, "kwargs": dict(kwargs)})
        prefixes = (kwargs.get("search_filter") or {}).get("prefixes") or []
        if any(str(p).startswith("knowledge/") for p in prefixes):
            return k_resp
        return a_resp

    mgr._run_reme_job = _fake_run  # type: ignore[method-assign]
    cfg = MagicMock()
    cfg.agent_type = BUSINESS_ANALYSIS_AGENT_TYPE
    cfg.running.reme_light_memory_config = _node_mem_cfg()

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        return_value=cfg,
    ):
        out = asyncio.run(mgr.memory_search("gmv", scope="all", bucket="all", max_results=5))

    assert len(captured["calls"]) == 2
    assert all(c["name"] == "search" for c in captured["calls"])
    prefix_sets = [
        c["kwargs"]["search_filter"]["prefixes"] for c in captured["calls"]
    ]
    assert knowledge_published_path_prefixes("knowledge") in prefix_sets
    assert ["digest/", "memory/"] in prefix_sets
    text = _chunk_text(out)
    assert "knowledge/business/wiki/gmv.md" in text
    assert "digest/notes.md" in text
    assert "source: [knowledge]" in text
    assert "source: [digest]" in text


def test_save_to_knowledge_triggers_index_sync():
    import asyncio

    from qwenpaw.agents.agent_types import BUSINESS_ANALYSIS_AGENT_TYPE

    captured: dict = {"jobs": []}
    mgr = _manager()
    mgr.agent_id = "ba-1"
    mgr._reme = object()  # present so _sync_search_index does not no-op

    async def _fake_run(name, **kwargs):
        captured["jobs"].append(name)
        return SimpleNamespace(success=True, answer="", metadata={})

    mgr._run_reme_job = _fake_run  # type: ignore[method-assign]
    mgr._kb_enabled = lambda: True  # type: ignore[method-assign]

    written = [MagicMock()]
    written[0].__str__ = lambda self: "knowledge/business/wiki/gmv.md"  # type: ignore[method-assign]

    cfg = MagicMock()
    cfg.agent_type = BUSINESS_ANALYSIS_AGENT_TYPE
    cfg.running.reme_light_memory_config = SimpleNamespace(
        knowledge_dir_name="knowledge",
        knowledge_base_id="kb1",
        knowledge_write_mode="open",
        knowledge_inbox_enabled=False,
        daily_dir="memory",
        digest_dir="digest",
    )

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        return_value=cfg,
    ), patch(
        "qwenpaw.agents.knowledge.dream.integrate_units",
        return_value=written,
    ):
        asyncio.run(
            mgr.save_to_knowledge(title="GMV", content="body", bucket="wiki"),
        )

    assert "index_sync" in captured["jobs"]


def test_index_sync_retries_then_succeeds():
    import asyncio

    from qwenpaw.agents.memory.reme_light_memory_manager import (
        ReMeLightMemoryManager,
        _INDEX_SYNC_ATTEMPTS,
    )

    mgr = object.__new__(ReMeLightMemoryManager)
    mgr._reme = object()
    calls = {"n": 0}

    async def _flaky(name, **kwargs):
        assert name == "index_sync"
        calls["n"] += 1
        if calls["n"] < 3:
            return None
        return SimpleNamespace(success=True, answer="", metadata={})

    mgr._run_reme_job = _flaky  # type: ignore[method-assign]
    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.asyncio.sleep",
        new=AsyncMock(),
    ):
        asyncio.run(mgr._sync_search_index())
    assert calls["n"] == 3
    assert calls["n"] <= _INDEX_SYNC_ATTEMPTS


def test_index_sync_exhausted_retries_does_not_raise():
    import asyncio

    from qwenpaw.agents.memory.reme_light_memory_manager import (
        ReMeLightMemoryManager,
        _INDEX_SYNC_ATTEMPTS,
    )

    mgr = object.__new__(ReMeLightMemoryManager)
    mgr._reme = object()
    calls = {"n": 0}

    async def _always_fail(name, **kwargs):
        calls["n"] += 1
        return SimpleNamespace(success=False, answer="busy", metadata={})

    mgr._run_reme_job = _always_fail  # type: ignore[method-assign]
    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.asyncio.sleep",
        new=AsyncMock(),
    ):
        asyncio.run(mgr._sync_search_index())
    assert calls["n"] == _INDEX_SYNC_ATTEMPTS


def test_index_sync_job_is_configured_for_kb_agents():
    from qwenpaw.agents.agent_types import BUSINESS_ANALYSIS_AGENT_TYPE
    from qwenpaw.agents.memory.reme_config import build_reme_app_config
    from qwenpaw.config.config import AgentProfileConfig

    cfg = AgentProfileConfig(
        id="b",
        name="B",
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    reme = build_reme_app_config(working_dir="/tmp/ws", agent_config=cfg)
    job = reme["jobs"]["index_sync"]
    assert job["steps"][0]["backend"] == "init_changes_step"
    assert "clear_store_step" not in [s.get("backend") for s in job["steps"]]
    watch = [str(p).replace("\\", "/") for p in job["watch_dirs"]]
    assert any(p.endswith("/ws/knowledge/business/wiki") for p in watch)
    assert not any(p.endswith("/ws/knowledge/_inbox") for p in watch)
    assert not any(p.endswith("/ws/knowledge") for p in watch)


def test_knowledge_scope_path_prefixes_by_bucket():
    from qwenpaw.agents.knowledge.store import (
        knowledge_published_path_prefixes,
        knowledge_scope_path_prefixes,
    )

    all_pub = knowledge_published_path_prefixes("knowledge")
    assert all_pub == knowledge_scope_path_prefixes("knowledge", "")
    assert "knowledge/business/" in all_pub
    assert "knowledge/test/" in all_pub

    test_only = knowledge_scope_path_prefixes("knowledge", "test")
    assert test_only == ["knowledge/test/"]
    cases = knowledge_scope_path_prefixes("knowledge", "test/test_cases")
    assert cases == ["knowledge/test/test_cases/"]
    wiki = knowledge_scope_path_prefixes("knowledge", "wiki")
    assert "knowledge/business/wiki/" in wiki
    assert "knowledge/wiki/" in wiki
    assert knowledge_scope_path_prefixes("knowledge", "all") == all_pub
    assert knowledge_scope_path_prefixes("knowledge", "*") == all_pub
    assert knowledge_scope_path_prefixes("knowledge", "nope") == []


def test_chunk_search_bucket_test_passes_test_prefix():
    import asyncio

    from qwenpaw.agents.agent_types import TEST_DESIGN_AGENT_TYPE
    from qwenpaw.agents.knowledge.store import knowledge_scope_path_prefixes

    captured: dict = {}
    mgr = _manager()
    mgr.agent_id = "td-1"
    mgr._get_reranker_config = lambda: None  # type: ignore[method-assign]
    response = SimpleNamespace(success=True, answer="", metadata={"results": []})

    async def _fake_run(name, **kwargs):
        captured["kwargs"] = kwargs
        return response

    mgr._run_reme_job = _fake_run  # type: ignore[method-assign]
    cfg = MagicMock()
    cfg.agent_type = TEST_DESIGN_AGENT_TYPE
    cfg.running.reme_light_memory_config = _node_mem_cfg()

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        return_value=cfg,
    ):
        asyncio.run(
            mgr.memory_search("refund", scope="knowledge", bucket="test"),
        )

    assert captured["kwargs"]["search_filter"]["prefixes"] == (
        knowledge_scope_path_prefixes("knowledge", "test")
    )


def test_memory_search_unknown_bucket_returns_error():
    import asyncio

    from qwenpaw.agents.agent_types import BUSINESS_ANALYSIS_AGENT_TYPE

    mgr = _manager()
    mgr.agent_id = "ba-1"
    cfg = MagicMock()
    cfg.agent_type = BUSINESS_ANALYSIS_AGENT_TYPE
    cfg.running.reme_light_memory_config = _node_mem_cfg()

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        return_value=cfg,
    ):
        out = asyncio.run(mgr.memory_search("q", bucket="finance"))

    assert out.state == ToolResultState.ERROR
    assert "unknown bucket" in _chunk_text(out)


def test_node_hit_enrichment_reads_frontmatter(tmp_path):
    mgr = _manager()
    mgr.working_dir = str(tmp_path)
    node = tmp_path / "knowledge" / "test" / "test_cases"
    node.mkdir(parents=True)
    (node / "pay.md").write_text(
        '---\nname: "支付拒绝"\nbucket: test/test_cases\n'
        'priority: "P0"\nrequirement_id: "REQ-1"\n---\n\n# 支付拒绝\n',
        encoding="utf-8",
    )
    hit = {
        "path": "knowledge/test/test_cases/pay.md",
        "name": "支付拒绝",
        "description": "应拒绝",
        "score": 0.8,
    }
    enriched = mgr._enrich_node_hit(hit)
    assert enriched["bucket"] == "test/test_cases"
    assert enriched["priority"] == "P0"
    assert enriched["requirement_id"] == "REQ-1"
    formatted = mgr._format_node_hit(
        enriched,
        knowledge_dir="knowledge",
        mem_cfg=_node_mem_cfg(),
    )
    assert "bucket: test/test_cases" in formatted
    assert "priority: P0" in formatted
    assert "requirement_id: REQ-1" in formatted
    assert "read_file" not in formatted


def test_resolve_kb_search_defaults_business_is_knowledge_plus_business():
    from qwenpaw.agents.agent_types import BUSINESS_ANALYSIS_AGENT_TYPE

    mgr = _manager()
    mem_cfg = _node_mem_cfg()
    mem_cfg.knowledge_search_default = "knowledge"
    scope, bucket = mgr._resolve_kb_search_defaults(
        scope="",
        bucket="",
        mem_cfg=mem_cfg,
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    assert scope == "knowledge"
    assert bucket == "business"


def test_resolve_kb_search_defaults_bucket_all_clears_filter():
    from qwenpaw.agents.agent_types import BUSINESS_ANALYSIS_AGENT_TYPE

    mgr = _manager()
    scope, bucket = mgr._resolve_kb_search_defaults(
        scope="knowledge",
        bucket="all",
        mem_cfg=_node_mem_cfg(),
        agent_type=BUSINESS_ANALYSIS_AGENT_TYPE,
    )
    assert scope == "knowledge"
    assert bucket == ""


def test_resolve_kb_search_defaults_test_agent_keeps_all_published():
    from qwenpaw.agents.agent_types import TEST_DESIGN_AGENT_TYPE

    mgr = _manager()
    scope, bucket = mgr._resolve_kb_search_defaults(
        scope="",
        bucket="",
        mem_cfg=_node_mem_cfg(),
        agent_type=TEST_DESIGN_AGENT_TYPE,
    )
    assert scope == "knowledge"
    assert bucket == ""


def test_ba_default_memory_search_uses_business_prefixes():
    import asyncio

    from qwenpaw.agents.agent_types import BUSINESS_ANALYSIS_AGENT_TYPE
    from qwenpaw.agents.knowledge.store import knowledge_scope_path_prefixes

    captured: dict = {}
    mgr = _manager()
    mgr.agent_id = "ba-1"
    mgr._get_reranker_config = lambda: None  # type: ignore[method-assign]
    response = SimpleNamespace(
        success=True,
        answer="========== knowledge/business/wiki/gmv.md:1-2 [0.9] ==========\nGMV",
        metadata={
            "results": [
                {
                    "path": "knowledge/business/wiki/gmv.md",
                    "start_line": 1,
                    "end_line": 2,
                    "text": "GMV",
                },
            ],
        },
    )

    async def _fake_run(name, **kwargs):
        captured["kwargs"] = kwargs
        return response

    mgr._run_reme_job = _fake_run  # type: ignore[method-assign]
    cfg = MagicMock()
    cfg.agent_type = BUSINESS_ANALYSIS_AGENT_TYPE
    mem_cfg = _node_mem_cfg()
    mem_cfg.knowledge_search_default = "knowledge"
    cfg.running.reme_light_memory_config = mem_cfg

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        return_value=cfg,
    ):
        asyncio.run(mgr.memory_search("gmv"))

    assert captured["kwargs"]["search_filter"]["prefixes"] == (
        knowledge_scope_path_prefixes("knowledge", "business")
    )


def test_drop_link_expansions_rebuilds_without_neighbors():
    mgr = _manager()
    answer = (
        "========== knowledge/business/wiki/gmv.md:1-2 [score=0.9000] ==========\n"
        "GMV body\n"
        "  outlinks (2):\n"
        "      → knowledge/business/wiki/other.md  name=Other\n"
        "  inlinks (1):\n"
        "      ← knowledge/test/test_cases/pay.md  name=Pay\n"
    )
    response = SimpleNamespace(
        success=True,
        answer=answer,
        metadata={
            "results": [
                {
                    "path": "knowledge/business/wiki/gmv.md",
                    "start_line": 1,
                    "end_line": 2,
                    "text": "GMV body",
                    "scores": {"score": 0.9},
                },
            ],
            "link_expansion": {
                "knowledge/business/wiki/gmv.md": {
                    "outlinks": [{"path": "knowledge/business/wiki/other.md", "meta": {}, "anchors": []}],
                    "inlinks": [{"path": "knowledge/test/test_cases/pay.md", "meta": {}, "anchors": []}],
                },
            },
        },
    )
    mgr._drop_link_expansions(response)
    assert response.metadata["link_expansion"] == {}
    assert "outlinks" not in response.answer
    assert "inlinks" not in response.answer
    assert "GMV body" in response.answer
    assert "knowledge/business/wiki/gmv.md" in response.answer


def test_strip_expansion_lines_keeps_chunk_body():
    mgr = _manager()
    answer = (
        "========== knowledge/wiki/a.md:1-2 [0.9] ==========\n"
        "keep me\n"
        "  outlinks (1):\n"
        "      → knowledge/wiki/b.md  name=B\n"
        "========== knowledge/wiki/c.md:3-4 [0.8] ==========\n"
        "also keep\n"
    )
    stripped = mgr._strip_expansion_lines(answer)
    assert "keep me" in stripped
    assert "also keep" in stripped
    assert "outlinks" not in stripped
    assert "knowledge/wiki/b.md" not in stripped


def test_auto_memory_search_ba_uses_knowledge_business_and_drops_links():
    import asyncio

    from qwenpaw.agents.agent_types import BUSINESS_ANALYSIS_AGENT_TYPE
    from qwenpaw.agents.knowledge.store import knowledge_scope_path_prefixes

    captured: dict = {"calls": []}
    mgr = _manager()
    mgr.agent_id = "ba-1"
    mgr._get_reranker_config = lambda: None  # type: ignore[method-assign]
    mgr._build_query = lambda msgs: "gmv"  # type: ignore[method-assign]
    mgr._build_auto_memory_search_msg = MagicMock(return_value="fake_msg")
    response = SimpleNamespace(
        success=True,
        answer=(
            "========== knowledge/business/wiki/gmv.md:1-2 [score=0.9000] ==========\n"
            "GMV body\n"
            "  outlinks (1):\n"
            "      → knowledge/business/wiki/other.md  name=Other\n"
        ),
        metadata={
            "results": [
                {
                    "path": "knowledge/business/wiki/gmv.md",
                    "start_line": 1,
                    "end_line": 2,
                    "text": "GMV body",
                    "scores": {"score": 0.9},
                },
            ],
            "link_expansion": {"knowledge/business/wiki/gmv.md": {"outlinks": [], "inlinks": []}},
        },
    )

    async def _fake_run(name, **kwargs):
        captured["calls"].append({"name": name, "kwargs": dict(kwargs)})
        return response

    mgr._run_reme_job = _fake_run  # type: ignore[method-assign]
    mem_cfg = _node_mem_cfg()
    mem_cfg.knowledge_search_default = "knowledge"
    mem_cfg.auto_memory_search_config = SimpleNamespace(enabled=True, max_results=2)
    cfg = MagicMock()
    cfg.agent_type = BUSINESS_ANALYSIS_AGENT_TYPE
    cfg.running.reme_light_memory_config = mem_cfg

    with patch(
        "qwenpaw.agents.memory.reme_light_memory_manager.load_agent_config",
        return_value=cfg,
    ):
        result = asyncio.run(
            mgr.auto_memory_search([MagicMock()]),
        )

    assert result is not None
    assert captured["calls"]
    prefixes = captured["calls"][0]["kwargs"]["search_filter"]["prefixes"]
    assert prefixes == knowledge_scope_path_prefixes("knowledge", "business")
    assert "outlinks" not in result["text"]
    assert "GMV body" in result["text"]




