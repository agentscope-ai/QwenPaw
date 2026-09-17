# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Cover the external memory-discovery family in external_state.py.

These helpers classify and collect *read-only* external memory stores
(Codex ``memories/``, Qoder ``memories/<account>/``, project transcripts)
without installing anything.  The existing ``test_external_state.py``
covers the plugin/MCP discovery side; this module covers the memory side:
the curated-vs-pipeline state ladder, the transcript-CWD probe, the
hyphen-encoded Qoder project-key resolver, and the markdown collector.

Every assertion checks observable output (returned source ids, cwds,
file lists, state strings, integer counts) rather than internals.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from qwenpaw.portability.providers import external_state as es


# --------------------------------------------------------------------------
# helpers shared by several tests
# --------------------------------------------------------------------------
def _md(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_stage1_db(home: Path, rows: list[tuple[str, str]]) -> Path:
    db = home / "memories_1.sqlite"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE stage1_outputs (raw_memory TEXT, rollout_summary TEXT)",
    )
    for raw, summary in rows:
        con.execute(
            "INSERT INTO stage1_outputs VALUES (?, ?)",
            (raw, summary),
        )
    con.commit()
    con.close()
    return db


# --------------------------------------------------------------------------
# _read_json
# --------------------------------------------------------------------------
def test_read_json_returns_parsed_object(tmp_path: Path) -> None:
    p = tmp_path / "ok.json"
    p.write_text('{"a": 1, "b": [2, 3]}', encoding="utf-8")
    assert es._read_json(p) == {"a": 1, "b": [2, 3]}


def test_read_json_malformed_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert es._read_json(p) is None


def test_read_json_missing_returns_none(tmp_path: Path) -> None:
    assert es._read_json(tmp_path / "absent.json") is None


def test_read_json_oversize_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "big.json"
    p.write_bytes(b" " * (es._MAX_CONFIG_BYTES + 16))
    assert es._read_json(p) is None


