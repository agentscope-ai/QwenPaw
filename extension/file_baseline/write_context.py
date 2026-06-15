# -*- coding: utf-8 -*-
"""Optional provenance override for nested persona maintenance operations."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_file_baseline_maintenance: ContextVar[bool] = ContextVar(
    "file_baseline_maintenance",
    default=False,
)


def is_file_baseline_maintenance() -> bool:
    return _file_baseline_maintenance.get()


@contextmanager
def file_baseline_maintenance_context():
    token = _file_baseline_maintenance.set(True)
    try:
        yield
    finally:
        _file_baseline_maintenance.reset(token)
