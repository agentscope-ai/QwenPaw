# -*- coding: utf-8 -*-
"""Unit tests for knowledge-dream auto-merge: gating matrix, field policy,
LLM-driven clean body, audit report + anomaly flags, merge_count cap,
staleness guard, and the audit read/ack helpers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qwenpaw.agents.knowledge.dream import (
    AuditReportSummary,
    KnowledgeUnit,
    MergeCandidate,
    MergePayload,
    _merge_node,
    _parse_frontmatter,
    _priority_rank,
    ack_audit_report,
    integrate_units,
    list_audit_reports,
    read_audit_report,
)
from qwenpaw.agents.knowledge.store import ensure_kb

_INTEGRITY_OK = '{"ok": true, "lost_claims": [], "injected_unrelated": []}'


def _integrity_ok_if_asked(prompt: str) -> str | None:
    if "完整性审查" in prompt or "information loss" in prompt.lower():
        return _INTEGRITY_OK
    return None


def _patch_kb_roots(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "qwenpaw.agents.knowledge.store.WORKING_DIR", tmp_path,
    )
    root = lambda kb_id: tmp_path / "knowledge_bases" / kb_id
    monkeypatch.setattr("qwenpaw.agents.knowledge.lock.kb_root", root)
    monkeypatch.setattr("qwenpaw.agents.knowledge.dream.kb_root", root)


def _seed_node(root: Path, bucket: str, name: str, **fm) -> Path:
    """Write a minimal published node and return its path."""
    d = root / bucket
    d.mkdir(parents=True, exist_ok=True)
    p = d / fname(name)
    fm_lines = ["---", f'name: "{name}"', f"bucket: {bucket}"]
    for k, v in fm.items():
        fm_lines.append(f"{k}: {v}")
    fm_lines += ["---", "", f"# {name}", "", "original body"]
    p.write_text("\n".join(fm_lines) + "\n", encoding="utf-8")
    return p


def fname(name: str) -> str:
    from qwenpaw.agents.knowledge.dream import _slugify
    return f"{_slugify(name)}.md"


# A deterministic "LLM-merged" clean body used by the merge tests.
CLEAN_BODY = """# 退款政策

7天无理由退换

## 前置条件

商品完好

## 测试步骤

1. 申请退款

## 预期结果

同意

## 关联

