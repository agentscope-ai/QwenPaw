# -*- coding: utf-8 -*-
"""Tests for the ast-grep coding tool helpers.

Covers _ast_grep_binary discovery (long/short form),
is_ast_grep_available, _make_response, _resolve_search_path,
_format_matches (1-indexed lines, relative paths, snippet truncation,
max-match cap), and _run_ast_grep_sync error paths, which previously
had no coverage.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

from pathlib import Path

import pytest

from qwenpaw.agents.tools import ast_tool as ast_mod


# ---------------------------------------------------------------------------
# _ast_grep_binary / is_ast_grep_available
# ---------------------------------------------------------------------------


class TestAstGrepBinary:
    def test_long_form_found(self, monkeypatch):
        monkeypatch.setattr(
            ast_mod.shutil,
            "which",
            lambda name: "/usr/bin/ast-grep" if name == "ast-grep" else None,
        )
        assert ast_mod._ast_grep_binary() == "/usr/bin/ast-grep"

    def test_short_form_found(self, monkeypatch):
        monkeypatch.setattr(
            ast_mod.shutil,
            "which",
            lambda name: "/usr/bin/sg" if name == "sg" else None,
        )
        assert ast_mod._ast_grep_binary() == "/usr/bin/sg"

    def test_none_when_missing(self, monkeypatch):
        monkeypatch.setattr(ast_mod.shutil, "which", lambda name: None)
        assert ast_mod._ast_grep_binary() is None

    def test_is_available_reflects_binary(self, monkeypatch):
        monkeypatch.setattr(ast_mod, "_ast_grep_binary", lambda: "/bin/sg")
        assert ast_mod.is_ast_grep_available() is True
        monkeypatch.setattr(ast_mod, "_ast_grep_binary", lambda: None)
        assert ast_mod.is_ast_grep_available() is False


# ---------------------------------------------------------------------------
# _make_response
# ---------------------------------------------------------------------------


class TestMakeResponse:
    def test_wraps_text(self):
        result = ast_mod._make_response("hello")
        assert result.is_last is True
        assert result.content[0].text == "hello"


# ---------------------------------------------------------------------------
# _resolve_search_path
# ---------------------------------------------------------------------------


class TestResolveSearchPath:
    def test_empty_path_returns_root(self, tmp_path):
        result = ast_mod._resolve_search_path("", tmp_path)
        assert result == tmp_path

    def test_absolute_path_used_as_given(self, tmp_path, monkeypatch):
        target = tmp_path / "sub"
        target.mkdir()
        monkeypatch.setattr(
            ast_mod,
            "_resolve_file_path",
            lambda p: str(target),
        )
        result = ast_mod._resolve_search_path(str(target), tmp_path)
        assert Path(result) == target

    def test_invalid_path_returns_tool_chunk(self, tmp_path, monkeypatch):
        def bad(path):
            raise ValueError("embedded null byte")

        monkeypatch.setattr(ast_mod, "_resolve_file_path", bad)
        result = ast_mod._resolve_search_path("bad", tmp_path)
        # ToolChunk (error) rather than a Path
        assert not isinstance(result, Path)


# ---------------------------------------------------------------------------
# _format_matches
# ---------------------------------------------------------------------------


def _match_entry(file, line=0, column=0, text="def foo():"):
    return {
        "file": file,
        "range": {
            "start": {"line": line, "column": column},
            "end": {"line": line, "column": column + 5},
        },
        "lines": text,
    }


class TestFormatMatches:
    def test_line_numbers_one_indexed(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x")
        matches, truncated = ast_mod._format_matches(
            [_match_entry(str(target), line=0, column=0)],
            tmp_path,
            max_matches=10,
        )
        assert truncated is False
        assert matches[0]["line"] == 1
        assert matches[0]["column"] == 1
        assert matches[0]["end_line"] == 1

    def test_relative_path_display(self, tmp_path):
        target = tmp_path / "sub" / "a.py"
        target.parent.mkdir()
        target.write_text("x")
        matches, _ = ast_mod._format_matches(
            [_match_entry(str(target))],
            tmp_path,
            max_matches=10,
        )
        assert matches[0]["file"] == "sub/a.py"

    def test_outside_root_keeps_original_path(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        target = outside / "b.py"
        target.write_text("x")
        root = tmp_path / "proj"
        root.mkdir()
        matches, _ = ast_mod._format_matches(
            [_match_entry(str(target))],
            root,
            max_matches=10,
        )
        assert matches[0]["file"] == str(target).replace("\\", "/")

    def test_snippet_truncated(self, tmp_path):
        target = tmp_path / "big.py"
        target.write_text("x")
        long_text = "y" * 1000
        matches, _ = ast_mod._format_matches(
            [_match_entry(str(target), text=long_text)],
            tmp_path,
            max_matches=10,
        )
        assert len(matches[0]["snippet"]) == ast_mod._MAX_SNIPPET_CHARS + 1
        assert matches[0]["snippet"].endswith("…")

    def test_max_matches_cap(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x")
        entries = [_match_entry(str(target), line=i) for i in range(10)]
        matches, truncated = ast_mod._format_matches(
            entries,
            tmp_path,
            max_matches=3,
        )
        assert len(matches) == 3
        assert truncated is True

    def test_fallback_text_field(self, tmp_path):
        target = tmp_path / "a.py"
        target.write_text("x")
        entry = _match_entry(str(target))
        del entry["lines"]
        entry["text"] = "from text field"
        matches, _ = ast_mod._format_matches([entry], tmp_path, max_matches=5)
        assert matches[0]["snippet"] == "from text field"

    def test_relative_file_path_joined(self, tmp_path):
        target = tmp_path / "rel.py"
        target.write_text("x")
        matches, _ = ast_mod._format_matches(
            [_match_entry("rel.py")],
            tmp_path,
            max_matches=5,
        )
        assert matches[0]["file"] == "rel.py"


# ---------------------------------------------------------------------------
# _run_ast_grep_sync
# ---------------------------------------------------------------------------


class TestRunAstGrepSync:
    def test_spawn_failure_returns_minus_one(self, tmp_path, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("no such binary")

        monkeypatch.setattr(ast_mod.subprocess, "Popen", boom)
        rc, stdout, stderr = ast_mod._run_ast_grep_sync(
            ["ast-grep"],
            tmp_path,
        )
        assert rc == -1

    def test_normal_execution(self, tmp_path, monkeypatch):
        class FakeProc:
            returncode = 0

            def communicate(self, timeout=None):
                return ("{}", "")

        monkeypatch.setattr(
            ast_mod.subprocess,
            "Popen",
            lambda *a, **kw: FakeProc(),
        )
        rc, stdout, stderr = ast_mod._run_ast_grep_sync(["sg"], tmp_path)
        assert rc == 0
        assert stdout == "{}"
        assert stderr == ""

    def test_timeout_returns_minus_one(self, tmp_path, monkeypatch):
        import subprocess as sp

        class HangingProc:
            returncode = None

            def communicate(self, timeout=None):
                raise sp.TimeoutExpired(cmd="sg", timeout=timeout)

            def kill(self):
                pass

        monkeypatch.setattr(
            ast_mod.subprocess,
            "Popen",
            lambda *a, **kw: HangingProc(),
        )
        rc, _, _ = ast_mod._run_ast_grep_sync(["sg"], tmp_path)
        assert rc == -1
