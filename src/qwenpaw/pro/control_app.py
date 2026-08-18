# -*- coding: utf-8 -*-
"""FastAPI control plane and server entry point for QwenPaw Pro."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Request
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

from ..constant import WORKING_DIR
from ..utils.http import is_loopback_host
from .auth import ProAuthService, ProUser
from .config import ProConfig, ProConfigStore
from .credentials import TenantCredentialVault
from .local_driver import LocalProcessRuntimeDriver
from .models import RuntimeRecord, RuntimeSpec, RuntimeState
from .registry import RuntimeRegistry
from .service import RuntimeService


class RuntimeCreateBody(BaseModel):
    """Request body for a new managed runtime."""

    runtime_id: str = Field(min_length=1, max_length=64)
    driver: str | None = None
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


def get_pro_root() -> Path:
    """Resolve the Pro data root without changing ordinary App paths."""
    configured = os.environ.get("QWENPAW_PRO_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (WORKING_DIR / "pro").resolve()


def build_runtime_service(
    root_dir: Path | None = None,
    pro_config: ProConfig | None = None,
) -> RuntimeService:
    """Build the local service through deployment-neutral interfaces."""
    resolved_root = (root_dir or get_pro_root()).resolve()
    registry = RuntimeRegistry(resolved_root / "control.db")
    credential_vault = TenantCredentialVault(
        registry.database_path,
        resolved_root / "secrets" / ".vault_key",
    )
    local_driver = LocalProcessRuntimeDriver()

    def runtime_environment(record: Any) -> dict[str, str]:
        environment = credential_vault.resolve_environment(
            tenant_id=record.tenant_id,
            runtime_id=record.runtime_id,
        )
        environment[
            "QWENPAW_PRO_INTERNAL_TOKEN"
        ] = credential_vault.get_or_create_runtime_secret(
            tenant_id=record.tenant_id,
            runtime_id=record.runtime_id,
            name="QWENPAW_PRO_INTERNAL_TOKEN",
        )
        return environment

    return RuntimeService(
        root_dir=resolved_root,
        registry=registry,
        drivers={local_driver.name: local_driver},
        credential_provider=runtime_environment,
        pro_config=pro_config,
    )


def create_pro_app(  # pylint: disable=too-many-statements
    service: RuntimeService | None = None,
    auth_service: ProAuthService | None = None,
    proxy_transport: httpx.AsyncBaseTransport | None = None,
    pro_config: ProConfig | None = None,
    root_dir: Path | None = None,
) -> FastAPI:
    """Create a Pro control-plane app with an injectable runtime service."""
    runtime_service = service or build_runtime_service(
        root_dir=root_dir,
        pro_config=pro_config,
    )
    effective_config = pro_config or runtime_service.pro_config
    credential_vault = TenantCredentialVault(
        runtime_service.registry.database_path,
        runtime_service.root_dir / "secrets" / ".vault_key",
    )
    pro_auth = auth_service or ProAuthService(
        runtime_service.registry.database_path,
        credential_vault,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await run_in_threadpool(runtime_service.close)

    app = FastAPI(title="QwenPaw Pro", lifespan=lifespan)
    app.state.runtime_service = runtime_service
    app.state.auth_service = pro_auth
    app.state.pro_config = effective_config

    def require_user(
        authorization: str | None = Header(default=None),
    ) -> ProUser:
        prefix = "Bearer "
        token = (
            authorization[len(prefix) :]
            if authorization and authorization.startswith(prefix)
            else ""
        )
        user = pro_auth.verify_token(token) if token else None
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        return user

    def require_admin(user: ProUser = Depends(require_user)) -> ProUser:
        if not user.is_admin:
            raise HTTPException(
                status_code=403,
                detail="Administrator permission required",
            )
        return user

    def require_runtime_access(runtime_id: str, user: ProUser) -> None:
        try:
            record = runtime_service.get(runtime_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Runtime not found",
            ) from exc
        if not user.is_admin and record.owner_user_id != user.user_id:
            raise HTTPException(status_code=404, detail="Runtime not found")

    def personal_tenant_id(user: ProUser) -> str:
        return f"personal-{user.user_id}"

    async def ensure_personal_runtime(user: ProUser) -> RuntimeRecord:
        records = await run_in_threadpool(
            runtime_service.list,
            user.user_id,
        )
        preferred = next(
            (
                record
                for record in records
                if record.metadata.get("pro_default") is True
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
                        metadata={"pro_default": True},
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

    def validate_credential_scope(scope: str, user: ProUser) -> None:
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

    @app.get("/api/pro/healthz")
    async def healthz() -> dict[str, Any]:
        security_levels = {
            name: driver.security_level
            for name, driver in runtime_service.drivers.items()
        }
        return {
            "status": "ok",
            "mode": "pro",
            "security_levels": security_levels,
            "drivers": sorted(runtime_service.drivers),
        }

    @app.get("/api/auth/status")
    async def auth_status() -> dict[str, object]:
        return pro_auth.status()

    @app.post("/api/auth/register")
    async def register(body: CredentialsBody) -> dict[str, object]:
        try:
            user, token = await run_in_threadpool(
                pro_auth.register,
                body.username,
                body.password,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "token": token,
            "username": user.username,
            "user": user.to_dict(),
        }

    @app.post("/api/auth/login")
    async def login(body: CredentialsBody) -> dict[str, object]:
        try:
            user, token = await run_in_threadpool(
                pro_auth.authenticate,
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
        user: ProUser = Depends(require_user),
    ) -> dict[str, object]:
        return {
            "valid": True,
            "username": user.username,
            "user": user.to_dict(),
        }

    @app.get("/api/pro/me")
    async def current_identity(
        user: ProUser = Depends(require_user),
    ) -> dict[str, object]:
        return user.to_dict()

    @app.get("/api/pro/admin/users")
    async def list_users(
        _: ProUser = Depends(require_admin),
    ) -> list[dict[str, object]]:
        users = await run_in_threadpool(pro_auth.list_users)
        return [user.to_dict() for user in users]

    @app.post("/api/pro/admin/users", status_code=201)
    async def create_user(
        body: AdminUserCreateBody,
        _: ProUser = Depends(require_admin),
    ) -> dict[str, object]:
        try:
            user = await run_in_threadpool(
                pro_auth.create_user,
                username=body.username,
                password=body.password,
                role=body.role,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return user.to_dict()

    @app.patch("/api/pro/admin/users/{user_id}")
    async def patch_user(
        user_id: str,
        body: AdminUserPatchBody,
        _: ProUser = Depends(require_admin),
    ) -> dict[str, object]:
        try:
            user = await run_in_threadpool(
                pro_auth.update_user,
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
        return user.to_dict()

    @app.get("/api/pro/admin/settings/registration")
    async def get_registration_settings(
        _: ProUser = Depends(require_admin),
    ) -> dict[str, object]:
        return await run_in_threadpool(pro_auth.registration_setting)

    @app.put("/api/pro/admin/settings/registration")
    async def update_registration_settings(
        body: RegistrationSettingsBody,
        _: ProUser = Depends(require_admin),
    ) -> dict[str, object]:
        await run_in_threadpool(
            pro_auth.set_registration_enabled,
            body.enabled,
        )
        return await run_in_threadpool(pro_auth.registration_setting)

    @app.get("/api/pro/credentials")
    async def list_credentials(
        user: ProUser = Depends(require_user),
    ) -> list[dict[str, str]]:
        return await run_in_threadpool(
            credential_vault.list_metadata,
            tenant_id=personal_tenant_id(user),
        )

    @app.put("/api/pro/credentials", status_code=204)
    async def put_credential(
        body: CredentialBody,
        user: ProUser = Depends(require_user),
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

    @app.delete("/api/pro/credentials/{scope}/{name}", status_code=204)
    async def delete_credential(
        scope: str,
        name: str,
        user: ProUser = Depends(require_user),
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

    @app.get("/api/pro/runtimes")
    async def list_runtimes(
        user: ProUser = Depends(require_user),
    ) -> list[dict[str, Any]]:
        owner_user_id = None if user.is_admin else user.user_id
        records = await run_in_threadpool(
            runtime_service.list,
            owner_user_id,
        )
        return [
            _runtime_payload(runtime_service, record) for record in records
        ]

    @app.post("/api/pro/runtimes", status_code=201)
    async def create_runtime(
        body: RuntimeCreateBody,
        user: ProUser = Depends(require_user),
    ) -> dict[str, Any]:
        try:
            record = await run_in_threadpool(
                runtime_service.create,
                RuntimeSpec(
                    runtime_id=body.runtime_id,
                    tenant_id=personal_tenant_id(user),
                    owner_user_id=user.user_id,
                    driver=body.driver,
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
            return _runtime_payload(runtime_service, record)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/pro/runtimes/{runtime_id}")
    async def get_runtime(
        runtime_id: str,
        user: ProUser = Depends(require_user),
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
        return _runtime_payload(runtime_service, record)

    @app.post("/api/pro/runtimes/{runtime_id}/start")
    async def start_runtime(
        runtime_id: str,
        user: ProUser = Depends(require_user),
    ) -> dict[str, Any]:
        require_runtime_access(runtime_id, user)
        try:
            record = await run_in_threadpool(
                runtime_service.start,
                runtime_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Runtime not found",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return _runtime_payload(runtime_service, record)

    @app.post("/api/pro/runtimes/{runtime_id}/stop")
    async def stop_runtime(
        runtime_id: str,
        user: ProUser = Depends(require_user),
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
        return _runtime_payload(runtime_service, record)

    @app.delete("/api/pro/runtimes/{runtime_id}", status_code=204)
    async def delete_runtime(
        runtime_id: str,
        user: ProUser = Depends(require_user),
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

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        include_in_schema=False,
    )
    async def personal_runtime_proxy(
        path: str,
        request: Request,
        user: ProUser = Depends(require_user),
    ) -> Response:
        record = await ensure_personal_runtime(user)
        internal_token = await run_in_threadpool(
            credential_vault.get,
            tenant_id=record.tenant_id,
            scope=f"runtime:{record.runtime_id}",
            name="QWENPAW_PRO_INTERNAL_TOKEN",
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
        }
        headers = {
            name: value
            for name, value in request.headers.items()
            if name.lower() not in excluded_request_headers
        }
        headers["X-QwenPaw-Pro-Runtime-Token"] = internal_token
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
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def pro_console(path: str) -> Response:
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
                    "QwenPaw Pro is running, but Console assets are "
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
) -> dict[str, Any]:
    payload = record.to_dict()
    payload["endpoint"] = f"http://{record.host}:{record.port}"
    payload["security_level"] = service.security_level(record.driver)
    return payload


def run_pro_app(
    *,
    host: str,
    port: int,
    log_level: str,
    config_path: Path | None = None,
) -> None:
    """Run the local-only QwenPaw Pro control plane."""
    if not is_loopback_host(host):
        raise ValueError(
            f"QwenPaw Pro local mode only supports a loopback host: {host}",
        )
    root_dir = get_pro_root()
    pro_config = ProConfigStore(
        root_dir / "control.db",
    ).resolve(config_path, available_drivers={"local"})
    uvicorn.run(
        create_pro_app(pro_config=pro_config, root_dir=root_dir),
        host=host,
        port=port,
        workers=1,
        log_level=log_level,
        timeout_graceful_shutdown=10,
    )
