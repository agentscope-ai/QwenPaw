# -*- coding: utf-8 -*-
"""Tests for ``qwenpaw.agents.tools.lsp_tool``.

The LSP client is stubbed; we only verify dispatch, validation and
the dynamically generated description.
"""
# pylint: disable=protected-access,redefined-outer-name,unused-argument
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from qwenpaw.agents.tools import _lsp_client as lsp_client
from qwenpaw.agents.tools import lsp_tool


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def project_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def with_workspace(monkeypatch, project_dir):
    monkeypatch.setattr(
        "qwenpaw.agents.tools.lsp_tool.get_current_workspace_dir",
        lambda: project_dir,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.tools.file_io.get_current_workspace_dir",
        lambda: project_dir,
    )
    return project_dir


class _FakeClient:
    """Drop-in replacement for :class:`LspClient` used by tests."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def definition(self, file_path, line, character):
        self.calls.append(("definition", (file_path, line, character)))
        return {"op": "definition", "line": line, "character": character}

    def references(self, file_path, line, character):
        self.calls.append(("references", (file_path, line, character)))
        return [{"file": str(file_path)}]

    def hover(self, file_path, line, character):
        self.calls.append(("hover", (file_path, line, character)))
        return {"contents": "hover-text"}

    def implementation(self, file_path, line, character):
        self.calls.append(("implementation", (file_path, line, character)))
        return [{"file": str(file_path)}]

    def document_symbol(self, file_path):
        self.calls.append(("document_symbol", (file_path,)))
        return [{"name": "sym"}]

    def workspace_symbol(self, query):
        self.calls.append(("workspace_symbol", (query,)))
        return [{"name": query}]


@pytest.fixture
def fake_client(monkeypatch):
    client = _FakeClient()
    monkeypatch.setattr(
        lsp_tool.lsp_client,
        "get_client",
        lambda *args, **kwargs: client,
    )
    return client


def _text(response) -> str:
    return response.content[0]["text"]


# ---------------------------------------------------------------------
# Description / factory shape
# ---------------------------------------------------------------------


def test_description_lists_available_languages():
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    desc = tool.__doc__ or ""
    assert "Python" in desc
    assert "TypeScript" not in desc


def test_description_joins_two_languages_with_and():
    tool = lsp_tool.make_lsp_tool(
        {"python": ["pylsp"], "typescript": ["tsls"]},
    )
    desc = tool.__doc__ or ""
    assert "Python" in desc and "TypeScript" in desc
    # Either "Python and TypeScript" or "TypeScript and Python".
    assert " and " in desc


def test_description_with_no_languages():
    tool = lsp_tool.make_lsp_tool({})
    desc = tool.__doc__ or ""
    assert "(none)" in desc


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_operation_rejected(with_workspace, fake_client):
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(operation="bogus")
    out = _text(resp)
    assert "unknown operation" in out


@pytest.mark.asyncio
async def test_missing_file_path_for_position_op(
    with_workspace,
    fake_client,
):
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(
        operation="goToDefinition",
        line=1,
        character=1,
    )
    assert "missing `file_path`" in _text(resp)


@pytest.mark.asyncio
async def test_zero_line_rejected(with_workspace, fake_client, project_dir):
    f = project_dir / "x.py"
    f.write_text("y = 1\n", encoding="utf-8")
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(
        operation="hover",
        file_path=str(f),
        line=0,
        character=1,
    )
    assert "1-based" in _text(resp)


@pytest.mark.asyncio
async def test_path_outside_workspace_rejected(
    with_workspace,
    fake_client,
    tmp_path,
):
    outside = tmp_path / "elsewhere.py"
    outside.write_text("z = 1\n", encoding="utf-8")
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(
        operation="hover",
        file_path=str(outside),
        line=1,
        character=1,
    )
    assert "outside the project root" in _text(resp)


@pytest.mark.asyncio
async def test_unknown_extension_falls_back_message(
    with_workspace,
    fake_client,
    project_dir,
):
    f = project_dir / "notes.md"
    f.write_text("# hi\n", encoding="utf-8")
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(
        operation="hover",
        file_path=str(f),
        line=1,
        character=1,
    )
    assert "cannot infer language" in _text(resp)


@pytest.mark.asyncio
async def test_language_not_in_available_returns_error(
    with_workspace,
    fake_client,
    project_dir,
):
    f = project_dir / "main.ts"
    f.write_text("export const x = 1;\n", encoding="utf-8")
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(
        operation="hover",
        file_path=str(f),
        line=1,
        character=1,
    )
    out = _text(resp)
    assert "TypeScript" in out
    assert "not available" in out
    assert "Python" in out  # supported list mentions Python


@pytest.mark.asyncio
async def test_workspace_symbol_requires_query(
    with_workspace,
    fake_client,
):
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(operation="workspaceSymbol", query="")
    assert "required" in _text(resp)


@pytest.mark.asyncio
async def test_workspace_symbol_no_servers(with_workspace, fake_client):
    tool = lsp_tool.make_lsp_tool({})
    resp = await tool(operation="workspaceSymbol", query="x")
    assert "no LSP servers" in _text(resp)


# ---------------------------------------------------------------------
# Dispatch happy paths
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_definition_dispatch(
    with_workspace,
    fake_client,
    project_dir,
):
    f = project_dir / "a.py"
    f.write_text("def foo(): pass\n", encoding="utf-8")
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(
        operation="goToDefinition",
        file_path=str(f),
        line=1,
        character=5,
    )
    payload = json.loads(_text(resp))
    assert payload == {"op": "definition", "line": 1, "character": 5}
    assert fake_client.calls[0][0] == "definition"


@pytest.mark.asyncio
async def test_references_dispatch(
    with_workspace,
    fake_client,
    project_dir,
):
    f = project_dir / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(
        operation="findReferences",
        file_path=str(f),
        line=1,
        character=1,
    )
    assert "a.py" in _text(resp)
    assert fake_client.calls[0][0] == "references"


@pytest.mark.asyncio
async def test_hover_dispatch(
    with_workspace,
    fake_client,
    project_dir,
):
    f = project_dir / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(
        operation="hover",
        file_path=str(f),
        line=1,
        character=1,
    )
    assert "hover-text" in _text(resp)
    assert fake_client.calls[0][0] == "hover"


@pytest.mark.asyncio
async def test_implementation_dispatch(
    with_workspace,
    fake_client,
    project_dir,
):
    f = project_dir / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(
        operation="goToImplementation",
        file_path=str(f),
        line=1,
        character=1,
    )
    assert "a.py" in _text(resp)
    assert fake_client.calls[0][0] == "implementation"


@pytest.mark.asyncio
async def test_document_symbol_dispatch(
    with_workspace,
    fake_client,
    project_dir,
):
    f = project_dir / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(
        operation="documentSymbol",
        file_path=str(f),
    )
    assert "sym" in _text(resp)
    assert fake_client.calls[0][0] == "document_symbol"


@pytest.mark.asyncio
async def test_workspace_symbol_dispatch(
    with_workspace,
    fake_client,
):
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(operation="workspaceSymbol", query="thing")
    assert "thing" in _text(resp)
    assert fake_client.calls[0] == ("workspace_symbol", ("thing",))


@pytest.mark.asyncio
async def test_workspace_symbol_prefers_python(
    with_workspace,
    fake_client,
    monkeypatch,
):
    """When multiple languages are available, Python is preferred."""
    seen_lang: dict = {}

    def fake_get(_root, lang, _argv):
        seen_lang["language"] = lang
        return fake_client

    monkeypatch.setattr(
        lsp_tool.lsp_client,
        "get_client",
        fake_get,
    )
    tool = lsp_tool.make_lsp_tool(
        {"typescript": ["tsls"], "python": ["pylsp"]},
    )
    await tool(operation="workspaceSymbol", query="x")
    assert seen_lang["language"] == "python"


# ---------------------------------------------------------------------
# Error / timeout surfacing
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lsp_error_is_surfaced(
    with_workspace,
    monkeypatch,
    project_dir,
):
    class _AngryClient:
        def hover(self, *_a, **_kw):
            raise lsp_client.LspError("server exploded")

    monkeypatch.setattr(
        lsp_tool.lsp_client,
        "get_client",
        lambda *a, **kw: _AngryClient(),
    )
    f = project_dir / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(
        operation="hover",
        file_path=str(f),
        line=1,
        character=1,
    )
    out = _text(resp)
    assert "Error" in out
    assert "server exploded" in out


@pytest.mark.asyncio
async def test_none_result_returns_friendly_message(
    with_workspace,
    monkeypatch,
    project_dir,
):
    class _NullClient:
        def hover(self, *_a, **_kw):
            return None

    monkeypatch.setattr(
        lsp_tool.lsp_client,
        "get_client",
        lambda *a, **kw: _NullClient(),
    )
    f = project_dir / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")
    tool = lsp_tool.make_lsp_tool({"python": ["pylsp"]})
    resp = await tool(
        operation="hover",
        file_path=str(f),
        line=1,
        character=1,
    )
    assert "No result for hover" in _text(resp)