- [[订单流程]]
"""


def _payload(target: Path, *, merged_body: str = CLEAN_BODY,
             llm_ok: bool = True, expected_updated_at: str = "") -> MergePayload:
    return MergePayload(
        target_path=target,
        expected_updated_at=expected_updated_at,
        merged_body=merged_body,
        llm_ok=llm_ok,
    )


# --- helpers ---------------------------------------------------------------


def test_priority_rank_ordering():
    assert _priority_rank("P0") == 4
    assert _priority_rank("p1") == 3
    assert _priority_rank("P2") == 2
    assert _priority_rank("P3") == 1
    assert _priority_rank("") == 0
    assert _priority_rank("P9") == 0


def test_parse_frontmatter_splits_fence_and_body():
    text = '---\nname: "x"\nbucket: business/wiki\nlinks: ["a", "b"]\n---\n\n# x\nbody line'
    fm, body = _parse_frontmatter(text)
    assert fm["name"] == '"x"'
    assert fm["bucket"] == "business/wiki"
    assert fm["links"] == '["a", "b"]'
    assert "# x" in body
    assert "body line" in body


def test_parse_frontmatter_no_fence_returns_empty():
    fm, body = _parse_frontmatter("# just body\n")
    assert fm == {}
    assert "just body" in body


# --- _merge_node: clean body + audit report --------------------------------


def test_merge_node_writes_clean_body_and_audit_report(tmp_path):
    root = tmp_path / "kb"
    # Seed a body comparable in size to CLEAN_BODY so the merge is the
    # normal no-anomaly case (avoids the large_body_diff flag).
    seed_body = "# 退款政策\n\n" + ("原始口径说明。 " * 8) + "\n\noriginal body"
    target = _seed_node(root, "business/wiki", "退款政策", priority='"P1"')
    target.write_text(
        target.read_text(encoding="utf-8").replace("original body", seed_body),
        encoding="utf-8",
    )
    unit = KnowledgeUnit(
        name="退款政策-补充", bucket="business/wiki",
        summary="7天无理由退换", confidence=0.9, signals=["note"],
        preconditions="商品完好",
        steps=["申请退款"], expected="同意",
        priority="P0", links=["订单流程"],
    )
    outcome = _merge_node(
        target, unit, agent_id="ba-1",
        derived_from=["memory/t.md"], mode="MERGE", max_updates=5,
        payload=_payload(target), kb_root_path=root,
    )
    assert outcome.done is True
    assert outcome.reason == "ok"
    text = target.read_text(encoding="utf-8")
    # Original body is gone — replaced by the clean LLM body.
    assert "original body" not in text
    assert "# 退款政策" in text
    assert "7天无理由退换" in text
    # No append-only history section.
    assert "## 更新" not in text
    assert "## 修正" not in text
    # Single test-steps section with the merged steps.
    assert text.count("## 测试步骤") == 1
    assert "1. 申请退款" in text
    # Frontmatter field policy applied.
    assert 'priority: "P0"' in text
    assert "merge_count: 1" in text
    # Audit report written.
    assert outcome.report_path is not None
    assert outcome.report_path.is_file()
    report = outcome.report_path.read_text(encoding="utf-8")
    assert "合并审计报告" in report
    assert "合并前" in report and "合并后" in report
    assert "original body" in report  # before snapshot preserved
    # Index entry appended; normal merge → no anomalies.
    index = (root / "_audit" / "index.jsonl").read_text(encoding="utf-8")
    entry = json.loads(index.strip().splitlines()[-1])
    assert entry["node_path"].endswith("退款政策.md")
    assert entry["mode"] == "MERGE"
    assert entry["anomalies"] == []
    assert entry["needs_review"] is False


def test_merge_node_priority_takes_more_urgent(tmp_path):
    root = tmp_path / "kb"
    target = _seed_node(root, "test/test_cases", "支付用例", priority='"P2"')
    unit = KnowledgeUnit(
        name="支付用例-补", bucket="test/test_cases",
        summary="s", priority="P0",
    )
    _merge_node(target, unit, agent_id="a", derived_from=["d"], mode="MERGE",
                max_updates=5, payload=_payload(target), kb_root_path=root)
    assert 'priority: "P0"' in target.read_text(encoding="utf-8")


def test_merge_node_priority_keeps_existing_when_new_lower(tmp_path):
    root = tmp_path / "kb"
    target = _seed_node(root, "test/test_cases", "支付用例", priority='"P0"')
    unit = KnowledgeUnit(
        name="支付用例-补", bucket="test/test_cases",
        summary="s", priority="P2",
    )
    _merge_node(target, unit, agent_id="a", derived_from=["d"], mode="MERGE",
                max_updates=5, payload=_payload(target), kb_root_path=root)
    assert 'priority: "P0"' in target.read_text(encoding="utf-8")


def test_merge_node_links_union(tmp_path):
    root = tmp_path / "kb"
    target = _seed_node(
        root, "business/wiki", "退款政策",
        links='["订单流程", "GMV口径"]',
    )
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="s", links=["GMV口径", "售后流程"],
    )
    _merge_node(target, unit, agent_id="a", derived_from=["d"], mode="MERGE",
                max_updates=5, payload=_payload(target), kb_root_path=root)
    text = target.read_text(encoding="utf-8")
    assert "订单流程" in text and "GMV口径" in text and "售后流程" in text


def test_merge_node_correct_replaces_description_merge_keeps(tmp_path):
    root = tmp_path / "kb"
    target = _seed_node(
        root, "business/wiki", "退款政策",
        description='"旧口径"',
    )
    unit = KnowledgeUnit(
        name="退款政策-修正", bucket="business/wiki",
        summary="新口径修正",
    )
    _merge_node(target, unit, agent_id="a", derived_from=["d"], mode="CORRECT",
                max_updates=5, payload=_payload(target), kb_root_path=root)
    text = target.read_text(encoding="utf-8")
    assert 'description: "7天无理由退换"' in text
    assert 'description: "旧口径"' not in text
    assert 'description: "新口径修正"' not in text


def test_merge_node_refine_refreshes_description(tmp_path):
    root = tmp_path / "kb"
    target = _seed_node(
        root, "business/wiki", "退款政策",
        description='"旧口径"',
    )
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="补充内容",
    )
    _merge_node(target, unit, agent_id="a", derived_from=["d"], mode="MERGE",
                max_updates=5, payload=_payload(target), kb_root_path=root)
    text = target.read_text(encoding="utf-8")
    assert 'description: "7天无理由退换"' in text
    assert 'description: "旧口径"' not in text
    assert 'description: "补充内容"' not in text


def test_merge_node_requirement_id_union(tmp_path):
    root = tmp_path / "kb"
    target = _seed_node(
        root, "test/test_cases", "用例A", requirement_id='"REQ-1"',
    )
    unit = KnowledgeUnit(
        name="用例A-补", bucket="test/test_cases",
        summary="s", requirement_id="REQ-2",
    )
    _merge_node(target, unit, agent_id="a", derived_from=["d"], mode="MERGE",
                max_updates=5, payload=_payload(target), kb_root_path=root)
    text = target.read_text(encoding="utf-8")
    assert "REQ-1" in text and "REQ-2" in text


def test_merge_node_at_cap_returns_not_done(tmp_path):
    root = tmp_path / "kb"
    target = _seed_node(root, "business/wiki", "退款政策", merge_count="5")
    unit = KnowledgeUnit(name="退款政策-补", bucket="business/wiki", summary="s")
    outcome = _merge_node(
        target, unit, agent_id="a", derived_from=["d"],
        mode="MERGE", max_updates=5,
        payload=_payload(target), kb_root_path=root,
    )
    assert outcome.done is False
    assert outcome.reason == "at_cap"
    assert "merge_count: 5" in target.read_text(encoding="utf-8")
    assert outcome.report_path is None


def test_merge_node_stale_payload_refuses_merge(tmp_path):
    root = tmp_path / "kb"
    target = _seed_node(
        root, "business/wiki", "退款政策",
        updated_at='"2026-01-01T00:00:00+00:00"',
    )
    unit = KnowledgeUnit(name="退款政策-补", bucket="business/wiki", summary="s")
    outcome = _merge_node(
        target, unit, agent_id="a", derived_from=["d"], mode="MERGE",
        max_updates=5,
        payload=_payload(target, expected_updated_at="2025-12-31T00:00:00+00:00"),
        kb_root_path=root,
    )
    assert outcome.done is False
    assert outcome.reason == "stale"
    assert "original body" in target.read_text(encoding="utf-8")


def test_merge_node_low_confidence_flags_needs_review(tmp_path):
    root = tmp_path / "kb"
    target = _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="s", confidence=0.3,
    )
    outcome = _merge_node(
        target, unit, agent_id="a", derived_from=["d"], mode="MERGE",
        max_updates=5, payload=_payload(target), kb_root_path=root,
    )
    assert outcome.done is True
    assert "low_confidence" in outcome.anomalies
    index = (root / "_audit" / "index.jsonl").read_text(encoding="utf-8")
    entry = json.loads(index.strip().splitlines()[-1])
    assert entry["needs_review"] is True
    assert "low_confidence" in entry["anomalies"]


def test_merge_node_correct_mode_flags_needs_review(tmp_path):
    root = tmp_path / "kb"
    target = _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-修", bucket="business/wiki",
        summary="s", confidence=0.9,
    )
    outcome = _merge_node(
        target, unit, agent_id="a", derived_from=["d"], mode="CORRECT",
        max_updates=5, payload=_payload(target), kb_root_path=root,
    )
    assert outcome.done is True
    assert "correct_mode" in outcome.anomalies


def test_merge_node_near_cap_flags_needs_review(tmp_path):
    root = tmp_path / "kb"
    target = _seed_node(root, "business/wiki", "退款政策", merge_count="4")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="s", confidence=0.9,
    )
    outcome = _merge_node(
        target, unit, agent_id="a", derived_from=["d"], mode="MERGE",
        max_updates=5, payload=_payload(target), kb_root_path=root,
    )
    assert outcome.done is True
    assert "near_merge_cap" in outcome.anomalies


def test_merge_node_large_body_diff_flags_needs_review(tmp_path):
    root = tmp_path / "kb"
    target = _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="s", confidence=0.9,
    )
    big_body = "# 退款政策\n\n" + ("x" * 500)
    outcome = _merge_node(
        target, unit, agent_id="a", derived_from=["d"], mode="MERGE",
        max_updates=5, payload=_payload(target, merged_body=big_body),
        kb_root_path=root,
    )
    assert outcome.done is True
    assert "large_body_diff" in outcome.anomalies


# --- integrate_units: gating matrix ----------------------------------------


def _biz_cand(name, path, ratio=0.9, is_clear=True):
    return MergeCandidate(name=name, path=path, ratio=ratio, is_clear=is_clear)


def _payload_for(root, target_name, bucket, merged_body=CLEAN_BODY):
    target = root / bucket / fname(target_name)
    return _payload(target, merged_body=merged_body)


def test_merge_enabled_clear_candidate_merges_into_target(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb1")
    root = tmp_path / "knowledge_bases" / "kb1"
    _seed_node(root, "business/wiki", "退款政策", priority='"P1"')
    unit = KnowledgeUnit(
        name="退款政策-补充", bucket="business/wiki",
        summary="s", priority="P0", action_hint="MERGE",
    )
    written = integrate_units(
        kb_id="kb1", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策-补充": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_payloads={"退款政策-补充": _payload_for(root, "退款政策", "business/wiki")},
    )
    assert len(written) == 1
    assert written[0].name == fname("退款政策")
    text = written[0].read_text(encoding="utf-8")
    assert "## 更新" not in text
    assert 'priority: "P0"' in text
    assert "merge_count: 1" in text
    assert not (root / "business" / "wiki" / fname("退款政策-补充")).exists()
    assert (root / "_audit").is_dir()
    assert list((root / "_audit").glob("*.md"))


def test_merge_enabled_create_with_candidate_refines_instead_of_sibling(
    tmp_path, monkeypatch,
):
    """CREATE against a clear same-abstraction node is a mis-label → REFINE."""
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb2")
    root = tmp_path / "knowledge_bases" / "kb2"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策新版", bucket="business/wiki",
        summary="s", action_hint="CREATE",
    )
    written = integrate_units(
        kb_id="kb2", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策新版": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_payloads={"退款政策新版": _payload_for(root, "退款政策", "business/wiki")},
    )
    assert len(written) == 1
    assert written[0].name == fname("退款政策")
    assert written[0].parent.name != "_inbox"
    text = written[0].read_text(encoding="utf-8")
    assert "merge_count: 1" in text
    assert not (root / "business" / "wiki" / fname("退款政策新版")).exists()


def test_merge_enabled_cross_domain_candidate_goes_to_inbox(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb3")
    root = tmp_path / "knowledge_bases" / "kb3"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策用例", bucket="test/test_cases",
        summary="s", action_hint="MERGE",
    )
    written = integrate_units(
        kb_id="kb3", agent_id="td-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策用例": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_payloads={"退款政策用例": _payload_for(root, "退款政策", "business/wiki")},
    )
    assert len(written) == 1
    assert written[0].parent.name == "_inbox"
    text = written[0].read_text(encoding="utf-8")
    assert "inbox_reason: cross_domain" in text
    assert "intended_bucket: test/test_cases" in text


def test_merge_enabled_ambiguous_candidate_goes_to_inbox(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb4")
    root = tmp_path / "knowledge_bases" / "kb4"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="s", action_hint="MERGE",
    )
    written = integrate_units(
        kb_id="kb4", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策-补": _biz_cand("退款政策", "business/wiki/退款政策.md", is_clear=False)},
        merge_enabled=True,
        merge_payloads={"退款政策-补": _payload_for(root, "退款政策", "business/wiki")},
    )
    assert len(written) == 1
    assert written[0].parent.name == "_inbox"
    text = written[0].read_text(encoding="utf-8")
    assert "inbox_reason: ambiguous_candidate" in text
    assert "merge_target_path:" in text
    assert "business/wiki/退款政策.md" in text


def test_merge_enabled_no_candidate_publishes_as_new(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb5")
    root = tmp_path / "knowledge_bases" / "kb5"
    unit = KnowledgeUnit(
        name="全新规则", bucket="business/wiki",
        summary="s", action_hint="MERGE",
    )
    written = integrate_units(
        kb_id="kb5", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={},
        merge_enabled=True,
    )
    assert len(written) == 1
    assert written[0].parent.name == "wiki"
    assert "status: published" in written[0].read_text(encoding="utf-8")


def test_merge_enabled_correct_without_candidate_goes_to_inbox(
    tmp_path, monkeypatch,
):
    """CORRECT with merge on but no target must not CREATE a sibling."""
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_correct_none")
    unit = KnowledgeUnit(
        name="退款政策-修正", bucket="business/wiki",
        summary="应改为7天", action_hint="CORRECT",
    )
    written = integrate_units(
        kb_id="kb_correct_none", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={},
        merge_enabled=True,
        write_mode="open",
    )
    assert len(written) == 1
    assert written[0].parent.name == "_inbox"
    text = written[0].read_text(encoding="utf-8")
    assert "inbox_reason: no_merge_target" in text


def test_merge_enabled_default_action_with_summary_refines(tmp_path, monkeypatch):
    """Empty action + non-empty summary + clear candidate → REFINE (summary is content)."""
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb6")
    root = tmp_path / "knowledge_bases" / "kb6"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(name="退款政策补充", bucket="business/wiki", summary="7天无理由")
    written = integrate_units(
        kb_id="kb6", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策补充": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_payloads={"退款政策补充": _payload_for(root, "退款政策", "business/wiki")},
    )
    assert len(written) == 1
    assert written[0].name == fname("退款政策")
    text = written[0].read_text(encoding="utf-8")
    assert "merge_count: 1" in text
    index = (root / "_audit" / "index.jsonl").read_text(encoding="utf-8")
    entry = json.loads(index.strip().splitlines()[-1])
    assert entry["mode"] == "REFINE"


def test_merge_enabled_explicit_corroborate_skips_llm_payload(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb6c")
    root = tmp_path / "knowledge_bases" / "kb6c"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策再确认", bucket="business/wiki",
        summary="再次确认", action_hint="CORROBORATE", signals=["daily"],
    )
    written = integrate_units(
        kb_id="kb6c", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策再确认": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_payloads={},
    )
    assert len(written) == 1
    text = written[0].read_text(encoding="utf-8")
    assert "original body" in text
    assert "daily" in text
    assert "corroborate_count: 1" in text
    assert "merge_count:" not in text or "merge_count: 0" in text


def test_enrich_unit_links_unions_related_names():
    from qwenpaw.agents.knowledge.dream import _enrich_unit_links

    unit = KnowledgeUnit(
        name="退款用例", bucket="test/test_cases",
        summary="s", links=["订单流程"],
    )
    _enrich_unit_links(unit, ["订单流程", "退款政策", "退款用例", ""])
    assert unit.links == ["订单流程", "退款政策"]


def test_enrich_unit_links_skips_business_synapse():
    from qwenpaw.agents.knowledge.dream import _enrich_unit_links

    unit = KnowledgeUnit(
        name="退款政策", bucket="business/wiki",
        summary="s", links=["订单流程"],
    )
    _enrich_unit_links(unit, ["退款流程", "退款说明"])
    assert unit.links == ["订单流程"]


def test_enrich_unit_links_caps_test_domain_synapse():
    from qwenpaw.agents.knowledge.dream import _enrich_unit_links

    unit = KnowledgeUnit(
        name="退款用例", bucket="test/test_cases",
        summary="s", links=["订单流程"],
    )
    _enrich_unit_links(
        unit,
        ["订单流程", "退款政策", "A", "B", "C", "退款用例", ""],
    )
    assert unit.links == ["订单流程", "退款政策", "A", "B"]
    assert "C" not in unit.links


def test_resolve_integrate_action_defaults():
    from qwenpaw.agents.knowledge.dream import _resolve_integrate_action

    # Empty summary → CORROBORATE (provenance only).
    assert _resolve_integrate_action(
        KnowledgeUnit(name="a", summary=""), has_clear_candidate=True,
    ) == "CORROBORATE"
    # Non-empty summary counts as substantive → REFINE.
    assert _resolve_integrate_action(
        KnowledgeUnit(name="a", summary="s"), has_clear_candidate=True,
    ) == "REFINE"
    assert _resolve_integrate_action(
        KnowledgeUnit(name="a", summary="s", steps=["x"]),
        has_clear_candidate=True,
    ) == "REFINE"
    assert _resolve_integrate_action(
        KnowledgeUnit(name="a", summary="s", action_hint="MERGE"),
        has_clear_candidate=True,
    ) == "REFINE"
    assert _resolve_integrate_action(
        KnowledgeUnit(name="a", summary="s", action_hint="CREATE"),
        has_clear_candidate=True,
        exact_title_match=True,
    ) == "REFINE"
    # CREATE + clear candidate (even without exact title) is also demoted.
    assert _resolve_integrate_action(
        KnowledgeUnit(name="a", summary="s", action_hint="CREATE"),
        has_clear_candidate=True,
    ) == "REFINE"
    assert _resolve_integrate_action(
        KnowledgeUnit(name="a", summary="s", action_hint="CREATE"),
        has_clear_candidate=False,
    ) == "CREATE"
    assert _resolve_integrate_action(
        KnowledgeUnit(name="a", summary="s"), has_clear_candidate=False,
    ) == "CREATE"
    assert _resolve_integrate_action(
        KnowledgeUnit(name="a", summary="s", action_hint="CORROBORATE"),
        has_clear_candidate=True,
    ) == "CORROBORATE"
    # Summary already in the existing body → CORROBORATE, not REFINE.
    assert _resolve_integrate_action(
        KnowledgeUnit(name="a", summary="7天无理由"),
        has_clear_candidate=True,
        old_body="# 退款政策\n\n7天无理由退换",
    ) == "CORROBORATE"
    # New claim vs existing body → REFINE.
    assert _resolve_integrate_action(
        KnowledgeUnit(name="a", summary="需包装完好"),
        has_clear_candidate=True,
        old_body="# 退款政策\n\n7天无理由退换",
    ) == "REFINE"


def test_exact_title_overrides_fuzzy_clear_candidate(tmp_path, monkeypatch):
    """Exact same-name node must win over a fuzzy clear near-neighbor."""
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_exact_win")
    root = tmp_path / "knowledge_bases" / "kb_exact_win"
    _seed_node(root, "business/wiki", "退款政策")
    _seed_node(root, "business/wiki", "退款政策说明")
    unit = KnowledgeUnit(
        name="退款政策", bucket="business/wiki",
        summary="", action_hint="CORROBORATE", signals=["x"],
    )
    # Fuzzy probe wrongly points at the near-neighbor.
    written = integrate_units(
        kb_id="kb_exact_win", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={
            "退款政策": _biz_cand("退款政策说明", "business/wiki/退款政策说明.md"),
        },
        merge_enabled=True,
    )
    assert len(written) == 1
    assert written[0].name == fname("退款政策")
    text = written[0].read_text(encoding="utf-8")
    assert "corroborate_count: 1" in text
    # Near-neighbor untouched.
    other = root / "business" / "wiki" / fname("退款政策说明")
    assert "corroborate_count" not in other.read_text(encoding="utf-8")
    assert "merge_count" not in other.read_text(encoding="utf-8")

def test_merge_disabled_preserves_legacy_inbox_behavior(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb7")
    root = tmp_path / "knowledge_bases" / "kb7"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="s", action_hint="MERGE",
    )
    written = integrate_units(
        kb_id="kb7", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策-补": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=False,
    )
    assert len(written) == 1
    assert written[0].parent.name == "_inbox"
    assert "inbox_reason: merge_disabled" in written[0].read_text(encoding="utf-8")


def test_merge_enabled_merge_target_hint_resolves(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb8")
    root = tmp_path / "knowledge_bases" / "kb8"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="s", action_hint="MERGE", merge_target="退款政策",
    )
    written = integrate_units(
        kb_id="kb8", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={},
        merge_enabled=True,
        merge_payloads={"退款政策-补": _payload_for(root, "退款政策", "business/wiki")},
    )
    assert len(written) == 1
    assert written[0].name == fname("退款政策")
    text = written[0].read_text(encoding="utf-8")
    assert "## 更新" not in text


def test_merge_enabled_missing_payload_routes_to_inbox(tmp_path, monkeypatch):
    """No clean LLM body available → keep body clean by holding for review."""
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb9")
    root = tmp_path / "knowledge_bases" / "kb9"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="s", action_hint="MERGE",
    )
    written = integrate_units(
        kb_id="kb9", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策-补": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_payloads={},  # no usable body → inbox
    )
    assert len(written) == 1
    assert written[0].parent.name == "_inbox"
    text = written[0].read_text(encoding="utf-8")
    assert "inbox_reason: missing_payload" in text
    assert "intended_bucket: business/wiki" in text
    # Target node untouched (no redundancy written).
    assert "original body" in _seed_node_read(root, "business/wiki", "退款政策")


def _seed_node_read(root, bucket, name):
    return (root / bucket / fname(name)).read_text(encoding="utf-8")


def test_merge_enabled_empty_update_corroborates(tmp_path, monkeypatch):
    """Empty action + no structural fields + clear candidate → CORROBORATE.

    Provenance is appended; body stays untouched (no LLM rewrite).
    """
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_empty")
    root = tmp_path / "knowledge_bases" / "kb_empty"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="", preconditions="", steps=[], expected="", links=[],
    )
    written = integrate_units(
        kb_id="kb_empty", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策-补": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_payloads={},
    )
    assert len(written) == 1
    assert written[0].name == fname("退款政策")
    target = root / "business" / "wiki" / fname("退款政策")
    text = target.read_text(encoding="utf-8")
    assert "original body" in text
    assert "corroborate_count: 1" in text
    assert "merge_count:" not in text or "merge_count: 0" in text
    assert "m/t.md" in text
    assert (root / "_audit").is_dir()


def test_corroborate_at_merge_cap_still_applies(tmp_path, monkeypatch):
    """CORROBORATE must not be blocked when merge_count is already at cap."""
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_corr_cap")
    root = tmp_path / "knowledge_bases" / "kb_corr_cap"
    target = _seed_node(root, "business/wiki", "退款政策", merge_count="5")
    unit = KnowledgeUnit(
        name="退款政策再确认", bucket="business/wiki",
        summary="再次确认", action_hint="CORROBORATE", signals=["daily"],
    )
    written = integrate_units(
        kb_id="kb_corr_cap", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策再确认": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_max_updates=5,
        merge_payloads={},
    )
    assert len(written) == 1
    assert written[0] == target
    text = target.read_text(encoding="utf-8")
    assert "merge_count: 5" in text
    assert "corroborate_count: 1" in text
    assert "daily" in text
    # REFINE at the same cap still goes to inbox.
    refine = KnowledgeUnit(
        name="退款政策补充", bucket="business/wiki",
        summary="新边界", action_hint="REFINE",
    )
    inboxed = integrate_units(
        kb_id="kb_corr_cap", agent_id="ba-1", units=[refine],
        derived_from=["m/t2.md"],
        merge_candidates={"退款政策补充": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_max_updates=5,
        merge_payloads={"退款政策补充": _payload_for(root, "退款政策", "business/wiki")},
    )
    assert len(inboxed) == 1
    assert inboxed[0].parent.name == "_inbox"
    assert "merge_count: 5" in target.read_text(encoding="utf-8")


def test_merge_enabled_explicit_refine_without_content_routes_to_inbox(
    tmp_path, monkeypatch,
):
    """Explicit REFINE/MERGE with no update content still goes to inbox."""
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_empty_refine")
    root = tmp_path / "knowledge_bases" / "kb_empty_refine"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="", preconditions="", steps=[], expected="", links=[],
        action_hint="REFINE",
    )
    written = integrate_units(
        kb_id="kb_empty_refine", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策-补": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_payloads={"退款政策-补": _payload_for(root, "退款政策", "business/wiki")},
    )
    assert len(written) == 1
    assert written[0].parent.name == "_inbox"
    assert "inbox_reason: empty_update" in written[0].read_text(encoding="utf-8")
    target = root / "business" / "wiki" / fname("退款政策")
    assert "merge_count" not in target.read_text(encoding="utf-8")
    assert not (root / "_audit").exists()


def test_merge_enabled_llm_failed_payload_routes_to_inbox(tmp_path, monkeypatch):
    """llm_ok=False → don't write a redundant fallback; route to inbox."""
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb10")
    root = tmp_path / "knowledge_bases" / "kb10"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="s", action_hint="MERGE",
    )
    target = root / "business" / "wiki" / fname("退款政策")
    written = integrate_units(
        kb_id="kb10", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策-补": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_payloads={"退款政策-补": _payload(target, llm_ok=False)},
    )
    assert len(written) == 1
    assert written[0].parent.name == "_inbox"
    assert "inbox_reason: missing_payload" in written[0].read_text(encoding="utf-8")
    assert "original body" in target.read_text(encoding="utf-8")


