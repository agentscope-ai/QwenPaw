# -*- coding: utf-8 -*-
"""DataPaw plugin shared constants."""

from __future__ import annotations

from pathlib import Path

from qwenpaw.constant import EnvVarLoader

PLUGIN_ID = "datapaw"
BUILTIN_DATAPAW_AGENT_ID = "datapaw"
PLUGIN_DIR = Path(__file__).resolve().parent
DATAPAW_SPAWN_SUBAGENT_ENABLED_ENV = "DATAPAW_SPAWN_SUBAGENT_ENABLED"


def is_spawn_subagent_enabled() -> bool:
    """Return whether DataPaw should expose its spawn_subagent tool."""
    return EnvVarLoader.get_bool(DATAPAW_SPAWN_SUBAGENT_ENABLED_ENV, True)
