# -*- coding: utf-8 -*-
"""Unit tests for the kb-test-derive skill scripts.

Covers the P0 regression surface:
- slugify (ASCII prefix + non-ASCII body)
- parse_link_spec / format_wikilink / extract_wikilink_targets
- render_node_markdown: frontmatter shape, inbox status, intended_bucket,
  duplicate H1 stripping, auto 关联 section
- write_nodes: dry-run preview, inbox re-render (no string surgery),
  published overwrite refused without --force, archive on --force
- validate_file: reflow_key_mismatch, stale_reflow_version,
  duplicate_requirement_id, missing_chapter, too_many_case_links
- derive.py: pre_errors NameError regression
- scan_module: status filter, signal/substr/hops, proposals embed
- propose_assist: near-dup + coverage gaps (propose-only)
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# conftest.py in this dir puts skill scripts on sys.path.
import reme_format  # type: ignore[import-not-found]
import scan_module  # type: ignore[import-not-found]
import validate_nodes  # type: ignore[import-not-found]
import write_nodes  # type: ignore[import-not-found]
import derive  # type: ignore[import-not-found]

from reme_format import (  # type: ignore[import-not-found]
    kb_root,
    parse_frontmatter,
    slugify,
    unquote_list,
)


# --- reme_format -----------------------------------------------------------

def test_slugify_design_prefix_and_non_ascii():
    assert slugify("指纹-生命周期", "design").startswith("td-")
    assert "指纹" in slugify("指纹-生命周期", "design")


def test_slugify_data_prefix():
    assert slugify("样本集", "data").startswith("ttd-")


def test_unquote_list_handles_empty_and_items():
    assert unquote_list("") == []
    assert unquote_list("[]") == []
    assert unquote_list('["a", "b"]') == ["a", "b"]


def test_parse_link_spec_with_display():
    path, display = reme_format.parse_link_spec("knowledge/business/wiki/x.md|标题")
    assert path == "business/wiki/x.md"
    assert display == "标题"


def test_parse_link_spec_strips_knowledge_prefix():
    path, _ = reme_format.parse_link_spec("knowledge/test/test_design/a.md|A")
    assert path == "test/test_design/a.md"


def test_format_wikilink_adds_knowledge_prefix():
    link = reme_format.format_wikilink("business/wiki/x.md", "X")
    assert link == "[[knowledge/business/wiki/x.md|X]]"


def test_extract_wikilink_targets_strips_prefix():
    body = "[[knowledge/business/wiki/x.md|X]] and [[knowledge/test/test_design/y.md|Y]]"
    targets = reme_format.extract_wikilink_targets(body)
    assert targets == ["business/wiki/x.md", "test/test_design/y.md"]


def test_render_node_markdown_emits_frontmatter_and_h1():
    md = reme_format.render_node_markdown(
        artifact="design",
        name="指纹-生命周期",
        description="指纹增删改生命周期主路径与取消保留语义。",
        requirement_id="TD-FP-01",
        body_markdown="## 目标场景\n\n新增/修改/删除主路径。\n",
        derived_from=["derived:fingerprint-design-v1"],
        signals=["module:指纹"],
        links=["business/procedure/用户管理-新增指纹.md|新增指纹"],
    )
    fm, body = parse_frontmatter(md)
    assert fm["name"] == "指纹-生命周期"
    assert fm["bucket"] == "test/test_design"
    assert fm["status"] == "published"
    assert fm["requirement_id"] == "TD-FP-01"
    assert "derived:fingerprint-design-v1" in fm["derived_from"]
    assert body.lstrip().startswith("# 指纹-生命周期")
    # auto 关联 section appended
    assert "## 关联" in body
    assert "[[knowledge/business/procedure/用户管理-新增指纹.md|新增指纹]]" in body


def test_render_node_markdown_strips_duplicate_h1_in_body():
    md = reme_format.render_node_markdown(
        artifact="design",
        name="X",
        description="描述说明文字足够长。",
        requirement_id="TD-X-01",
        body_markdown="# X\n\n## 目标场景\n\n正文足够长一些。\n",
        derived_from=["derived:x-design-v1"],
        signals=["module:X"],
    )
    _, body = parse_frontmatter(md)
    # only one H1 (the auto-emitted one); body's H1 dropped
    assert body.lstrip().count("# X") == 1


def test_render_node_markdown_inbox_status_and_intended_bucket():
    md = reme_format.render_node_markdown(
        artifact="design",
        name="X",
        description="描述说明文字足够长。",
        requirement_id="TD-X-01",
        body_markdown="## 目标场景\n\n正文足够长一些。\n",
        derived_from=["derived:x-design-v1"],
        signals=["module:X"],
        status="inbox",
        intended_bucket="test/test_design",
    )
    fm, _ = parse_frontmatter(md)
    assert fm["status"] == "inbox"
    assert fm["intended_bucket"] == "test/test_design"
    assert fm["inbox_reason"] == "derived_pending_review"


# --- write_nodes ----------------------------------------------------------

def _minimal_plan(*, artifact="design", module="指纹", reflow="derived:fingerprint-design-v1",
                   nodes=None) -> dict:
    if nodes is None:
        nodes = [{
            "requirement_id": "TD-FP-01",
            "name": "指纹-生命周期",
            "description": "指纹增删改生命周期主路径与取消保留语义。",
            "body_markdown": "## 目标场景\n\n新增/修改/删除主路径。\n",
            "derived_from": [reflow],
            "signals": ["module:指纹"],
            "links": [],
        }]
    return {
        "module": module,
        "artifact": artifact,
        "reflow_key": reflow,
        "nodes": nodes,
    }


def test_write_nodes_dry_run_does_not_write(tmp_path):
    root = kb_root(tmp_path, "zhb")
    root.joinpath("test/test_design").mkdir(parents=True, exist_ok=True)
    ledger = write_nodes.write_nodes(
        working_dir=tmp_path, kb_id="zhb",
        plan=_minimal_plan(), mode="dry-run",
    )
    assert ledger["mode"] == "dry-run"
    assert ledger["nodes"] and ledger["nodes"][0]["bytes"] > 0
    # nothing published
    assert not (root / "test/test_design").glob("*.md") or not list(
        (root / "test/test_design").glob("*.md")
    )
    # preview ledger exists
    assert (root / "_audit/derived_design").is_dir()


def test_write_nodes_inbox_uses_inbox_status(tmp_path):
    root = kb_root(tmp_path, "zhb")
    ledger = write_nodes.write_nodes(
        working_dir=tmp_path, kb_id="zhb",
        plan=_minimal_plan(), mode="inbox",
    )
    assert ledger["mode"] == "inbox"
    inbox_file = root / "_inbox" / "td-指纹-生命周期.md"
    assert inbox_file.is_file()
    fm, _ = parse_frontmatter(inbox_file.read_text(encoding="utf-8"))
    assert fm["status"] == "inbox"
    assert fm["intended_bucket"] == "test/test_design"
    assert fm["inbox_reason"] == "derived_pending_review"


def test_write_nodes_published_writes_to_bucket(tmp_path):
    root = kb_root(tmp_path, "zhb")
    ledger = write_nodes.write_nodes(
        working_dir=tmp_path, kb_id="zhb",
        plan=_minimal_plan(), mode="published",
    )
    assert ledger["mode"] == "published"
    dest = root / "test/test_design" / "td-指纹-生命周期.md"
    assert dest.is_file()
    fm, _ = parse_frontmatter(dest.read_text(encoding="utf-8"))
    assert fm["status"] == "published"


def test_write_nodes_published_refuses_changed_overwrite_without_force(tmp_path):
    root = kb_root(tmp_path, "zhb")
    plan = _minimal_plan()
    write_nodes.write_nodes(working_dir=tmp_path, kb_id="zhb", plan=plan, mode="published")
    dest = root / "test/test_design" / "td-指纹-生命周期.md"
    # hand-edit the published node
    dest.write_text(dest.read_text(encoding="utf-8") + "\n<!-- hand edit -->\n", encoding="utf-8")
    # re-publish same plan -> content differs -> refused
    ledger = write_nodes.write_nodes(
        working_dir=tmp_path, kb_id="zhb", plan=plan, mode="published",
    )
    assert ledger["refused"], ledger
    assert ledger["refused"][0]["reason"] == "content_changed_requires_force"
    # hand edit preserved (not clobbered)
    assert "<!-- hand edit -->" in dest.read_text(encoding="utf-8")


def test_write_nodes_published_force_archives_previous(tmp_path):
    root = kb_root(tmp_path, "zhb")
    plan = _minimal_plan()
    write_nodes.write_nodes(working_dir=tmp_path, kb_id="zhb", plan=plan, mode="published")
    dest = root / "test/test_design" / "td-指纹-生命周期.md"
    dest.write_text(dest.read_text(encoding="utf-8") + "\n<!-- hand edit -->\n", encoding="utf-8")
    ledger = write_nodes.write_nodes(
        working_dir=tmp_path, kb_id="zhb", plan=plan, mode="published", force=True,
    )
    assert ledger["overwritten"], ledger
    archive = root / ledger["overwritten"][0]["archive"]
    assert archive.is_file()
    assert "<!-- hand edit -->" in archive.read_text(encoding="utf-8")
    # new content written, hand edit gone from live file
    assert "<!-- hand edit -->" not in dest.read_text(encoding="utf-8")


def test_write_nodes_published_idempotent_no_force_needed(tmp_path):
    """Re-publishing identical content is not an overwrite (no diff)."""
    root = kb_root(tmp_path, "zhb")
    plan = _minimal_plan()
    write_nodes.write_nodes(working_dir=tmp_path, kb_id="zhb", plan=plan, mode="published")
    ledger = write_nodes.write_nodes(
        working_dir=tmp_path, kb_id="zhb", plan=plan, mode="published",
    )
    assert not ledger["refused"]
    assert not ledger["overwritten"]


def test_write_nodes_force_refreshes_stale_updated_at(tmp_path):
    """Overwriting with a plan updated_at not newer than existing must force
    a fresh timestamp so recall can detect the change."""
    root = kb_root(tmp_path, "zhb")
    plan = _minimal_plan()
    plan["nodes"][0]["updated_at"] = "2020-01-01T00:00:00+00:00"
    write_nodes.write_nodes(working_dir=tmp_path, kb_id="zhb", plan=plan, mode="published")
    dest = root / "test/test_design" / "td-指纹-生命周期.md"
    # mutate body so overwrite is triggered
    plan["nodes"][0]["body_markdown"] = "## 目标场景\n\n更新后的正文内容。\n"
    ledger = write_nodes.write_nodes(
        working_dir=tmp_path, kb_id="zhb", plan=plan, mode="published", force=True,
    )
    assert ledger["forced_refresh"], ledger
    fr = ledger["forced_refresh"][0]
    # new updated_at must be later than the stale 2020 value
    assert fr["new_updated_at"] > "2020-01-01T00:00:00+00:00"
    fm, _ = parse_frontmatter(dest.read_text(encoding="utf-8"))
    assert fm["updated_at"] > "2020-01-01T00:00:00+00:00"


def test_write_nodes_force_keeps_advancing_updated_at(tmp_path):
    """If plan updated_at is newer than existing, no forced refresh needed."""
    root = kb_root(tmp_path, "zhb")
    plan = _minimal_plan()
    plan["nodes"][0]["updated_at"] = "2020-01-01T00:00:00+00:00"
    write_nodes.write_nodes(working_dir=tmp_path, kb_id="zhb", plan=plan, mode="published")
    plan["nodes"][0]["body_markdown"] = "## 目标场景\n\n更新后的正文内容。\n"
    plan["nodes"][0]["updated_at"] = "2030-01-01T00:00:00+00:00"
    ledger = write_nodes.write_nodes(
        working_dir=tmp_path, kb_id="zhb", plan=plan, mode="published", force=True,
    )
    assert not ledger["forced_refresh"]
    dest = root / "test/test_design" / "td-指纹-生命周期.md"
    fm, _ = parse_frontmatter(dest.read_text(encoding="utf-8"))
    assert fm["updated_at"] == "2030-01-01T00:00:00+00:00"


# --- validate_nodes -------------------------------------------------------

def _write_node(path: Path, *, name, description, requirement_id, derived_from,
                bucket="test/test_design", status="published",
                body="## 目标场景\n\n正文足够长一些。\n",
                links_section="", signals=None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    derived = "[" + ", ".join(f'"{d}"' for d in derived_from) + "]"
    sig_line = ""
    if signals is not None:
        sig = "[" + ", ".join(f'"{s}"' for s in signals) + "]"
        sig_line = f"signals: {sig}\n"
    md = (
        "---\n"
        f'name: "{name}"\n'
        f'description: "{description}"\n'
        f"bucket: {bucket}\n"
        f"status: {status}\n"
        f"{sig_line}"
        f"derived_from: {derived}\n"
        f'requirement_id: "{requirement_id}"\n'
        "---\n\n"
        f"# {name}\n\n{body}{links_section}"
    )
    path.write_text(md, encoding="utf-8")
    return path


def test_validate_file_passes_for_well_formed_node(tmp_path):
    root = kb_root(tmp_path, "zhb")
    # create a link target so wikilink resolves
    target = root / "business/procedure/新增指纹.md"
    _write_node(target, name="新增指纹", description="业务节点描述。",
                requirement_id="B-FP-01", derived_from=[])
    node = _write_node(
        root / "test/test_design/td-指纹-生命周期.md",
        name="指纹-生命周期", description="指纹增删改生命周期主路径。",
        requirement_id="TD-FP-01",
        derived_from=["derived:fingerprint-design-v1"],
        links_section="\n## 关联\n\n- [[knowledge/business/procedure/新增指纹.md|新增指纹]]\n",
    )
    findings = validate_nodes.validate_file(node, kb=root, artifact="design",
                                             expected_reflow="derived:fingerprint-design-v1")
    errors = [f for f in findings if f.severity == "error"]
    assert errors == [], errors


def test_validate_file_missing_chapter_is_warn(tmp_path):
    """A design missing required chapters (目标场景/等价类/必测要点) warns."""
    root = kb_root(tmp_path, "zhb")
    node = _write_node(
        root / "test/test_design/td-x.md",
        name="X", description="描述说明文字足够长。",
        requirement_id="TD-X-01",
        derived_from=["derived:x-design-v1"],
        body="## 只有这一段正文，缺章节。\n" * 3,
    )
    findings = validate_nodes.validate_file(
        node, kb=root, artifact="design",
        expected_reflow="derived:x-design-v1",
    )
    codes = [f.code for f in findings if f.severity == "warn"]
    # All three required design chapters should be flagged missing.
    missing = [c for c in codes if c == "missing_chapter"]
    assert len(missing) == 3, findings


def test_validate_file_too_many_case_links_is_warn(tmp_path):
    """A design linking >8 test_cases triggers too_many_case_links warn."""
    root = kb_root(tmp_path, "zhb")
    # Create 10 case targets so wikilinks resolve.
    links = []
    for i in range(10):
        case_path = root / f"test/test_cases/t-case-{i}.md"
        _write_node(case_path, name=f"case-{i}", description=f"用例{i}描述。",
                    requirement_id=f"T-FP-{i}", derived_from=[],
                    bucket="test/test_cases")
        links.append(f"- [[knowledge/test/test_cases/t-case-{i}.md|case-{i}]]")
    body = "## 目标场景\n\n## 等价类\n\n## 必测要点\n\n- 要点\n\n## 关联\n\n" + "\n".join(links)
    node = _write_node(
        root / "test/test_design/td-x.md",
        name="X", description="描述说明文字足够长。",
        requirement_id="TD-X-01",
        derived_from=["derived:x-design-v1"],
        body=body,
    )
    findings = validate_nodes.validate_file(
        node, kb=root, artifact="design",
        expected_reflow="derived:x-design-v1",
    )
    codes = [f.code for f in findings if f.severity == "warn"]
    assert "too_many_case_links" in codes, findings


def test_derive_main_pre_errors_no_nameerror(tmp_path):
    """Regression: derive.py used to raise NameError on pre_errors when
    expected_reflow was set. Now it must exit cleanly with code 0/1,
    not crash."""
    import json as _json
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        _json.dumps(_minimal_plan(), ensure_ascii=False), encoding="utf-8",
    )
    rc = derive.main([
        "--working-dir", str(tmp_path), "--kb-id", "zhb",
        "--artifact", "design", "--module", "指纹",
        "--plan", str(plan_path), "--mode", "dry-run",
        "--expected-reflow", "derived:fingerprint-design-v1",
    ])
    assert rc in (0, 1)


def test_validate_file_reflow_key_mismatch_is_error(tmp_path):
    root = kb_root(tmp_path, "zhb")
    node = _write_node(
        root / "test/test_design/td-x.md",
        name="X", description="描述说明文字足够长。",
        requirement_id="TD-X-01",
        derived_from=["derived:x-design-v1"],
    )
    findings = validate_nodes.validate_file(
        node, kb=root, artifact="design",
        expected_reflow="derived:x-design-v2",
    )
    codes = [f.code for f in findings if f.severity == "error"]
    assert "reflow_key_mismatch" in codes


def test_validate_file_stale_reflow_version_is_warn(tmp_path):
    root = kb_root(tmp_path, "zhb")
    node = _write_node(
        root / "test/test_design/td-x.md",
        name="X", description="描述说明文字足够长。",
        requirement_id="TD-X-01",
        derived_from=["derived:x-design-v1", "derived:x-design-v2"],
    )
    findings = validate_nodes.validate_file(
        node, kb=root, artifact="design",
        expected_reflow="derived:x-design-v2",
    )
    codes = [f.code for f in findings if f.severity == "warn"]
    assert "stale_reflow_version" in codes


def test_validate_main_flags_duplicate_requirement_id(tmp_path, capsys):
    root = kb_root(tmp_path, "zhb")
    _write_node(
        root / "test/test_design/td-a.md",
        name="A", description="描述说明文字足够长A。",
        requirement_id="TD-FP-01",
        derived_from=["derived:fingerprint-design-v1"],
    )
    _write_node(
        root / "test/test_design/td-b.md",
        name="B", description="描述说明文字足够长B。",
        requirement_id="TD-FP-01",
        derived_from=["derived:fingerprint-design-v1"],
    )
    rc = validate_nodes.main([
        "--working-dir", str(tmp_path), "--kb-id", "zhb",
        "--path", str(root / "test/test_design"),
        "--artifact", "design", "--json",
    ])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["errors"] >= 1
    codes = [f["code"] for f in payload["findings"]]
    assert "duplicate_requirement_id" in codes
    assert rc == 1


# --- scan_module ----------------------------------------------------------

def test_scan_module_skips_inbox_status(tmp_path):
    root = kb_root(tmp_path, "zhb")
    _write_node(
        root / "business/wiki/指纹.md",
        name="指纹", description="指纹模块业务定义说明。",
        requirement_id="B-FP-01", derived_from=[],
        bucket="business/wiki",
    )
    _write_node(
        root / "business/wiki/指纹-inbox.md",
        name="指纹-inbox", description="指纹模块待审节点说明。",
        requirement_id="B-FP-02", derived_from=[],
        bucket="business/wiki", status="inbox",
    )
    report = scan_module.scan(tmp_path, "zhb", "指纹", [], propose=False)
    names = [n["name"] for n in report["business"]]
    assert "指纹" in names
    assert "指纹-inbox" not in names


def test_scan_module_alias_matches(tmp_path):
    root = kb_root(tmp_path, "zhb")
    _write_node(
        root / "business/wiki/指纹模组.md",
        name="指纹模组", description="指纹模组业务说明文字。",
        requirement_id="B-FP-03", derived_from=[],
        bucket="business/wiki",
    )
    report = scan_module.scan(tmp_path, "zhb", "指纹", ["指纹模组"], propose=False)
    names = [n["name"] for n in report["business"]]
    assert "指纹模组" in names


def test_scan_module_prefers_signal_over_unrelated_substr_noise(tmp_path):
    """signal:module:指纹 seeds; node without term in card but with signal hits."""
    root = kb_root(tmp_path, "zhb")
    _write_node(
        root / "business/wiki/生物识别入口.md",
        name="生物识别入口", description="门禁主流程说明文字足够。",
        requirement_id="B-FP-10", derived_from=[],
        bucket="business/wiki",
        signals=["module:指纹"],
    )
    report = scan_module.scan(
        tmp_path, "zhb", "指纹", [], hops=0, propose=False, match_mode="hybrid",
    )
    by_name = {n["name"]: n for n in report["business"]}
    assert "生物识别入口" in by_name
    assert any(r.startswith("signal:") for r in by_name["生物识别入口"]["match_reasons"])


def test_scan_module_signal_only_ignores_substr(tmp_path):
    root = kb_root(tmp_path, "zhb")
    _write_node(
        root / "business/wiki/指纹模组.md",
        name="指纹模组", description="指纹模组业务说明文字。",
        requirement_id="B-FP-03", derived_from=[],
        bucket="business/wiki",
    )
    report = scan_module.scan(
        tmp_path, "zhb", "指纹", [], hops=0, propose=False, match_mode="signal",
    )
    assert report["counts"]["business"] == 0


def test_scan_module_hops_expand_wikilink_neighbors(tmp_path):
    root = kb_root(tmp_path, "zhb")
    # Seed via signal only (name/path/body must not contain the module term).
    biz = root / "business/procedure/enroll-flow.md"
    case2 = root / "test/test_cases/t-enroll.md"
    _write_node(
        biz, name="登记主流程", description="门禁登记主路径说明足够长。",
        requirement_id="B-FP-01", derived_from=[],
        bucket="business/procedure",
        signals=["module:指纹"],
        body="## 流程\n\n主路径说明足够长。\n",
    )
    _write_node(
        case2, name="enroll-main", description="主路径登记验收步骤说明。",
        requirement_id="T-FP-02", derived_from=[],
        bucket="test/test_cases",
        body="## 步骤\n\n执行登记。\n\n## 关联\n\n"
             "- [[knowledge/business/procedure/enroll-flow.md|登记主流程]]\n",
    )
    report = scan_module.scan(
        tmp_path, "zhb", "指纹", [], hops=1, propose=False, match_mode="hybrid",
    )
    case_names = {n["name"] for n in report["test_cases"]}
    assert "enroll-main" in case_names
    hop_node = next(n for n in report["test_cases"] if n["name"] == "enroll-main")
    assert hop_node["match_reasons"] == ["hop:1"]
    biz_node = next(n for n in report["business"] if n["name"] == "登记主流程")
    assert any(r.startswith("signal:") for r in biz_node["match_reasons"])


def test_scan_module_includes_proposals_by_default(tmp_path):
    root = kb_root(tmp_path, "zhb")
    _write_node(
        root / "business/wiki/指纹.md",
        name="指纹", description="指纹模块业务定义说明。",
        requirement_id="B-FP-01", derived_from=[],
        bucket="business/wiki",
    )
    report = scan_module.scan(tmp_path, "zhb", "指纹", [], hops=0, propose=True)
    assert "proposals" in report
    assert report["proposals"]["propose_only"] is True
    assert "coverage_gaps" in report["proposals"]


# --- propose_assist -------------------------------------------------------

def test_propose_near_duplicates_detects_similar_designs():
    import propose_assist  # type: ignore[import-not-found]

    designs = [
        {
            "path": "test/test_design/td-a.md",
            "name": "指纹-生命周期-增删改",
            "description": "指纹增删改生命周期主路径与取消保留。",
            "requirement_id": "TD-FP-01",
        },
        {
            "path": "test/test_design/td-b.md",
            "name": "指纹-生命周期增删改",
            "description": "指纹增删改生命周期主路径取消后保留旧指纹。",
            "requirement_id": "TD-FP-02",
        },
    ]
    props = propose_assist.propose_near_duplicates(designs, threshold=0.4)
    assert props
    assert props[0]["suggested_action"] == "REFINE"


def test_propose_coverage_gaps_business_without_case(tmp_path):
    import propose_assist  # type: ignore[import-not-found]

    report = {
        "business": [{
            "path": "business/wiki/指纹.md",
            "name": "指纹",
            "description": "指纹模块",
            "out_links": [],
            "body_preview": "",
        }],
        "test_cases": [],
        "defects": [],
        "existing_design": [],
    }
    gaps = propose_assist.propose_coverage_gaps(report)
    kinds = [g["kind"] for g in gaps]
    assert "business_without_case" in kinds


def test_propose_coverage_gaps_active_defect_uncovered():
    import propose_assist  # type: ignore[import-not-found]

    report = {
        "business": [],
        "test_cases": [],
        "defects": [{
            "path": "test/defects/dp-指纹取消残留.md",
            "name": "指纹取消残留",
            "description": "取消后旧指纹仍可用。",
            "signals": ["pattern_active:true"],
            "requirement_id": "DP-FP-01",
            "out_links": [],
            "body_preview": "",
        }],
        "existing_design": [{
            "path": "test/test_design/td-other.md",
            "name": "其它设计",
            "description": "无关主题",
            "out_links": [],
            "body_preview": "",
        }],
    }
    gaps = propose_assist.propose_coverage_gaps(report)
    kinds = [g["kind"] for g in gaps]
    assert "active_defect_uncovered" in kinds


def test_propose_draft_vs_existing():
    import propose_assist  # type: ignore[import-not-found]

    existing = [{
        "path": "test/test_design/td-a.md",
        "name": "指纹-活体检测",
        "description": "指纹活体验收与仿制拒绝。",
        "requirement_id": "TD-FP-03",
    }]
    drafts = [{
        "name": "指纹-活体与仿制",
        "description": "指纹活体验收与仿制样本拒绝策略。",
        "requirement_id": "TD-FP-99",
    }]
    props = propose_assist.propose_near_duplicates(
        existing, drafts=drafts, threshold=0.35,
    )
    assert any(p["kind"] == "near_duplicate_draft" for p in props)
    assert props[0]["prefer_requirement_id"] == "TD-FP-03"