def test_integrate_units_audit_sink_collected(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb11")
    root = tmp_path / "knowledge_bases" / "kb11"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="s", confidence=0.3, action_hint="MERGE",
    )
    sink: list = []
    written = integrate_units(
        kb_id="kb11", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策-补": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_payloads={"退款政策-补": _payload_for(root, "退款政策", "business/wiki")},
        audit_sink=sink,
    )
    assert len(written) == 1
    assert len(sink) == 1
    assert isinstance(sink[0], AuditReportSummary)
    assert sink[0].needs_review is True  # low_confidence
    assert "low_confidence" in sink[0].anomalies


# --- audit read/ack helpers ------------------------------------------------


def test_list_read_ack_audit_reports(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_audit")
    root = tmp_path / "knowledge_bases" / "kb_audit"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="s", confidence=0.3, action_hint="MERGE",
    )
    integrate_units(
        kb_id="kb_audit", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={"退款政策-补": _biz_cand("退款政策", "business/wiki/退款政策.md")},
        merge_enabled=True,
        merge_payloads={"退款政策-补": _payload_for(root, "退款政策", "business/wiki")},
    )

    reports = list_audit_reports("kb_audit")
    assert len(reports) == 1
    assert reports[0].needs_review is True
    assert not reports[0].reviewed

    needs_only = list_audit_reports("kb_audit", needs_review_only=True)
    assert len(needs_only) == 1

    report_id = reports[0].report_id
    body = read_audit_report("kb_audit", report_id)
    assert body is not None
    assert "合并审计报告" in body

    acked = ack_audit_report("kb_audit", report_id)
    assert acked is not None
    assert acked.reviewed is True
    # Reflected in subsequent listing.
    after = list_audit_reports("kb_audit", needs_review_only=True)
    assert after == []


