# -*- coding: utf-8 -*-
"""Meta-test: scan tests/unit for module-state isolation hazards.

This is NOT a unit test of production code — it is a boundary test of the
test suite itself. It pins the two isolation failure modes that bit #5813,
which "passed in isolation, failed in the full suite" and cost hours to
debug:

1. A test that imports a heavy module which mutates global state
   (``qwenpaw.app._app``, app singletons) leaves it in ``sys.modules`` and
   poisons later tests on the same ``-n auto --dist=loadscope`` worker.
2. An autouse isolation fixture that blanket-deletes an entire module
   family (``for name in sys.modules: if name.startswith("qwenpaw.app"):
   del``) re-imports siblings (e.g. ``agent_context``) as NEW module
   objects, so monkeypatches in other tests land on the old object and
   silently break.

Both are static properties of a test file; we assert them here so the next
contributor who copies either pattern is caught before CI.
"""

# pylint: disable=line-too-long
# flake8: noqa: E501

from __future__ import annotations

import ast
import re
from pathlib import Path

# Modules whose import has strong global side-effects and which later tests
# assert the absence of (see tauri/test_entry.py::_ensure_qwenpaw_app_not_loaded).
# A test file importing any of these MUST isolate with an autouse fixture.
HEAVY_MODULES: frozenset[str] = frozenset({"qwenpaw.app._app"})

# A fixture deleting sys.modules entries matching a *prefix* (rather than a
# specific name) is the #5813 footgun: it re-creates sibling module objects.
# e.g. `for name in list(sys.modules): if name.startswith("qwenpaw.app"): del`
_PREFIX_DEL_PATTERN = re.compile(
    r"\.startswith\(\s*[\"']qwenpaw\.[^\"']+[\"']\s*\)",
)

TESTS_UNIT = Path(__file__).resolve().parent


def _python_test_files() -> list[Path]:
    # Exclude this meta-test itself: it contains the regex literal we scan for.
    self_name = Path(__file__).name
    return sorted(
        p
        for p in TESTS_UNIT.rglob("test_*.py")
        if p.is_file() and p.name != self_name
    )


def _read_ast(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports_heavy_module(path: Path) -> bool:
    """True if the file imports any module in HEAVY_MODULES."""
    try:
        tree = _read_ast(path)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module in HEAVY_MODULES
        ):
            return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in HEAVY_MODULES:
                    return True
    return False


def _has_autouse_fixture(path: Path) -> bool:
    """True if the file declares at least one autouse fixture."""
    try:
        tree = _read_ast(path)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            # @pytest.fixture(autouse=True)  OR  @pytest.fixture(autouse=True, ...)
            if (
                isinstance(dec, ast.Call)
                and _fixture_name(dec.func) == "fixture"
            ):
                for kw in dec.keywords:
                    if kw.arg == "autouse" and _is_true(kw.value):
                        return True
            # @pytest.fixture(autouse=True)
            if isinstance(dec, ast.Attribute) and dec.attr == "fixture":
                pass
    return False


def _fixture_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_true(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _has_prefix_sysmodules_delete(path: Path) -> bool:
    """True if the file deletes sys.modules entries by a *prefix* match.

    This is the footgun form that re-imports sibling modules as new objects.
    Deleting a *specific* name (``sys.modules.pop("qwenpaw.app._app", None)``)
    is fine and not flagged.
    """
    src = path.read_text(encoding="utf-8")
    if "sys.modules" not in src:
        return False
    return bool(_PREFIX_DEL_PATTERN.search(src))


def test_files_importing_heavy_module_isolate_with_autouse() -> None:
    """Every test importing a heavy module must have an autouse fixture.

    Regression for #5813: test_install_smoke imported qwenpaw.app._app and
    leaked it into sys.modules, breaking test_entry on the same worker.
    """
    offenders: list[str] = []
    for path in _python_test_files():
        if _imports_heavy_module(path) and not _has_autouse_fixture(path):
            offenders.append(
                f"{path.relative_to(TESTS_UNIT)}: imports a heavy module "
                f"({HEAVY_MODULES}) without an autouse isolation fixture",
            )
    assert not offenders, (
        "Tests importing heavy/side-effectful modules must isolate with an "
        "autouse fixture that restores sys.modules on teardown "
        "(declared in the test file itself or in a conftest.py):\n  - "
        + "\n  - ".join(offenders)
    )


def test_no_isolation_fixture_deletes_module_family_by_prefix() -> None:
    """No fixture may delete sys.modules by a module-family prefix.

    Regression for #5813 (second bite): an isolation fixture deleted
    every qwenpaw.app.* from sys.modules on teardown; re-importing
    qwenpaw.app.agent_context created a NEW module object, so
    test_token_usage's monkeypatch of get_current_session_id landed on the
    old object while _record_usage imported the new one -> returned None.

    Delete the specific heavy module you import (e.g.
    ``sys.modules.pop("qwenpaw.app._app", None)``), not a whole family.
    """
    offenders: list[str] = []
    for path in _python_test_files():
        if _has_prefix_sysmodules_delete(path):
            offenders.append(
                f"{path.relative_to(TESTS_UNIT)}: deletes sys.modules by a "
                f'family prefix (e.g. startswith("qwenpaw.app")) — re-imports '
                f"siblings as new module objects and breaks monkeypatches",
            )
    assert not offenders, (
        "Isolation fixtures must not delete a whole module family; remove "
        "only the specific heavy module you import:\n  - "
        + "\n  - ".join(offenders)
    )


if __name__ == "__main__":
    # Allow `python -m pytest` discovery; manual run prints the scan result.
    files = _python_test_files()
    print(f"Scanning {len(files)} test files under {TESTS_UNIT}")
    print(
        "Heavy-module importers:",
        [p.name for p in files if _imports_heavy_module(p)],
    )
    print(
        "Prefix-delete offenders:",
        [p.name for p in files if _has_prefix_sysmodules_delete(p)],
    )
