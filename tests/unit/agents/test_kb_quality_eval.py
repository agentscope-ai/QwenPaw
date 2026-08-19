# -*- coding: utf-8 -*-
"""Unit tests for the kb-quality-eval skill.

Covers core scoring/grading logic and regression fixes:
- #1 redundancy cap must not skip description checks
- #3 completeness passes weave=False
- #4 auto-probes use leave-one-out (no self-hit)
- #7 stale_published dedup by node path
- #9 redundancy_metrics includes all dup codes
"""
from __future__ import annotations

from pathlib import Path

import pytest

# conftest.py in this dir puts skill scripts on sys.path.
import catalog  # type: ignore[import-not-found]
import checks_completeness  # type: ignore[import-not-found]
import checks_redundancy  # type: ignore[import-not-found]
import checks_retrieval  # type: ignore[import-not-found]
import water_level  # type: ignore[import-not-found]

from catalog import Finding, NodeRecord  # type: ignore[import-not-found]


def _node(*, path="business/wiki/a.md", name="节点A", description="节点A的描述说明",
          bucket="business/wiki", status="published",
          body="# 节点A\n\n这是一个足够长的正文段落用于测试。\n",
          signals=None, derived_from=None, requirement_id="", priority=""):
    return NodeRecord(
        path=path, abs_path=Path(path), name=name, description=description,
        bucket=bucket, status=status, body=body, signals=signals or [],
        derived_from=derived_from or [], requirement_id=requirement_id,
        priority=priority,
        frontmatter={"name": name, "description": description, "bucket": bucket, "status": status},
    )


# --- catalog ---------------------------------------------------------------

def test_parse_frontmatter_basic():
    fm, body = catalog.parse_frontmatter('---\nname: "x"\n---\nbody')
    assert fm["name"] == "x"
    assert body == "body"


def test_parse_frontmatter_no_fm():
    fm, body = catalog.parse_frontmatter("plain")
    assert fm == {}
    assert body == "plain"


def test_extract_wikilinks():
    links = catalog.extract_wikilinks("[[knowledge/business/wiki/foo.md|标题]] and [[标题]]")
    targets = [t for _r, t in links]
    assert "knowledge/business/wiki/foo.md" in targets
    assert "标题" in targets


def test_normalize_text():
    assert catalog.normalize_text("Hello World") == "helloworld"


def test_resolve_kb_root_uses_store_when_available(tmp_path, monkeypatch):
    """When qwenpaw.store is importable, resolve_kb_root delegates to it."""
    import sys
    import types

    fake_mod = types.ModuleType("qwenpaw.agents.knowledge.store")
    fake_mod.kb_root = lambda kb_id: Path("/resolved/by/store") / kb_id
    pkg = types.ModuleType("qwenpaw")
    pkg_agents = types.ModuleType("qwenpaw.agents")
    pkg_kn = types.ModuleType("qwenpaw.agents.knowledge")
    monkeypatch.setitem(sys.modules, "qwenpaw", pkg)
    monkeypatch.setitem(sys.modules, "qwenpaw.agents", pkg_agents)
    monkeypatch.setitem(sys.modules, "qwenpaw.agents.knowledge", pkg_kn)
    monkeypatch.setitem(sys.modules, "qwenpaw.agents.knowledge.store", fake_mod)

    root = catalog.resolve_kb_root(Path("/anywhere"), "zhb")
    assert root == Path("/resolved/by/store/zhb")


def test_resolve_kb_root_falls_back_with_warning(tmp_path, caplog, monkeypatch):
    """Fix #12: fallback must log a warning naming the fallback path."""
    # Force the store import to fail by hiding qwenpaw if present.
    import sys
    monkeypatch.setattr(
        catalog, "__file__",
        str(Path(catalog.__file__).resolve()),
    )
    # Make the repo src lookup fail by pointing parents[4] at a non-src path.
    # Simpler: poison the import by setting a bogus module.
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "qwenpaw.agents.knowledge.store" or name.startswith("qwenpaw"):
            raise ImportError("poisoned for test")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    working = tmp_path / "wd"
    with caplog.at_level("WARNING", logger="kb_quality_eval.catalog"):
        root = catalog.resolve_kb_root(working, "zhb")
    assert root == working / "knowledge_bases" / "zhb"
    assert any("resolve_kb_root" in r.message and "falling back" in r.message
               for r in caplog.records), "expected fallback warning"


# --- water_level -----------------------------------------------------------

@pytest.mark.parametrize("score,expected",
                         [(95, "A"), (89, "B"), (74, "C"), (59, "D"), (39, "F")])
