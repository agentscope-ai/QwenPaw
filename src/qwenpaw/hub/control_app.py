# -*- coding: utf-8 -*-
"""FastAPI control plane and server entry point for QwenPaw Hub."""

from __future__ import annotations

import logging
import mimetypes
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

from ..__version__ import __version__
from ..constant import WORKING_DIR
from ..utils.http import is_loopback_host
from ..utils.oauth_callback import HUB_OAUTH_CALLBACK_URL_HEADER
from .auth import HubAuthService, HubUser
from .config import HubConfig, HubConfigStore
from .credentials import TenantCredentialVault
from .provisioner import RuntimeProvisionerUnavailableError
from .local_provisioner import LocalProcessRuntimeProvisioner
from .models import RuntimeRecord, RuntimeSpec, RuntimeState
from .oauth_relay import OAuthRelayStore
from .operations import HubOperationsStore
from .registry import RuntimeRegistry
from .service import RuntimeService

_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"


def _accepted_asset_encodings(scope: Scope) -> list[tuple[str, str]]:
    headers = {name.lower(): value for name, value in scope.get("headers", [])}
    raw = headers.get(b"accept-encoding", b"").decode(
        "latin-1",
    )
    quality_by_name: dict[str, float] = {}
    for item in raw.split(","):
        parts = [part.strip() for part in item.split(";")]
        name = parts[0].lower()
        quality = 1.0
        for parameter in parts[1:]:
            if parameter.startswith("q="):
                try:
                    quality = float(parameter[2:])
                except ValueError:
                    quality = 0.0
        quality_by_name[name] = quality
    wildcard_quality = quality_by_name.get("*", 0.0)
    supported = [("br", ".br"), ("gzip", ".gz")]
    candidates = [
        (quality_by_name.get(name, wildcard_quality), index, name, suffix)
        for index, (name, suffix) in enumerate(supported)
        if quality_by_name.get(name, wildcard_quality) > 0
    ]
    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [(name, suffix) for _, _, name, suffix in candidates]


class CompressedStaticFiles(StaticFiles):
    """Serve precompressed hashed assets with production cache headers."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Negotiate Brotli or gzip while retaining identity fallback."""
        for encoding, suffix in _accepted_asset_encodings(scope):
            try:
                response = await super().get_response(
                    f"{path}{suffix}",
                    scope,
                )
            except StarletteHTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            if response.status_code == 404:
                continue
            media_type, _ = mimetypes.guess_type(path)
            if media_type:
                response.headers["Content-Type"] = media_type
            response.headers["Content-Encoding"] = encoding
            response.headers["Vary"] = "Accept-Encoding"
            response.headers["Cache-Control"] = _ASSET_CACHE_CONTROL
            return response
        response = await super().get_response(path, scope)
        response.headers["Vary"] = "Accept-Encoding"
        response.headers["Cache-Control"] = _ASSET_CACHE_CONTROL
        return response


class RuntimeCreateBody(BaseModel):
    """Request body for a new managed runtime."""

    runtime_id: str = Field(min_length=1, max_length=64)
    provisioner: str | None = None
    host: str = "127.0.0.1"
    port: int = Field(default=0, ge=0, le=65535)
    metadata: dict[str, Any] = Field(default_factory=dict)
    auto_start: bool = False


