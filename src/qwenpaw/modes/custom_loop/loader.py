# -*- coding: utf-8 -*-
"""Load saved custom loop modes into one workspace."""
from __future__ import annotations

import logging

from .mode import (
    CustomLoopController,
    DeclarativeLoopMode,
    LoopModeActivationStore,
)

logger = logging.getLogger(__name__)


def load_custom_loop_modes(workspace: object) -> None:
    """Compile and register every enabled, conflict-free custom mode."""
    configs = workspace.config.running.loop.custom_modes
    enabled = [config for config in configs if config.enabled]
    if not enabled:
        return

    registry = workspace.plugins.slash_command_registry
    reserved = set(registry.names())
    store = LoopModeActivationStore()
    loaded = 0
    for config in enabled:
        if config.slash_command in reserved:
            logger.warning(
                "Custom loop mode '%s' skipped: /%s already exists",
                config.id,
                config.slash_command,
            )
            continue
        try:
            mode = DeclarativeLoopMode(config, store)
            workspace.plugins.register_mode(mode, workspace)
        except Exception:
            logger.warning(
                "Custom loop mode '%s' could not be loaded",
                config.id,
                exc_info=True,
            )
            continue
        reserved.add(config.slash_command)
        loaded += 1

    if loaded and "mode" not in reserved:
        workspace.plugins.register_mode(CustomLoopController(store), workspace)


__all__ = ["load_custom_loop_modes"]
