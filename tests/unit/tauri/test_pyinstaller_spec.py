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


def _called_packages(function_name: str) -> set[str]:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    packages = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name):
            continue
        if node.func.id != function_name or not node.args:
            continue
        package = node.args[0]
        if isinstance(package, ast.Constant) and isinstance(
            package.value,
            str,
        ):
            packages.add(package.value)
    return packages


def _metadata_packages() -> set[str]:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "_metadata_pkgs"
            for target in node.targets
        ):
            continue
        return {
            item.value
            for item in node.value.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        }
    return set()


def _data_directories() -> set[tuple[str, str]]:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "_data_dirs"
            for target in node.targets
        ):
            continue
        return {
            (source.value, target.value)
            for item in node.value.elts
            if isinstance(item, ast.Tuple)
            for source, target in [item.elts]
            if isinstance(source, ast.Constant)
            and isinstance(source.value, str)
            and isinstance(target, ast.Constant)
            and isinstance(target.value, str)
        }
    return set()


def _analysis_path_names() -> set[str]:
    tree = ast.parse(SPEC_PATH.read_text(encoding="utf-8"))
    analysis = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Analysis"
    )
    pathex = next(
        keyword.value
        for keyword in analysis.keywords
        if keyword.arg == "pathex"
    )
    return {node.id for node in ast.walk(pathex) if isinstance(node, ast.Name)}


def test_desktop_spec_collects_pawapp_sdk_for_runtime_loaded_plugins():
    assert "qwenpaw.pawapp" in _collected_submodule_packages()


def test_desktop_spec_collects_qwenpawmail_from_nested_source_root():
    assert "qwenpawmail_mcp" in _collected_submodule_packages()
    assert "MAIL_MCP_SRC" in _analysis_path_names()


def test_desktop_spec_collects_provider_catalog_data():
    assert (
        "providers/data",
        "qwenpaw/providers/data",
    ) in _data_directories()


def test_desktop_spec_collects_reme_entry_point_plugins():
    plugin_modules = {"reme_auto_fin", "reme_daily_paper"}
    plugin_distributions = {"reme-auto-fin", "reme-daily-paper"}

    assert plugin_modules <= _collected_submodule_packages()
    assert plugin_modules <= _called_packages("collect_data_files")
    assert {"reme-ai", *plugin_distributions} <= _metadata_packages()
