# -*- coding: utf-8 -*-
"""DataPaw plugin entry.

Module-level intentionally has **no relative imports**. Reason: host CLI's
``qwenpaw plugin install`` validates the plugin by loading ``plugin.py``
with ``importlib.util.spec_from_file_location`` and **does not pass**
``submodule_search_locations``. A ``from . import constants`` at module
level would crash that validator with "attempted relative import with no
known parent package", even though the real plugin loader (which DOES
pass ``submodule_search_locations``) handles it fine. cloudpaw follows
the same convention — relative imports happen lazily inside hooks.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class DataPawPlugin:
    """DataPaw plugin entry. Wires startup / shutdown hooks only."""

    def register(self, api):
        api.register_startup_hook(
            hook_name="datapaw_init",
            callback=self._on_startup,
            priority=50,
        )
        api.register_shutdown_hook(
            hook_name="datapaw_cleanup",
            callback=self._on_shutdown,
            priority=50,
        )

    async def _on_startup(self):
        # Load constants first — its module body inserts PLUGIN_DIR into
        # sys.path, which is what lets subsequent `from agents_setup
        # import …` / `from hooks import …` work as absolute imports.
        from . import constants  # noqa: F401

        logger.info("DataPaw plugin starting up")

        # Imports inside the hook so plugin.py at register-time stays
        # cheap; per cloudpaw / qwenpaw plugin loader contract, register()
        # only wires the hooks while the actual setup happens at startup.
        from agents_setup import ensure_builtin_agents
        from hooks import (
            patch_plugin_loader_unload,
            setup_channel_sse_hook,
            setup_runner_hooks,
        )
        from routers_setup import mount_routers

        ensure_builtin_agents()
        setup_runner_hooks()
        setup_channel_sse_hook()
        mount_routers()
        patch_plugin_loader_unload()

        logger.info("DataPaw plugin startup complete")

    async def _on_shutdown(self):
        # Plugin form has no sandbox subsystem to clean up; PluginLoader
        # uninstall path triggers profile/workspace cleanup. Nothing to do
        # at lifespan-end teardown beyond logging.
        logger.info("DataPaw plugin shutting down")


plugin = DataPawPlugin()
