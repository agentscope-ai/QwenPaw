# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = REPO_ROOT / "scripts" / "pack-tauri" / "qwenpaw.spec"


def _collected_submodule_packages() -> set[str]:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    packages = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name):
            continue
        if node.func.id != "collect_submodules" or not node.args:
            continue
        package = node.args[0]
        if isinstance(package, ast.Constant) and isinstance(
            package.value,
            str,
        ):
            packages.add(package.value)
    return packages


def test_desktop_spec_collects_pawapp_sdk_for_runtime_loaded_plugins():
    assert "qwenpaw.pawapp" in _collected_submodule_packages()
