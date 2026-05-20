# -*- coding: utf-8 -*-
"""Backup package public API.

Keep this module lightweight: startup imports low-level backup utilities for
restore-lock cleanup, and eager public API imports pull in the app stack.
"""
from __future__ import annotations

from importlib import import_module

__all__ = [
    "create_stream",
    "list_backups",
    "get_backup",
    "delete_backups",
    "export_backup",
    "import_backup",
    "execute_restore",
]

_EXPORTS = {
    "create_stream": ("._ops.create", "create_stream"),
    "list_backups": ("._ops.storage", "list_backups"),
    "get_backup": ("._ops.storage", "get_backup"),
    "delete_backups": ("._ops.storage", "delete_backups"),
    "export_backup": ("._ops.storage", "export_backup"),
    "import_backup": ("._ops.storage", "import_backup"),
    "execute_restore": (".orchestration", "execute_restore"),
}


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name, __name__), attr_name)
    globals()[name] = value
    return value
