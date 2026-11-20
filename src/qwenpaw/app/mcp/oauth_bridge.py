# -*- coding: utf-8 -*-
"""Host routing grants for the MCP plugin's legacy anonymous callback."""

import json
import time
import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from uuid import uuid4

from fastapi import HTTPException

from ...drivers.adapters.mcp_console import (
    attach_mcp_oauth_credential,
    mcp_oauth_credential_ref,
)
from ...drivers.adapters.mcp_card_builder import (
    detach_mcp_oauth_credential,
    mcp_oauth_alias,
)
from ...drivers.constants import (
    CREDENTIAL_ALIAS_STATIC,
    CREDENTIAL_KIND_OAUTH_AUTH_CODE,
    CREDENTIAL_KIND_STATIC,
)
from ...drivers.credentials.types import CredentialRecord
from ...drivers.credential_commit import (
    CredentialCleanupError,
    commit_credential_binding,
    cleanup_credential_candidates,
)
from ...drivers.errors import (
    CredentialNotFoundError,
    DriverCardError,
    driver_error_diagnostic,
)
from ...drivers.contracts import CredentialRef, iter_credential_refs
from ...plugins._driver_management import CredentialOverlayGrant
from ...pawapp.context import PawAppContext
from ...plugins.apps import HttpRequest
from ...plugins.errors import SDKAccessError, StaleContextError
from ...plugins._drivers import _instance_id, _revision, workspace_is_current
from ..driver_config_service import DriverConfigService
from ...utils.io_utils import run_async_to_completion, run_sync_io
from .config_service import (
    oauth_secrets_to_clear,
    saved_oauth_records,
    versioned_static_credential,
)
from .oauth_pending import (
    PendingAuthorization,
    attempts,
    purge,
    candidate_meta,
    CANDIDATE_OWNER,
)
from .plugin_service import (
    configuration_workspace,
    require_runtime,
    unavailable,
)

_TTL_SECONDS = 600
logger = logging.getLogger(__name__)


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
    purge(request, state.mcp_oauth_grants, time.monotonic())
    return state.mcp_oauth_grants


def _dispatcher(request):
    require_runtime(request)
    registry = getattr(request.app.state, "plugin_registry", None)
    dispatcher = getattr(registry, "_app_dispatchers", {}).get("qwenpaw-mcp")
    if dispatcher is None:
        raise unavailable()
    return dispatcher


def _identity(request, agent_id, user_id, overlay=None):
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
        _driver_management_grant=overlay,
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


