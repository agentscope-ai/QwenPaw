# -*- coding: utf-8 -*-
"""Python environment details for diagnostics."""

from __future__ import annotations

import os
import sys
from typing import Mapping


def summarize_python_environment(
    environ: Mapping[str, str] | None = None,
) -> str:
    """Short label for the venv/conda context of current ``sys.executable``.

    When *environ* is omitted, uses :data:`os.environ`. Passing a mapping is
    mainly for tests.
    """
    env = os.environ if environ is None else environ
    ve = (env.get("VIRTUAL_ENV") or "").strip()
    if ve:
        return ve
    cenv = (env.get("CONDA_DEFAULT_ENV") or "").strip()
    cpfx = (env.get("CONDA_PREFIX") or "").strip()
    if cenv and cpfx:
        return f"conda {cenv} ({cpfx})"
    base = getattr(sys, "base_prefix", sys.prefix)
    if sys.prefix != base:
        return f"venv (sys.prefix={sys.prefix})"
    return "system interpreter (no virtualenv in effect)"
