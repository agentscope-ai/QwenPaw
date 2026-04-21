# -*- coding: utf-8 -*-
"""Plugin API routes: list plugins with UI metadata and serve plugin
static files."""

import json
import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plugins", tags=["plugins"])

# ── Helpers ──────────────────────────────────────────────────────────────


def _list_plugins_from_disk() -> list[dict]:
    """Read plugin manifests directly from the plugins directory on disk.

    Used as a fallback when the plugin loader has not finished initialising
    (e.g. the frontend opens before the backend startup coroutine completes).
    Returns the same shape as the normal list endpoint so the frontend does
    not need to handle a different schema.
    """
    from ...config.utils import get_plugins_dir

    plugins_dir: Path = get_plugins_dir()
    if not plugins_dir.exists():
        return []

    result: list[dict] = []
    for item in sorted(plugins_dir.iterdir()):
        if not item.is_dir():
            continue
        manifest_path = item / "plugin.json"
        if not manifest_path.exists():
            continue
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read %s: %s", manifest_path, exc)
            continue

        plugin_id = manifest.get("id", item.name)
        frontend_entry = manifest.get("entry", {}).get("frontend")

        result.append(
            {
                "id": plugin_id,
                "name": manifest.get("name", plugin_id),
                "version": manifest.get("version", "0.0.0"),
                "description": manifest.get("description", ""),
                "enabled": True,  # disk-listed plugins are assumed enabled
                "frontend_entry": frontend_entry,
            },
        )
    return result


# ── Routes ───────────────────────────────────────────────────────────────


@router.get(
    "",
    summary="List loaded plugins",
    description="Return all loaded plugins with optional UI metadata.",
)
async def list_plugins(request: Request):
    """Return every loaded plugin with basic metadata and entry points.

    If the plugin loader has not yet finished initialising (backend still
    starting up when the frontend first requests the list), the response is
    built by scanning the plugins directory on disk — the same approach used
    by the CLI ``qwenpaw plugin list`` command.  This prevents a 503 error
    that would cause the frontend to miss all plugin JS bundles.

    Plugins that declare ``entry.frontend`` in their ``plugin.json``
    include a ``frontend_entry`` URL so the frontend can dynamically
    load the plugin's JS module.
    """
    loader = getattr(request.app.state, "plugin_loader", None)

    if loader is None:
        # Backend not ready yet — read manifests from disk (same as CLI)
        logger.debug(
            "[plugins] plugin_loader not ready, falling back to disk scan",
        )
        return _list_plugins_from_disk()

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

    When the plugin loader is ready, the plugin's source path is taken from
    the in-memory record.  If the loader is not yet initialised, the file is
    resolved directly from the plugins directory on disk so that the frontend
    can still fetch JS bundles during backend startup.

    A path-traversal guard ensures the resolved path stays inside the
    plugin's source directory.
    """
    # Resolve source path — prefer in-memory loader, fall back to disk
    loader = getattr(request.app.state, "plugin_loader", None)

    if loader is not None:
        record = loader.get_loaded_plugin(plugin_id)
        if record is None:
            raise HTTPException(404, f"Plugin '{plugin_id}' not found")
        source_path: Path = record.source_path
    else:
        # Loader not ready — resolve from disk (same logic as CLI)
        from ...config.utils import get_plugins_dir

        candidate = get_plugins_dir() / plugin_id
        if not candidate.is_dir() or not (candidate / "plugin.json").exists():
            raise HTTPException(404, f"Plugin '{plugin_id}' not found")
        source_path = candidate

    full_path = (source_path / file_path).resolve()

    # Security: prevent path traversal
    if not full_path.is_relative_to(source_path.resolve()):
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