def test_read_audit_report_missing_returns_none(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_none")
    assert read_audit_report("kb_none", "nope") is None
    assert ack_audit_report("kb_none", "nope") is None
    assert list_audit_reports("kb_none") == []


# --- merge prompt: domain-agnostic ----------------------------------------


def test_build_merge_prompt_renders_only_nonempty_fields():
    from qwenpaw.agents.knowledge.prompts import build_merge_prompt

    # Business-style unit: only summary + links.
    biz = KnowledgeUnit(
        name="退款政策", bucket="business/wiki",
        summary="7天无理由", links=["订单流程"],
    )
    prompt = build_merge_prompt(
        language="zh", mode="MERGE", old_body="# 退款政策\n\n旧口径", unit=biz,
    )
    assert "摘要: 7天无理由" in prompt
    assert "关联" in prompt and "[[订单流程]]" in prompt
    # Empty test-case fields are not rendered.
    assert "前置条件" not in prompt
    assert "测试步骤" not in prompt
    assert "预期结果" not in prompt
    # No domain-specific section enumeration in the rules.
    assert "## 前置条件" not in prompt
    assert "## 测试步骤" not in prompt


def test_build_merge_prompt_renders_test_fields_when_present():
    from qwenpaw.agents.knowledge.prompts import build_merge_prompt

    case = KnowledgeUnit(
        name="支付-余额不足", bucket="test/test_cases",
        summary="s", preconditions="账户余额<应付金额",
        steps=["发起支付", "断言拒绝"], expected="交易拒绝",
    )
    prompt = build_merge_prompt(
        language="zh", mode="MERGE", old_body="# 支付-余额不足\n\n旧用例", unit=case,
    )
    assert "前置条件: 账户余额<应付金额" in prompt
    assert "1. 发起支付" in prompt and "2. 断言拒绝" in prompt
    assert "预期结果: 交易拒绝" in prompt


# --- run_knowledge_dream: LLM merge wiring ---------------------------------


def test_run_knowledge_dream_merges_via_llm_and_reports(tmp_path, monkeypatch):
    """End-to-end: dream extracts a unit, merge_search finds a clear
    candidate, the merge LLM produces a clean body, integrate merges
    in place, and the result carries audit_reports + needs_review_count.
    """
    from datetime import datetime, timezone

    from qwenpaw.agents.knowledge.dream import run_knowledge_dream

    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_dream_merge")
    root = tmp_path / "knowledge_bases" / "kb_dream_merge"
    _seed_node(root, "business/wiki", "退款政策", priority='"P1"')

    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text("退款政策补充：7天无理由\n", encoding="utf-8")

    call_log: list[str] = []

    async def fake_llm(prompt: str) -> str:
        call_log.append(prompt)
        # The extract call returns a unit; the merge call returns a body.
        ok = _integrity_ok_if_asked(prompt)
        if ok is not None:
            return ok
        if "合并助手" in prompt or "merge assistant" in prompt.lower():
            return "# 退款政策\n\n7天无理由退换\n"
        return (
            '[{"name": "退款政策-补充", "bucket": "business/wiki", '
            '"summary": "7天无理由", "confidence": 0.9, '
            '"action_hint": "MERGE", "merge_target": "退款政策"}]'
        )

    async def merge_search(name: str, summary: str):
        from qwenpaw.agents.knowledge.dream import MergeCandidate
        return MergeCandidate(
            name="退款政策",
            path="business/wiki/退款政策.md",
            ratio=0.95,
            is_clear=True,
        )

    import asyncio

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba-1",
            workspace_dir=workspace,
            kb_id="kb_dream_merge",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
            merge_search=merge_search,
            merge_enabled=True,
            merge_max_updates=5,
        ),
    )
    assert result["skipped"] is False
    assert result["units"] == 1
    # Merged into the existing node (target path), not a new file.
    written = Path(result["written"][0])
    assert written.name == fname("退款政策")
    text = written.read_text(encoding="utf-8")
    assert "## 更新" not in text
    assert "7天无理由退换" in text
    assert "merge_count: 1" in text
    # Audit reports surfaced in the result.
    assert result["audit_reports"], "expected at least one audit report"
    assert "report_id" in result["audit_reports"][0]
    # The merge LLM was actually invoked (merge prompt sent).
    assert any("合并助手" in p for p in call_log)