async def _prepare(request, client_key):
    dispatcher = _dispatcher(request)
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    service = DriverConfigService(workspace)
    card = await service.load_card(client_key, protocol="mcp")
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
    )
    if not (card.endpoint.get("url") or body.get("url")):
        raise HTTPException(400, "OAuth MCP client must have a remote URL.")
    grants = _ledger(request)
    service = DriverConfigService(workspace)
    try:
        from .oauth_pending import time as pending_time

        await cleanup_credential_candidates(
            service.card_store,
            service.credential_store,
            owner=CANDIDATE_OWNER,
            now=pending_time.time(),
        )
    except Exception as exc:
        logger.warning(
            "Deferred MCP OAuth candidate cleanup for source %r in workspace %r: %s",
            client_key,
            workspace.agent_id,
            driver_error_diagnostic(exc),
        )
    alias = mcp_oauth_alias(card)
    old_ref = card.credentials[alias].ref if alias else None
    refs = {item.ref for item in iter_credential_refs(card).values()}
    expected = {}
    existing = None
    for ref in refs:
        try:
            record, version = await service.credential_store.get_versioned(ref)
        except CredentialNotFoundError:
            version, record = None, None
        expected[ref] = version
        if ref == old_ref:
            existing = record
    overlay = CredentialOverlayGrant(
        plugin_id="qwenpaw-mcp",
        generation=dispatcher.generation,
        workspace_id=workspace.agent_id,
        workspace_instance_id=_instance_id(workspace),
        user_id=identity.user_id,
        channel=identity.channel,
        card=card,
        alias="oauth",
        expires_at=time.monotonic() + _TTL_SECONDS,
        record=CredentialRecord(
            ref=f"{mcp_oauth_credential_ref(client_key)}/{uuid4().hex}",
            kind="oauth2_auth_code",
            public=dict(existing.public) if existing else {},
            secrets=dict(existing.secrets) if existing else {},
            meta=candidate_meta(existing.meta if existing else {}),
        ),
        base_store=service.credential_store,
    )
    # pylint: disable-next=protected-access
    identity._driver_management_grant = overlay
    revision = _revision(card)
    binding_token = secrets.token_urlsafe(32)
    try:
        result = await _call(
            dispatcher,
            identity,
            "POST",
            "/oauth/start/{client_key:path}",
            client_key,
            {**body, "_management_token": binding_token},
        )
        current = await service.load_card(client_key, protocol="mcp")
        if (
            not workspace_is_current(
                request.app.state.plugin_registry,
                workspace,
            )
            or _revision(current) != revision
        ):
            raise HTTPException(409, "OAuth source changed")
    except BaseException:
        overlay.close()
        raise
    now = time.monotonic()
    grants[result["session_id"]] = RoutingGrant(
        workspace.agent_id,
        _instance_id(workspace),
        client_key,
        revision,
        dispatcher.generation,
        identity.user_id,
        now + _TTL_SECONDS,
    )
    attempts(request)[result["session_id"]] = PendingAuthorization(
        overlay,
        expected,
        binding_token,
    )
    return result


async def _callback(request, body, grant, attempt):
    # Consume before *any* await, including invalid/provider-error callbacks.
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

    config = await run_sync_io(load_config)
    profile = config.agents.profiles.get(grant.agent_id)
    if profile is None or not profile.enabled:
        raise HTTPException(403, "OAuth workspace is unavailable")
    service = DriverConfigService(workspace)
    card = await service.load_card(grant.client_key, protocol="mcp")
    if _revision(card) != grant.source_revision:
        raise HTTPException(409, "OAuth source changed")
    result = await _call(
        dispatcher,
        _identity(request, grant.agent_id, grant.user_id, attempt.overlay),
        "POST",
        "/oauth/callback",
        body={**body, "_management_token": attempt.binding_token},
    )
    record, _ = await attempt.overlay.store.get_versioned(
        attempt.overlay.record.ref,
    )
    if not record.secrets.get("access_token"):
        raise HTTPException(400, "OAuth token response is incomplete")

    def guard():
        dispatcher.plugin._guard()  # pylint: disable=protected-access
        current_profile = load_config().agents.profiles.get(grant.agent_id)
        if (
            current_profile is None
            or not current_profile.enabled
            or grant.agent_id in getattr(manager, "_uninstalling_agents", ())
            or id(workspace) in getattr(manager, "_agent_stop_tasks", {})
        ):
            raise StaleContextError("OAuth workspace is unavailable")
        attempt.overlay.check(
            plugin_id="qwenpaw-mcp",
            generation=dispatcher.generation,
            workspace_id=workspace.agent_id,
            workspace_instance_id=_instance_id(workspace),
            user_id=grant.user_id,
            channel="console",
        )
        if not dispatcher.admitted() or not workspace_is_current(
            request.app.state.plugin_registry,
            workspace,
        ):
            raise StaleContextError("OAuth source changed")

    async def publish():
        async with _oauth_publication(manager, dispatcher):
            try:
                await commit_credential_binding(
                    service.card_store,
                    service.credential_store,
                    expected_card=attempt.overlay.card,
                    expected_credentials=attempt.expected_credentials,
                    candidate_card=attach_mcp_oauth_credential(
                        card,
                        record.ref,
                    ),
                    candidate_record=record,
                    guard=guard,
                )
            except Exception as exc:
                if isinstance(exc, (StaleContextError, SDKAccessError)) or (
                    isinstance(exc, DriverCardError)
                    and not isinstance(exc.__cause__, OSError)
                ):
                    raise HTTPException(409, "OAuth source changed") from exc
                raise HTTPException(
                    400,
                    "OAuth credentials could not be saved",
                ) from exc
            attempt.finish("succeeded", time.monotonic())
        await service.reload_driver_best_effort(grant.client_key)

    await run_async_to_completion(publish())
    return result


