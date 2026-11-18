# -*- coding: utf-8 -*-
"""Missing Windows dependencies must not prevent application startup."""

import subprocess
import sys


def test_app_starts_without_winpty():
    script = """
import builtins
import importlib
from types import SimpleNamespace
original = builtins.__import__
original_module = importlib.import_module
def isolated_import(name, globals=None, locals=None, fromlist=(), level=0):
    caller = (globals or {}).get('__name__', '')
    if name == 'sys' and caller == 'qwenpaw.services.terminal':
        return SimpleNamespace(platform='win32')
    if name == 'winpty':
        raise ModuleNotFoundError('winpty')
    return original(name, globals, locals, fromlist, level)
def missing_module(name, *args, **kwargs):
    if name == 'winpty':
        raise ModuleNotFoundError('winpty')
    return original_module(name, *args, **kwargs)
builtins.__import__ = isolated_import
importlib.import_module = missing_module
import qwenpaw.app._app
from qwenpaw.services.terminal import terminal_unavailable_reason
assert terminal_unavailable_reason() == 'dependency_missing'
print('APP_IMPORT_OK')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "APP_IMPORT_OK" in result.stdout