def test_knowledge_name_similarity_strips_extract_aliases():
    from qwenpaw.agents.knowledge.dream import knowledge_name_similarity

    assert knowledge_name_similarity("退款政策-补充", "退款政策") >= 0.94
    assert knowledge_name_similarity("退款政策补充", "退款政策") >= 0.94
    # Genuine neighbor — not an extract alias.
    assert knowledge_name_similarity("退款政策说明", "退款政策") < 0.82
    assert knowledge_name_similarity("退款流程", "退款政策") < 0.78


def test_knowledge_claim_similarity_lifts_near_miss_titles():
    from qwenpaw.agents.knowledge.dream import (
        knowledge_claim_similarity,
        knowledge_name_similarity,
    )

    left, right = "退款规则", "退款口径"
    assert knowledge_name_similarity(left, right) < 0.78
    shared = "消费者在收货后7天内可无理由退换，商品须完好。"
    assert knowledge_claim_similarity(left, right, shared, shared) >= 0.78
    assert knowledge_claim_similarity(
        left, right, shared, "GMV统计口径不含增值税",
    ) < 0.78


def test_knowledge_claim_similarity_does_not_lift_unrelated_titles():
    from qwenpaw.agents.knowledge.dream import knowledge_claim_similarity

    shared = "消费者在收货后7天内可无理由退换，商品须完好。"
    assert knowledge_claim_similarity("GMV口径", "退款政策", shared, shared) < 0.50


