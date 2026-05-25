# -*- coding: utf-8 -*-
"""Tests for ``qwenpaw.agents.tools.ast_tool``.

The CLI is mocked so the test suite does not need a real
``ast-grep`` binary installed.
"""
# pylint: disable=redefined-outer-name,protected-access,unused-argument
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from qwenpaw.agents.tools import ast_tool


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def project_root():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / "src" / "foo.py").write_text(
            "def login(req):\n    return req\n",
            encoding="utf-8",
        )
        (root / "outside_marker.txt").write_text("x", encoding="utf-8")
        yield root


@pytest.fixture
def with_workspace(monkeypatch, project_root):
    monkeypatch.setattr(
        "qwenpaw.agents.tools.ast_tool.get_current_workspace_dir",
        lambda: project_root,
    )
    # file_io also reads from the same context var.
    monkeypatch.setattr(
        "qwenpaw.agents.tools.file_io.get_current_workspace_dir",
        lambda: project_root,
    )
    return project_root


@pytest.fixture
def stub_binary(monkeypatch):
    monkeypatch.setattr(
        ast_tool,
        "_ast_grep_binary",
        lambda: "/fake/ast-grep",
    )


def _text(response) -> str:
    return response.content[0]["text"]


# ---------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_empty_pattern(with_workspace, stub_binary):
    resp = await ast_tool.ast_search(pattern="", language="python")
    assert "Error" in _text(resp)
    assert "pattern" in _text(resp)


@pytest.mark.asyncio
async def test_rejects_missing_language(with_workspace, stub_binary):
    resp = await ast_tool.ast_search(pattern="def $A", language="")
    assert "Error" in _text(resp)
    assert "language" in _text(resp)


@pytest.mark.asyncio
async def test_missing_binary_reports_install_hint(
    with_workspace,
    monkeypatch,
):
    monkeypatch.setattr(ast_tool, "_ast_grep_binary", lambda: None)
    resp = await ast_tool.ast_search(
        pattern="def $A",
        language="python",
    )
    out = _text(resp)
    assert "Error" in out
    assert "ast-grep" in out
    assert "pip install" in out


# ---------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_path_outside_root_is_rejected(
    with_workspace,
    stub_binary,
    tmp_path,
):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    resp = await ast_tool.ast_search(
        pattern="def $A",
        language="python",
        path=str(outside),
    )
    assert "outside the project root" in _text(resp)


@pytest.mark.asyncio
async def test_nonexistent_path_rejected(with_workspace, stub_binary):
    resp = await ast_tool.ast_search(
        pattern="def $A",
        language="python",
        path="does/not/exist.py",
    )
    assert "does not exist" in _text(resp)


# ---------------------------------------------------------------------
# Subprocess call shape
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_builds_expected_argv(
    with_workspace,
    stub_binary,
    monkeypatch,
):
    seen: dict = {}

    def fake_run(args, cwd):
        seen["args"] = args
        seen["cwd"] = cwd
        return 0, "[]", ""

    monkeypatch.setattr(ast_tool, "_run_ast_grep_sync", fake_run)

    await ast_tool.ast_search(
        pattern="def $A",
        language="python",
        path="src",
    )

    assert seen["args"][0] == "/fake/ast-grep"
    assert seen["args"][1] == "run"
    assert "--pattern" in seen["args"]
    assert seen["args"][seen["args"].index("--pattern") + 1] == "def $A"
    assert "--lang" in seen["args"]
    assert seen["args"][seen["args"].index("--lang") + 1] == "python"
    assert "--json=compact" in seen["args"]
    # Last arg must be the resolved search target (absolute path).
    assert seen["args"][-1].endswith("src")


# ---------------------------------------------------------------------
# Parsing & formatting
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_matches_returns_friendly_message(
    with_workspace,
    stub_binary,
    monkeypatch,
):
    monkeypatch.setattr(
        ast_tool,
        "_run_ast_grep_sync",
        lambda args, cwd: (0, "[]", ""),
    )
    resp = await ast_tool.ast_search(
        pattern="def $A",
        language="python",
    )
    assert "No matches" in _text(resp)


@pytest.mark.asyncio
async def test_matches_are_formatted_one_indexed(
    with_workspace,
    stub_binary,
    monkeypatch,
):
    raw = json.dumps(
        [
            {
                "file": "src/foo.py",
                "range": {
                    "start": {"line": 0, "column": 0},
                    "end": {"line": 1, "column": 14},
                },
                "lines": "def login(req):\n    return req",
                "text": "def login(req):\n    return req",
            },
        ],
    )
    monkeypatch.setattr(
        ast_tool,
        "_run_ast_grep_sync",
        lambda args, cwd: (0, raw, ""),
    )
    resp = await ast_tool.ast_search(
        pattern="def $A",
        language="python",
    )
    payload = json.loads(_text(resp))
    assert payload["truncated"] is False
    assert len(payload["matches"]) == 1
    match = payload["matches"][0]
    assert match["file"] == "src/foo.py"
    assert match["line"] == 1  # 0 → 1
    assert match["column"] == 1  # 0 → 1
    assert match["end_line"] == 2
    assert "def login(req)" in match["snippet"]


@pytest.mark.asyncio
async def test_max_matches_truncation(
    with_workspace,
    stub_binary,
    monkeypatch,
):
    raw_entries = [
        {
            "file": f"src/file_{i}.py",
            "range": {
                "start": {"line": i, "column": 0},
                "end": {"line": i, "column": 5},
            },
            "lines": f"def f{i}():",
        }
        for i in range(10)
    ]
    monkeypatch.setattr(
        ast_tool,
        "_run_ast_grep_sync",
        lambda args, cwd: (0, json.dumps(raw_entries), ""),
    )
    resp = await ast_tool.ast_search(
        pattern="def $A",
        language="python",
        max_matches=3,
    )
    payload = json.loads(_text(resp))
    assert payload["truncated"] is True
    assert len(payload["matches"]) == 3


@pytest.mark.asyncio
async def test_ast_grep_failure_surfaces_stderr(
    with_workspace,
    stub_binary,
    monkeypatch,
):
    monkeypatch.setattr(
        ast_tool,
        "_run_ast_grep_sync",
        lambda args, cwd: (1, "", "pattern parse error: bad syntax"),
    )
    resp = await ast_tool.ast_search(
        pattern="def @@",
        language="python",
    )
    out = _text(resp)
    assert "Error" in out
    assert "ast-grep failed" in out
    assert "pattern parse error" in out


@pytest.mark.asyncio
async def test_malformed_json_handled(
    with_workspace,
    stub_binary,
    monkeypatch,
):
    monkeypatch.setattr(
        ast_tool,
        "_run_ast_grep_sync",
        lambda args, cwd: (0, "not-json-at-all", ""),
    )
    resp = await ast_tool.ast_search(
        pattern="def $A",
        language="python",
    )
    out = _text(resp)
    assert "Error" in out
    assert "could not parse" in out


# ---------------------------------------------------------------------
# Discovery helper
# ---------------------------------------------------------------------


def test_is_ast_grep_available_true(monkeypatch):
    monkeypatch.setattr(
        ast_tool,
        "_ast_grep_binary",
        lambda: "/fake/ast-grep",
    )
    assert ast_tool.is_ast_grep_available() is True


def test_is_ast_grep_available_false(monkeypatch):
    monkeypatch.setattr(ast_tool, "_ast_grep_binary", lambda: None)
    assert ast_tool.is_ast_grep_available() is False
