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

from ...plugins.errors import SDKCompatibilityError
from ...plugins.lifecycle import PluginState
from ...plugins.sdk_version import validate_sdk
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


def _sdk_declaration(manifest):
    """The SDK declaration, downgraded to "not declared" when it is invalid.

    The loader rejects an incompatible declaration before a plugin loads, so
    the loaded path only ever sees valid ones. The disk fallback has no loader
    and used to forward whatever the manifest said, which made the console the
    only judge: a pre-release spelling such as ``1.2.0rc1`` is below 1.2.0
    under PEP 440 and may not carry ``themeTokens``, yet the console compared
    the raw string numerically and accepted the extended roles. Asking the
    same question on both paths keeps one decision in one place; the console
    now reads only the capability this function returns.
    """
    sdk = manifest.sdk or {}
    try:
        validate_sdk(sdk)
    except SDKCompatibilityError:
        return None, []
    version = sdk.get("version")
    capabilities = sdk.get("capabilities") or []
    return (
        version if isinstance(version, str) else None,
        (
            [item for item in capabilities if isinstance(item, str)]
            if isinstance(capabilities, list)
            else []
        ),
    )


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
    rows = [
        row
        for row in _list_plugins_from_disk()
        if row["enabled"] and not row.get("sdk_harnesses")
    ]
    # This listing is shared with the management endpoint, whose response
    # shape is already fixed; fill the SDK declaration in here instead.
    from ...config.utils import get_plugins_dir
    from ...plugins.architecture import PluginManifest

    plugins_dir = get_plugins_dir()
    for row in rows:
        try:
            manifest = PluginManifest.from_dict(
                json.loads(
                    (plugins_dir / row["id"] / "plugin.json").read_text(
                        encoding="utf-8",
                    ),
                ),
            )
        except (OSError, ValueError):
            continue
        # Same compatibility question as the loaded path.
        row["sdk_version"], row["sdk_capabilities"] = _sdk_declaration(
            manifest,
        )
    return rows


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
        sdk_version, sdk_capabilities = _sdk_declaration(manifest)
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
                "sdk_version": sdk_version,
                "sdk_capabilities": sdk_capabilities,
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