def test_union_body_wikilinks_restores_dropped_links():
    from qwenpaw.agents.knowledge.dream import _union_body_wikilinks

    old = "# 退款\n\n口径\n\n## 关联\n\n- [[订单流程]]\n- [[GMV口径]]\n"
    new = "# 退款\n\n新口径\n\n## 关联\n\n- [[GMV口径]]\n"
    out = _union_body_wikilinks(old, new)
    assert "[[订单流程]]" in out
    assert "[[GMV口径]]" in out


def test_structural_merge_body_replaces_lead_and_keeps_sections():
    from qwenpaw.agents.knowledge.dream import structural_merge_body

    old = "# 退款政策\n\n旧口径\n\n## 关联\n\n- [[订单流程]]\n"
    unit = KnowledgeUnit(
        name="退款政策", bucket="business/wiki",
        summary="7天无理由，包装完好", links=["售后流程"],
    )
    out = structural_merge_body(old, unit)
    assert "# 退款政策" in out
    assert "7天无理由，包装完好" in out
    assert "旧口径" not in out
    assert "[[订单流程]]" in out
    assert "[[售后流程]]" in out


def test_same_batch_second_refine_corroborates(tmp_path, monkeypatch):
    """Two REFINE units hitting the same node in one integrate pass.

    The first rewrites the body; the second must CORROBORATE (not stale
    into _inbox, and not consume another merge_count).
    """
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_batch")
    root = tmp_path / "knowledge_bases" / "kb_batch"
    _seed_node(root, "business/wiki", "退款政策")
    cand = _biz_cand("退款政策", "business/wiki/退款政策.md")
    payload = _payload_for(root, "退款政策", "business/wiki")
    u1 = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="7天无理由", action_hint="REFINE",
    )
    u2 = KnowledgeUnit(
        name="退款政策-再补", bucket="business/wiki",
        summary="包装完好", action_hint="REFINE",
    )
    written = integrate_units(
        kb_id="kb_batch", agent_id="ba-1", units=[u1, u2],
        derived_from=["m/t.md"],
        merge_candidates={
            "退款政策-补": cand,
            "退款政策-再补": cand,
        },
        merge_enabled=True,
        merge_payloads={
            "退款政策-补": payload,
            "退款政策-再补": payload,
        },
    )
    assert len(written) == 2
    assert all(p.name == fname("退款政策") for p in written)
    text = written[0].read_text(encoding="utf-8")
    assert "merge_count: 1" in text
    assert "corroborate_count: 1" in text
    assert not (root / "_inbox").exists() or not list((root / "_inbox").glob("*.md"))


