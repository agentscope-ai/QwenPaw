# -*- coding: utf-8 -*-
"""Public-facing plugin endpoints for the frontend.

These routes are intentionally served without authentication so that
unauthenticated page loads (e.g. a customised login page) can fetch the
plugin list and load plugin JS/CSS bundles.

Only read operations are exposed here.  All plugin management operations
(install, upload, uninstall, reload) remain under /api/plugins/ and
require a valid Bearer token.
"""

import json

from fastapi import APIRouter, HTTPException, Request

from ...plugins.lifecycle import PluginState
from ...utils.io_utils import run_sync_io

from .plugins import (
    _list_plugins_from_disk,
    _plugin_config_row,
    _plugin_file_response,
    serve_plugin_ui_file,
)

router = APIRouter(prefix="/frontend_plugin", tags=["frontend-plugin"])


def _is_harness(manifest):
    return "harnesses" in (manifest.sdk or {}).get("capabilities", [])


def _executable(loader, record):
    if not record.enabled or getattr(record, "status", "active") == "failed":
        return False
    if not _is_harness(record.manifest):
        return True
    instance = loader.lifecycle.get_instance(record.manifest.id)
    return bool(
        getattr(record, "status", None) == "active"
        and instance is not None
        and instance.state is PluginState.ACTIVE
        and instance.activated,
    )


def _disk_frontends():
    # A disk copy cannot prove an SDK Harness's live activation.
    return [
        row
        for row in _list_plugins_from_disk()
        if row["enabled"] and not row.get("sdk_harnesses")
    ]


def _disk_frontend_source(plugin_id):
    from ...config.utils import get_plugins_dir
    from ...plugins.architecture import PluginManifest
    from ...plugins.settings import is_plugin_enabled

    source = get_plugins_dir() / plugin_id
    try:
        manifest = PluginManifest.from_dict(
            json.loads(
                (source / "plugin.json").read_text(encoding="utf-8"),
            ),
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(404, "Plugin frontend is unavailable") from exc
    if _is_harness(manifest) or not is_plugin_enabled(
        _plugin_config_row(plugin_id),
    ):
        raise HTTPException(404, "Plugin frontend is unavailable")
    return source


@router.get(
    "",
    summary="List plugins (public)",
    description=(
        "Return all loaded plugins with frontend metadata. "
        "This endpoint is public so the frontend can load plugin bundles "
        "before the user has authenticated."
    ),
)
async def list_frontend_plugins(request: Request):
    """Return every plugin that has a frontend entry point.

    Only fields required by the frontend loader are included.  Sensitive
    management data (install paths, etc.) is not exposed here.
    """
    loader = getattr(request.app.state, "plugin_loader", None)

    if loader is None:
        return await run_sync_io(_disk_frontends)

    result = []
    for _plugin_id, record in loader.get_all_loaded_plugins().items():
        if not _executable(loader, record):
            continue
        manifest = record.manifest
        result.append(
            {
                "id": manifest.id,
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description,
                "author": manifest.author,
                "enabled": record.enabled,
                "loaded": True,
                "plugin_type": manifest.plugin_type,
                "frontend_entry": manifest.entry.frontend,
                "status": getattr(record, "status", "active"),
                "harnesses": [
                    item["id"]
                    for item in (manifest.meta or {}).get("harnesses", [])
                ]
                if _is_harness(manifest)
                else [],
            },
        )

    return result


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
    loader = getattr(request.app.state, "plugin_loader", None)
    if loader is None:
        source = await run_sync_io(_disk_frontend_source, plugin_id)
        return await run_sync_io(_plugin_file_response, source, file_path)
    record = loader.get_loaded_plugin(plugin_id)
    if record is None or not _executable(loader, record):
        raise HTTPException(404, "Plugin frontend is unavailable")
    response = await serve_plugin_ui_file(plugin_id, file_path, request)
    if loader.get_loaded_plugin(plugin_id) is not record or not _executable(
        loader,
        record,
    ):
        raise HTTPException(404, "Plugin frontend is unavailable")
    return response