def test_read_json_symlink_returns_none(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text('{"k": "v"}', encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    # read_regular_file refuses to follow symlinks -> ValueError -> None
    assert es._read_json(link) is None


# --------------------------------------------------------------------------
# _markdown_files
# --------------------------------------------------------------------------
def test_markdown_files_collects_md_recursively_and_sorts(
    tmp_path: Path,
) -> None:
    root = tmp_path / "md"
    _md(root / "b.md", "b")
    _md(root / "A.MD", "A")  # uppercase suffix must still be accepted
    _md(root / "c.txt", "c")  # non-md must be skipped
    _md(root / "sub" / "d.md", "d")

    out = es._markdown_files(root)

    rels = [str(item.relative_path) for item in out]
    assert rels == ["A.MD", "b.md", "sub/d.md"]  # sorted by str(relative)
    assert all(item.source_path.is_absolute() for item in out)


def test_markdown_files_missing_root_returns_empty(tmp_path: Path) -> None:
    assert es._markdown_files(tmp_path / "nope") == []


def test_markdown_files_root_is_file_returns_empty(tmp_path: Path) -> None:
    f = tmp_path / "f.md"
    f.write_text("x", encoding="utf-8")
    assert es._markdown_files(f) == []


def test_markdown_files_symlinked_root_returns_empty(tmp_path: Path) -> None:
    real = tmp_path / "real"
    _md(real / "a.md")
    link = tmp_path / "link"
    link.symlink_to(real)
    assert es._markdown_files(link) == []


def test_markdown_files_ignores_broken_symlink_entry(tmp_path: Path) -> None:
    root = tmp_path / "md"
    _md(root / "good.md", "good")
    (root / "broken.md").symlink_to(tmp_path / "absent_target.md")

    out = es._markdown_files(root)

    # the broken symlink is skipped silently, the good file survives
    assert [str(item.relative_path) for item in out] == ["good.md"]


# --------------------------------------------------------------------------
# _codex_stage1_count
# --------------------------------------------------------------------------
def test_stage1_count_no_database(tmp_path: Path) -> None:
    assert es._codex_stage1_count(tmp_path) == 0


def test_stage1_count_counts_only_non_empty_rows(tmp_path: Path) -> None:
    _make_stage1_db(
        tmp_path,
        [
            ("  ", "   "),  # whitespace-only -> excluded by trim()
            ("real", ""),  # counts
            ("", "summary"),  # counts
            ("", ""),  # excluded
        ],
    )
    assert es._codex_stage1_count(tmp_path) == 2


def test_stage1_count_corrupt_database_returns_zero(tmp_path: Path) -> None:
    (tmp_path / "memories_1.sqlite").write_bytes(b"not a sqlite file")
    assert es._codex_stage1_count(tmp_path) == 0


def test_stage1_count_missing_table_returns_zero(tmp_path: Path) -> None:
    con = sqlite3.connect(tmp_path / "memories_1.sqlite")
    con.execute("CREATE TABLE unrelated (x TEXT)")
    con.commit()
    con.close()
    assert es._codex_stage1_count(tmp_path) == 0


def test_stage1_count_symlinked_database_returns_zero(tmp_path: Path) -> None:
    real = tmp_path / "real.sqlite"
    con = sqlite3.connect(real)
    con.execute(
        "CREATE TABLE stage1_outputs (raw_memory TEXT, rollout_summary TEXT)",
    )
    con.execute("INSERT INTO stage1_outputs VALUES ('x','')")
    con.commit()
    con.close()
    (tmp_path / "memories_1.sqlite").symlink_to(real)
    assert es._codex_stage1_count(tmp_path) == 0


# --------------------------------------------------------------------------
# codex_memory_status — the full state ladder
# --------------------------------------------------------------------------
def test_memory_status_empty(tmp_path: Path) -> None:
    status = es.codex_memory_status(tmp_path)
    assert status["state"] == "empty"
    assert status["curated_files"] == []
    assert status["ad_hoc_note_count"] == 0
    assert status["stage1_output_count"] == 0
    assert status["ignored_internal_files"] == []


def test_memory_status_consolidated(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    _md(root / "MEMORY.md")
    status = es.codex_memory_status(tmp_path)
    assert status["state"] == "consolidated"
    assert status["curated_files"] == ["MEMORY.md"]
    assert status["ignored_internal_files"] == []


def test_memory_status_consolidated_with_internal_residue(
    tmp_path: Path,
) -> None:
    root = tmp_path / "memories"
    _md(root / "MEMORY.md")
    _md(root / "raw_memories.md")
    status = es.codex_memory_status(tmp_path)
    assert status["state"] == "consolidated_with_internal_residue"
    assert status["ignored_internal_files"] == ["raw_memories.md"]


def test_memory_status_phase2_incomplete(tmp_path: Path) -> None:
    root = tmp_path / "memories"
    _md(root / "phase2_workspace_diff.md")
    assert (
        es.codex_memory_status(tmp_path)["state"] == "consolidation_incomplete"
    )


def test_memory_status_internal_only_is_incomplete(tmp_path: Path) -> None:
    # raw_memories.md alone (no curated, no phase2, no notes, no stage1)
    root = tmp_path / "memories"
    _md(root / "raw_memories.md")
    assert (
        es.codex_memory_status(tmp_path)["state"] == "consolidation_incomplete"
    )


def test_memory_status_pending_ad_hoc(tmp_path: Path) -> None:
    notes = tmp_path / "memories" / "extensions" / "ad_hoc" / "notes"
    _md(notes / "n0.md")
    _md(notes / "n1.md")
    status = es.codex_memory_status(tmp_path)
    assert status["state"] == "pending_ad_hoc"
    assert status["ad_hoc_note_count"] == 2


def test_memory_status_phase1_only(tmp_path: Path) -> None:
    _make_stage1_db(tmp_path, [("m", ""), ("m2", "")])
    status = es.codex_memory_status(tmp_path)
    assert status["state"] == "phase1_only"
    assert status["stage1_output_count"] == 2


def test_memory_status_notes_outrank_stage1(tmp_path: Path) -> None:
    notes = tmp_path / "memories" / "extensions" / "ad_hoc" / "notes"
    _md(notes / "n.md")
    _make_stage1_db(tmp_path, [("m", "")])
    assert es.codex_memory_status(tmp_path)["state"] == "pending_ad_hoc"


def test_memory_status_phase2_outranks_notes(tmp_path: Path) -> None:
    _md(tmp_path / "memories" / "phase2_workspace_diff.md")
    notes = tmp_path / "memories" / "extensions" / "ad_hoc" / "notes"
    _md(notes / "n.md")
    assert (
        es.codex_memory_status(tmp_path)["state"] == "consolidation_incomplete"
    )


def test_memory_status_symlinked_curated_is_ignored(tmp_path: Path) -> None:
    real = tmp_path / "outside.md"
    real.write_text("x", encoding="utf-8")
    root = tmp_path / "memories"
    root.mkdir(parents=True)
    (root / "MEMORY.md").symlink_to(real)
    status = es.codex_memory_status(tmp_path)
    # a symlinked curated file does NOT count -> stays "empty"
    assert status["state"] == "empty"
    assert status["curated_files"] == []


# --------------------------------------------------------------------------
# discover_codex_memory
# --------------------------------------------------------------------------
def test_discover_codex_memory_no_dir(tmp_path: Path) -> None:
    assert es.discover_codex_memory(tmp_path) == []


def test_discover_codex_memory_curated_suppresses_notes(
    tmp_path: Path,
) -> None:
    root = tmp_path / "memories"
    _md(root / "MEMORY.md", "curated")
    notes = root / "extensions" / "ad_hoc" / "notes"
    _md(notes / "n1.md", "note")

    projects = es.discover_codex_memory(tmp_path)

    assert len(projects) == 1
    p = projects[0]
    assert p.source_id == "codex:global"
    assert p.project_key == "global"
    assert len(p.files) == 1
    assert p.metadata["layout"] == "codex_global_memory"
    assert p.metadata["memory_state"] == "consolidated"
    # notes must NOT be emitted once consolidation exists
    assert all(q.source_id != "codex:ad-hoc" for q in projects)


def test_discover_codex_memory_notes_only(tmp_path: Path) -> None:
    notes = tmp_path / "memories" / "extensions" / "ad_hoc" / "notes"
    _md(notes / "n1.md")
    _md(notes / "n2.md")

    projects = es.discover_codex_memory(tmp_path)

    assert len(projects) == 1
    p = projects[0]
    assert p.source_id == "codex:ad-hoc"
    assert p.project_key == "ad-hoc-notes"
    assert [str(f.relative_path) for f in p.files] == ["n1.md", "n2.md"]
    assert p.metadata["layout"] == "codex_ad_hoc_notes"
    assert p.metadata["memory_state"] == "pending_ad_hoc"


def test_discover_codex_memory_extension_resources(tmp_path: Path) -> None:
    ext = tmp_path / "memories" / "extensions" / "ext1"
    proj_a = ext / "resources" / "projA"
    _md(proj_a / "m.md")
    (proj_a / "scope.json").write_text(
        json.dumps({"cwd": "/abs/cwd"}),
        encoding="utf-8",
    )
    proj_b = ext / "resources" / "projB"
    _md(proj_b / "m.md")  # no scope.json -> empty cwd
    (ext / "resources" / "empty").mkdir(parents=True)  # no md -> skipped
    (tmp_path / "memories" / "extensions" / "ext2").mkdir(parents=True)

    projects = es.discover_codex_memory(tmp_path)
    by_id = {p.source_id: p for p in projects}

    assert set(by_id) == {
        "codex:extension:ext1:projA",
        "codex:extension:ext1:projB",
    }
    assert by_id["codex:extension:ext1:projA"].cwd == "/abs/cwd"
    assert by_id["codex:extension:ext1:projB"].cwd == ""
    assert by_id["codex:extension:ext1:projA"].project_key == "ext1-projA"
    assert by_id["codex:extension:ext1:projA"].metadata == {
        "layout": "codex_extension_resource",
        "extension": "ext1",
        "source_project_key": "projA",
    }


def test_discover_codex_memory_skips_symlinked_resource(
    tmp_path: Path,
) -> None:
    ext = tmp_path / "memories" / "extensions" / "ext1" / "resources"
    ext.mkdir(parents=True)
    outside = tmp_path / "outside"
    _md(outside / "z.md")
    (ext / "linked").symlink_to(outside)

    projects = es.discover_codex_memory(tmp_path)
    assert all("linked" not in p.source_id for p in projects)


def test_discover_codex_memory_scope_not_dict(tmp_path: Path) -> None:
    proj = tmp_path / "memories" / "extensions" / "ext" / "resources" / "p"
    _md(proj / "m.md")
    (proj / "scope.json").write_text('["a","b"]', encoding="utf-8")
    projects = es.discover_codex_memory(tmp_path)
    assert projects[0].cwd == ""


def test_discover_codex_memory_scope_malformed(tmp_path: Path) -> None:
    proj = tmp_path / "memories" / "extensions" / "ext" / "resources" / "p"
    _md(proj / "m.md")
    (proj / "scope.json").write_text("{oops", encoding="utf-8")
    projects = es.discover_codex_memory(tmp_path)
    assert projects[0].cwd == ""


def test_discover_codex_memory_scope_cwd_null(tmp_path: Path) -> None:
    proj = tmp_path / "memories" / "extensions" / "ext" / "resources" / "p"
    _md(proj / "m.md")
    (proj / "scope.json").write_text('{"cwd": null}', encoding="utf-8")
    projects = es.discover_codex_memory(tmp_path)
    assert projects[0].cwd == ""


def test_discover_codex_memory_no_extensions(tmp_path: Path) -> None:
    (tmp_path / "memories").mkdir()
    assert es.discover_codex_memory(tmp_path) == []


# --------------------------------------------------------------------------
# _absolute_cwd / _cwd_in_value
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/abs/path", "/abs/path"),
        # strip() is used only for the blank test, NOT to normalise: a
        # leading space makes Path() see a relative path -> rejected.
        ("  /abs/pad  ", ""),
        (" /abs", ""),
        # a trailing space is preserved verbatim (still absolute).
        ("/abs ", "/abs "),
        ("relative/path", ""),
        ("", ""),
        ("   ", ""),
        (None, ""),
        (123, ""),
        ({"a": 1}, ""),
    ],
)
def test_absolute_cwd(value: object, expected: str) -> None:
    assert es._absolute_cwd(value) == expected


def test_absolute_cwd_expands_user() -> None:
    # ~ is expanded, so the result is absolute -> returned expanded.
    assert es._absolute_cwd("~/some-cwd") == str(
        Path("~/some-cwd").expanduser(),
    )


def test_cwd_in_value_finds_nested_key() -> None:
    payload = {"meta": {"projectPath": "/abs/nested"}}
    assert es._cwd_in_value(payload) == "/abs/nested"


def test_cwd_in_value_no_match() -> None:
    assert es._cwd_in_value({"other": 1}) == ""


# --------------------------------------------------------------------------
# _project_cwd_from_transcripts
# --------------------------------------------------------------------------
def test_transcript_cwd_top_level(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").write_text(
        '{"cwd": "/abs/one"}\n',
        encoding="utf-8",
    )
    assert es._project_cwd_from_transcripts(tmp_path) == "/abs/one"


def test_transcript_cwd_nested(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").write_text(
        json.dumps({"meta": {"projectPath": "/abs/two"}}) + "\n",
        encoding="utf-8",
    )
    assert es._project_cwd_from_transcripts(tmp_path) == "/abs/two"


def test_transcript_cwd_skips_bad_lines_and_relative(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").write_text(
        "not json\n"
        + '{"cwd": "relative/path"}\n'
        + '{"cwd": "/abs/three"}\n',
        encoding="utf-8",
    )
    assert es._project_cwd_from_transcripts(tmp_path) == "/abs/three"


def test_transcript_cwd_ignores_non_jsonl(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text('{"cwd": "/abs/x"}\n', encoding="utf-8")
    assert es._project_cwd_from_transcripts(tmp_path) == ""


def test_transcript_cwd_empty_when_only_blank(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").write_text('{"cwd": ""}\n{}\n', encoding="utf-8")
    assert es._project_cwd_from_transcripts(tmp_path) == ""


def test_transcript_cwd_prefers_newest_by_mtime(tmp_path: Path) -> None:
    import os

    a = tmp_path / "a.jsonl"
    b = tmp_path / "b.jsonl"
    a.write_text('{"cwd": "/first"}\n', encoding="utf-8")
    b.write_text('{"cwd": "/second"}\n', encoding="utf-8")
    os.utime(a, (2_000_000_000, 2_000_000_000))
    os.utime(b, (1_000_000_000, 1_000_000_000))
    # nlargest(20, key=mtime) -> newest first -> "/first"
    assert es._project_cwd_from_transcripts(tmp_path) == "/first"


def test_transcript_cwd_empty_dir(tmp_path: Path) -> None:
    assert es._project_cwd_from_transcripts(tmp_path) == ""


def test_transcript_cwd_nonexistent_dir(tmp_path: Path) -> None:
    assert es._project_cwd_from_transcripts(tmp_path / "absent") == ""


def test_transcript_cwd_skips_symlinked_jsonl(tmp_path: Path) -> None:
    (tmp_path / "a.jsonl").symlink_to(Path("/etc/hostname"))
    assert es._project_cwd_from_transcripts(tmp_path) == ""


# --------------------------------------------------------------------------
# discover_project_memory
# --------------------------------------------------------------------------
def test_discover_project_memory_no_dir(tmp_path: Path) -> None:
    assert es.discover_project_memory(tmp_path) == []


def test_discover_project_memory_collects_and_skips(tmp_path: Path) -> None:
    proj = tmp_path / "projects" / "proj1"
    _md(proj / "memory" / "m.md")
    (proj / "t.jsonl").write_text('{"cwd": "/cwd/one"}\n', encoding="utf-8")
    (tmp_path / "projects" / "empty").mkdir()  # no memory dir
    (tmp_path / "projects" / "plainfile").write_text("x", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "projects" / "link").symlink_to(outside)

    projects = es.discover_project_memory(tmp_path)

    assert len(projects) == 1
    p = projects[0]
    assert p.source_id == "project-memory:proj1"
    assert p.project_key == "proj1"
    assert p.cwd == "/cwd/one"
    assert p.metadata == {"layout": "project_memory"}


def test_discover_project_memory_memory_without_md(tmp_path: Path) -> None:
    (tmp_path / "projects" / "proj1" / "memory").mkdir(parents=True)
    assert es.discover_project_memory(tmp_path) == []


# --------------------------------------------------------------------------
# _qoder_project_cwds
# --------------------------------------------------------------------------
def test_qoder_project_cwds_no_dir(tmp_path: Path) -> None:
    assert es._qoder_project_cwds(tmp_path) == {}


def test_qoder_project_cwds_encodes_key(tmp_path: Path) -> None:
    d = tmp_path / "projects" / "pa"
    d.mkdir(parents=True)
    (d / "x.jsonl").write_text('{"cwd": "/tmp/Some/Dir"}\n', encoding="utf-8")
    mapping = es._qoder_project_cwds(tmp_path)
    assert mapping == {"tmp-Some-Dir": "/tmp/Some/Dir"}


def test_qoder_project_cwds_relative_skipped(tmp_path: Path) -> None:
    d = tmp_path / "projects" / "pa"
    d.mkdir(parents=True)
    (d / "x.jsonl").write_text('{"cwd": "rel/only"}\n', encoding="utf-8")
    assert es._qoder_project_cwds(tmp_path) == {}


# --------------------------------------------------------------------------
# _match_qoder_path
# --------------------------------------------------------------------------
def test_match_qoder_path_exact(tmp_path: Path) -> None:
    (tmp_path / "some-dir").mkdir()
    assert es._match_qoder_path(tmp_path, "some-dir") == str(
        (tmp_path / "some-dir").resolve(),
    )


def test_match_qoder_path_two_level(tmp_path: Path) -> None:
    (tmp_path / "some-dir" / "nested").mkdir(parents=True)
    assert es._match_qoder_path(tmp_path, "some-dir-nested") == str(
        (tmp_path / "some-dir" / "nested").resolve(),
    )


def test_match_qoder_path_no_match(tmp_path: Path) -> None:
    (tmp_path / "some-dir").mkdir()
    assert es._match_qoder_path(tmp_path, "nope") == ""


def test_match_qoder_path_empty_encoded_returns_base(tmp_path: Path) -> None:
    # empty encoded with a real base -> returns the base itself
    assert es._match_qoder_path(tmp_path, "") == str(tmp_path)


def test_match_qoder_path_base_not_dir(tmp_path: Path) -> None:
    f = tmp_path / "afile"
    f.write_text("x", encoding="utf-8")
    assert es._match_qoder_path(f, "x") == ""


def test_match_qoder_path_longest_first_resolves_ambiguity(
    tmp_path: Path,
) -> None:
    (tmp_path / "a-b" / "c").mkdir(parents=True)
    (tmp_path / "a" / "b-c").mkdir(parents=True)
    # children are sorted longest-name-first -> "a-b" wins -> a-b/c
    assert es._match_qoder_path(tmp_path, "a-b-c") == str(
        (tmp_path / "a-b" / "c").resolve(),
    )


def test_match_qoder_path_depth_guard(tmp_path: Path) -> None:
    deep = tmp_path
    for i in range(40):
        deep = deep / f"d{i}"
    deep.mkdir(parents=True)
    encoded = "-".join(f"d{i}" for i in range(40))
    # depth > 32 guard -> empty even though the path exists
    assert es._match_qoder_path(tmp_path, encoded) == ""


def test_match_qoder_path_shallow_ok(tmp_path: Path) -> None:
    (tmp_path / "d0" / "d1" / "d2").mkdir(parents=True)
    assert es._match_qoder_path(tmp_path, "d0-d1-d2") != ""


def test_match_qoder_path_skips_symlink_child(tmp_path: Path) -> None:
    real = tmp_path / "realdir"
    real.mkdir()
    (tmp_path / "linkdir").symlink_to(real)
    assert es._match_qoder_path(tmp_path, "linkdir") == ""
    assert es._match_qoder_path(tmp_path, "realdir") != ""


# --------------------------------------------------------------------------
# _qoder_memory_cwd
# --------------------------------------------------------------------------
def test_qoder_memory_cwd_map_hit() -> None:
    assert es._qoder_memory_cwd("k1", {"k1": "/from/map"}) == "/from/map"


def test_qoder_memory_cwd_home_key_returns_home() -> None:
    home = Path.home().resolve()
    home_key = str(home).lstrip("/\\").replace("/", "-").replace("\\", "-")
    assert es._qoder_memory_cwd(home_key, {}) == str(home)


def test_qoder_memory_cwd_no_prefix_returns_empty() -> None:
    assert es._qoder_memory_cwd("totally-other", {}) == ""


def test_qoder_memory_cwd_prefix_without_child_returns_empty(
    tmp_path: Path,
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    with patch.object(Path, "home", staticmethod(lambda: fake_home)):
        key = str(fake_home).lstrip("/\\").replace("/", "-").replace("\\", "-")
        assert es._qoder_memory_cwd(f"{key}-missing_child", {}) == ""


def test_qoder_memory_cwd_resolves_real_child(tmp_path: Path) -> None:
    fake_home = tmp_path / "home"
    child = fake_home / "child_x"
    child.mkdir(parents=True)
    with patch.object(Path, "home", staticmethod(lambda: fake_home)):
        key = str(fake_home).lstrip("/\\").replace("/", "-").replace("\\", "-")
        assert es._qoder_memory_cwd(f"{key}-child_x", {}) == str(
            child.resolve(),
        )


# --------------------------------------------------------------------------
# discover_qoder_memory
# --------------------------------------------------------------------------
def test_discover_qoder_memory_falls_back_to_project_memory(
    tmp_path: Path,
) -> None:
    proj = tmp_path / "projects" / "p1" / "memory"
    _md(proj / "m.md")
    projects = es.discover_qoder_memory(tmp_path)
    assert [p.source_id for p in projects] == ["project-memory:p1"]
    assert projects[0].metadata["layout"] == "project_memory"


def test_discover_qoder_memory_v2_layout(tmp_path: Path) -> None:
    home = Path.home().resolve()
    home_key = str(home).lstrip("/\\").replace("/", "-").replace("\\", "-")
    acct = tmp_path / "memories" / "acct1"
    _md(acct / "global" / "g.md")
    _md(acct / "projects" / home_key / "s.md")  # resolvable to HOME
    _md(acct / "projects" / "unknown-key" / "s.md")  # not resolvable
    (acct / "projects" / "no-md").mkdir()  # no markdown -> skipped
    (tmp_path / "memories" / "acct2").mkdir()  # empty account
    (tmp_path / "memories" / "plain.json").write_text("x", encoding="utf-8")

    projects = es.discover_qoder_memory(tmp_path)
    by_id = {p.source_id: p for p in projects}

    assert "qoder-memory:acct1:global" in by_id
    g = by_id["qoder-memory:acct1:global"]
    assert g.project_key == "acct1-global"
    assert g.metadata["scope"] == "global"
    assert g.metadata["account"] == "acct1"

    assert f"qoder-memory:acct1:project:{home_key}" in by_id
    scoped = by_id[f"qoder-memory:acct1:project:{home_key}"]
    assert scoped.cwd == str(home)
    assert scoped.metadata["scope"] == "project"

    unk = by_id["qoder-memory:acct1:project:unknown-key"]
    assert unk.cwd == ""

    # the no-md project is never emitted
    assert all("no-md" not in sid for sid in by_id)


def test_discover_qoder_memory_symlinked_memories_falls_back(
    tmp_path: Path,
) -> None:
    (tmp_path / "memories").symlink_to(tmp_path)
    assert es.discover_qoder_memory(tmp_path) == []


def test_discover_qoder_memory_symlinked_projects_dir(tmp_path: Path) -> None:
    acct = tmp_path / "memories" / "acct1"
    _md(acct / "global" / "g.md")
    (acct / "projects").symlink_to(tmp_path)
    projects = es.discover_qoder_memory(tmp_path)
    # only the global project survives; the symlinked projects dir is skipped
    assert [p.source_id for p in projects] == ["qoder-memory:acct1:global"]


def test_discover_qoder_memory_cwd_from_transcript_map(tmp_path: Path) -> None:
    real_cwd = tmp_path / "realproj"
    real_cwd.mkdir()
    tp = tmp_path / "projects" / "pa"
    tp.mkdir(parents=True)
    (tp / "x.jsonl").write_text(
        json.dumps({"cwd": str(real_cwd)}) + "\n",
        encoding="utf-8",
    )
    encoded = str(real_cwd).lstrip("/\\").replace("/", "-").replace("\\", "-")
    _md(tmp_path / "memories" / "acct" / "projects" / encoded / "s.md")

    projects = es.discover_qoder_memory(tmp_path)
    scoped = next(
        p for p in projects if p.source_id.endswith(f"project:{encoded}")
    )
    assert scoped.cwd == str(real_cwd)


# --------------------------------------------------------------------------
# _skill_directories / discover_qoder_skills
# --------------------------------------------------------------------------
def test_skill_directories_missing(tmp_path: Path) -> None:
    assert es._skill_directories(tmp_path) == []


def test_skill_directories_root_is_skill(tmp_path: Path) -> None:
    _md(tmp_path / "SKILL.md")
    assert es._skill_directories(tmp_path) == [tmp_path]


def test_skill_directories_children(tmp_path: Path) -> None:
    _md(tmp_path / "a" / "SKILL.md")
    _md(tmp_path / "b" / "SKILL.md")
    (tmp_path / "c").mkdir()  # no SKILL.md
    (tmp_path / "f.txt").write_text("f", encoding="utf-8")
    real = tmp_path / "real"
    _md(real / "SKILL.md")
    (tmp_path / "link").symlink_to(real)  # symlinked child skipped

    names = sorted(p.name for p in es._skill_directories(tmp_path))
    assert names == ["a", "b", "real"]


def test_discover_qoder_skills_nothing(tmp_path: Path) -> None:
    assert es.discover_qoder_skills(tmp_path) == []


def test_discover_qoder_skills_user_scope(tmp_path: Path) -> None:
    _md(tmp_path / "skills" / "myskill" / "SKILL.md")
    skills = es.discover_qoder_skills(tmp_path)
    assert len(skills) == 1
    assert skills[0].name == "myskill"
    assert skills[0].source_id.startswith("qoder-skill:user:")


def test_discover_qoder_skills_root_level(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _md(skills_dir / "SKILL.md")
    skills = es.discover_qoder_skills(tmp_path)
    assert [s.name for s in skills] == ["skills"]