def test_merge_enabled_summary_already_in_body_corroborates(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_same_claim")
    root = tmp_path / "knowledge_bases" / "kb_same_claim"
    target = _seed_node(root, "business/wiki", "退款政策")
    target.write_text(
        target.read_text(encoding="utf-8").replace(
            "original body", "7天无理由退换",
        ),
        encoding="utf-8",
    )
    unit = KnowledgeUnit(
        name="退款政策补充", bucket="business/wiki",
        summary="7天无理由退换",
    )
    written = integrate_units(
        kb_id="kb_same_claim", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={
            "退款政策补充": _biz_cand("退款政策", "business/wiki/退款政策.md"),
        },
        merge_enabled=True,
        merge_payloads={},
    )
    assert len(written) == 1
    assert written[0].name == fname("退款政策")
    text = written[0].read_text(encoding="utf-8")
    assert "corroborate_count: 1" in text
    assert "merge_count:" not in text or "merge_count: 0" in text


def test_run_knowledge_dream_merge_target_precomputes_payload(tmp_path, monkeypatch):
    """merge_target hint (no merge_search hit) must still get an LLM payload."""
    from datetime import datetime, timezone

    from qwenpaw.agents.knowledge.dream import run_knowledge_dream

    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_hint")
    root = tmp_path / "knowledge_bases" / "kb_hint"
    _seed_node(root, "business/wiki", "退款政策", priority='"P1"')

    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text("退款政策补充：7天无理由\n", encoding="utf-8")

    merge_prompts: list[str] = []

    async def fake_llm(prompt: str) -> str:
        ok = _integrity_ok_if_asked(prompt)
        if ok is not None:
            return ok
        if "合并助手" in prompt or "merge assistant" in prompt.lower():
            merge_prompts.append(prompt)
            return "# 退款政策\n\n7天无理由退换\n"
        return (
            '[{"name": "退款政策-补充", "bucket": "business/wiki", '
            '"summary": "7天无理由", "confidence": 0.9, '
            '"action_hint": "REFINE", "merge_target": "退款政策"}]'
        )

    import asyncio

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba-1",
            workspace_dir=workspace,
            kb_id="kb_hint",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
            merge_search=None,
            merge_enabled=True,
            merge_max_updates=5,
        ),
    )
    assert result["skipped"] is False
    assert merge_prompts, "merge_target should trigger payload pre-compute"
    written = Path(result["written"][0])
    assert written.name == fname("退款政策")
    assert written.parent.name != "_inbox"
    assert "7天无理由退换" in written.read_text(encoding="utf-8")


def test_run_knowledge_dream_groups_same_target_into_one_merge_llm(
    tmp_path, monkeypatch,
):
    from datetime import datetime, timezone

    from qwenpaw.agents.knowledge.dream import MergeCandidate, run_knowledge_dream

    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_group")
    root = tmp_path / "knowledge_bases" / "kb_group"
    _seed_node(root, "business/wiki", "退款政策")

    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text("退款两则补充\n", encoding="utf-8")

    merge_prompts: list[str] = []

    async def fake_llm(prompt: str) -> str:
        ok = _integrity_ok_if_asked(prompt)
        if ok is not None:
            return ok
        if "合并助手" in prompt:
            merge_prompts.append(prompt)
            return "# 退款政策\n\n合并后口径\n"
        return (
            '[{"name": "退款政策-补A", "bucket": "business/wiki", '
            '"summary": "7天无理由", "confidence": 0.9, '
            '"action_hint": "REFINE", "merge_target": "退款政策"},'
            ' {"name": "退款政策-补B", "bucket": "business/wiki", '
            '"summary": "包装完好", "confidence": 0.9, '
            '"action_hint": "REFINE", "merge_target": "退款政策"}]'
        )

    async def merge_search(name: str, summary: str):
        return MergeCandidate(
            name="退款政策",
            path="business/wiki/退款政策.md",
            ratio=0.95,
            is_clear=True,
        )

    import asyncio

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba-1",
            workspace_dir=workspace,
            kb_id="kb_group",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
            merge_search=merge_search,
            merge_enabled=True,
            merge_max_updates=5,
        ),
    )
    assert result["skipped"] is False
    assert len(merge_prompts) == 1
    assert "7天无理由" in merge_prompts[0]
    assert "包装完好" in merge_prompts[0]
    text = Path(result["written"][0]).read_text(encoding="utf-8")
    assert "merge_count: 1" in text
    assert "corroborate_count: 1" in text
    inbox = root / "_inbox"
    assert not inbox.exists() or not list(inbox.glob("*.md"))


def test_parse_integrity_verdict_ok_and_rejected():
    from qwenpaw.agents.knowledge.dream import _parse_integrity_verdict

    ok, parsed = _parse_integrity_verdict(
        '{"ok": true, "lost_claims": [], "injected_unrelated": []}',
    )
    assert parsed is True
    assert ok is True
    lost, parsed_lost = _parse_integrity_verdict(
        '{"ok": false, "lost_claims": ["7天时限"], "injected_unrelated": []}',
    )
    assert parsed_lost is True
    assert lost is False
    injected, parsed_inj = _parse_integrity_verdict(
        '{"ok": true, "lost_claims": [], "injected_unrelated": ["闲聊"]}',
    )
    assert parsed_inj is True
    assert injected is False
    skipped_ok, parsed_skip = _parse_integrity_verdict("not json")
    assert parsed_skip is False
    assert skipped_ok is False


