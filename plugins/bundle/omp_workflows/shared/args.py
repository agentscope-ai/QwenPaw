# -*- coding: utf-8 -*-
"""Shared slash-command argument parsing helpers."""

from __future__ import annotations

import shlex


def split_args(raw: str) -> list[str] | None:
    """Split *raw* with shlex; return ``None`` on unbalanced quotes."""
    try:
        return shlex.split(raw)
    except ValueError:
        return None
