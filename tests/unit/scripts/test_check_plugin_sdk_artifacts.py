# -*- coding: utf-8 -*-
"""The exported author suite collects without repository test helpers."""

import os
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

pytestmark = pytest.mark.p1


def test_exported_author_suite_collects_outside_checkout(tmp_path):
    source = Path(__file__).resolve().parents[3]
    checker = runpy.run_path(
        str(source / "scripts/check_plugin_sdk_artifacts.py"),
    )
    selected = checker["prepare_author_tests"](source, tmp_path)
    assert "test_sdk_install_transaction.py" in selected
    assert "test_sdk_dependency_environment.py" not in selected
    code = """
import importlib.abc
import sys
import pytest

class NoRepositoryTests(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "tests" or fullname.startswith("tests."):
            raise AssertionError("Repository test import: " + fullname)

sys.meta_path.insert(0, NoRepositoryTests())
raise SystemExit(pytest.main([
    sys.argv[1], "--collect-only", "-q", "--tb=short",
]))
"""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PYTHON", "QWENPAW_"))
    }
    env.update(
        QWENPAW_WORKING_DIR=str(tmp_path / "working"),
        QWENPAW_SECRET_DIR=str(tmp_path / "secrets"),
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(tmp_path / "author_tests")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "test_sdk_install_transaction.py::" in result.stdout
    assert "tests collected" in result.stdout