@asynccontextmanager
async def _workspace_commit_lock(manager):
    # The real manager serializes publication/replacement under this lock.
    lock = getattr(manager, "_lock", None)
    if isinstance(lock, asyncio.Lock):
        async with lock:
            yield
    else:
        yield


@asynccontextmanager
async def _oauth_publication(manager, dispatcher):
    # Plugin interruption must drain publication and its terminal status.
    async with _workspace_commit_lock(manager):
        # pylint: disable-next=protected-access
        with dispatcher.plugin._admission():
            # pylint: disable-next=protected-access
            dispatcher.plugin._instance.activity.retain_cleanup(
                asyncio.current_task(),
            )
            yield


async def callback(request, body):
    state = str(body.get("state") or "")
    grant = _ledger(request).pop(state, None)
    attempt = attempts(request).get(state)
    if grant is None:
        # A replay owns no attempt and must not terminate its live callback.
        return await _callback(request, body, None, None)
    try:
        if attempt is None or attempt.phase != "pending":
            raise HTTPException(
                400,
                "OAuth session expired or not found. Please try again.",
            )
        return await _callback(request, body, grant, attempt)
    except Exception as exc:
        # Plain 400s include expected callback rejection and token exchange
        # failures already logged by the plugin. Host faults retain the cause.
        if (
            not isinstance(exc, HTTPException)
            or exc.status_code != 400
            or exc.__cause__ is not None
        ):
            status = exc.status_code if isinstance(exc, HTTPException) else 500
            logger.warning(
                "OAuth callback failed for source %r in workspace %r "
                "(HTTP %s): %s",
                grant.client_key,
                grant.agent_id,
                status,
                driver_error_diagnostic(exc),
            )
        raise
    finally:
        if attempt is not None and attempt.phase == "pending":
            attempt.finish("failed", time.monotonic())


async def revoke(request, client_key):
    dispatcher, _, workspace, card = await _prepare(request, client_key)
    state = request.app.state
    manager = state.multi_agent_manager
    registry = state.plugin_registry
    service = DriverConfigService(workspace)
    expected = {}
    clear_secrets = await oauth_secrets_to_clear(service, card, expected)
    candidate, remainder = await _detach_oauth(service, card, expected)

    def guard():
        from ...config.utils import load_config

        dispatcher.plugin._guard()  # pylint: disable=protected-access
        protocol = registry.describe_driver_protocol("mcp")
        profile = load_config().agents.profiles.get(workspace.agent_id)
        if (
            protocol is None
            or not protocol.active
            or protocol.plugin_id != dispatcher.app_id
            or protocol.generation != dispatcher.generation
            or not dispatcher.admitted()
            or not workspace_is_current(registry, workspace)
            or getattr(manager, "_closing", False)
            or id(workspace) in getattr(manager, "_agent_stop_tasks", {})
            or workspace.agent_id
            in getattr(manager, "_uninstalling_agents", ())
            or profile is None
            or not profile.enabled
        ):
            raise StaleContextError("OAuth source changed")

    async def publish():
        cleanup_failure = None
        async with _oauth_publication(manager, dispatcher):
            try:
                await commit_credential_binding(
                    service.card_store,
                    service.credential_store,
                    expected_card=card,
                    expected_credentials=expected,
                    candidate_card=candidate,
                    candidate_record=remainder,
                    guard=guard,
                    clear_secrets=clear_secrets,
                    require_unshared={
                        mcp_oauth_credential_ref(client_key),
                        *(ref.ref for ref in card.credentials.values()),
                    },
                )
            except CredentialCleanupError as exc:
                cleanup_failure = exc
            except (DriverCardError, StaleContextError, SDKAccessError) as exc:
                raise HTTPException(
                    409,
                    "OAuth source changed or the credential is shared",
                ) from exc
            grants = _ledger(request)
            for key, attempt in attempts(request).items():
                overlay = attempt.overlay
                if (
                    attempt.phase == "pending"
                    and overlay.workspace_id == workspace.agent_id
                    and overlay.card.name == client_key
                ):
                    attempt.finish("failed", time.monotonic())
                    grants.pop(key, None)
        if candidate != card:
            await service.reload_driver_best_effort(client_key)
        if cleanup_failure:
            logger.warning(
                "MCP OAuth token cleanup failed for source %r in workspace %r: %s",
                client_key,
                workspace.agent_id,
                driver_error_diagnostic(cleanup_failure),
            )
            raise HTTPException(
                500,
                "OAuth tokens could not be cleared; retry revoke",
            ) from cleanup_failure

    await run_async_to_completion(publish())
    return {"message": "OAuth tokens cleared"}


