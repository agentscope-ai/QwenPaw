# -*- coding: utf-8 -*-
"""Environment variable compatibility: BOOSTCLAW_* preferred, COPAW_* fallback.

When reading config from the environment, we check BOOSTCLAW_<SUFFIX> first,
then COPAW_<SUFFIX>. This keeps compatibility with CoPaw while allowing
BoostClaw to use its own prefix. Use these helpers wherever app-level env
vars are read (paths, log level, feature flags, etc.).
"""
from __future__ import annotations

import os


def get_app_env(suffix: str, default: str = "") -> str:
    """Return value for BOOSTCLAW_<suffix> or COPAW_<suffix> (prefer BOOSTCLAW)."""
    b = os.environ.get(f"BOOSTCLAW_{suffix}")
    if b is not None and b != "":
        return b
    return os.environ.get(f"COPAW_{suffix}", default)


def get_app_env_bool(suffix: str, default: bool = False) -> bool:
    """Return bool for BOOSTCLAW_<suffix> or COPAW_<suffix> (true/1/yes)."""
    val = get_app_env(suffix, str(default)).lower()
    return val in ("true", "1", "yes")


def get_app_env_int(
    suffix: str,
    default: int = 0,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    """Return int for BOOSTCLAW_<suffix> or COPAW_<suffix>, with optional bounds."""
    try:
        value = int(get_app_env(suffix, str(default)))
        if min_value is not None and value < min_value:
            return min_value
        if max_value is not None and value > max_value:
            return max_value
        return value
    except (TypeError, ValueError):
        return default


def get_app_env_float(
    suffix: str,
    default: float = 0.0,
    min_value: float | None = None,
    max_value: float | None = None,
    allow_inf: bool = False,
) -> float:
    """Return float for BOOSTCLAW_<suffix> or COPAW_<suffix>, with optional bounds."""
    try:
        value = float(get_app_env(suffix, str(default)))
        if min_value is not None and value < min_value:
            return min_value
        if max_value is not None and value > max_value:
            return max_value
        if not allow_inf and value in (float("inf"), float("-inf")):
            return default
        return value
    except (TypeError, ValueError):
        return default
