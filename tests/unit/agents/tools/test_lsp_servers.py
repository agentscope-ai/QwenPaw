# -*- coding: utf-8 -*-
"""Tests for ``qwenpaw.agents.tools._lsp_servers``."""
# pylint: disable=protected-access,redefined-outer-name
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

from qwenpaw.agents.tools import _lsp_servers as srv


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


@pytest.fixture
def project_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


# ---------------------------------------------------------------------
# Python discovery — fallback chain
# ---------------------------------------------------------------------


def test_python_prefers_pyright_when_on_path(monkeypatch, project_dir):
    monkeypatch.setattr(
        srv.shutil,
        "which",
        lambda name: "/usr/bin/pyright-langserver"
        if name == "pyright-langserver"
        else None,
    )
    cmd = srv._discover_python(project_dir)
    assert cmd == ["/usr/bin/pyright-langserver", "--stdio"]


def test_python_falls_back_to_pylsp_when_pyright_absent(
    monkeypatch,
    project_dir,
):
    def fake_which(name):
        return "/usr/local/bin/pylsp" if name == "pylsp" else None

    monkeypatch.setattr(srv.shutil, "which", fake_which)
    cmd = srv._discover_python(project_dir)
    assert cmd == ["/usr/local/bin/pylsp"]


def test_python_falls_back_to_module_when_no_binary(
    monkeypatch,
    project_dir,
):
    monkeypatch.setattr(srv.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        srv,
        "_module_importable",
        lambda name: name == "pylsp",
    )
    cmd = srv._discover_python(project_dir)
    assert cmd == [sys.executable, "-m", "pylsp"]


def test_python_returns_none_when_nothing_available(
    monkeypatch,
    project_dir,
):
    monkeypatch.setattr(srv.shutil, "which", lambda name: None)
    monkeypatch.setattr(srv, "_module_importable", lambda name: False)
    assert srv._discover_python(project_dir) is None


# ---------------------------------------------------------------------
# TypeScript / JavaScript discovery
# ---------------------------------------------------------------------


def test_typescript_prefers_global_binary(monkeypatch, project_dir):
    monkeypatch.setattr(
        srv.shutil,
        "which",
        lambda name: "/usr/local/bin/typescript-language-server"
        if name == "typescript-language-server"
        else None,
    )
    cmd = srv._discover_typescript(project_dir)
    assert cmd == [
        "/usr/local/bin/typescript-language-server",
        "--stdio",
    ]


def test_typescript_falls_back_to_project_local(
    monkeypatch,
    project_dir,
):
    monkeypatch.setattr(srv.shutil, "which", lambda name: None)
    bin_dir = project_dir / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    suffix = ".cmd" if sys.platform == "win32" else ""
    local = bin_dir / f"typescript-language-server{suffix}"
    local.write_text("#!/bin/sh\n", encoding="utf-8")
    cmd = srv._discover_typescript(project_dir)
    assert cmd is not None
    assert cmd[0] == str(local)
    assert "--stdio" in cmd


def test_typescript_returns_none_when_missing(
    monkeypatch,
    project_dir,
):
    monkeypatch.setattr(srv.shutil, "which", lambda name: None)
    assert srv._discover_typescript(project_dir) is None


# ---------------------------------------------------------------------
# detect_available_lsp_languages
# ---------------------------------------------------------------------


def test_detect_available_smart_registration(monkeypatch, project_dir):
    """Only languages whose discover returns argv appear in the dict."""

    def fake_python(_pd):
        return [sys.executable, "-m", "pylsp"]

    def fake_missing(_pd):
        return None

    # Frozen dataclass → build replacement specs with the fake discover
    # and swap the whole registry instead of mutating instances.
    fake_registry = {
        "python": srv.LspServerSpec(
            id="python",
            display_name="Python",
            extensions=srv.PYTHON_SPEC.extensions,
            root_markers=srv.PYTHON_SPEC.root_markers,
            discover=fake_python,
        ),
        "typescript": srv.LspServerSpec(
            id="typescript",
            display_name="TypeScript",
            extensions=srv.TYPESCRIPT_SPEC.extensions,
            root_markers=srv.TYPESCRIPT_SPEC.root_markers,
            discover=fake_missing,
        ),
    }
    monkeypatch.setattr(srv, "LSP_SERVERS", fake_registry)

    result = srv.detect_available_lsp_languages(project_dir)
    assert "python" in result
    assert result["python"] == [sys.executable, "-m", "pylsp"]
    assert "typescript" not in result


# ---------------------------------------------------------------------
# language_for_file
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename,expected_lang",
    [
        ("foo.py", "python"),
        ("foo.pyi", "python"),
        ("foo.ts", "typescript"),
        ("foo.tsx", "typescript"),
        ("foo.mts", "typescript"),
        ("foo.js", "javascript"),
        ("foo.jsx", "javascript"),
        ("foo.mjs", "javascript"),
        ("README.md", None),
        ("foo.rs", None),
        ("Makefile", None),
    ],
)
def test_language_for_file(filename, expected_lang):
    assert srv.language_for_file(Path(filename)) == expected_lang


def test_display_name_known_and_unknown():
    assert srv.display_name("python") == "Python"
    assert srv.display_name("typescript") == "TypeScript"
    assert srv.display_name("unknown-lang") == "unknown-lang"


# ---------------------------------------------------------------------
# Spec sanity
# ---------------------------------------------------------------------


def test_lsp_servers_registry_keys_match_ids():
    for key, spec in srv.LSP_SERVERS.items():
        assert key == spec.id


def test_module_importable_with_real_module():
    # Sanity: pytest itself must be importable in this env.
    assert srv._module_importable("pytest") is True


def test_module_importable_with_nonexistent_module():
    assert srv._module_importable("definitely_not_a_real_module_xyz") is False
