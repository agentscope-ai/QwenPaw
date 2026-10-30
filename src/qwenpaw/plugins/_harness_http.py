# -*- coding: utf-8 -*-
"""One host-owned management gateway for active harness contributions."""

# HTTP integration rechecks private SDK owner and generation state.
# pylint: disable=protected-access

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .activity import PluginBusyError
from .errors import SDKError
from .harnesses import HarnessLogin, HarnessOperationNotSupportedError


class _Settings(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    device_code: bool = False


def backend_catalog(registry):
    """Describe backends without discovery, status calls or factories."""
    rows = [
        {
            "id": "qwenpaw",
            "label": "QwenPaw",
            "plugin_id": None,
            "status": "available",
            "capabilities": {},
            "config_fields": [],
        },
    ]
    states = registry.get_harness_states()
    for descriptor in registry.backend_registry.descriptors():
        entry = registry.backend_registry._entries.get(descriptor.id)
        available = False
        if entry is not None:
            try:
                entry.assert_active()
                available = True
            except SDKError:
                pass
        failed = (
            entry is not None
            and entry._context is not None
            and entry._context._instance.state.value == "failed"
        )
        rows.append(
            {
                "id": descriptor.id,
                "label": descriptor.label,
                "plugin_id": descriptor.plugin_id,
                "status": (
                    "available"
                    if available
                    else (
                        "failed"
                        if failed
                        else states.get(descriptor.plugin_id, "disabled")
                    )
                ),
                "capabilities": (
                    asdict(descriptor.capabilities)
                    if descriptor.capabilities
                    else {}
                ),
                "config_fields": (
                    list(entry.spec.config_fields) if entry is not None else []
                ),
            },
        )
    return rows


class _Gateway:
    def __init__(self, registry, app):
        self.registry, self.app = registry, app
        self.entries = {}
        self.routes = []

    def refresh(self):
        for route in self.routes:
            if route in self.app.router.routes:
                self.app.router.routes.remove(route)
        self.routes = []
        self.app.openapi_schema = None
        snapshot = dict(self.entries)
        router = APIRouter(prefix="/harnesses", tags=["harnesses"])

        def owner(provider_id):
            entry = snapshot.get(provider_id)
            if entry is None:
                raise HTTPException(
                    404,
                    {"code": "backend_unavailable", "backend_id": provider_id},
                )
            try:
                entry.assert_active()
            except SDKError as exc:
                raise HTTPException(
                    409,
                    {"code": "backend_unavailable", "backend_id": provider_id},
                ) from exc
            return entry

        async def dispatch(
            provider_id,
            request,
            operation,
            settings=None,
            **arguments,
        ):
            # Resolve the trusted Agent before constructing any backend.
            from ..app.agent_context import get_agent_for_request

            entry = owner(provider_id)
            workspace = await get_agent_for_request(request)
            values = settings
            if values is None:
                from ..config.config import load_agent_config_async

                config = await load_agent_config_async(workspace.agent_id)
                values = (
                    dict(config.backend_settings)
                    if config.backend == provider_id
                    else {}
                )
            try:
                entry.assert_active()
                result = await workspace.backend_runtime.call(
                    provider_id,
                    operation,
                    values,
                    **arguments,
                )
            except HarnessOperationNotSupportedError as exc:
                raise HTTPException(
                    409,
                    {
                        "code": f"{operation}_not_supported",
                        "message": str(exc),
                    },
                ) from exc
            except PluginBusyError as exc:
                raise HTTPException(409, exc.detail) from exc
            except SDKError as exc:
                raise HTTPException(
                    409,
                    {"code": "backend_unavailable", "message": str(exc)},
                ) from exc
            return entry, result

        @router.get("")
        async def catalog(request: Request):
            from ..app.agent_context import get_agent_for_request

            await get_agent_for_request(request)
            return {"providers": backend_catalog(self.registry)[1:]}

        @router.post("/{provider_id}/status")
        async def status(provider_id: str, body: _Settings, request: Request):
            entry, result = await dispatch(
                provider_id,
                request,
                "status",
                body.settings,
            )
            return {
                **asdict(result),
                "id": entry.spec.id,
                "name": entry.spec.label,
                "capabilities": asdict(entry.spec.capabilities),
            }

        @router.post("/{provider_id}/login")
        async def login(provider_id: str, body: _Settings, request: Request):
            _, result = await dispatch(
                provider_id,
                request,
                "start_login",
                body.settings,
                device_code=body.device_code,
            )
            return result.data if isinstance(result, HarnessLogin) else result

        @router.post("/{provider_id}/logout")
        async def logout(provider_id: str, body: _Settings, request: Request):
            await dispatch(provider_id, request, "logout", body.settings)
            return {"ok": True}

        def listing(operation, key):
            async def endpoint(provider_id: str, request: Request):
                _, result = await dispatch(provider_id, request, operation)
                return {key: [asdict(item) for item in result]}

            return endpoint

        for suffix, operation, key in (
            ("models", "models", "models"),
            ("skills", "discover_skills", "skills"),
            ("mcp", "discover_mcp", "servers"),
        ):
            router.add_api_route(
                "/{provider_id}/" + suffix,
                listing(operation, key),
                methods=["GET"],
            )
        from .registry import _mount_plugin_http_on_app

        self.routes = _mount_plugin_http_on_app(
            self.app,
            router,
            full_path_prefix="/api",
            tags=["harnesses"],
        )


def install_gateway(registry, app):
    """Keep the host management API available even without contributions."""
    gateway = getattr(registry, "_harness_gateway", None)
    if gateway is None:
        gateway = registry._harness_gateway = _Gateway(registry, app)
    elif gateway.app is app:
        return gateway
    else:
        for route in gateway.routes:
            if route in gateway.app.router.routes:
                gateway.app.router.routes.remove(route)
        gateway.app.openapi_schema = None
        gateway.routes = []
        gateway.app = app
    gateway.refresh()
    return gateway


def activate_gateway(context, backend_id):
    registry = context._api._registry
    app = registry.get_plugin_http_app()
    if app is None:
        return
    gateway = install_gateway(registry, app)
    gateway.entries[backend_id] = registry.backend_registry._entries[
        backend_id
    ]
    gateway.refresh()


def release_gateway(context, backend_id):
    registry = context._api._registry
    gateway = getattr(registry, "_harness_gateway", None)
    if gateway is not None:
        entry = gateway.entries.get(backend_id)
        if entry is not None and entry.owner == context.resources.owner:
            del gateway.entries[backend_id]
            gateway.refresh()
