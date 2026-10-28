# -*- coding: utf-8 -*-
"""Host routing grants for the MCP plugin's legacy anonymous callback."""

import json
import time
from dataclasses import dataclass

from fastapi import HTTPException

from ...drivers.adapters.mcp_console import (
    attach_mcp_oauth_credential,
    mcp_oauth_credential_ref,
)
from ...drivers.credentials.types import CredentialRecord
from ...pawapp.context import PawAppContext
from ...plugins.apps import HttpRequest
from ...plugins.errors import SDKAccessError, StaleContextError
from ...plugins._drivers import _instance_id, _revision, workspace_is_current
from ..driver_config_service import DriverConfigService
from .plugin_service import (
    configuration_workspace,
    require_runtime,
    unavailable,
)

_TTL_SECONDS = 600


@dataclass(frozen=True)
class RoutingGrant:
    agent_id: str
    workspace_instance_id: str
    client_key: str
    source_revision: int
    generation: int
    user_id: str
    expires_at: float


def _ledger(request):
    state = request.app.state
    if not hasattr(state, "mcp_oauth_grants"):
        state.mcp_oauth_grants = {}
    return state.mcp_oauth_grants


def _dispatcher(request):
    require_runtime(request)
    registry = getattr(request.app.state, "plugin_registry", None)
    dispatcher = getattr(registry, "_app_dispatchers", {}).get("qwenpaw-mcp")
    if dispatcher is None:
        raise unavailable()
    return dispatcher


def _identity(request, agent_id, user_id):
    """Reconstruct identity from trusted fields, never callback claims."""
    state = request.app.state
    return PawAppContext(
        app_id="qwenpaw-mcp",
        agent_id=agent_id,
        user_id=user_id,
        channel="console",
        _workspace_registry=state.multi_agent_manager,
        _plugin_registry=state.plugin_registry,
        _app_services=getattr(state, "app_services", None),
    )


async def _call(dispatcher, identity, method, path, key="", body=None):
    try:
        response = await dispatcher.dispatch(
            identity,
            HttpRequest(
                method,
                path,
                {"client_key": key} if key else {},
                {},
                {},
                json.dumps(body or {}).encode(),
            ),
        )
    except StaleContextError as exc:
        raise unavailable() from exc
    except SDKAccessError as exc:
        raise HTTPException(403, str(exc)) from exc
    if response.status >= 400:
        raise HTTPException(
            response.status,
            response.body.get("detail", "OAuth request failed"),
        )
    return response.body


async def _prepare(request, client_key, *, declare=False, url=""):
    dispatcher = _dispatcher(request)
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    service = DriverConfigService(workspace)
    card = await service.load_card(client_key, protocol="mcp")
    if declare and not (card.endpoint.get("url") or url):
        raise HTTPException(400, "OAuth MCP client must have a remote URL.")
    alias = card.credentials.get("oauth")
    ref = alias.ref if alias else mcp_oauth_credential_ref(client_key)
    existing = await service.load_optional_credential(ref)
    if declare or existing is not None:
        if existing is None:
            await service.credential_store.put_if_absent(
                CredentialRecord(ref=ref, kind="oauth2_auth_code"),
            )
        if alias is None:
            card = attach_mcp_oauth_credential(card, ref)
            await service.card_store.save(card)
    identity = _identity(
        request,
        workspace.agent_id,
        str(getattr(request.state, "user", None) or "default"),
    )
    return dispatcher, identity, workspace, card


async def start(request, client_key, body):
    dispatcher, identity, workspace, card = await _prepare(
        request,
        client_key,
        declare=True,
        url=body.get("url"),
    )
    revision = _revision(card)
    result = await _call(
        dispatcher,
        identity,
        "POST",
        "/oauth/start/{client_key:path}",
        client_key,
        body,
    )
    # A successful network discovery cannot grant a replaced source's callback.
    current = await DriverConfigService(workspace).load_card(
        client_key,
        protocol="mcp",
    )
    if (
        not workspace_is_current(request.app.state.plugin_registry, workspace)
        or _revision(current) != revision
    ):
        raise HTTPException(409, "OAuth source changed")
    grants = _ledger(request)
    now = time.monotonic()
    for state, grant in tuple(grants.items()):
        if grant.expires_at <= now:
            grants.pop(state, None)
    grants[result["session_id"]] = RoutingGrant(
        workspace.agent_id,
        _instance_id(workspace),
        client_key,
        revision,
        dispatcher.generation,
        identity.user_id,
        now + _TTL_SECONDS,
    )
    return result


async def callback(request, body):
    # Consume before *any* await, including invalid/provider-error callbacks.
    grant = _ledger(request).pop(str(body.get("state") or ""), None)
    if not body.get("state"):
        raise HTTPException(
            400,
            body.get("error_description")
            or body.get("error")
            or "Missing 'code' or 'state' parameter.",
        )
    if grant is None or grant.expires_at <= time.monotonic():
        raise HTTPException(
            400,
            "OAuth session expired or not found. Please try again.",
        )
    dispatcher = _dispatcher(request)
    manager = request.app.state.multi_agent_manager
    workspace = getattr(manager, "agents", {}).get(grant.agent_id)
    if (
        dispatcher.generation != grant.generation
        or workspace is None
        or _instance_id(workspace) != grant.workspace_instance_id
    ):
        raise HTTPException(409, "OAuth source changed")
    from ...config.utils import load_config

    profile = load_config().agents.profiles.get(grant.agent_id)
    if profile is None or not profile.enabled:
        raise HTTPException(403, "OAuth workspace is unavailable")
    service = DriverConfigService(workspace)
    card = await service.load_card(grant.client_key, protocol="mcp")
    if _revision(card) != grant.source_revision:
        raise HTTPException(409, "OAuth source changed")
    result = await _call(
        dispatcher,
        _identity(request, grant.agent_id, grant.user_id),
        "POST",
        "/oauth/callback",
        body=body,
    )
    await service.reload_driver_best_effort(grant.client_key)
    return result


async def revoke(request, client_key):
    dispatcher, identity, workspace, card = await _prepare(request, client_key)
    if "oauth" not in card.credentials:
        return {"message": "OAuth tokens cleared"}
    result = await _call(
        dispatcher,
        identity,
        "DELETE",
        "/oauth/{client_key:path}",
        client_key,
    )
    await DriverConfigService(workspace).reload_driver_best_effort(client_key)
    return result


async def saved_status(request, client_key):
    """Present saved OAuth metadata without admitting a runtime workspace."""
    require_runtime(request)
    workspace = await configuration_workspace(request)
    service = DriverConfigService(workspace)
    card = await service.load_card(client_key, protocol="mcp")
    from ...drivers.contracts import iter_credential_refs

    refs = iter_credential_refs(card)
    alias = refs.get("oauth") or next(
        (item for item in refs.values() if item.kind == "oauth2_auth_code"),
        None,
    )
    record = await service.load_optional_credential(
        alias.ref if alias else mcp_oauth_credential_ref(client_key),
    )
    if record is None or not record.secrets.get("access_token"):
        return {"authorized": False, "expires_at": 0.0, "scope": ""}
    expiry = float(record.public.get("expires_at") or 0)
    return {
        "authorized": expiry <= 0 or expiry > time.time(),
        "expires_at": expiry,
        "scope": str(record.public.get("scope") or ""),
    }
