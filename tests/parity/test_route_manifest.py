# -*- coding: utf-8 -*-
"""锁定多用户改造前的后端 API 与 Agent 作用域路由基线。"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "tests" / "parity" / "baseline_manifest.json"


def _load_manifest() -> dict[str, Any]:
    assert MANIFEST_PATH.is_file(), (
        "缺少显式基线清单 tests/parity/baseline_manifest.json；"
        "禁止在测试运行时自动接受当前实现。"
    )
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _included_router_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "include_router" or not node.args:
            continue
        router_arg = node.args[0]
        if isinstance(router_arg, ast.Name):
            names.append(router_arg.id)
    return names


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _api_methods() -> list[dict[str, str]]:
    """读取源码中的显式 FastAPI 装饰器，不导入应用或触发生命周期。"""
    roots = [
        ROOT / "src" / "qwenpaw" / "app",
        ROOT / "src" / "qwenpaw" / "browser" / "control_link",
        ROOT / "src" / "qwenpaw" / "plugins" / "api.py",
    ]
    files: set[Path] = set()
    for root in roots:
        if root.is_file():
            files.add(root)
        elif root.is_dir():
            files.update(root.rglob("*.py"))

    methods: list[dict[str, str]] = []
    http_methods = {"get", "post", "put", "patch", "delete", "websocket"}
    for path in sorted(files):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute) or func.attr not in http_methods:
                    continue
                if not isinstance(func.value, ast.Name) or not decorator.args:
                    continue
                route_path = _literal_string(decorator.args[0])
                if route_path is None:
                    continue
                methods.append(
                    {
                        "source": path.relative_to(ROOT).as_posix(),
                        "router": func.value.id,
                        "method": "WS" if func.attr == "websocket" else func.attr.upper(),
                        "path": route_path,
                    }
                )
    return sorted(methods, key=lambda row: tuple(row.values()))


def test_global_router_mounts_match_explicit_manifest() -> None:
    manifest = _load_manifest()
    actual = _included_router_names(ROOT / "src/qwenpaw/app/routers/__init__.py")
    assert actual == manifest["backend"]["global_router_modules"]


def test_agent_scoped_router_mounts_match_explicit_manifest() -> None:
    manifest = _load_manifest()
    actual = _included_router_names(
        ROOT / "src/qwenpaw/app/routers/agent_scoped.py"
    )
    assert actual == manifest["backend"]["agent_scoped_router_modules"]


def test_api_methods_match_explicit_manifest() -> None:
    manifest = _load_manifest()
    assert _api_methods() == manifest["backend"]["api_methods"]

