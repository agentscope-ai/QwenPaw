# -*- coding: utf-8 -*-
"""Unit tests for test-domain knowledge dream: prompt routing, buckets,
structured test fields, wikilink traceability, and agent-type routing.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from qwenpaw.agents.agent_types import (
    BUSINESS_ANALYSIS_AGENT_TYPE,
    DEFAULT_AGENT_TYPE,
    TEST_DESIGN_AGENT_TYPE,
    agent_type_to_domain,
    list_agent_types,
)
from qwenpaw.agents.knowledge.dream import (
    KnowledgeUnit,
    _node_markdown,
    _parse_units,
    integrate_units,
    run_knowledge_dream,
)
from qwenpaw.agents.knowledge.prompts import build_extract_prompt
from qwenpaw.agents.knowledge.store import (
    BUSINESS_BUCKETS,
    INBOX_BUCKET,
    KB_BUCKETS,
    PUBLISHED_BUCKETS,
    TEST_BUCKETS,
    ensure_kb,
)


def _patch_kb_roots(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR",
        tmp_path,
    )
    root = lambda kb_id: tmp_path / "knowledge_bases" / kb_id
    monkeypatch.setattr("qwenpaw.agents.knowledge.lock.kb_root", root)
    monkeypatch.setattr("qwenpaw.agents.knowledge.dream.kb_root", root)


# --- bucket layout ----------------------------------------------------------


def test_kb_buckets_are_domain_namespaced():
    assert "business/wiki" in KB_BUCKETS
    assert "business/procedure" in KB_BUCKETS
    assert "test/test_design" in KB_BUCKETS
    assert "test/test_cases" in KB_BUCKETS
    assert "test/test_data" in KB_BUCKETS
    assert "test/defects" in KB_BUCKETS
    assert INBOX_BUCKET in KB_BUCKETS
    assert INBOX_BUCKET not in PUBLISHED_BUCKETS
    assert INBOX_BUCKET not in BUSINESS_BUCKETS
    assert INBOX_BUCKET not in TEST_BUCKETS


def test_ensure_kb_creates_namespaced_bucket_dirs(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_layout")
    root = tmp_path / "knowledge_bases" / "kb_layout"
    for bucket in KB_BUCKETS:
        assert (root / bucket).is_dir(), f"missing bucket dir: {bucket}"
    assert (root / ".locks").is_dir()


# --- agent type -> domain ---------------------------------------------------


def test_test_design_agent_type_is_registered():
    ids = {t.id for t in list_agent_types()}
    assert TEST_DESIGN_AGENT_TYPE in ids


def test_agent_type_to_domain_mapping():
    assert agent_type_to_domain(BUSINESS_ANALYSIS_AGENT_TYPE) == "business"
    assert agent_type_to_domain(TEST_DESIGN_AGENT_TYPE) == "testcase"
    assert agent_type_to_domain(DEFAULT_AGENT_TYPE) == "business"
    assert agent_type_to_domain("nonexistent") == "business"


# --- prompt routing ---------------------------------------------------------


def test_build_extract_prompt_test_domain_zh():
    prompt = build_extract_prompt(
        language="zh", domain="testcase", daily_corpus="corpus", max_units=5,
    )
    assert "测试知识提炼助手" in prompt
    assert "test/test_cases" in prompt
    assert "preconditions" in prompt
    assert "requirement_id" in prompt
    assert "links" in prompt
    assert "5" in prompt


def test_build_extract_prompt_test_domain_en():
    prompt = build_extract_prompt(
        language="en", domain="testcase", daily_corpus="corpus", max_units=8,
    )
    assert "test knowledge units" in prompt
    assert "test/test_cases" in prompt
    assert "preconditions" in prompt


def test_build_extract_prompt_business_domain_unchanged():
    prompt = build_extract_prompt(
        language="zh", domain="business", daily_corpus="corpus", max_units=5,
    )
    assert "业务知识提炼助手" in prompt
    assert "business/wiki" in prompt
    assert "preconditions" not in prompt
    assert "test/test_cases" not in prompt
    assert "已有知识库节点" in prompt
    assert "（无）" in prompt
    assert "name / bucket / description" in prompt
    assert "定义、边界、例外、约束" in prompt


def test_build_extract_prompt_test_alias_works():
    p1 = build_extract_prompt(
        language="zh", domain="testcase", daily_corpus="c", max_units=5,
    )
    p2 = build_extract_prompt(
        language="zh", domain="test", daily_corpus="c", max_units=5,
    )
    assert p1 == p2


# --- _parse_units: domain-aware defaults + structured fields ----------------


def test_parse_units_test_domain_defaults_to_test_cases_bucket():
    raw = '[{"name": "支付-余额不足", "summary": "应拒绝"}]'
    units = _parse_units(raw, max_units=8, domain="testcase")
    assert len(units) == 1
    assert units[0].bucket == "test/test_cases"


def test_parse_units_business_domain_defaults_to_business_wiki():
    raw = '[{"name": "GMV口径", "summary": "不含退款"}]'
    units = _parse_units(raw, max_units=8, domain="business")
    assert len(units) == 1
    assert units[0].bucket == "business/wiki"


def test_parse_units_accepts_explicit_test_bucket():
    raw = (
        '[{"name": "支付等价类划分", "bucket": "test/test_design", '
        '"summary": "s"}]'
    )
    units = _parse_units(raw, max_units=8, domain="testcase")
    assert units[0].bucket == "test/test_design"


def test_parse_units_rejects_unknown_bucket_falls_back_to_domain_default():
    raw = '[{"name": "x", "bucket": "nonsense/whatever", "summary": "s"}]'
    units = _parse_units(raw, max_units=8, domain="testcase")
    assert units[0].bucket == "test/test_cases"


def test_parse_units_extracts_structured_test_fields():
    raw = (
        '[{"name": "支付-余额不足应拒绝", "bucket": "test/test_cases", '
        '"summary": "余额不足时支付应被拒绝", "confidence": 0.9, '
        '"signals": ["daily note"], "action_hint": "CREATE", '
        '"preconditions": "账户余额=0", '
        '"steps": ["发起支付", "观察返回"], '
        '"expected": "返回余额不足错误", "priority": "P0", '
        '"requirement_id": "REQ-PAY-1", '
        '"links": ["支付-余额充足应成功", "GMV口径"]}]'
    )
    units = _parse_units(raw, max_units=8, domain="testcase")
    assert len(units) == 1
    u = units[0]
    assert u.preconditions == "账户余额=0"
    assert u.steps == ["发起支付", "观察返回"]
    assert u.expected == "返回余额不足错误"
    assert u.priority == "P0"
    assert u.requirement_id == "REQ-PAY-1"
    assert u.links == ["支付-余额充足应成功", "GMV口径"]


def test_parse_units_business_units_have_empty_test_fields():
    raw = '[{"name": "GMV口径", "bucket": "business/wiki", "summary": "s"}]'
    units = _parse_units(raw, max_units=8, domain="business")
    u = units[0]
    assert u.preconditions == ""
    assert u.steps == []
    assert u.expected == ""
    assert u.priority == ""
    assert u.requirement_id == ""
    assert u.links == []


# --- _node_markdown: frontmatter + body + wikilinks -------------------------


def test_node_markdown_serializes_test_fields_to_frontmatter():
    unit = KnowledgeUnit(
        name="支付-余额不足应拒绝",
        bucket="test/test_cases",
        summary="余额不足时支付应被拒绝",
        confidence=0.9,
        signals=["daily"],
        preconditions="账户余额=0",
        steps=["发起支付", "观察返回"],
        expected="返回余额不足错误",
        priority="P0",
        requirement_id="REQ-PAY-1",
        links=["支付-余额充足应成功", "GMV口径"],
    )
    md = _node_markdown(unit, agent_id="td-1", derived_from=["memory/t.md"])
    assert 'name: "支付-余额不足应拒绝"' in md
    assert "bucket: test/test_cases" in md
    assert 'priority: "P0"' in md
    assert 'requirement_id: "REQ-PAY-1"' in md
    assert 'links: ["支付-余额充足应成功", "GMV口径"]' in md
    assert "## 前置条件" in md
    assert "账户余额=0" in md
    assert "## 测试步骤" in md
    assert "1. 发起支付" in md
    assert "2. 观察返回" in md
    assert "## 预期结果" in md
    assert "返回余额不足错误" in md
    assert "[[支付-余额充足应成功]]" in md
    assert "[[GMV口径]]" in md


def test_node_markdown_omits_empty_test_fields_for_business_units():
    unit = KnowledgeUnit(
        name="GMV口径",
        bucket="business/wiki",
        summary="不含退款",
        confidence=0.9,
    )
    md = _node_markdown(unit, agent_id="ba-1", derived_from=["memory/t.md"])
    assert "priority:" not in md
    assert "requirement_id:" not in md
    assert "links:" not in md
    assert "## 前置条件" not in md
    assert "## 测试步骤" not in md
    assert "## 预期结果" not in md
    assert "## 关联" not in md
    assert "bucket: business/wiki" in md
    assert "GMV口径" in md


def test_node_markdown_resolves_wikilink_to_workspace_path():
    unit = KnowledgeUnit(
        name="支付-余额不足应拒绝",
        bucket="test/test_cases",
        summary="应拒绝",
        links=["GMV口径"],
    )
    md = _node_markdown(
        unit,
        agent_id="td-1",
        derived_from=["d"],
        title_index={"gmv口径": "business/wiki/gmv口径.md"},
        knowledge_dir="knowledge",
    )
    assert "[[knowledge/business/wiki/gmv口径.md|GMV口径]]" in md
    assert "[[GMV口径]]" not in md


def test_node_markdown_sanitizes_wikilink_brackets():
    unit = KnowledgeUnit(
        name="x",
        bucket="test/test_cases",
        summary="s",
        links=["ev]]il[[name"],
    )
    md = _node_markdown(unit, agent_id="a", derived_from=["d"])
    assert "[[evilname]]" in md
    assert "[[ev]]il[[name]]" not in md


def test_migrate_wikilink_targets_rewrites_title_only_links(tmp_path, monkeypatch):
    from qwenpaw.agents.knowledge.dream import migrate_wikilink_targets

    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_links")
    root = tmp_path / "knowledge_bases" / "kb_links"
    gmv = root / "business" / "wiki" / "gmv口径.md"
    gmv.write_text(
        '---\nname: "GMV口径"\ndescription: "x"\nbucket: business/wiki\n---\n\n# GMV口径\n',
        encoding="utf-8",
    )
    case = root / "test" / "test_cases" / "refund.md"
    case.parent.mkdir(parents=True, exist_ok=True)
    case.write_text(
        '---\nname: "退款用例"\n---\n\n# 退款用例\n\n- [[GMV口径]]\n',
        encoding="utf-8",
    )
    changed = migrate_wikilink_targets("kb_links", knowledge_dir="knowledge")
    assert changed >= 1
    text = case.read_text(encoding="utf-8")
    assert "[[knowledge/business/wiki/gmv口径.md|GMV口径]]" in text
    # Idempotent.
    assert migrate_wikilink_targets("kb_links", knowledge_dir="knowledge") == 0


def test_integrate_resolves_links_when_target_exists(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_link_res")
    integrate_units(
        kb_id="kb_link_res",
        agent_id="ba-1",
        units=[
            KnowledgeUnit(
                name="GMV口径",
                bucket="business/wiki",
                summary="不含退款",
                confidence=0.9,
            ),
        ],
        derived_from=["memory/t.md"],
    )
    written = integrate_units(
        kb_id="kb_link_res",
        agent_id="td-1",
        units=[
            KnowledgeUnit(
                name="支付-余额不足应拒绝",
                bucket="test/test_cases",
                summary="应拒绝",
                confidence=0.9,
                links=["GMV口径"],
            ),
        ],
        derived_from=["memory/t.md"],
    )
    text = written[0].read_text(encoding="utf-8")
    assert "[[knowledge/business/wiki/gmv口径.md|GMV口径]]" in text
    unit = KnowledgeUnit(
        name="x",
        bucket="test/test_cases",
        summary="s",
        links=["ev]]il[[name"],
    )
    md = _node_markdown(unit, agent_id="a", derived_from=["d"])
    assert "[[evilname]]" in md
    assert "[[ev]]il[[name]]" not in md


# --- integrate_units: writes to namespaced buckets -------------------------


def test_integrate_test_case_writes_to_test_cases_bucket(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_tc")
    written = integrate_units(
        kb_id="kb_tc",
        agent_id="td-1",
        units=[
            KnowledgeUnit(
                name="支付-余额不足应拒绝",
                bucket="test/test_cases",
                summary="应拒绝",
                confidence=0.9,
                preconditions="余额=0",
                steps=["发起支付"],
                expected="拒绝",
                priority="P0",
                requirement_id="REQ-1",
                links=["GMV口径"],
            ),
        ],
        derived_from=["memory/2026-08-12.md"],
    )
    assert len(written) == 1
    assert written[0].parent.name == "test_cases"
    assert written[0].parent.parent.name == "test"
    text = written[0].read_text(encoding="utf-8")
    assert "bucket: test/test_cases" in text
    assert 'priority: "P0"' in text
    assert "[[GMV口径]]" in text


def test_integrate_business_unit_writes_to_business_bucket(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_biz")
    written = integrate_units(
        kb_id="kb_biz",
        agent_id="ba-1",
        units=[
            KnowledgeUnit(
                name="GMV口径",
                bucket="business/wiki",
                summary="不含退款",
                confidence=0.9,
            ),
        ],
        derived_from=["memory/2026-08-12.md"],
    )
    assert len(written) == 1
    assert written[0].parent.name == "wiki"
    assert written[0].parent.parent.name == "business"


def test_integrate_dedup_across_domains(tmp_path, monkeypatch):
    """A test case and a business rule with the same title dedup against
    each other — _existing_node_titles scans all published buckets.
    """
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_dedup_cross")
    first = integrate_units(
        kb_id="kb_dedup_cross",
        agent_id="ba-1",
        units=[
            KnowledgeUnit(
                name="退款政策",
                bucket="business/wiki",
                summary="7天无理由",
            ),
        ],
        derived_from=["memory/t.md"],
    )
    assert len(first) == 1
    again = integrate_units(
        kb_id="kb_dedup_cross",
        agent_id="td-1",
        units=[
            KnowledgeUnit(
                name="退款政策",
                bucket="test/test_cases",
                summary="应支持7天",
            ),
        ],
        derived_from=["memory/t.md"],
        merge_enabled=False,
    )
    assert again == []


def test_integrate_legacy_flat_bucket_nodes_still_dedup(tmp_path, monkeypatch):
    """Nodes written under legacy flat buckets (pre-domain) must still
    be found by _existing_node_titles so dedup keeps working.
    """
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_legacy_dedup")
    root = tmp_path / "knowledge_bases" / "kb_legacy_dedup"
    (root / "wiki").mkdir(parents=True, exist_ok=True)
    (root / "wiki" / "退款政策.md").write_text(
        "---\nname: 退款政策\n---\n\n# 退款政策\n旧版本\n",
        encoding="utf-8",
    )
    again = integrate_units(
        kb_id="kb_legacy_dedup",
        agent_id="ba-1",
        units=[
            KnowledgeUnit(
                name="退款政策",
                bucket="business/wiki",
                summary="新版",
            ),
        ],
        derived_from=["memory/t.md"],
        merge_enabled=False,
    )
    assert again == []


# --- run_knowledge_dream: end-to-end domain routing ------------------------


def test_run_knowledge_dream_test_domain_routes_to_test_prompt(
    tmp_path, monkeypatch,
):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_dream_test")
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text(
        "支付余额不足应拒绝，前置：余额=0\n",
        encoding="utf-8",
    )

    captured_prompts: list[str] = []

    async def fake_llm(prompt: str) -> str:
        captured_prompts.append(prompt)
        return (
            '[{"name": "支付-余额不足应拒绝", "bucket": "test/test_cases", '
            '"summary": "应拒绝", "confidence": 0.9, '
            '"preconditions": "余额=0", "steps": ["发起支付"], '
            '"expected": "拒绝", "priority": "P0", '
            '"requirement_id": "REQ-1", "links": ["GMV口径"]}]'
        )

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="td-1",
            workspace_dir=workspace,
            kb_id="kb_dream_test",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="testcase",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
        ),
    )
    assert result["skipped"] is False
    assert result["units"] == 1
    assert any("测试知识提炼助手" in p for p in captured_prompts)
    assert any("补漏审查" in p for p in captured_prompts)
    written_path = tmp_path / result["written"][0]
    assert written_path.parent.parent.name == "test"
    assert written_path.parent.name == "test_cases"
    text = written_path.read_text(encoding="utf-8")
    assert 'priority: "P0"' in text
    assert "[[GMV口径]]" in text


def test_run_knowledge_dream_business_domain_unchanged(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_dream_biz")
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text("GMV 口径不含退款\n", encoding="utf-8")

    captured_prompts: list[str] = []

    async def fake_llm(prompt: str) -> str:
        captured_prompts.append(prompt)
        return (
            '[{"name": "GMV口径", "bucket": "business/wiki", '
            '"summary": "不含退款", "confidence": 0.9}]'
        )

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba-1",
            workspace_dir=workspace,
            kb_id="kb_dream_biz",
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
    assert any("业务知识提炼助手" in p for p in captured_prompts)
    written_path = tmp_path / result["written"][0]
    assert written_path.parent.parent.name == "business"
    assert written_path.parent.name == "wiki"