def test_merge_integrity_failed_payload_goes_to_inbox(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_int")
    root = tmp_path / "knowledge_bases" / "kb_int"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="7天无理由", action_hint="REFINE",
    )
    payload = _payload_for(root, "退款政策", "business/wiki")
    payload.integrity_ok = False
    written = integrate_units(
        kb_id="kb_int", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={
            "退款政策-补": _biz_cand("退款政策", "business/wiki/退款政策.md"),
        },
        merge_enabled=True,
        merge_payloads={"退款政策-补": payload},
    )
    assert len(written) == 1
    assert written[0].parent.name == "_inbox"
    text = written[0].read_text(encoding="utf-8")
    assert "inbox_reason: integrity_failed" in text
    # Original published node is untouched.
    published = (root / "business" / "wiki" / fname("退款政策")).read_text(
        encoding="utf-8",
    )
    assert "original body" in published


def test_merge_integrity_skipped_payload_goes_to_inbox(tmp_path, monkeypatch):
    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_int_skip")
    root = tmp_path / "knowledge_bases" / "kb_int_skip"
    _seed_node(root, "business/wiki", "退款政策")
    unit = KnowledgeUnit(
        name="退款政策-补", bucket="business/wiki",
        summary="7天无理由", action_hint="REFINE",
    )
    payload = _payload_for(root, "退款政策", "business/wiki")
    payload.integrity_ok = False
    payload.integrity_skipped = True
    written = integrate_units(
        kb_id="kb_int_skip", agent_id="ba-1", units=[unit],
        derived_from=["m/t.md"],
        merge_candidates={
            "退款政策-补": _biz_cand("退款政策", "business/wiki/退款政策.md"),
        },
        merge_enabled=True,
        merge_payloads={"退款政策-补": payload},
    )
    assert len(written) == 1
    assert written[0].parent.name == "_inbox"
    text = written[0].read_text(encoding="utf-8")
    assert "inbox_reason: integrity_check_skipped" in text
    from qwenpaw.agents.knowledge.dream import list_inbox_items
    items = list_inbox_items("kb_int_skip")
    assert items[0].retryable is True
    published = (root / "business" / "wiki" / fname("退款政策")).read_text(
        encoding="utf-8",
    )
    assert "original body" in published


def test_run_knowledge_dream_integrity_reject_does_not_rewrite(
    tmp_path, monkeypatch,
):
    from datetime import datetime, timezone

    from qwenpaw.agents.knowledge.dream import MergeCandidate, run_knowledge_dream

    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_int_dream")
    root = tmp_path / "knowledge_bases" / "kb_int_dream"
    _seed_node(root, "business/wiki", "退款政策")
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text("退款政策补充：7天无理由\n", encoding="utf-8")

    async def fake_llm(prompt: str) -> str:
        if "完整性审查" in prompt or "information loss" in prompt.lower():
            return (
                '{"ok": false, "lost_claims": ["原7天时限"], '
                '"injected_unrelated": []}'
            )
        if "合并助手" in prompt or "merge assistant" in prompt.lower():
            return "# 退款政策\n\n被截断的正文\n"
        if "补漏审查" in prompt or "coverage reviewer" in prompt.lower():
            return "[]"
        return (
            '[{"name": "退款政策-补充", "bucket": "business/wiki", '
            '"summary": "7天无理由", "confidence": 0.9, '
            '"action_hint": "REFINE", "merge_target": "退款政策"}]'
        )

    async def merge_search(name: str, summary: str):
        return MergeCandidate(
            name="退款政策",
            path="business/wiki/退款政策.md",
            ratio=0.95,
            is_clear=True,
        )

    import asyncio

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba-1",
            workspace_dir=workspace,
            kb_id="kb_int_dream",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
            merge_search=merge_search,
            merge_enabled=True,
            merge_max_updates=5,
        ),
    )
    assert result["skipped"] is False
    written = Path(result["written"][0])
    assert written.parent.name == "_inbox"
    assert "inbox_reason: integrity_failed" in written.read_text(encoding="utf-8")
    published = (root / "business" / "wiki" / fname("退款政策")).read_text(
        encoding="utf-8",
    )
    assert "被截断的正文" not in published
    assert "original body" in published


def test_run_knowledge_dream_integrity_unparseable_does_not_rewrite(
    tmp_path, monkeypatch,
):
    from datetime import datetime, timezone

    from qwenpaw.agents.knowledge.dream import MergeCandidate, run_knowledge_dream

    _patch_kb_roots(monkeypatch, tmp_path)
    ensure_kb("kb_int_skip_dream")
    root = tmp_path / "knowledge_bases" / "kb_int_skip_dream"
    _seed_node(root, "business/wiki", "退款政策")
    workspace = tmp_path / "ws"
    daily = workspace / "memory"
    daily.mkdir(parents=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (daily / f"{today}.md").write_text("退款政策补充：7天无理由\n", encoding="utf-8")

    async def fake_llm(prompt: str) -> str:
        if "完整性审查" in prompt or "information loss" in prompt.lower():
            return "sorry, not json"
        if "合并助手" in prompt or "merge assistant" in prompt.lower():
            return "# 退款政策\n\n被截断的正文\n"
        if "补漏审查" in prompt or "coverage reviewer" in prompt.lower():
            return "[]"
        return (
            '[{"name": "退款政策-补充", "bucket": "business/wiki", '
            '"summary": "7天无理由", "confidence": 0.9, '
            '"action_hint": "REFINE", "merge_target": "退款政策"}]'
        )

    async def merge_search(name: str, summary: str):
        return MergeCandidate(
            name="退款政策",
            path="business/wiki/退款政策.md",
            ratio=0.95,
            is_clear=True,
        )

    import asyncio

    result = asyncio.run(
        run_knowledge_dream(
            agent_id="ba-1",
            workspace_dir=workspace,
            kb_id="kb_int_skip_dream",
            daily_dir_name="memory",
            metadata_dir="mem_metadata",
            language="zh",
            domain="business",
            scan_days=2,
            max_units=8,
            write_mode="open",
            inbox_enabled=False,
            llm_call=fake_llm,
            merge_search=merge_search,
            merge_enabled=True,
            merge_max_updates=5,
        ),
    )
    assert result["skipped"] is False
    written = Path(result["written"][0])
    assert written.parent.name == "_inbox"
    assert "inbox_reason: integrity_check_skipped" in written.read_text(
        encoding="utf-8",
    )
    published = (root / "business" / "wiki" / fname("退款政策")).read_text(
        encoding="utf-8",
    )
    assert "被截断的正文" not in published
    assert "original body" in published


