# -*- coding: utf-8 -*-
"""Beta Platform login, binding, and mobile handoff for the Console."""

from __future__ import annotations

from dataclasses import asdict
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from ...constant import EnvVarLoader, SECRET_DIR
from ...remote_access.platform_client import RelayPlatformError
from ...remote_access.runtime import PlatformRuntimeConnection
from ..auth import platform_runtime_headers

router = APIRouter(prefix="/remote-access/platform", tags=["Platform"])
callback_router = APIRouter()


class LoginBody(BaseModel):
    """Start one PKCE login in the selected Platform environment."""

    name: str = Field(min_length=1, max_length=128)


class ApprovalBody(BaseModel):
    """Verification code shown on the phone before login approval."""

    verification_code: str = Field(pattern=r"^\d{6}$")


async def _service(request: Request) -> PlatformRuntimeConnection:
    scoped = getattr(request.state, "platform_connection", None)
    if scoped is not None:
        return scoped
    service = getattr(request.app.state, "platform_connection", None)
    if service is None:
        server = request.scope.get("server")
        if not server:
            raise HTTPException(status_code=503, detail="No Runtime endpoint")
        host, port = server
        host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
        service = PlatformRuntimeConnection(
            SECRET_DIR,
            str(httpx.URL(scheme="http", host=host, port=port)),
            headers=platform_runtime_headers,
        )
        request.app.state.platform_connection = service
        await service.start()
    return service


def _same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    expected = urlsplit(str(request.base_url))
    if origin is not None and origin != (
        f"{expected.scheme}://{expected.netloc}"
    ):
        raise HTTPException(status_code=403, detail="Invalid request origin")


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, RelayPlatformError):
        return HTTPException(
            status_code=409 if exc.status_code == 401 else exc.status_code,
            detail=str(exc),
        )
    return HTTPException(status_code=409, detail=str(exc))


@router.get("")
async def status(request: Request) -> dict:
    """Show account identity separately from live transport status."""
    service = await _service(request)
    return {
        **asdict(await service.account.status()),
        "transport_status": service.supervisor.status,
        "beta": True,
    }


@router.post("/login")
async def login(body: LoginBody, request: Request) -> dict:
    """Sign in without creating another standalone local account."""
    _same_origin(request)
    try:
        result = await (await _service(request)).account.start(
            platform_url=EnvVarLoader.get_str(
                "QWENPAW_PLATFORM_URL",
                "https://platform.agentscope.io",
            ),
            name=body.name.strip(),
            callback_origin=str(request.base_url),
        )
        prepare = getattr(request.state, "prepare_platform_login", None)
        if prepare is not None:
            try:
                await prepare()
            except Exception:
                (await _service(request)).account.cancel_login()
                raise
        return asdict(result)
    except (ValueError, RelayPlatformError) as exc:
        raise _error(exc) from exc


@router.post("/bind")
async def bind(request: Request) -> dict:
    """Retry registration using the current protected cloud session."""
    _same_origin(request)
    service = await _service(request)
    try:
        result = await service.account.bind()
        await service.close()
        await service.start()
        return asdict(result)
    except (ValueError, RelayPlatformError) as exc:
        raise _error(exc) from exc


@router.post("/mobile")
async def mobile(request: Request) -> dict:
    """Issue a short-lived, single-use QR login, never a Node token."""
    _same_origin(request)
    try:
        return await (await _service(request)).mobile_login()
    except (ValueError, RelayPlatformError) as exc:
        raise _error(exc) from exc


@router.api_route("/mobile/{request_id}", methods=["GET", "DELETE"])
async def mobile_status(request_id: UUID, request: Request) -> dict:
    """Read or cancel this user's pending mobile login."""
    _same_origin(request)
    try:
        return dict(
            await (await _service(request)).account.account_request(
                request.method,
                f"/api/v1/qwenpaw-web/login-requests/{request_id}",
            ),
        )
    except (ValueError, RelayPlatformError) as exc:
        raise _error(exc) from exc


@router.post("/mobile/{request_id}/approve")
async def approve(
    request_id: UUID,
    body: ApprovalBody,
    request: Request,
) -> dict:
    """Approve the phone shown in the current local Console session."""
    _same_origin(request)
    try:
        return dict(
            await (await _service(request)).account.account_request(
                "POST",
                f"/api/v1/qwenpaw-web/login-requests/{request_id}/approve",
                body.model_dump(),
            ),
        )
    except (ValueError, RelayPlatformError) as exc:
        raise _error(exc) from exc


@router.post("/logout")
async def logout(request: Request) -> dict:
    """End only the Console's cloud login, leaving Node binding explicit."""
    _same_origin(request)
    try:
        await (await _service(request)).account.logout()
    except (ValueError, RelayPlatformError) as exc:
        raise _error(exc) from exc
    return {"ok": True}


@router.delete("")
async def disconnect(request: Request) -> dict:
    """Revoke only this binding, preserving other devices and accounts."""
    _same_origin(request)
    service = await _service(request)
    try:
        current = await service.account.status()
        if current.node_id:
            try:
                await service.account.account_request(
                    "DELETE",
                    f"/api/v1/qwenpaw-relay/nodes/{current.node_id}",
                )
            except RelayPlatformError as exc:
                if exc.status_code != 404:
                    raise
        await service.close()
        try:
            await service.account.logout()
        finally:
            async with service.store.mutation_lock:
                service.store.path.unlink(missing_ok=True)
    except (ValueError, RelayPlatformError) as exc:
        raise _error(exc) from exc
    return {"ok": True}


@callback_router.get("/callback/{nonce}", response_class=HTMLResponse)
async def callback(
    nonce: str,
    state: str,
    code: str,
    request: Request,
) -> HTMLResponse:
    """Complete a validated Console PKCE callback from Platform."""
    try:
        service = await _service(request)
        await service.account.complete_oauth(
            nonce=nonce,
            state_value=state,
            code=code,
        )
        await service.start()
    except (ValueError, RelayPlatformError) as exc:
        raise _error(exc) from exc
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        "<title>QwenPaw Platform</title>"
        "<p>Platform connected. Return to QwenPaw.</p>",
        headers={"Cache-Control": "no-store"},
    )
