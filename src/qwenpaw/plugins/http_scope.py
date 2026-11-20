"""Trusted user and agent scope for installed plugin HTTP handlers."""

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, Request

from ..access.agent_repository import agent_database_id
from ..access.dependencies import get_actor, require_platform_settings_manage
from ..identity.runtime import is_multi_user_enabled


@dataclass(frozen=True)
class PluginScope:
    user_id: UUID
    agent_id: str

    @property
    def storage_parts(self) -> tuple[str, str]:
        return str(self.user_id), str(agent_database_id(self.agent_id))


current_plugin_scope: ContextVar[PluginScope | None] = ContextVar(
    "current_plugin_scope",
    default=None,
)


def runtime_plugin_scope() -> PluginScope | None:
    """Resolve the server's HTTP or model-tool identity for scoped plugin state."""
    if not is_multi_user_enabled():
        return None
    scope = current_plugin_scope.get()
    if scope is not None:
        return scope
    from ..app.agent_context import get_current_agent_id
    from ..config.context import get_current_request_context
    from ..runtime_status.scope import execution_user_id

    user = execution_user_id(get_current_request_context())
    if not user:
        raise PermissionError("Plugin execution requires an authenticated user")
    return PluginScope(UUID(user), get_current_agent_id())


def require_plugin_route(plugin_id: str, prefix: str):
    async def authorize(request: Request):
        if not is_multi_user_enabled():
            yield
            return
        from ..app.agent_context import get_agent_for_request
        from ..app.routers.frontend_plugin import get_plugin_governance_service
        from .governance import PluginAccessError

        actor = get_actor(request)
        try:
            await get_plugin_governance_service().require_app_access(actor, plugin_id)
        except PluginAccessError as exc:
            raise HTTPException(404, "plugin_not_found") from exc
        if plugin_id in {"chrome", "computer-use", "qwenpaw-pet"}:
            # These backends manage the shared physical host and its grants.
            require_platform_settings_manage(actor)
        if plugin_id == "cloudpaw" and prefix in {"/a2a", "/prd"}:
            # The original cloud connection catalogue and filesystem PRDs
            # use machine-wide configuration and credentials.
            require_platform_settings_manage(actor)
        if plugin_id == "qwenpaw-creator" and "/models/" in request.url.path:
            # Provider credentials and policy are installation-wide.
            require_platform_settings_manage(actor)
        workspace = await get_agent_for_request(request)
        request.state.app_id = plugin_id
        # Preserve the governance decision for the lifetime of a streaming response.
        # The PawApp SDK also uses app_id for routing its own handlers.
        request.state.authorized_plugin = (plugin_id, actor)
        token = current_plugin_scope.set(PluginScope(actor.user_id, workspace.agent_id))
        try:
            yield
        finally:
            current_plugin_scope.reset(token)

    return authorize
