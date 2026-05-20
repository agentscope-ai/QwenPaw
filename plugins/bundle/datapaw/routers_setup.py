# -*- coding: utf-8 -*-
"""Mount DataPaw routers onto the host FastAPI app.

Sequence on plugin startup:

1. Locate the running FastAPI app instance.
2. ``include_router(tasks_router)`` — **without** an extra ``prefix``,
   because ``tasks_router`` already carries ``/api/tasks`` as its own
   prefix from the migrated source.
3. Move the SPA catch-all (``/{full_path:path}``) to the end of
   ``app.routes`` so it doesn't shadow the newly-mounted plugin routes.
4. Reset ``app.middleware_stack`` so Starlette rebuilds the middleware
   pipeline on the next request and picks up the new routes.
"""
from __future__ import annotations

import logging
from typing import Any

from core.routers import tasks_router

logger = logging.getLogger(__name__)


def _find_fastapi_app() -> Any | None:
    """Locate the running FastAPI app instance from host.

    Returns ``None`` if it can't be found (e.g., during CLI-only usage),
    in which case ``mount_routers`` becomes a no-op.
    """
    try:
        from qwenpaw.app._app import app
        return app
    except Exception:  # pylint: disable=broad-except
        logger.warning(
            "Cannot import qwenpaw.app._app.app; routers will not be mounted",
            exc_info=True,
        )
        return None


def _reorder_catch_all(app: Any) -> None:
    """Move SPA catch-all route to the end of ``app.routes``.

    Starlette matches routes in registration order. The host registers
    ``/{full_path:path}`` as a SPA fallback before plugins load, so any
    ``/api/*`` route added by a plugin is shadowed unless we move the
    fallback to the end.
    """
    catch_all_indices = [
        i
        for i, r in enumerate(app.routes)
        if getattr(r, "path", "") == "/{full_path:path}"
    ]
    if not catch_all_indices:
        return
    for idx in reversed(catch_all_indices):
        route = app.routes.pop(idx)
        app.routes.append(route)
        logger.info(
            "Moved SPA catch-all from index %d to end (%d)",
            idx,
            len(app.routes) - 1,
        )


def mount_routers() -> None:
    app = _find_fastapi_app()
    if app is None:
        return

    try:
        # tasks_router already carries the /api/tasks prefix; don't add another.
        app.include_router(tasks_router)
        logger.info("Mounted DataPaw tasks_router (%s)", tasks_router.prefix)
    except Exception:  # pylint: disable=broad-except
        logger.error("Failed to mount DataPaw tasks_router", exc_info=True)
        return

    _reorder_catch_all(app)

    if hasattr(app, "middleware_stack"):
        app.middleware_stack = None
        logger.info("Reset middleware_stack so new routes become reachable")
