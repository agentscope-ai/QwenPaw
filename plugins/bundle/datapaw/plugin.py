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
        # Load constants first — its module body inserts PLUGIN_DIR into
        # sys.path, which is what lets the absolute import of core.routers
        # below (and later imports inside _on_startup) resolve. Use
        # importlib instead of a `from . import constants` binding so
        # pylint doesn't flag an unused import; we only want the
        # side-effect.
        import importlib

        importlib.import_module(".constants", __package__)

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

        # HTTP routes are registered at register-time (mirrors qwenpaw-pet),
        # not in the startup hook: host's register_http_router itself does
        # the SPA-catch-all-aware mount + bookkeeping for unload cleanup.
        from core.routers import tasks_router

        api.register_http_router(
            tasks_router,
            prefix="/tasks",  # final URL: /api/tasks/...
            tags=["datapaw-tasks"],
        )

    async def _on_startup(self):
        logger.info("DataPaw plugin starting up")

        # Relative imports (not absolute) so they resolve against the
        # ``__package__`` host's PluginLoader sets on this module
        # (``plugin_datapaw``) rather than walking sys.path. Other
        # plugins (cloudpaw) also ship a top-level ``agents_setup`` /
        # ``hooks`` module and inject their plugin dir into sys.path
        # from their own ``constants.py``; an absolute ``from
        # agents_setup import ...`` could resolve to cloudpaw's file and
        # blow up on cloudpaw's own ``from .constants`` (no known parent
        # package in this load context). The ``no relative imports at
        # module level`` rule from this file's docstring applies only to
        # the top of plugin.py — method bodies execute after the loader
        # has set __package__ / __path__.
        # pylint: disable-next=relative-beyond-top-level
        from .agents_setup import ensure_builtin_agents
        from .hooks import (  # pylint: disable=relative-beyond-top-level
            patch_plugin_loader_unload,
            setup_channel_sse_hook,
            setup_runner_hooks,
        )

        ensure_builtin_agents()
        setup_runner_hooks()
        setup_channel_sse_hook()
        patch_plugin_loader_unload()

        logger.info("DataPaw plugin startup complete")

    async def _on_shutdown(self):
        # PluginLoader uninstall handles profile/workspace cleanup; nothing
        # to do at lifespan-end teardown beyond logging.
        logger.info("DataPaw plugin shutting down")


plugin = DataPawPlugin()
