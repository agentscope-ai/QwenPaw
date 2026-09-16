# -*- coding: utf-8 -*-
"""Public-facing plugin endpoints for the frontend.

These routes are intentionally served without authentication so that
unauthenticated page loads (e.g. a customised login page) can fetch the
plugin list and load plugin JS/CSS bundles.

Only read operations are exposed here.  All plugin management operations
(install, upload, uninstall, reload) remain under /api/plugins/ and
require a valid Bearer token.
"""

from fastapi import APIRouter, Request

from .plugins import (
    _list_plugins_from_disk,
    _list_plugins_with_runtime,
    serve_plugin_ui_file,
)

router = APIRouter(prefix="/frontend_plugin", tags=["frontend-plugin"])


@router.get(
    "",
    summary="List installed plugins (public)",
    description=(
        "Return installed plugins with static frontend metadata and runtime "
        "status. "
        "This endpoint is public so the frontend can load plugin bundles "
        "before the user has authenticated."
    ),
)
async def list_frontend_plugins(request: Request):
    """Return installed plugin metadata without importing package code.

    Only fields required by the frontend loader are included.  Sensitive
    management data (install paths, etc.) is not exposed here.
    """
    loader = getattr(request.app.state, "plugin_loader", None)

    if loader is None:
        return _list_plugins_from_disk()

    return _list_plugins_with_runtime(loader)


@router.get(
    "/{plugin_id}/files/{file_path:path}",
    summary="Serve plugin static file (public)",
    description=(
        "Serve a static asset (JS, CSS, images) from a plugin's directory. "
        "Public so plugin bundles can be loaded on the unauthenticated "
        "login page."
    ),
)
async def serve_frontend_plugin_file(
    plugin_id: str,
    file_path: str,
    request: Request,
):
    """Delegate to the authenticated static-file handler in plugins.py.

    Path-traversal protection is handled inside serve_plugin_ui_file.
    """
    return await serve_plugin_ui_file(plugin_id, file_path, request)
