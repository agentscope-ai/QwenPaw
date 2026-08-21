# -*- coding: utf-8 -*-
"""FastAPI control plane and server entry point for QwenPaw Hub."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
import uvicorn
from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    WebSocket,
)
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    Response,
    StreamingResponse,
)
from starlette.concurrency import run_in_threadpool

from ..__version__ import __version__
from ..constant import WORKING_DIR
from ..utils.http import is_loopback_host
from ..utils.oauth_callback import HUB_OAUTH_CALLBACK_URL_HEADER
from .access_security import HubAccessSecurity
from .api_models import (
    AdminUserCreateBody,
    AdminUserPatchBody,
    CredentialBody,
    CredentialsBody,
    DockerImagePullBody,
    HubSettingsBody,
    PasswordChangeBody,
    RuntimeCreateBody,
)
from .auth import HubAuthService, HubUser
from .config import HubConfig, HubConfigStore
from .credentials import TenantCredentialVault
from .provisioner import RuntimeProvisionerUnavailableError
from .local_provisioner import LocalProcessRuntimeProvisioner
from .docker_images import DockerImagePullStore
from .docker_provisioner import (
    OFFICIAL_DOCKER_IMAGES,
    OFFICIAL_DOCKER_TAGS,
    DockerRuntimeProvisioner,
)
from .models import (
    RuntimeRecord,
    RuntimeSpec,
    RuntimeStartPolicy,
    RuntimeState,
)
from .operations import HubOperationsStore
from .oauth_routes import oauth_callback_route, runtime_oauth_callback_path
from .proxy_limits import (
    ProxyRequestIdleTimeoutError,
    ProxyRequestTooLargeError,
    limited_request_stream,
    send_with_response_header_timeout,
)
from .registry import RuntimeRegistry
from .service import RuntimeService
from .static_files import (
    CompressedStaticFiles,
    resolve_console_response,
    resolve_console_static_dir,
)
from . import websocket_proxy


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
    docker_provisioner = DockerRuntimeProvisioner(resolved_root)

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
        provisioners={
            local_provisioner.name: local_provisioner,
            docker_provisioner.name: docker_provisioner,
        },
        credential_provider=runtime_environment,
        hub_config=hub_config,
    )


def create_hub_app(  # pylint: disable=too-many-statements
    service: RuntimeService | None = None,
    auth_service: HubAuthService | None = None,
    proxy_transport: httpx.AsyncBaseTransport | None = None,
    hub_config: HubConfig | None = None,
    root_dir: Path | None = None,
    public_bind: bool = False,
) -> FastAPI:
    """Create a Hub control-plane app with an injectable runtime service."""
    runtime_service = service or build_runtime_service(
        root_dir=root_dir,
        hub_config=hub_config,
    )
    config_store = HubConfigStore(runtime_service.registry.database_path)
    effective_config = config_store.ensure(
        hub_config or runtime_service.hub_config,
        available_provisioners=set(runtime_service.provisioners),
    )
    runtime_service.apply_config(effective_config)
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
    access_security = HubAccessSecurity(
        effective_config.control_plane.security,
    )
    docker_provisioner = runtime_service.provisioners.get("docker")
    docker_pulls = (
        DockerImagePullStore(docker_provisioner)
        if isinstance(docker_provisioner, DockerRuntimeProvisioner)
        else None
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
            if docker_pulls is not None:
                await run_in_threadpool(docker_pulls.close)
            await run_in_threadpool(runtime_service.close)

    app = FastAPI(title="QwenPaw Hub", lifespan=lifespan)
    app.state.runtime_service = runtime_service
    app.state.auth_service = hub_auth
    app.state.hub_config = effective_config
    app.state.config_store = config_store
    app.state.operations = operations
    app.state.access_security = access_security
    app.state.docker_pulls = docker_pulls

    def require_loopback_runtime(record: RuntimeRecord) -> None:
        if not is_loopback_host(record.host):
            raise HTTPException(
                status_code=503,
                detail="Managed runtime endpoint must be loopback-only",
            )

    def runtime_url(
        record: RuntimeRecord,
        *,
        scheme: str,
        path: str,
        query: bytes = b"",
    ) -> httpx.URL:
        require_loopback_runtime(record)
        return httpx.URL(
            scheme=scheme,
            host=record.host.strip().strip("[]"),
            port=record.port,
            path=path,
            query=query,
        )

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

    def require_auth_access(request: Request, action: str) -> str:
        client_ip = access_security.client_ip(request)
        if access_security.is_blacklisted(client_ip):
            raise HTTPException(
                status_code=403,
                detail="This IP address is blocked by the Hub administrator.",
            )
        retry_after = access_security.retry_after(action, client_ip)
        if retry_after is not None:
            raise HTTPException(
                status_code=429,
                detail="Too many authentication attempts. Try again later.",
                headers={"Retry-After": str(retry_after)},
            )
        return client_ip

    async def require_runtime_access(
        runtime_id: str,
        user: HubUser,
    ) -> None:
        try:
            record = await run_in_threadpool(
                runtime_service.get,
                runtime_id,
            )
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

    async def personal_runtime(user: HubUser) -> RuntimeRecord:
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
        return record

    async def ensure_personal_runtime(user: HubUser) -> RuntimeRecord:
        record = await personal_runtime(user)
        if record.desired_state is RuntimeState.STOPPED:
            detail = (
                "Personal runtime was disabled by an administrator."
                if record.start_policy is RuntimeStartPolicy.ADMIN_ONLY
                else "Personal runtime is stopped. Restart it to continue."
            )
            raise HTTPException(status_code=423, detail=detail)
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

    async def validate_credential_scope(
        scope: str,
        user: HubUser,
    ) -> None:
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
            record = await run_in_threadpool(
                runtime_service.get,
                runtime_id,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Runtime not found",
            ) from exc
        if record.owner_user_id != user.user_id:
            raise HTTPException(status_code=404, detail="Runtime not found")

    @app.get("/api/hub/healthz")
    async def healthz(
        user: HubUser = Depends(require_user),
    ) -> dict[str, Any]:
        runtime_available = runtime_service.runtime_available()
        record = await personal_runtime(user) if runtime_available else None
        security_levels = {
            name: provisioner.security_level
            for name, provisioner in runtime_service.provisioners.items()
        }
        return {
            "status": ("ok" if runtime_available else "degraded"),
            "mode": "hub",
            "security_levels": security_levels,
            "provisioners": sorted(runtime_service.provisioners),
            "provisioner_statuses": runtime_service.provisioner_statuses(),
            "default_provisioner": runtime_service.default_provisioner,
            "runtime_available": runtime_available,
            "runtime_state": record.state.value if record else None,
            "runtime_desired_state": (
                record.desired_state.value if record else None
            ),
            "runtime_start_policy": (
                record.start_policy.value if record else None
            ),
        }

    @app.get("/api/version")
    async def version() -> dict[str, str]:
        """Return a public-safe control-plane readiness payload."""
        return {"version": __version__}

    @app.get("/api/auth/status")
    async def auth_status() -> dict[str, object]:
        return await run_in_threadpool(hub_auth.status)

    @app.post("/api/auth/register")
    async def register(
        body: CredentialsBody,
        request: Request,
    ) -> dict[str, object]:
        client_ip = require_auth_access(request, "registration")
        access_security.record_attempt("registration", client_ip)
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
    async def login(
        body: CredentialsBody,
        request: Request,
    ) -> dict[str, object]:
        client_ip = require_auth_access(request, "login")
        try:
            user, token = await run_in_threadpool(
                hub_auth.authenticate,
                body.username,
                body.password,
            )
        except PermissionError as exc:
            access_security.record_attempt("login", client_ip)
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        access_security.clear("login", client_ip)
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

    @app.post("/api/hub/me/password")
    async def change_password(
        body: PasswordChangeBody,
        user: HubUser = Depends(require_user),
    ) -> dict[str, object]:
        updated = await run_in_threadpool(
            hub_auth.change_password,
            user.user_id,
            body.new_password,
        )
        await record_audit(
            updated,
            "auth.password_change",
            "user",
            updated.user_id,
        )
        return updated.to_dict()

    @app.post("/api/hub/me/runtime/restart")
    async def restart_own_runtime(
        user: HubUser = Depends(require_user),
    ) -> dict[str, Any]:
        record = await personal_runtime(user)
        try:
            restarted = await run_in_threadpool(
                runtime_service.restart,
                record.runtime_id,
                owner_initiated=True,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=423, detail=str(exc)) from exc
        except RuntimeProvisionerUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503,
                detail=f"Personal QwenPaw failed to restart: {exc}",
            ) from exc
        await record_audit(
            user,
            "runtime.restart",
            "runtime",
            restarted.runtime_id,
        )
        return await runtime_payload(restarted)

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
                actor_user_id=admin.user_id,
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

    @app.get("/api/hub/admin/settings")
    async def get_hub_settings(
        _: HubUser = Depends(require_admin),
    ) -> dict[str, object]:
        config, revision, updated_at = await run_in_threadpool(
            config_store.snapshot,
        )
        config_payload = config.model_dump(mode="json")
        return {
            "config": config_payload,
            "revision": revision,
            "updated_at": updated_at,
            "available_provisioners": sorted(runtime_service.provisioners),
        }

    @app.put("/api/hub/admin/settings")
    async def update_hub_settings(
        body: HubSettingsBody,
        admin: HubUser = Depends(require_admin),
    ) -> dict[str, object]:
        if public_bind and body.config.control_plane.public_base_url is None:
            raise HTTPException(
                status_code=422,
                detail="Public Hub binding requires public_base_url",
            )
        try:
            config, revision, updated_at = await run_in_threadpool(
                config_store.update,
                body.config,
                expected_revision=body.revision,
                available_provisioners=set(runtime_service.provisioners),
                updated_by_user_id=admin.user_id,
            )
            await run_in_threadpool(runtime_service.apply_config, config)
            access_security.configure(config.control_plane.security)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        app.state.hub_config = config
        await record_audit(
            admin,
            "settings.update",
            "setting",
            "hub_config",
            {"revision": revision},
        )
        return {
            "config": config.model_dump(mode="json"),
            "revision": revision,
            "updated_at": updated_at,
            "available_provisioners": sorted(runtime_service.provisioners),
        }

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
        await validate_credential_scope(body.scope, user)
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
        await validate_credential_scope(scope, user)
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

    @app.get("/api/hub/images")
    async def list_runtime_images(
        _: HubUser = Depends(require_admin),
    ) -> dict[str, object]:
        """List administrator-managed Docker image choices and status."""
        provisioner = runtime_service.provisioners.get("docker")
        status = runtime_service.provisioner_statuses().get("docker")
        policy = runtime_service.hub_config.runtime.docker
        official = []
        if isinstance(provisioner, DockerRuntimeProvisioner):
            available = bool(status and status.get("available"))
            for source, repository in OFFICIAL_DOCKER_IMAGES.items():
                for tag in OFFICIAL_DOCKER_TAGS:
                    reference = f"{repository}:{tag}"
                    official.append(
                        {
                            "source": source,
                            "reference": reference,
                            "tag": tag,
                            "downloaded": (
                                await run_in_threadpool(
                                    provisioner.image_exists,
                                    reference,
                                )
                                if available
                                else False
                            ),
                        },
                    )
        local_images: list[dict[str, object]] = []
        if (
            isinstance(provisioner, DockerRuntimeProvisioner)
            and status
            and status.get("available")
        ):
            local_images = await run_in_threadpool(provisioner.list_images)
        return {
            "available": bool(status and status.get("available")),
            "reason": status.get("reason") if status else None,
            "sources": OFFICIAL_DOCKER_IMAGES,
            "official_images": official,
            "local_images": local_images,
            "policy": policy.model_dump(),
        }

    @app.get("/api/hub/images/pulls")
    async def list_image_pulls(
        _: HubUser = Depends(require_admin),
    ) -> list[dict[str, object]]:
        """List current and recent Docker image pulls."""
        if docker_pulls is None:
            return []
        pulls = await run_in_threadpool(docker_pulls.list)
        return [pull.to_dict() for pull in pulls]

    @app.get("/api/hub/images/pulls/{pull_id}")
    async def get_image_pull(
        pull_id: str,
        _: HubUser = Depends(require_admin),
    ) -> dict[str, object]:
        """Return one Docker image pull status."""
        if docker_pulls is None:
            raise HTTPException(
                status_code=503,
                detail="Docker is unavailable",
            )
        try:
            pull = await run_in_threadpool(docker_pulls.get, pull_id)
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Pull not found",
            ) from exc
        return pull.to_dict()

    @app.post("/api/hub/images/pulls", status_code=202)
    async def pull_runtime_image(
        body: DockerImagePullBody,
        user: HubUser = Depends(require_admin),
    ) -> dict[str, object]:
        """Start a deduplicated Docker image pull."""
        if docker_pulls is None:
            raise HTTPException(
                status_code=503,
                detail="Docker is unavailable",
            )
        try:
            runtime_service.require_provisioner_available("docker")
            pull = await run_in_threadpool(
                docker_pulls.submit,
                body.reference,
            )
        except RuntimeProvisionerUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await record_audit(
            user,
            "image.pull",
            "docker_image",
            body.reference,
            {"pull_id": pull.pull_id},
        )
        return pull.to_dict()

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
        reserved_metadata = {"local", "docker"} & set(body.metadata)
        if reserved_metadata:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Runtime backend settings are " "administrator-controlled."
                ),
            )
        try:
            record = await run_in_threadpool(
                runtime_service.create,
                RuntimeSpec(
                    runtime_id=body.runtime_id,
                    tenant_id=personal_tenant_id(user),
                    owner_user_id=user.user_id,
                    provisioner=None,
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
        await require_runtime_access(runtime_id, user)
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
        user: HubUser = Depends(require_admin),
    ) -> dict[str, Any]:
        await require_runtime_access(runtime_id, user)
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

    @app.post("/api/hub/runtimes/{runtime_id}/rebuild")
    async def rebuild_runtime(
        runtime_id: str,
        user: HubUser = Depends(require_admin),
    ) -> dict[str, Any]:
        """Rebuild a Docker runtime with the current global image."""
        await require_runtime_access(runtime_id, user)
        try:
            record = await run_in_threadpool(
                runtime_service.rebuild,
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
            "runtime.rebuild",
            "runtime",
            runtime_id,
        )
        return await runtime_payload(record)

    @app.post("/api/hub/runtimes/{runtime_id}/stop")
    async def stop_runtime(
        runtime_id: str,
        user: HubUser = Depends(require_admin),
    ) -> dict[str, Any]:
        await require_runtime_access(runtime_id, user)
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

    @app.post("/api/hub/runtimes/{runtime_id}/disable")
    async def disable_runtime(
        runtime_id: str,
        user: HubUser = Depends(require_admin),
    ) -> dict[str, Any]:
        await require_runtime_access(runtime_id, user)
        try:
            record = await run_in_threadpool(
                runtime_service.stop,
                runtime_id,
                start_policy=RuntimeStartPolicy.ADMIN_ONLY,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Runtime not found",
            ) from exc
        await record_audit(
            user,
            "runtime.disable",
            "runtime",
            runtime_id,
        )
        return await runtime_payload(record)

    @app.delete("/api/hub/runtimes/{runtime_id}", status_code=204)
    async def delete_runtime(
        runtime_id: str,
        user: HubUser = Depends(require_admin),
    ) -> None:
        await require_runtime_access(runtime_id, user)
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
        "/api/hub/oauth/callback/{runtime_id}/{callback_route:path}",
        include_in_schema=False,
    )
    async def oauth_callback_relay(
        runtime_id: str,
        callback_route: str,
        request: Request,
    ) -> Response:
        callback_path = runtime_oauth_callback_path(callback_route)
        if callback_path is None:
            raise HTTPException(
                status_code=404,
                detail="OAuth callback route is invalid",
            )
        try:
            record = await run_in_threadpool(
                runtime_service.status,
                runtime_id,
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
        target = runtime_url(
            record,
            scheme="http",
            path=callback_path,
            query=request.url.query.encode("utf-8"),
        )
        internal_token = await run_in_threadpool(
            credential_vault.get_runtime_secret,
            tenant_id=record.tenant_id,
            runtime_id=record.runtime_id,
            name="QWENPAW_RUNTIME_INTERNAL_TOKEN",
        )
        if internal_token is None:
            raise HTTPException(
                status_code=503,
                detail="Personal runtime boundary token is unavailable",
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
        target = runtime_url(
            record,
            scheme="http",
            path=f"/api/{path}",
            query=request.url.query.encode("utf-8"),
        )
        proxy_config = app.state.hub_config.control_plane.proxy
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > proxy_config.max_request_size_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"Request body exceeds the configured "
                        f"{proxy_config.max_request_size_mb} MiB limit"
                    ),
                )
        internal_token = await run_in_threadpool(
            credential_vault.get_runtime_secret,
            tenant_id=record.tenant_id,
            runtime_id=record.runtime_id,
            name="QWENPAW_RUNTIME_INTERNAL_TOKEN",
        )
        if internal_token is None:
            raise HTTPException(
                status_code=503,
                detail="Personal runtime boundary token is unavailable",
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
        callback_route = oauth_callback_route(request.method, path)
        if callback_route:
            public_base_url = (
                app.state.hub_config.control_plane.public_base_url
                or str(request.base_url).rstrip("/")
            )
            headers[HUB_OAUTH_CALLBACK_URL_HEADER] = (
                f"{public_base_url}/api/hub/oauth/callback/"
                f"{record.runtime_id}/{callback_route}"
            )
        timeout = httpx.Timeout(
            connect=proxy_config.connect_timeout_seconds,
            read=None,
            write=proxy_config.request_idle_timeout_seconds,
            pool=proxy_config.connect_timeout_seconds,
        )
        client = httpx.AsyncClient(
            timeout=timeout,
            transport=proxy_transport,
        )
        request_complete = asyncio.Event()
        try:
            upstream_request = client.build_request(
                request.method,
                target,
                headers=headers,
                content=limited_request_stream(
                    request.stream(),
                    max_bytes=proxy_config.max_request_size_bytes,
                    idle_timeout_seconds=(
                        proxy_config.request_idle_timeout_seconds
                    ),
                    completion_event=request_complete,
                ),
            )
            upstream = await send_with_response_header_timeout(
                client,
                upstream_request,
                request_complete=request_complete,
                timeout_seconds=(proxy_config.response_header_timeout_seconds),
            )
        except ProxyRequestTooLargeError as exc:
            await client.aclose()
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Request body exceeds the configured "
                    f"{proxy_config.max_request_size_mb} MiB limit"
                ),
            ) from exc
        except ProxyRequestIdleTimeoutError as exc:
            await client.aclose()
            raise HTTPException(
                status_code=408,
                detail="Request body upload timed out",
            ) from exc
        except TimeoutError as exc:
            await client.aclose()
            raise HTTPException(
                status_code=504,
                detail="Personal runtime response headers timed out",
            ) from exc
        except httpx.TimeoutException as exc:
            await client.aclose()
            raise HTTPException(
                status_code=504,
                detail="Personal runtime proxy request timed out",
            ) from exc
        except httpx.HTTPError as exc:
            await client.aclose()
            raise HTTPException(
                status_code=502,
                detail=f"Personal QwenPaw is unavailable: {exc}",
            ) from exc
        except BaseException:
            await client.aclose()
            raise

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

        async def stream_upstream() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_upstream(),
            status_code=upstream.status_code,
            headers=response_headers,
        )

    @app.websocket("/api/{path:path}")
    async def personal_runtime_websocket_proxy(
        websocket: WebSocket,
        path: str,
    ) -> None:
        authorization = websocket.headers.get("authorization", "")
        prefix = "Bearer "
        token = (
            authorization[len(prefix) :]
            if authorization.startswith(prefix)
            else ""
        )
        if not token:
            await websocket.close(code=4401)
            return
        user = await run_in_threadpool(hub_auth.verify_token, token)
        if user is None:
            await websocket.close(code=4401)
            return
        try:
            record = await ensure_personal_runtime(user)
            target = runtime_url(
                record,
                scheme="ws",
                path=f"/api/{path}",
                query=websocket.url.query.encode("utf-8"),
            )
            proxy_config = app.state.hub_config.control_plane.proxy
            internal_token = await run_in_threadpool(
                credential_vault.get_runtime_secret,
                tenant_id=record.tenant_id,
                runtime_id=record.runtime_id,
                name="QWENPAW_RUNTIME_INTERNAL_TOKEN",
            )
            if internal_token is None:
                await websocket.close(code=1013)
                return
            await websocket_proxy.relay_websocket(
                websocket,
                str(target),
                headers={
                    "X-QwenPaw-Runtime-Token": internal_token,
                },
                max_size=(proxy_config.websocket_max_message_size_bytes),
            )
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Personal runtime WebSocket proxy failed")
            try:
                await websocket.close(code=1013)
            except RuntimeError:
                return

    static_dir = resolve_console_static_dir()
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
        requested, index_file = await run_in_threadpool(
            resolve_console_response,
            static_dir,
            path,
        )
        if requested is not None:
            return FileResponse(requested)
        if index_file is not None:
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
    ).resolve(config_path, available_provisioners={"local", "docker"})
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
        create_hub_app(
            hub_config=hub_config,
            root_dir=root_dir,
            public_bind=public_bind,
        ),
        host=host,
        port=port,
        workers=1,
        log_level=log_level,
        timeout_graceful_shutdown=10,
    )
