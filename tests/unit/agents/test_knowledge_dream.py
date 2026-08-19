# -*- coding: utf-8 -*-
"""Unit tests for knowledge dream integrate / parse / catalog."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.agents.knowledge.dream import (
    KnowledgeUnit,
    _frontmatter_description,
    _frontmatter_description_from_body,
    _node_markdown,
    _parse_units,
    _slugify,
    integrate_units,
    load_catalog,
    run_knowledge_dream,
)
from qwenpaw.agents.knowledge.lock import KnowledgeLockTimeout
from qwenpaw.agents.knowledge.store import ensure_kb


def test_slugify_preserves_cjk_and_avoids_collision():
    assert _slugify("退款政策") == "退款政策"
    assert _slugify("业务实体-订单") == "业务实体-订单"
    assert _slugify("GMV口径") == "gmv口径"
    assert _slugify("Refund Policy") == "refund-policy"
    # Empty after strip → hashed fallback, not a shared "node".
    a = _slugify("!!!")
    b = _slugify("@@@")
    assert a.startswith("node-")
    assert b.startswith("node-")
    assert a != b


def test_frontmatter_description_collapses_and_truncates():
    long = "退款流程的第一步是联系客服。" * 20
    desc = _frontmatter_description(long)
    assert "\n" not in desc
    assert '"' not in desc
    assert len(desc) <= 120
    assert desc.endswith("...")


def test_frontmatter_description_strips_quotes_and_whitespace():
    desc = _frontmatter_description('  退款\n政策 "重点"  ')
    assert desc == '退款 政策 重点'


def test_frontmatter_description_from_body_skips_heading_and_links():
    body = "# 退款政策\n\n7天无理由退换\n\n## 关联\n\n- [[订单流程]]\n"
    assert _frontmatter_description_from_body(body) == "7天无理由退换"
    assert _frontmatter_description_from_body("", fallback="摘要回退") == "摘要回退"


def test_node_markdown_writes_description_frontmatter():
    unit = KnowledgeUnit(
        name="退款政策",
        bucket="wiki",
        summary="客户发起退款需在7日内联系客服。",
        confidence=0.9,
        signals=[],
    )
    md = _node_markdown(unit, agent_id="biz-1", derived_from=["2026-08-12.md"])
    assert 'name: "退款政策"' in md
    assert 'description: "客户发起退款需在7日内联系客服。"' in md
    # Body still carries the full summary.
    assert md.count("客户发起退款需在7日内联系客服。") == 2


def test_parse_units_from_json_array():
    raw = """
    [
      {
        "name": "GMV口径",
        "bucket": "wiki",
        "summary": "GMV不含退款",
        "confidence": 0.9,
        "signals": ["daily note"],
        "action_hint": "CREATE"
      }
    ]
    """
    units = _parse_units(raw, max_units=8)
    assert len(units) == 1
    assert units[0].name == "GMV口径"
    # Legacy flat bucket "wiki" is normalized to "business/wiki".
    assert units[0].bucket == "business/wiki"


def test_parse_units_deduplicates_steps_and_drops_blanks():
    from qwenpaw.agents.knowledge.dream import _parse_units

    raw = """[
      {"name": "A", "bucket": "test/test_cases", "summary": "s", "steps": [
        "登录", "登录", "", "下单", "  ", "下单"
      ]}
    ]"""
    units = _parse_units(raw, max_units=8)
    assert len(units) == 1
    assert units[0].steps == ["登录", "下单"]


def test_parse_units_from_fenced_json():
    raw = """```json
[{"name": "A", "bucket": "wiki", "summary": "s", "confidence": 0.8}]
```"""
    units = _parse_units(raw, max_units=8)
    assert len(units) == 1
    assert units[0].name == "A"


def test_integrate_units_writes_published_node(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.lock.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.dream.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    ensure_kb("kb_write")
    written = integrate_units(
        kb_id="kb_write",
        agent_id="ba1",
        units=[
            KnowledgeUnit(
                name="Refund Policy",
                bucket="procedure",
                summary="Refunds within 7 days.",
                confidence=0.95,
                signals=["explicit"],
            ),
        ],
        derived_from=["memory/2026-08-12.md"],
    )
    assert len(written) == 1
    text = written[0].read_text(encoding="utf-8")
    assert "Refund Policy" in text
    assert "derived_from:" in text
    assert "updated_by_agent: ba1" in text
    assert 'derived_from: ["memory/2026-08-12.md"]' in text
    # Duplicate title should be skipped.
    again = integrate_units(
        kb_id="kb_write",
        agent_id="ba1",
        units=[
            KnowledgeUnit(
                name="Refund Policy",
                bucket="procedure",
                summary="dup",
            ),
        ],
        derived_from=["memory/2026-08-12.md"],
    )
    assert again == []


def test_integrate_chinese_titles_do_not_collide(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.lock.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.dream.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    ensure_kb("kb_zh")
    written = integrate_units(
        kb_id="kb_zh",
        agent_id="ba1",
        units=[
            KnowledgeUnit(name="退款政策", bucket="procedure", summary="7天"),
            KnowledgeUnit(name="业务实体-订单", bucket="wiki", summary="订单"),
        ],
        derived_from=["memory/2026-08-12.md"],
    )
    assert len(written) == 2
    stems = {p.stem for p in written}
    assert "退款政策" in stems
    assert "业务实体-订单" in stems


def test_integrate_correct_goes_to_inbox(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.lock.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.dream.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    ensure_kb("kb_inbox")
    written = integrate_units(
        kb_id="kb_inbox",
        agent_id="ba1",
        units=[
            KnowledgeUnit(
                name="旧口径修正",
                bucket="wiki",
                summary="应改为不含税",
                action_hint="CORRECT",
            ),
        ],
        derived_from=["memory/2026-08-12.md"],
        write_mode="open",
    )
    assert len(written) == 1
    assert written[0].parent.name == "_inbox"
    assert "status: inbox" in written[0].read_text(encoding="utf-8")


def test_integrate_semantic_dup_routed_to_inbox(tmp_path, monkeypatch):
    """A unit flagged as a semantic duplicate is held in _inbox, not skipped."""
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.lock.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.dream.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    ensure_kb("kb_sem")
    units = [
        KnowledgeUnit(
            name="客户画像分析",
            bucket="wiki",
            summary="基于订单的画像",
            confidence=0.9,
        ),
        KnowledgeUnit(
            name="全新知识点",
            bucket="wiki",
            summary="独立内容",
            confidence=0.9,
        ),
    ]
    written = integrate_units(
        kb_id="kb_sem",
        agent_id="ba1",
        units=units,
        derived_from=["memory/2026-08-12.md"],
        write_mode="open",
        semantic_dup_names={"客户画像分析"},
    )
    assert len(written) == 2
    by_stem = {p.stem: p for p in written}
    # Semantic duplicate → inbox.
    assert by_stem["客户画像分析"].parent.name == "_inbox"
    inbox_text = by_stem["客户画像分析"].read_text(encoding="utf-8")
    assert "status: inbox" in inbox_text
    assert "inbox_reason: semantic_dup" in inbox_text
    # Non-duplicate → published.
    assert by_stem["全新知识点"].parent.name == "wiki"
    assert "status: published" in by_stem["全新知识点"].read_text(encoding="utf-8")


def test_integrate_semantic_dup_skipped_if_exact_title_exists(tmp_path, monkeypatch):
    """With merge disabled, exact title still skips (no near-dup file)."""
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.lock.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.dream.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    ensure_kb("kb_sem_exact")
    first = integrate_units(
        kb_id="kb_sem_exact",
        agent_id="ba1",
        units=[
            KnowledgeUnit(name="客户画像", bucket="wiki", summary="v1"),
        ],
        derived_from=["memory/2026-08-12.md"],
        merge_enabled=False,
    )
    assert len(first) == 1
    # Same title + merge off → skipped (exact match, no second file).
    again = integrate_units(
        kb_id="kb_sem_exact",
        agent_id="ba1",
        units=[
            KnowledgeUnit(name="客户画像", bucket="wiki", summary="v2"),
        ],
        derived_from=["memory/2026-08-12.md"],
        semantic_dup_names={"客户画像"},
        merge_enabled=False,
    )
    assert again == []


def test_integrate_exact_title_corroborates_when_merge_enabled(tmp_path, monkeypatch):
    """Exact title/slug hit with merge on → CORROBORATE, not silent skip."""
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.lock.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.dream.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    ensure_kb("kb_exact_merge")
    first = integrate_units(
        kb_id="kb_exact_merge",
        agent_id="ba1",
        units=[
            KnowledgeUnit(name="客户画像", bucket="business/wiki", summary="v1"),
        ],
        derived_from=["memory/day1.md"],
        merge_enabled=True,
    )
    assert len(first) == 1
    again = integrate_units(
        kb_id="kb_exact_merge",
        agent_id="ba1",
        units=[
            KnowledgeUnit(
                name="客户画像",
                bucket="business/wiki",
                summary="v2 再确认",
                signals=["note"],
                action_hint="CORROBORATE",
            ),
        ],
        derived_from=["memory/day2.md"],
        merge_enabled=True,
    )
    assert len(again) == 1
    assert again[0] == first[0]
    text = again[0].read_text(encoding="utf-8")
    assert "v1" in text  # original summary body preserved under CORROBORATE
    assert "corroborate_count: 1" in text
    assert "merge_count:" not in text or "merge_count: 0" in text
    assert "memory/day2.md" in text
    assert "note" in text
    root = tmp_path / "knowledge_bases" / "kb_exact_merge"
    index = (root / "_audit" / "index.jsonl").read_text(encoding="utf-8")
    entry = __import__("json").loads(index.strip().splitlines()[-1])
    assert entry["mode"] == "CORROBORATE"
    assert entry.get("corroborate_count") == 1
    assert entry.get("merge_count", 0) == 0


def test_integrate_exact_title_refine_with_steps(tmp_path, monkeypatch):
    """Exact title + substantive steps → REFINE into the existing node."""
    from qwenpaw.agents.knowledge.dream import MergePayload

    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.lock.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.dream.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    ensure_kb("kb_exact_refine")
    first = integrate_units(
        kb_id="kb_exact_refine",
        agent_id="td1",
        units=[
            KnowledgeUnit(
                name="支付-余额不足",
                bucket="test/test_cases",
                summary="旧用例",
                steps=["打开支付页"],
            ),
        ],
        derived_from=["memory/day1.md"],
        merge_enabled=True,
    )
    target = first[0]
    unit = KnowledgeUnit(
        name="支付-余额不足",
        bucket="test/test_cases",
        summary="补步骤",
        steps=["打开支付页", "提交并断言拒绝"],
    )
    again = integrate_units(
        kb_id="kb_exact_refine",
        agent_id="td1",
        units=[unit],
        derived_from=["memory/day2.md"],
        merge_enabled=True,
        merge_payloads={
            "支付-余额不足": MergePayload(
                target_path=target,
                expected_updated_at="",
                merged_body="# 支付-余额不足\n\n补步骤\n\n## 测试步骤\n1. 打开支付页\n2. 提交并断言拒绝\n",
                llm_ok=True,
            ),
        },
    )
    assert len(again) == 1
    assert again[0] == target
    text = target.read_text(encoding="utf-8")
    assert "提交并断言拒绝" in text
    assert "merge_count: 1" in text
    # REFINE keeps frontmatter description unless CORRECT; body is replaced.
    assert "# 支付-余额不足\n\n补步骤" in text or "补步骤\n\n## 测试步骤" in text
    assert "打开支付页" in text


def test_run_knowledge_dream_dedup_search_routes_to_inbox(tmp_path, monkeypatch):
    """dedup_search flagging a unit routes it to _inbox via run_knowledge_dream."""
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.lock.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.dream.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    ensure_kb("kb_dream_dedup")
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text("客户画像 基于订单\n", encoding="utf-8")

    async def fake_llm(_prompt: str) -> str:
        return (
            '[{"name": "客户画像", "bucket": "wiki", '
            '"summary": "基于订单", "confidence": 0.9}]'
        )

    async def dedup_search(name: str, summary: str) -> bool:
        return name == "客户画像"

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba1",
            workspace_dir=workspace,
            kb_id="kb_dream_dedup",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
            dedup_search=dedup_search,
        ),
    )
    assert result["skipped"] is False
    assert result["units"] == 1
    written_path = tmp_path / result["written"][0]
    assert written_path.parent.name == "_inbox"
    assert "status: inbox" in written_path.read_text(encoding="utf-8")


def test_run_knowledge_dream_dedup_search_failure_is_non_blocking(
    tmp_path, monkeypatch,
):
    """A failing dedup_search must not block publishing (best-effort)."""
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.lock.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.dream.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    ensure_kb("kb_dream_dedup_fail")
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text("新知识\n", encoding="utf-8")

    async def fake_llm(_prompt: str) -> str:
        return (
            '[{"name": "新知识", "bucket": "wiki", "summary": "s", '
            '"confidence": 0.9}]'
        )

    async def dedup_search(name: str, summary: str) -> bool:
        raise RuntimeError("index unavailable")

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba1",
            workspace_dir=workspace,
            kb_id="kb_dream_dedup_fail",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
            dedup_search=dedup_search,
        ),
    )
    assert result["skipped"] is False
    written_path = tmp_path / result["written"][0]
    # Failure → published (not blocked, not inboxed).
    assert written_path.parent.name == "wiki"
    assert "status: published" in written_path.read_text(encoding="utf-8")


def test_run_knowledge_dream_checkpoints_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.lock.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.dream.kb_root",
        lambda kb_id: tmp_path / "knowledge_bases" / kb_id,
    )
    ensure_kb("kb_dream")
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note = daily / f"{today}.md"
    note.write_text("GMV 口径不含退款\n", encoding="utf-8")

    async def fake_llm(_prompt: str) -> str:
        return (
            '[{"name": "GMV口径", "bucket": "wiki", '
            '"summary": "不含退款", "confidence": 0.9}]'
        )

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba1",
            workspace_dir=workspace,
            kb_id="kb_dream",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
        ),
    )
    assert result["skipped"] is False
    assert result["units"] == 1
    assert len(result["written"]) == 1
    catalog = load_catalog(workspace, "mem_metadata")
    assert note.name in catalog["processed"]

    # Second run with unchanged mtime should skip.
    result2 = asyncio.run(
        run_knowledge_dream(
            agent_id="ba1",
            workspace_dir=workspace,
            kb_id="kb_dream",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
        ),
    )
    assert result2["skipped"] is True
    assert result2["reason"] == "no_changed_daily"


def test_run_knowledge_dream_lock_timeout_skips_catalog(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note = daily / f"{today}.md"
    note.write_text("x\n", encoding="utf-8")

    async def fake_llm(_prompt: str) -> str:
        return '[{"name": "X", "bucket": "wiki", "summary": "s"}]'

    def boom(*_a, **_k):
        raise KnowledgeLockTimeout("locked")

    with patch(
        "qwenpaw.agents.knowledge.dream.integrate_units",
        side_effect=boom,
    ):
        result = asyncio.run(
            run_knowledge_dream(
                agent_id="ba1",
                workspace_dir=workspace,
                kb_id="kb_lock",
                daily_dir_name="memory",
                metadata_dir="mem_metadata",
                language="en",
                domain="business",
                scan_days=2,
                max_units=8,
                write_mode="open",
                inbox_enabled=False,
                llm_call=fake_llm,
            ),
        )
    assert result["skipped"] is True
    assert result["reason"] == "lock_timeout"
    catalog = load_catalog(workspace, "mem_metadata")
    assert note.name not in catalog.get("processed", {})


# --- extract catalog: related nodes, not filesystem-first -----------------


def _patch_dream_kb(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR", tmp_path,
    )
    root = lambda kb_id: tmp_path / "knowledge_bases" / kb_id
    monkeypatch.setattr("qwenpaw.agents.knowledge.lock.kb_root", root)
    monkeypatch.setattr("qwenpaw.agents.knowledge.dream.kb_root", root)


def _seed_published_node(tmp_path, kb_id, bucket, name, *, description=""):
    d = tmp_path / "knowledge_bases" / kb_id / bucket
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{_slugify(name)}.md"
    lines = ["---", f'name: "{name}"', f"bucket: {bucket}"]
    if description:
        lines.append(f'description: "{description}"')
    lines += ["---", "", f"# {name}", "", "body"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_catalog_query_chunks_splits_daily_sections():
    from qwenpaw.agents.knowledge.dream import _catalog_query_chunks

    chunks = _catalog_query_chunks(
        "## 2026-08-13.md\n退款政策\n\n## 2026-08-12.md\nGMV口径\n",
    )
    assert len(chunks) == 2
    assert "退款政策" in chunks[0]
    assert "GMV口径" in chunks[1]


def test_catalog_query_chunks_truncates_long_section():
    from qwenpaw.agents.knowledge.dream import (
        _CATALOG_QUERY_CHARS,
        _catalog_query_chunks,
    )

    blob = "退款" * 800
    chunks = _catalog_query_chunks(f"## today.md\n{blob}")
    assert len(chunks) == 1
    assert len(chunks[0]) == _CATALOG_QUERY_CHARS


def test_catalog_relevance_prefers_title_mentioned_in_notes():
    from qwenpaw.agents.knowledge.dream import _catalog_relevance_score

    query = "今天把退款政策改成7天无理由".lower()
    assert _catalog_relevance_score("退款政策", "", query) > 2
    assert _catalog_relevance_score("GMV口径", "", query) == 0


def test_published_catalog_ranks_related_over_filesystem_order(
    tmp_path, monkeypatch,
):
    from qwenpaw.agents.knowledge.dream import _published_node_catalog

    _patch_dream_kb(monkeypatch, tmp_path)
    ensure_kb("kb_cat")
    for i in range(90):
        _seed_published_node(
            tmp_path, "kb_cat", "business/wiki", f"占位节点{i:03d}",
        )
    _seed_published_node(
        tmp_path, "kb_cat", "business/wiki", "退款政策",
        description="7天无理由退换",
    )
    text = _published_node_catalog(
        "kb_cat", query="今日纪要：退款政策改为7天无理由",
    )
    assert "- 退款政策 (business/wiki)" in text
    assert "占位节点000" not in text
    assert text.splitlines()[0] == "- 退款政策 (business/wiki): 7天无理由退换"


def test_published_catalog_recalled_hits_come_first(tmp_path, monkeypatch):
    from qwenpaw.agents.knowledge.dream import _published_node_catalog

    _patch_dream_kb(monkeypatch, tmp_path)
    ensure_kb("kb_cat2")
    _seed_published_node(tmp_path, "kb_cat2", "business/wiki", "退款政策")
    text = _published_node_catalog(
        "kb_cat2",
        query="退款政策补充",
        recalled=[("语义召回节点", "test/test_cases")],
    )
    lines = text.splitlines()
    assert lines[0] == "- 语义召回节点 (test/test_cases)"
    assert "- 退款政策 (business/wiki)" in text


def test_published_catalog_falls_back_when_nothing_matches(
    tmp_path, monkeypatch,
):
    from qwenpaw.agents.knowledge.dream import _published_node_catalog

    _patch_dream_kb(monkeypatch, tmp_path)
    ensure_kb("kb_cat3")
    _seed_published_node(tmp_path, "kb_cat3", "business/wiki", "占位节点")
    text = _published_node_catalog("kb_cat3", query="完全无关的主题xyz")
    assert "- 占位节点 (business/wiki)" in text


def test_run_knowledge_dream_catalog_uses_daily_notes(tmp_path, monkeypatch):
    _patch_dream_kb(monkeypatch, tmp_path)
    ensure_kb("kb_cat_dream")
    for i in range(90):
        _seed_published_node(
            tmp_path, "kb_cat_dream", "business/wiki", f"占位节点{i:03d}",
        )
    _seed_published_node(
        tmp_path, "kb_cat_dream", "business/wiki", "退款政策",
    )
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text("退款政策改为7天\n", encoding="utf-8")
    captured: dict = {}

    async def fake_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return "[]"

    asyncio.run(
        run_knowledge_dream(
            agent_id="ba1",
            workspace_dir=workspace,
            kb_id="kb_cat_dream",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
        ),
    )
    prompt = captured["prompt"]
    assert "- 退款政策 (business/wiki)" in prompt
    assert "占位节点000" not in prompt


def test_run_knowledge_dream_catalog_search_failure_is_non_blocking(
    tmp_path, monkeypatch,
):
    _patch_dream_kb(monkeypatch, tmp_path)
    ensure_kb("kb_cat_fail")
    _seed_published_node(tmp_path, "kb_cat_fail", "business/wiki", "退款政策")
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text("退款政策\n", encoding="utf-8")
    captured: dict = {}

    async def fake_llm(prompt: str) -> str:
        captured["prompt"] = prompt
        return "[]"

    async def boom(_query: str):
        raise RuntimeError("index down")

    asyncio.run(
        run_knowledge_dream(
            agent_id="ba1",
            workspace_dir=workspace,
            kb_id="kb_cat_fail",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
            catalog_search=boom,
        ),
    )
    assert "- 退款政策 (business/wiki)" in captured["prompt"]


def test_try_parse_units_distinguishes_empty_from_malformed():
    from qwenpaw.agents.knowledge.dream import _try_parse_units

    empty, ok = _try_parse_units("[]", max_units=8)
    assert ok is True
    assert empty == []
    bad, bad_ok = _try_parse_units("sorry, no json", max_units=8)
    assert bad_ok is False
    assert bad == []
    obj, obj_ok = _try_parse_units('{"name": "x"}', max_units=8)
    assert obj_ok is False
    assert obj == []


def test_dedupe_units_keeps_first_canonical_title():
    from qwenpaw.agents.knowledge.dream import _dedupe_units

    units = _dedupe_units([
        KnowledgeUnit(name="退款政策", summary="a"),
        KnowledgeUnit(name="退款政策-补充", summary="b"),
        KnowledgeUnit(name="GMV口径", summary="c"),
    ])
    assert [u.name for u in units] == ["退款政策", "GMV口径"]


def test_title_mentioned_in_summary_ignores_neighbor_prefix():
    from qwenpaw.agents.knowledge.dream import _title_mentioned_in_summary

    assert _title_mentioned_in_summary(
        "退款政策", "按退款政策，7日内可退", unit_name="7天退款规则",
    )
    assert not _title_mentioned_in_summary(
        "退款政策", "补充包装要求", unit_name="退款政策说明",
    )


def test_run_knowledge_dream_parse_failure_does_not_checkpoint(
    tmp_path, monkeypatch,
):
    _patch_dream_kb(monkeypatch, tmp_path)
    ensure_kb("kb_parse_fail")
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note = daily / f"{today}.md"
    note.write_text("GMV 口径不含退款\n", encoding="utf-8")

    async def fake_llm(_prompt: str) -> str:
        return "I cannot extract knowledge today."

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba1",
            workspace_dir=workspace,
            kb_id="kb_parse_fail",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
        ),
    )
    assert result["skipped"] is False
    assert result.get("reason") == "extract_parse_failed"
    assert result["units"] == 0
    catalog = load_catalog(workspace, "mem_metadata")
    assert note.name not in catalog.get("processed", {})


def test_run_knowledge_dream_coverage_pass_adds_missed_unit(
    tmp_path, monkeypatch,
):
    _patch_dream_kb(monkeypatch, tmp_path)
    ensure_kb("kb_cover")
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text(
        "GMV 口径不含退款。退款政策为7天无理由。\n", encoding="utf-8",
    )

    async def fake_llm(prompt: str) -> str:
        if "补漏审查" in prompt or "coverage reviewer" in prompt.lower():
            return (
                '[{"name": "退款政策", "bucket": "wiki", '
                '"summary": "7天无理由", "confidence": 0.9}]'
            )
        return (
            '[{"name": "GMV口径", "bucket": "wiki", '
            '"summary": "不含退款", "confidence": 0.9}]'
        )

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba1",
            workspace_dir=workspace,
            kb_id="kb_cover",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
        ),
    )
    assert result["skipped"] is False
    assert result["units"] == 2
    names = " ".join(Path(p).read_text(encoding="utf-8") for p in result["written"])
    assert "GMV口径" in names
    assert "退款政策" in names


def test_run_knowledge_dream_coverage_failure_does_not_checkpoint(
    tmp_path, monkeypatch,
):
    _patch_dream_kb(monkeypatch, tmp_path)
    ensure_kb("kb_cover_fail")
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    note = daily / f"{today}.md"
    note.write_text("GMV 口径不含退款\n", encoding="utf-8")

    async def fake_llm(prompt: str) -> str:
        if "补漏审查" in prompt or "coverage reviewer" in prompt.lower():
            return "sorry, coverage unavailable"
        return (
            '[{"name": "GMV口径", "bucket": "wiki", '
            '"summary": "不含退款", "confidence": 0.9}]'
        )

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba1",
            workspace_dir=workspace,
            kb_id="kb_cover_fail",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
        ),
    )
    assert result["skipped"] is False
    assert result.get("reason") == "coverage_incomplete"
    assert result["units"] == 1
    assert len(result["written"]) == 1
    catalog = load_catalog(workspace, "mem_metadata")
    assert note.name not in catalog.get("processed", {})


def test_lexical_merge_candidate_links_title_in_summary(tmp_path, monkeypatch):
    from qwenpaw.agents.knowledge.dream import _lexical_merge_candidate

    _patch_dream_kb(monkeypatch, tmp_path)
    ensure_kb("kb_lex")
    _seed_published_node(tmp_path, "kb_lex", "business/wiki", "退款政策")
    cand = _lexical_merge_candidate(
        "kb_lex",
        KnowledgeUnit(
            name="7天退款规则",
            bucket="business/wiki",
            summary="按退款政策，客户7日内可退",
        ),
    )
    assert cand is not None
    assert cand.is_clear is True
    assert cand.path.endswith("退款政策.md")
