# -*- coding: utf-8 -*-
"""按当前主体返回可用前端插件与静态资源。"""

from fastapi import APIRouter, HTTPException, Request

from ...access.dependencies import get_actor
from ...identity.runtime import get_identity_schema, is_multi_user_enabled
from ...plugins.governance import (
    PluginAccessError,
    PluginGovernanceService,
    PostgresPluginGovernanceRepository,
)
from .plugins import (
    _list_plugins_from_disk,
    serve_plugin_ui_file,
)

router = APIRouter(prefix="/frontend_plugin", tags=["frontend-plugin"])


def get_plugin_governance_service() -> PluginGovernanceService:
    return PluginGovernanceService(
        PostgresPluginGovernanceRepository(schema=get_identity_schema())
    )


async def _authorized_plugin_ids(request: Request) -> set[str] | None:
    if not is_multi_user_enabled():
        return None
    rows = await get_plugin_governance_service().list_authorized(get_actor(request))
    return {row.plugin_id for row in rows}


@router.get(
    "",
    summary="List authorized frontend plugins",
    description=(
        "Return frontend metadata for plugins authorized to the current actor."
    ),
)
async def list_frontend_plugins(request: Request):
    """Return every plugin that has a frontend entry point.

    Only fields required by the frontend loader are included.  Sensitive
    management data (install paths, etc.) is not exposed here.
    """
    allowed = await _authorized_plugin_ids(request)
    loader = getattr(request.app.state, "plugin_loader", None)

    if loader is None:
        rows = _list_plugins_from_disk()
        return (
            rows if allowed is None else [row for row in rows if row["id"] in allowed]
        )

    result = []
    for _plugin_id, record in loader.get_all_loaded_plugins().items():
        manifest = record.manifest
        if allowed is not None and manifest.id not in allowed:
            continue
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
            },
        )

    return result


@router.get(
    "/{plugin_id}/files/{file_path:path}",
    summary="Serve authorized plugin static file",
    description=("Serve a static asset from a plugin authorized to the current actor."),
)
async def serve_frontend_plugin_file(
    plugin_id: str,
    file_path: str,
    request: Request,
):
    """Delegate to the authenticated static-file handler in plugins.py.

    Path-traversal protection is handled inside serve_plugin_ui_file.
    """
    if is_multi_user_enabled():
        try:
            await get_plugin_governance_service().require_app_access(
                get_actor(request), plugin_id
            )
        except PluginAccessError as exc:
            raise HTTPException(404, "plugin_not_found") from exc
    return await serve_plugin_ui_file(plugin_id, file_path, request)
