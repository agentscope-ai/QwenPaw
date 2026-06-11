# -*- coding: utf-8 -*-
"""API router builders for CloudPaw plugin.

Returns FastAPI APIRouter instances that the plugin registers via
``api.register_http_router()`` — no manual app mounting needed.
"""

import logging

logger = logging.getLogger("qwenpaw").getChild(
    __name__.replace("plugin_cloudpaw.", ""),
)


def build_plugin_routers():
    """Build and return all plugin API routers.

    The caller should register each router via
    ``api.register_http_router(router, prefix=...)``.
    """
    from .routers.a2a import router as a2a_router
    from .routers.interaction import router as interaction_router
    from .routers.prd import router as prd_router

    return [
        (interaction_router, "/interaction"),
        (prd_router, "/prd"),
        (a2a_router, "/a2a"),
    ]


def _reorder_catch_all(app) -> None:
    """Move SPA catch-all route to the end of the route list.

    The main app registers ``/{full_path:path}`` as a SPA fallback.
    Because Starlette matches routes by registration order, any route
    added *after* the catch-all (e.g. by a plugin startup hook) will
    never be reached — the catch-all grabs the request first and
    returns 404 for ``/api/*`` paths.

    This function finds that route and moves it to the very end so
    that all concrete API routes are tried before the fallback.
    """
    try:
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
                "Moved SPA catch-all route from position %d to end (%d)",
                idx,
                len(app.routes) - 1,
            )
    except Exception as exc:
        logger.warning("Failed to reorder catch-all route: %s", exc)


def _inject_routers(routers: list) -> None:
    """Inject routers into the running FastAPI application."""
    app = None
    try:
        from qwenpaw.app._app import app as _app

        if hasattr(_app, "state"):
            app = _app
    except Exception:
        pass

    if app is None:
        logger.warning(
            "Cannot find FastAPI app instance; plugin routers not mounted. "
            "This is expected during CLI-only usage.",
        )
        return

    for router in routers:
        try:
            app.include_router(router, prefix="/api")
            logger.info("Mounted plugin router: %s", router.prefix)
        except Exception as e:
            logger.warning("Failed to mount router %s: %s", router.prefix, e)

    # Move the SPA catch-all route to the end so dynamically added
    # /api/* routes are matched first.  Starlette matches routes in
    # registration order; the catch-all `/{full_path:path}` was
    # registered before our plugin routes and would intercept them.
    _reorder_catch_all(app)

    # Force Starlette to rebuild its middleware stack so that
    # dynamically added routes become reachable.
    if hasattr(app, "middleware_stack"):
        app.middleware_stack = None
        logger.info("Reset middleware_stack to pick up new routes")
