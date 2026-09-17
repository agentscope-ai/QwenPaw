# -*- coding: utf-8 -*-
"""Authorize browser reads against the runtime's actual route ownership."""

from urllib.parse import unquote

from starlette.routing import Match
from starlette.types import Scope

PAWAPP_SCOPE_HEADER = "X-QwenPaw-PawApp-Scope"


def browser_prefixes(registry, app_id: str) -> list[str]:
    """Expose registered prefixes rather than guessing from an app ID."""
    if registry is None:
        return []
    return [
        f"{registration.prefix.lstrip('/')}"
        for registration in registry.get_http_router_registrations()
        if registration.plugin_id == app_id
    ]


def browser_read_allowed(scope: Scope, app_id: str) -> bool:
    """Require the first matching route to belong to the installed app."""
    app = scope["app"]
    registry = getattr(app.state, "plugin_registry", None)
    if registry is None:
        return False
    manifest = registry.get_all_plugin_manifests().get(app_id)
    if not manifest or not manifest.get("meta", {}).get("pawapp"):
        return False
    path = scope.get("path", "")
    if (
        scope.get("method") not in {"GET", "HEAD"}
        or unquote(unquote(path)) != path
        or "\\" in path
        or any(part in {".", ".."} for part in path.split("/"))
    ):
        return False
    for route in app.router.routes:
        match, child_scope = route.matches(scope)
        if match is not Match.FULL:
            continue
        if route.path in {
            "/api/frontend_plugin/{plugin_id}/files/{file_path:path}",
            "/api/pawapps/{app_id}/static/{file_path:path}",
        }:
            params = child_scope["path_params"]
            return params.get("plugin_id", params.get("app_id")) == app_id
        return any(
            registration.plugin_id == app_id
            and any(route is owned for owned in registration.routes)
            for registration in registry.get_http_router_registrations()
        )
    return False
