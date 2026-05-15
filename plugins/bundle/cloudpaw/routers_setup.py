# -*- coding: utf-8 -*-
"""API router mounting for CloudPaw plugin."""

import logging

logger = logging.getLogger(__name__)


def mount_routers() -> None:
    """Mount plugin API routers onto the FastAPI app."""
    try:
        from fastapi import APIRouter, Query

        # pylint: disable=no-name-in-module
        from qwenpaw.app.interaction import InteractionManager

        interaction_router = APIRouter(
            prefix="/interaction",
            tags=["interaction"],
        )

        from pydantic import BaseModel

        class InteractionRequest(BaseModel):
            session_id: str
            result: str

        @interaction_router.post("")
        async def resolve_interaction(body: InteractionRequest) -> dict:
            success = InteractionManager.resolve(body.session_id, body.result)
            if not success:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=404,
                    detail="No pending interaction for this session",
                )
            return {"status": "ok"}

        prd_router = APIRouter(prefix="/prd", tags=["prd"])

        @prd_router.get("")
        async def read_prd(loop_dir: str = Query(...)) -> dict:
            """Read prd.json from a mission loop directory."""
            import json
            from pathlib import Path
            from fastapi import HTTPException

            prd_path = Path(loop_dir).expanduser().resolve() / "prd.json"
            if not prd_path.exists():
                raise HTTPException(
                    status_code=404,
                    detail="prd.json not found",
                )
            try:
                return json.loads(prd_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid prd.json: {exc}",
                ) from exc

        from routers.a2a import router as a2a_router

        _inject_routers([interaction_router, prd_router, a2a_router])

    except Exception as e:
        logger.error("Failed to mount plugin routers: %s", e, exc_info=True)


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
        from agentscope_runtime.engine.app import AgentApp

        # pylint: disable=protected-access
        agent_app = (
            AgentApp._instances.get(AgentApp)
            if hasattr(AgentApp, "_instances")
            else None
        )
        if agent_app:
            app = agent_app.app
    except Exception:
        pass

    if app is None:
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