class CredentialsBody(BaseModel):
    """Login or bootstrap registration credentials."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8, max_length=1024)


class AdminUserCreateBody(CredentialsBody):
    """Administrator request for a managed account."""

    role: str = "user"


class AdminUserPatchBody(BaseModel):
    """Administrator changes that invalidate existing user tokens."""

    role: str | None = None
    disabled: bool | None = None


class RegistrationSettingsBody(BaseModel):
    """Public registration policy update."""

    enabled: bool


class CredentialBody(BaseModel):
    """Tenant-scoped credential write without a plaintext read endpoint."""

    scope: str = "tenant"
    name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1, max_length=65536)


_PROVIDER_OAUTH_START = re.compile(
    r"^providers/(?P<provider_id>[A-Za-z0-9_.-]+)/oauth/start$",
)
_MCP_OAUTH_START = re.compile(
    r"^(?:agents/[^/]+/)?mcp/oauth/start/[^/].*$",
)


def _oauth_callback_path(method: str, path: str) -> str | None:
    """Map a managed OAuth start request to its fixed callback path."""
    if method != "POST":
        return None
    provider_match = _PROVIDER_OAUTH_START.fullmatch(path)
    if provider_match:
        provider_id = provider_match.group("provider_id")
        return f"/api/providers/{provider_id}/oauth/callback"
    if _MCP_OAUTH_START.fullmatch(path):
        return "/api/mcp/oauth/callback"
    return None


def get_hub_root() -> Path:
    """Resolve the Hub data root without changing ordinary App paths."""
    configured = os.environ.get("QWENPAW_HUB_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (WORKING_DIR / "hub").resolve()


def build_runtime_service(
    root_dir: Path | None = None,
    hub_config: HubConfig | None = None,
) -> RuntimeService:
    """Build the local service through deployment-neutral interfaces."""
    resolved_root = (root_dir or get_hub_root()).resolve()
    registry = RuntimeRegistry(resolved_root / "control.db")
    credential_vault = TenantCredentialVault(
        registry.database_path,
        resolved_root / "secrets" / ".vault_key",
    )
    local_provisioner = LocalProcessRuntimeProvisioner()

    def runtime_environment(record: Any) -> dict[str, str]:
        environment = credential_vault.resolve_environment(
            tenant_id=record.tenant_id,
            runtime_id=record.runtime_id,
        )
        environment[
            "QWENPAW_RUNTIME_INTERNAL_TOKEN"
        ] = credential_vault.get_or_create_runtime_secret(
            tenant_id=record.tenant_id,
            runtime_id=record.runtime_id,
            name="QWENPAW_RUNTIME_INTERNAL_TOKEN",
        )
        return environment

    return RuntimeService(
        root_dir=resolved_root,
        registry=registry,
        provisioners={local_provisioner.name: local_provisioner},
        credential_provider=runtime_environment,
        hub_config=hub_config,
    )


def create_hub_app(  # pylint: disable=too-many-statements
    service: RuntimeService | None = None,
    auth_service: HubAuthService | None = None,
    proxy_transport: httpx.AsyncBaseTransport | None = None,
    hub_config: HubConfig | None = None,
    root_dir: Path | None = None,
) -> FastAPI:
    """Create a Hub control-plane app with an injectable runtime service."""
    runtime_service = service or build_runtime_service(
        root_dir=root_dir,
        hub_config=hub_config,
    )
    effective_config = hub_config or runtime_service.hub_config
    credential_vault = TenantCredentialVault(
        runtime_service.registry.database_path,
        runtime_service.root_dir / "secrets" / ".vault_key",
    )
    hub_auth = auth_service or HubAuthService(
        runtime_service.registry.database_path,
        credential_vault,
    )
    operations = HubOperationsStore(
        runtime_service.registry.database_path,
        runtime_service.root_dir,
    )

    async def runtime_payload(record: Any) -> dict[str, Any]:
        owner = await run_in_threadpool(
            hub_auth.get_user,
            record.owner_user_id,
        )
        return _runtime_payload(
            runtime_service,
            record,
            owner_username=owner.username if owner else None,
        )

    async def runtime_payloads(records: list[Any]) -> list[dict[str, Any]]:
        owner_usernames = await run_in_threadpool(
            hub_auth.get_usernames,
            {record.owner_user_id for record in records},
        )
        return [
            _runtime_payload(
                runtime_service,
                record,
                owner_username=owner_usernames.get(record.owner_user_id),
            )
            for record in records
        ]

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await run_in_threadpool(runtime_service.close)

    app = FastAPI(title="QwenPaw Hub", lifespan=lifespan)
    app.state.runtime_service = runtime_service
    app.state.auth_service = hub_auth
    app.state.hub_config = effective_config
    app.state.operations = operations
    oauth_relays = OAuthRelayStore()
    app.state.oauth_relays = oauth_relays

    def require_user(
        authorization: str | None = Header(default=None),
    ) -> HubUser:
        prefix = "Bearer "
        token = (
            authorization[len(prefix) :]
            if authorization and authorization.startswith(prefix)
            else ""
        )
        user = hub_auth.verify_token(token) if token else None
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return user

    def require_admin(user: HubUser = Depends(require_user)) -> HubUser:
        if not user.is_admin:
            raise HTTPException(
                status_code=403,
                detail="Administrator permission required",
            )
        return user

    def require_runtime_access(runtime_id: str, user: HubUser) -> None:
        try:
            record = runtime_service.get(runtime_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Runtime not found",
            ) from exc
        if not user.is_admin and record.owner_user_id != user.user_id:
            raise HTTPException(status_code=404, detail="Runtime not found")

    def personal_tenant_id(user: HubUser) -> str:
        return f"personal-{user.user_id}"

    async def record_audit(
        user: HubUser,
        action: str,
        resource_type: str,
        resource_id: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        await run_in_threadpool(
            operations.record,
            actor_user_id=user.user_id,
            actor_username=user.username,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
        )

    async def ensure_personal_runtime(user: HubUser) -> RuntimeRecord:
        try:
            runtime_service.require_provisioner_available(
                runtime_service.default_provisioner,
            )
        except RuntimeProvisionerUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        records = await run_in_threadpool(
            runtime_service.list,
            user.user_id,
        )
        preferred = next(
            (
                record
                for record in records
                if record.metadata.get("hub_default") is True
            ),
            None,
        )
        record = preferred or (records[0] if records else None)
        if record is None:
            runtime_id = f"personal-{user.user_id[:24]}"
            try:
                record = await run_in_threadpool(
                    runtime_service.create,
                    RuntimeSpec(
                        runtime_id=runtime_id,
                        tenant_id=personal_tenant_id(user),
                        owner_user_id=user.user_id,
                        metadata={"hub_default": True},
                    ),
                )
            except ValueError as exc:
                record = await run_in_threadpool(
                    runtime_service.get,
                    runtime_id,
                )
                if record.owner_user_id != user.user_id:
                    raise HTTPException(
                        status_code=409,
                        detail="Personal runtime ID is unavailable",
                    ) from exc
        if record.state is not RuntimeState.RUNNING:
            try:
                record = await run_in_threadpool(
                    runtime_service.start,
                    record.runtime_id,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=503,
                    detail=f"Personal QwenPaw failed to start: {exc}",
                ) from exc
        return record

    def validate_credential_scope(scope: str, user: HubUser) -> None:
        if scope == "tenant":
            return
        prefix = "runtime:"
        if not scope.startswith(prefix):
            raise HTTPException(
                status_code=400,
                detail="Invalid credential scope",
            )
        runtime_id = scope[len(prefix) :]
        try:
            record = runtime_service.get(runtime_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Runtime not found",
            ) from exc
        if record.owner_user_id != user.user_id:
            raise HTTPException(status_code=404, detail="Runtime not found")

    @app.get("/api/hub/healthz")
    async def healthz(
        _: HubUser = Depends(require_user),
    ) -> dict[str, Any]:
        security_levels = {
            name: provisioner.security_level
            for name, provisioner in runtime_service.provisioners.items()
        }
        return {
            "status": (
                "ok" if runtime_service.runtime_available() else "degraded"
            ),
            "mode": "hub",
            "security_levels": security_levels,
            "provisioners": sorted(runtime_service.provisioners),
            "provisioner_statuses": runtime_service.provisioner_statuses(),
            "default_provisioner": runtime_service.default_provisioner,
            "runtime_available": runtime_service.runtime_available(),
        }

    @app.get("/api/version")
    async def version() -> dict[str, str]:
        """Return a public-safe control-plane readiness payload."""
        return {"version": __version__}

    @app.get("/api/auth/status")
    async def auth_status() -> dict[str, object]:
        return hub_auth.status()

    @app.post("/api/auth/register")
    async def register(body: CredentialsBody) -> dict[str, object]:
        try:
            user, token = await run_in_threadpool(
                hub_auth.register,
                body.username,
                body.password,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await record_audit(
            user,
            "auth.register",
            "user",
            user.user_id,
            {"role": user.role},
        )
        return {
            "token": token,
            "username": user.username,
            "user": user.to_dict(),
        }

    @app.post("/api/auth/login")
    async def login(body: CredentialsBody) -> dict[str, object]:
        try:
            user, token = await run_in_threadpool(
                hub_auth.authenticate,
                body.username,
                body.password,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        return {
            "token": token,
            "username": user.username,
            "user": user.to_dict(),
        }

    @app.get("/api/auth/verify")
    async def verify(
        user: HubUser = Depends(require_user),
    ) -> dict[str, object]:
        return {
            "valid": True,
            "username": user.username,
            "user": user.to_dict(),
        }

    @app.get("/api/hub/me")
    async def current_identity(
        user: HubUser = Depends(require_user),
    ) -> dict[str, object]:
        return user.to_dict()

    @app.get("/api/hub/admin/users")
    async def list_users(
        _: HubUser = Depends(require_admin),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        query: str | None = Query(default=None, alias="q", max_length=128),
        role: str | None = Query(default=None),
        disabled: bool | None = Query(default=None),
    ) -> dict[str, object]:
        try:
            users, total = await run_in_threadpool(
                hub_auth.list_users_page,
                page=page,
                page_size=page_size,
                query=query,
                role=role,
                disabled=disabled,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _page_payload(
            [listed_user.to_dict() for listed_user in users],
            page,
            page_size,
            total,
        )

    @app.post("/api/hub/admin/users", status_code=201)
    async def create_user(
        body: AdminUserCreateBody,
        admin: HubUser = Depends(require_admin),
    ) -> dict[str, object]:
        try:
            user = await run_in_threadpool(
                hub_auth.create_user,
                username=body.username,
                password=body.password,
                role=body.role,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await record_audit(
            admin,
            "user.create",
            "user",
            user.user_id,
            {"role": user.role, "username": user.username},
        )
        return user.to_dict()

    @app.patch("/api/hub/admin/users/{user_id}")
    async def patch_user(
        user_id: str,
        body: AdminUserPatchBody,
        admin: HubUser = Depends(require_admin),
    ) -> dict[str, object]:
        try:
            user = await run_in_threadpool(
                hub_auth.update_user,
                user_id,
                role=body.role,
                disabled=body.disabled,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="User not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await record_audit(
            admin,
            "user.update",
            "user",
            user_id,
            {"disabled": user.disabled, "role": user.role},
        )
        return user.to_dict()

    @app.get("/api/hub/admin/settings/registration")
    async def get_registration_settings(
        _: HubUser = Depends(require_admin),
    ) -> dict[str, object]:
        return await run_in_threadpool(hub_auth.registration_setting)

    @app.put("/api/hub/admin/settings/registration")
    async def update_registration_settings(
        body: RegistrationSettingsBody,
        admin: HubUser = Depends(require_admin),
    ) -> dict[str, object]:
        await run_in_threadpool(
            hub_auth.set_registration_enabled,
            body.enabled,
        )
        await record_audit(
            admin,
            "settings.registration.update",
            "setting",
            "registration_enabled",
            {"enabled": body.enabled},
        )
        return await run_in_threadpool(hub_auth.registration_setting)

    @app.get("/api/hub/credentials")
    async def list_credentials(
        user: HubUser = Depends(require_user),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        query: str | None = Query(default=None, alias="q", max_length=128),
        scope: str | None = Query(default=None, max_length=128),
    ) -> dict[str, object]:
        items, total = await run_in_threadpool(
            credential_vault.list_metadata_page,
            tenant_id=personal_tenant_id(user),
            page=page,
            page_size=page_size,
            query=query,
            scope=scope,
        )
        return _page_payload(
            items,
            page,
            page_size,
            total,
        )

    @app.put("/api/hub/credentials", status_code=204)
    async def put_credential(
        body: CredentialBody,
        user: HubUser = Depends(require_user),
    ) -> None:
        validate_credential_scope(body.scope, user)
        try:
            await run_in_threadpool(
                credential_vault.put,
                tenant_id=personal_tenant_id(user),
                scope=body.scope,
                name=body.name,
                value=body.value,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await record_audit(
            user,
            "credential.store",
            "credential",
            f"{body.scope}:{body.name}",
        )

    @app.delete("/api/hub/credentials/{scope}/{name}", status_code=204)
    async def delete_credential(
        scope: str,
        name: str,
        user: HubUser = Depends(require_user),
    ) -> None:
        validate_credential_scope(scope, user)
        try:
            await run_in_threadpool(
                credential_vault.delete,
                tenant_id=personal_tenant_id(user),
                scope=scope,
                name=name,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Credential not found",
            ) from exc
        await record_audit(
            user,
            "credential.delete",
            "credential",
            f"{scope}:{name}",
        )

    @app.get("/api/hub/runtimes")
    async def list_runtimes(
        user: HubUser = Depends(require_user),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        query: str | None = Query(default=None, alias="q", max_length=128),
        state: RuntimeState | None = Query(default=None),
        provisioner: str | None = Query(default=None, max_length=64),
        owner: str | None = Query(default=None, max_length=128),
    ) -> dict[str, object]:
        owner_user_id = None if user.is_admin else user.user_id
        records, total = await run_in_threadpool(
            runtime_service.list_page,
            page=page,
            page_size=page_size,
            owner_user_id=owner_user_id,
            query=query,
            state=state,
            provisioner=provisioner,
            owner=owner if user.is_admin else None,
        )
        items = await runtime_payloads(records)
        return _page_payload(items, page, page_size, total)

    @app.post("/api/hub/runtimes", status_code=201)
    async def create_runtime(
        body: RuntimeCreateBody,
        user: HubUser = Depends(require_user),
    ) -> dict[str, Any]:
        try:
            record = await run_in_threadpool(
                runtime_service.create,
                RuntimeSpec(
                    runtime_id=body.runtime_id,
                    tenant_id=personal_tenant_id(user),
                    owner_user_id=user.user_id,
                    provisioner=body.provisioner,
                    host=body.host,
                    port=body.port,
                    metadata=body.metadata,
                ),
            )
            if body.auto_start:
                record = await run_in_threadpool(
                    runtime_service.start,
                    body.runtime_id,
                )
            await record_audit(
                user,
                "runtime.create",
                "runtime",
                record.runtime_id,
                {
                    "auto_start": body.auto_start,
                    "provisioner": record.provisioner,
                },
            )
            return await runtime_payload(record)
        except RuntimeProvisionerUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/hub/runtimes/{runtime_id}")
    async def get_runtime(
        runtime_id: str,
        user: HubUser = Depends(require_user),
    ) -> dict[str, Any]:
        require_runtime_access(runtime_id, user)
        try:
            record = await run_in_threadpool(
                runtime_service.status,
                runtime_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Runtime not found",
            ) from exc
        return await runtime_payload(record)

    @app.post("/api/hub/runtimes/{runtime_id}/start")
    async def start_runtime(
        runtime_id: str,
        user: HubUser = Depends(require_user),
    ) -> dict[str, Any]:
        require_runtime_access(runtime_id, user)
        try:
            record = await run_in_threadpool(
                runtime_service.start,
                runtime_id,
            )
        except RuntimeProvisionerUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Runtime not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        await record_audit(
            user,
            "runtime.start",
            "runtime",
            runtime_id,
        )
        return await runtime_payload(record)

    @app.post("/api/hub/runtimes/{runtime_id}/stop")
    async def stop_runtime(
        runtime_id: str,
        user: HubUser = Depends(require_user),
    ) -> dict[str, Any]:
        require_runtime_access(runtime_id, user)
        try:
            record = await run_in_threadpool(
                runtime_service.stop,
                runtime_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Runtime not found",
            ) from exc
        await record_audit(
            user,
            "runtime.stop",
            "runtime",
            runtime_id,
        )
        return await runtime_payload(record)

    @app.delete("/api/hub/runtimes/{runtime_id}", status_code=204)
    async def delete_runtime(
        runtime_id: str,
        user: HubUser = Depends(require_user),
    ) -> None:
        require_runtime_access(runtime_id, user)
        try:
            await run_in_threadpool(runtime_service.delete, runtime_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Runtime not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        await record_audit(
            user,
            "runtime.delete",
            "runtime",
            runtime_id,
        )

    @app.get("/api/hub/admin/overview")
    async def operations_overview(
        _: HubUser = Depends(require_admin),
    ) -> dict[str, object]:
        runtime_counts = await run_in_threadpool(
            runtime_service.registry.count_by_state,
        )
        host = await run_in_threadpool(operations.host_metrics)
        recent_events, _ = await run_in_threadpool(
            operations.list_events,
            page=1,
            page_size=5,
        )
        return {
            "runtime_counts": runtime_counts,
            "total_runtimes": sum(runtime_counts.values()),
            "total_users": await run_in_threadpool(hub_auth.user_count),
            "runtime_available": runtime_service.runtime_available(),
            "host": host,
            "recent_events": recent_events,
        }

    @app.get("/api/hub/admin/audit")
    async def list_audit_events(
        _: HubUser = Depends(require_admin),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        query: str | None = Query(default=None, alias="q", max_length=128),
        action: str | None = Query(default=None, max_length=128),
        outcome: str | None = Query(default=None, max_length=32),
    ) -> dict[str, object]:
        events, total = await run_in_threadpool(
            operations.list_events,
            page=page,
            page_size=page_size,
            query=query,
            action=action,
            outcome=outcome,
        )
        return _page_payload(events, page, page_size, total)

    @app.get(
        "/api/hub/oauth/callback/{relay_token}",
        include_in_schema=False,
    )
    async def oauth_callback_relay(
        relay_token: str,
        request: Request,
    ) -> Response:
        relay = oauth_relays.take(relay_token)
        if relay is None:
            raise HTTPException(
                status_code=404,
                detail="OAuth callback relay is invalid or expired",
            )
        try:
            record = await run_in_threadpool(
                runtime_service.status,
                relay.runtime_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="OAuth callback runtime is unavailable",
            ) from exc
        if record.state != RuntimeState.RUNNING:
            raise HTTPException(
                status_code=503,
                detail="OAuth callback runtime is not running",
            )
        internal_token = await run_in_threadpool(
            credential_vault.get,
            tenant_id=record.tenant_id,
            scope=f"runtime:{record.runtime_id}",
            name="QWENPAW_RUNTIME_INTERNAL_TOKEN",
        )
        if internal_token is None:
            raise HTTPException(
                status_code=503,
                detail="Personal runtime boundary token is unavailable",
            )
        target = httpx.URL(
            f"http://{record.host}:{record.port}{relay.callback_path}",
            query=request.url.query.encode("utf-8"),
        )
        try:
            async with httpx.AsyncClient(
                transport=proxy_transport,
            ) as client:
                upstream = await client.get(
                    target,
                    headers={
                        "X-QwenPaw-Runtime-Token": internal_token,
                    },
                )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Personal QwenPaw is unavailable: {exc}",
            ) from exc
        excluded_headers = {
            "connection",
            "content-length",
            "transfer-encoding",
        }
        response_headers = {
            name: value
            for name, value in upstream.headers.items()
            if name.lower() not in excluded_headers
        }
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=response_headers,
        )

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        include_in_schema=False,
    )
    async def personal_runtime_proxy(
        path: str,
        request: Request,
        user: HubUser = Depends(require_user),
    ) -> Response:
        record = await ensure_personal_runtime(user)
        internal_token = await run_in_threadpool(
            credential_vault.get,
            tenant_id=record.tenant_id,
            scope=f"runtime:{record.runtime_id}",
            name="QWENPAW_RUNTIME_INTERNAL_TOKEN",
        )
        if internal_token is None:
            raise HTTPException(
                status_code=503,
                detail="Personal runtime boundary token is unavailable",
            )

        target = httpx.URL(
            f"http://{record.host}:{record.port}/api/{path}",
            query=request.url.query.encode("utf-8"),
        )
        excluded_request_headers = {
            "authorization",
            "connection",
            "content-length",
            "host",
            HUB_OAUTH_CALLBACK_URL_HEADER.lower(),
        }
        headers = {
            name: value
            for name, value in request.headers.items()
            if name.lower() not in excluded_request_headers
        }
        headers["X-QwenPaw-Runtime-Token"] = internal_token
        callback_path = _oauth_callback_path(request.method, path)
        if callback_path:
            relay_token = oauth_relays.create(
                record.runtime_id,
                callback_path,
            )
            public_base_url = (
                effective_config.control_plane.public_base_url
                or str(request.base_url).rstrip("/")
            )
            headers[
                HUB_OAUTH_CALLBACK_URL_HEADER
            ] = f"{public_base_url}/api/hub/oauth/callback/{relay_token}"
        client = httpx.AsyncClient(
            timeout=None,
            transport=proxy_transport,
        )
        upstream_request = client.build_request(
            request.method,
            target,
            headers=headers,
            content=request.stream(),
        )
        try:
            upstream = await client.send(upstream_request, stream=True)
        except httpx.HTTPError as exc:
            await client.aclose()
            raise HTTPException(
                status_code=502,
                detail=f"Personal QwenPaw is unavailable: {exc}",
            ) from exc

        excluded_response_headers = {
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailers",
            "transfer-encoding",
            "upgrade",
        }
        response_headers = {
            name: value
            for name, value in upstream.headers.items()
            if name.lower() not in excluded_response_headers
        }

        async def close_upstream() -> None:
            await upstream.aclose()
            await client.aclose()

        return StreamingResponse(
            upstream.aiter_raw(),
            status_code=upstream.status_code,
            headers=response_headers,
            background=BackgroundTask(close_upstream),
        )

    static_dir = _resolve_console_static_dir()
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            CompressedStaticFiles(directory=assets_dir),
            name="assets",
        )

    @app.get("/{path:path}", include_in_schema=False)
    async def hub_console(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        index_file = static_dir / "index.html"
        requested = (static_dir / path).resolve()
        if requested.is_file() and static_dir in requested.parents:
            return FileResponse(requested)
        if index_file.is_file():
            return FileResponse(
                index_file,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                },
            )
        return JSONResponse(
            {
                "message": (
                    "QwenPaw Hub is running, but Console assets are "
                    "unavailable. "
                    "Run `npm ci && npm run build` in the console directory."
                ),
            },
        )

    return app


def _resolve_console_static_dir() -> Path:
    configured = os.environ.get("QWENPAW_CONSOLE_STATIC_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    package_root = Path(__file__).resolve().parents[1]
    packaged = package_root / "console"
    if (packaged / "index.html").is_file():
        return packaged
    repository = Path(__file__).resolve().parents[3]
    return repository / "console" / "dist"


def _runtime_payload(
    service: RuntimeService,
    record: Any,
    *,
    owner_username: str | None,
) -> dict[str, Any]:
    payload = record.to_dict()
    payload["owner_username"] = owner_username
    payload["endpoint"] = f"http://{record.host}:{record.port}"
    payload["security_level"] = service.security_level(record.provisioner)
    return payload


def _page_payload(
    items: list[Any],
    page: int,
    page_size: int,
    total: int,
) -> dict[str, object]:
    """Return the shared Hub pagination envelope."""
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def run_hub_app(
    *,
    host: str,
    port: int,
    log_level: str,
    config_path: Path | None = None,
    force_public: bool = False,
) -> None:
    """Run the QwenPaw Hub control plane with safe public-bind defaults."""
    public_bind = not is_loopback_host(host)
    if public_bind and not force_public:
        raise ValueError(
            "QwenPaw Hub refuses a non-loopback host by default. "
            "Use --force-public after initializing an administrator.",
        )
    root_dir = get_hub_root()
    hub_config = HubConfigStore(
        root_dir / "control.db",
    ).resolve(config_path, available_provisioners={"local"})
    if public_bind:
        database_path = root_dir / "control.db"
        credential_vault = TenantCredentialVault(
            database_path,
            root_dir / "secrets" / ".vault_key",
        )
        hub_auth = HubAuthService(database_path, credential_vault)
        if not hub_auth.has_enabled_admin():
            raise ValueError(
                "Public Hub binding requires an initialized, enabled "
                "administrator. Start on loopback first and create the "
                "administrator account.",
            )
        if not hub_config.control_plane.public_base_url:
            raise ValueError(
                "Public Hub binding requires "
                "control_plane.public_base_url in the Hub config.",
            )
        warning = (
            "QwenPaw Hub is accepting network connections at "
            f"{host}:{port}. --force-public does not provide TLS. "
            "Use a trusted network or a TLS reverse proxy."
        )
        logging.getLogger(__name__).warning("%s", warning)
    uvicorn.run(
        create_hub_app(hub_config=hub_config, root_dir=root_dir),
        host=host,
        port=port,
        workers=1,
        log_level=log_level,
        timeout_graceful_shutdown=10,
    )