def test_level_floors(score, expected):
    assert water_level.assign_water_level(
        score=score, structural_errors=0, broken_links=0,
        hard_leaks=0, completeness_scored=True) == expected


def test_cap_structural_errors_to_D():
    assert water_level.assign_water_level(
        score=95, structural_errors=1, broken_links=0,
        hard_leaks=0, completeness_scored=True) == "D"


def test_cap_broken_links_to_B():
    assert water_level.assign_water_level(
        score=95, structural_errors=0, broken_links=1,
        hard_leaks=0, completeness_scored=True) == "B"


def test_cap_hard_leaks_to_C():
    assert water_level.assign_water_level(
        score=95, structural_errors=0, broken_links=0,
        hard_leaks=1, completeness_scored=True) == "C"


def test_cap_unscored_to_B():
    assert water_level.assign_water_level(
        score=95, structural_errors=0, broken_links=0,
        hard_leaks=0, completeness_scored=False) == "B"


def test_ok_for_use():
    assert water_level.ok_for_use("B") is True
    assert water_level.ok_for_use("C") is False


def test_compute_total_scored():
    assert water_level.compute_total(
        structural=100, graph=100, retrieval=100,
        completeness=100, completeness_scored=True) == 100.0


def test_compute_total_unscored():
    assert water_level.compute_total(
        structural=100, graph=100, retrieval=100,
        completeness=None, completeness_scored=False) == 100.0


def test_trend_legacy_score_scaled():
    t = water_level.build_trend({"score": 0.82}, water_level="B", score=80)
    assert t["prev_score"] == 82.0
    assert t["direction"] == "down"  # 80 < 82


def test_top_actions_limit():
    structural = [{"severity": "error", "code": "missing_frontmatter",
                   "path": "a.md", "message": "m"}] * 20
    actions = water_level.top_actions(
        structural=structural, graph=[], probe_misses=[],
        completeness=None, limit=5)
    assert len(actions) == 5


# --- checks_redundancy (#1, #9) --------------------------------------------

def test_exact_duplicate_body():
    body = "# X\n\n" + "相同正文内容" * 10
    a = _node(path="business/wiki/a.md", name="A", body=body)
    b = _node(path="business/wiki/b.md", name="B", body=body)
    codes = {f.code for f in checks_redundancy.check_redundancy([a, b])}
    assert "duplicate_body" in codes


def test_duplicate_description():
    a = _node(path="business/wiki/a.md", name="A", description="相同的描述说明文字")
    b = _node(path="business/wiki/b.md", name="B", description="相同的描述说明文字")
    codes = {f.code for f in checks_redundancy.check_redundancy([a, b])}
    assert "duplicate_description" in codes


def test_cap_does_not_skip_description_checks(monkeypatch):
    """Fix #1: hitting pairwise cap must not skip description dup checks."""
    monkeypatch.setattr(checks_redundancy, "_MAX_PAIRWISE", 1)
    nodes = [
        _node(path=f"business/wiki/n{i}.md", name=f"N{i}",
              description="共享的描述说明文字",
              body=f"# N{i}\n\n" + f"独立正文{i}" * 20)
        for i in range(5)
    ]
    codes = {f.code for f in checks_redundancy.check_redundancy(nodes)}
    assert "duplicate_description" in codes
    assert "redundancy_scan_capped" in codes


def test_redundancy_metrics_includes_all_dup_codes():
    """Fix #9: metrics must count near_duplicate_title/description too."""
    findings = [
        Finding("warn", "duplicate_body", "a", "x"),
        Finding("warn", "near_duplicate_body", "a", "x"),
        Finding("warn", "duplicate_description", "a", "x"),
        Finding("info", "near_duplicate_description", "a", "x"),
        Finding("warn", "near_duplicate_title", "a", "x"),
    ]
    m = checks_redundancy.redundancy_metrics(findings)
    assert m["near_duplicate_description"] == 1
    assert m["near_duplicate_title"] == 1


# --- checks_retrieval (#4) -------------------------------------------------

def test_probes_from_strings_tagged():
    probes = checks_retrieval.probes_from_strings(["a", " ", "b"], source="smoke")
    assert [p["query"] for p in probes] == ["a", "b"]
    assert all(p["source"] == "smoke" and p["exclude_path"] is None for p in probes)


def test_auto_probes_carry_exclude_path():
    a = _node(path="business/wiki/a.md", name="访客管理")
    probes = checks_retrieval.default_auto_probes([a])
    assert probes[0]["query"] == "访客管理"
    assert probes[0]["exclude_path"] == "business/wiki/a.md"
    assert probes[0]["source"] == "title"


