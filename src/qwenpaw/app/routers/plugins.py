# -*- coding: utf-8 -*-
"""Plugin API routes: list plugins with UI metadata and serve plugin
static files."""

import logging
import mimetypes

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plugins", tags=["plugins"])

# ── Helpers ──────────────────────────────────────────────────────────────


def _get_plugin_loader(request: Request):
    loader = getattr(request.app.state, "plugin_loader", None)
    if loader is None:
        raise HTTPException(503, "Plugin system not initialized")
    return loader


# ── Routes ───────────────────────────────────────────────────────────────


@router.get(
    "",
    summary="List loaded plugins",
    description="Return all loaded plugins with optional UI metadata.",
)
async def list_plugins(request: Request):
    """Return every loaded plugin with basic metadata and entry points.

    Plugins that declare ``entry.frontend`` in their ``plugin.json``
    include a ``frontend_entry`` URL so the frontend can dynamically
    load the plugin's JS module.  All UI registration (routes, tool
    renderers) is handled by the plugin JS itself via
        ``window.register_routes`` / ``window.register_tool_render``.
    """

    loader = _get_plugin_loader(request)
    result = []

    for _plugin_id, record in loader.get_all_loaded_plugins().items():
        manifest = record.manifest
        frontend_entry = manifest.entry.frontend
        plugin_info: dict = {
            "id": manifest.id,
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "enabled": record.enabled,
            "frontend_entry": frontend_entry,
        }

        result.append(plugin_info)

    return result


@router.get(
    "/{plugin_id}/files/{file_path:path}",
    summary="Serve plugin static file",
    description="Serve a static file from a plugin's directory.",
)
async def serve_plugin_ui_file(
    plugin_id: str,
    file_path: str,
    request: Request,
):
    """Serve a static file that belongs to a plugin (JS / CSS / images …).

    A path-traversal guard ensures the resolved path stays inside the
    plugin's source directory.
    """
    loader = _get_plugin_loader(request)
    record = loader.get_loaded_plugin(plugin_id)

    if record is None:
        raise HTTPException(404, f"Plugin '{plugin_id}' not found")

    full_path = (record.source_path / file_path).resolve()

    # Security: prevent path traversal
    if not full_path.is_relative_to(record.source_path.resolve()):
        raise HTTPException(403, "Access denied")

    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(404, f"File not found: {file_path}")

    # Guess MIME type; default to application/octet-stream
    content_type, _ = mimetypes.guess_type(str(full_path))

    # For JS modules, ensure correct MIME so browsers accept dynamic import()
    if full_path.suffix in (".js", ".mjs"):
        content_type = "application/javascript"
    elif full_path.suffix == ".css":
        content_type = "text/css"

    if content_type:
        return FileResponse(
            str(full_path),
            media_type=content_type,
        )

    return FileResponse(str(full_path))
