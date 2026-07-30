# -*- coding: utf-8 -*-
"""Two-track isolation contract: deprecated browser remains deletable."""

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "qwenpaw"
FORK = SRC / "agents" / "tools" / "__init__.py"
DEPRECATED = SRC / "agents" / "tools" / "deprecated_browser"
UNIFIED = SRC / "browser"

IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+[\w.]*deprecated_browser",
    re.MULTILINE,
)


def _python_files(root: Path):
    return (
        path for path in root.rglob("*.py") if "__pycache__" not in path.parts
    )


def test_inbound_imports_limited_to_the_fork() -> None:
    offenders = []
    for path in _python_files(SRC):
        if path == FORK or DEPRECATED in path.parents:
            continue
        if IMPORT_RE.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path))
    assert not offenders


def test_unified_never_imports_deprecated() -> None:
    offenders = [
        str(path)
        for path in _python_files(UNIFIED)
        if "deprecated_browser" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_deprecated_never_imports_unified_package() -> None:
    pattern = re.compile(
        r"^\s*(?:from|import)\s+qwenpaw\.browser\b"
        r"|^\s*from\s+\.\.\.browser\b",
        re.MULTILINE,
    )
    offenders = [
        str(path)
        for path in _python_files(DEPRECATED)
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