async def _detach_oauth(service, card, expected):
    alias = mcp_oauth_alias(card)
    if alias is None:
        if any(
            ref.kind == CREDENTIAL_KIND_OAUTH_AUTH_CODE
            for ref in card.credentials.values()
        ):
            raise HTTPException(409, "OAuth source has ambiguous bindings")
        return card, None
    # Legacy cards can reference unrelated secrets from the OAuth record.
    remainder_alias = (
        CREDENTIAL_ALIAS_STATIC
        if CREDENTIAL_ALIAS_STATIC not in card.credentials
        else f"static-{uuid4().hex}"
    )
    candidate = detach_mcp_oauth_credential(
        card,
        alias,
        remainder_alias=remainder_alias,
    )
    fields = {
        spec["field"]
        for section in ("headers", "env")
        for spec in (candidate.endpoint.get(section) or {}).values()
        if isinstance(spec, dict) and spec.get("credential") == remainder_alias
    }
    if not fields:
        return candidate, None
    ref = card.credentials[alias].ref
    try:
        record, revision = await service.credential_store.get_versioned(ref)
    except CredentialNotFoundError as exc:
        raise HTTPException(409, "OAuth credential is missing") from exc
    if expected.setdefault(ref, revision) != revision:
        raise HTTPException(409, "OAuth credential changed")
    remainder = versioned_static_credential(
        CredentialRecord(
            ref="",
            kind=CREDENTIAL_KIND_STATIC,
            secrets={
                field: record.secrets[field]
                for field in fields
                if field in record.secrets
            },
        ),
        card.name,
    )
    return (
        replace(
            candidate,
            credentials={
                **candidate.credentials,
                remainder_alias: CredentialRef(remainder.kind, remainder.ref),
            },
        ),
        remainder,
    )


async def saved_status(request, client_key, session_id=None):
    """Present saved OAuth metadata without admitting a runtime workspace."""
    require_runtime(request)
    workspace = await configuration_workspace(request)
    service = DriverConfigService(workspace)
    card = await service.load_card(client_key, protocol="mcp")
    record, can_revoke = await saved_oauth_records(service, card)
    result = {"authorized": False, "expires_at": 0.0, "scope": ""}
    if record is not None and record.secrets.get("access_token"):
        expiry = float(record.public.get("expires_at") or 0)
        result = {
            "authorized": expiry <= 0 or expiry > time.time(),
            "expires_at": expiry,
            "scope": str(record.public.get("scope") or ""),
        }
    if can_revoke:
        result["can_revoke"] = True
    if session_id is not None:
        _ledger(request)
        attempt = attempts(request).get(session_id)
        if attempt is not None:
            overlay = attempt.overlay
            if (
                overlay.workspace_id != workspace.agent_id
                or overlay.card.name != client_key
                or overlay.user_id
                != str(getattr(request.state, "user", None) or "default")
                or overlay.channel != "console"
            ):
                raise HTTPException(403, "OAuth session is unavailable")
        result["attempt_status"] = attempt.phase if attempt else "expired"
    return result