def test_leave_one_out_prevents_self_hit():
    """Fix #4: a title probe must not hit its own node."""
    target = _node(path="business/wiki/target.md", name="访客管理", description="访客管理说明")
    other = _node(path="business/wiki/other.md", name="其它节点", description="无关内容")
    probes = checks_retrieval.default_auto_probes([target, other])
    hits, misses = checks_retrieval.run_lexical_probes([target, other], probes)
    target_q = [p for p in probes if p["exclude_path"] == "business/wiki/target.md"][0]["query"]
    assert [h for h in hits if h["query"] == target_q] == []


def test_external_probe_can_hit_any_node():
    node = _node(path="business/wiki/a.md", name="访客管理", description="访客管理说明")
    probes = checks_retrieval.probes_from_strings(["访客管理"], source="smoke")
    hits, misses = checks_retrieval.run_lexical_probes([node], probes)
    assert len(hits) == 1
    assert hits[0]["source"] == "smoke"


def test_run_lexical_probes_accepts_legacy_strings():
    node = _node(path="business/wiki/a.md", name="访客管理", description="访客管理说明")
    hits, misses = checks_retrieval.run_lexical_probes([node], ["访客管理"])
    assert len(hits) == 1


# --- checks_completeness (#3, #7) ------------------------------------------

class _StubAtom:
    def __init__(self, atom_id, name, body="正文内容", anchors=None,
                 source_file="x.md", source_kind="prd", image_refs=None, module="M"):
        self.atom_id = atom_id
        self.name = name
        self.body = body
        self.anchors = anchors or []
        self.source_file = source_file
        self.source_kind = source_kind
        self.image_refs = image_refs or []
        self.module = module
        self.size_tag = ""


def _stub_ingest(monkeypatch, atoms, skipped_ids, *, plan_fn=None):
    """Patch ingest parsers + plan at their source modules.

    If ``plan_fn`` is given, use it for ``plan_business_nodes`` (so a test can
    capture the ``weave`` kwarg); otherwise install a default that returns
    ``skipped_ids``.
    """
    import granularity  # type: ignore[import-not-found]
    import parse_prd  # type: ignore[import-not-found]
    import parse_xlsx  # type: ignore[import-not-found]
    parse_prd.parse_prd_dir = lambda d: (atoms, [])
    parse_xlsx.parse_xlsx_dir = lambda d: ([], [])
    parse_xlsx.parse_business_xlsx_dir = lambda d: ([], [])
    granularity.plan_case_nodes = lambda cases: []

    if plan_fn is not None:
        granularity.plan_business_nodes = plan_fn
    else:
        def default_plan(atoms_list, *, llm_dedupe_judge=None, weave=True):
            return [], [], list(skipped_ids)
        granularity.plan_business_nodes = default_plan


def test_completeness_passes_weave_false(tmp_path, monkeypatch):
    """Fix #3: completeness must call plan_business_nodes with weave=False."""
    captured = {}

    def capturing_plan(atoms_list, *, llm_dedupe_judge=None, weave=True):
        captured["weave"] = weave
        return [], [], [a.atom_id for a in atoms_list]

    atoms = [_StubAtom("a1", "原子一", body="P0")]
    _stub_ingest(monkeypatch, atoms, ["a1"], plan_fn=capturing_plan)

    src = tmp_path / "src"
    src.mkdir()
    node = _node(path="business/wiki/n.md", name="N",
                 derived_from=["ingest:a1"])
    checks_completeness.evaluate_completeness(
        catalog=[node], source_dirs=[src], skip_images=True,
        assume_full_source=False)
    assert captured.get("weave") is False


def test_stale_published_dedup_by_path(tmp_path, monkeypatch):
    """Fix #7: one node with two dropped ingest ids -> ONE stale entry."""
    atoms = [_StubAtom("a1", "原子一", body="P0"),
             _StubAtom("a2", "原子二", body="P1")]
    _stub_ingest(monkeypatch, atoms, ["a1", "a2"])

    src = tmp_path / "src"
    src.mkdir()
    node = _node(path="business/wiki/merged.md", name="合并",
                 derived_from=["ingest:a1", "ingest:a2"])
    report = checks_completeness.evaluate_completeness(
        catalog=[node], source_dirs=[src], skip_images=True,
        assume_full_source=False)

    assert len(report.stale_published) == 1
    entry = report.stale_published[0]
    assert entry["path"].endswith("merged.md")
    assert set(entry["atom_ids"]) == {"a1", "a2"}
    assert report.excess_hard == 1
    assert report.hard_leaks == 1


def test_completeness_unscored_without_source(tmp_path):
    report = checks_completeness.evaluate_completeness(
        catalog=[], source_dirs=[], skip_images=True,
        assume_full_source=False)
    assert report.scored is False
