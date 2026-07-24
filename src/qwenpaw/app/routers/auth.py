# -*- coding: utf-8 -*-
"""Authentication API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import (
    ExternalLoginDenied,
    authenticate_external_login,
    is_auth_enabled,
    resolve_client_ip,
    resolve_external_identity,
)
from ..rate_limiter import rate_limiter

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str
    expires_in: int | None = None


class LoginResponse(BaseModel):
    token: str
    username: str


class AuthStatusResponse(BaseModel):
    enabled: bool
    mode: str


@router.post("/login")
async def login(request: Request, req: LoginRequest):
    """Authenticate with username/password via the external provider."""
    if not is_auth_enabled():
        return LoginResponse(token="", username="")

    client_ip = resolve_client_ip(request)

    if rate_limiter.is_user_locked(req.username):
        raise HTTPException(
            status_code=423,
            detail="Account temporarily locked. Please try again later",
        )
    if rate_limiter.is_ip_locked(client_ip):
        raise HTTPException(
            status_code=423,
            detail="Too many login attempts. Please try again later",
        )
    if rate_limiter.is_ip_rate_limited(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please slow down",
        )

    try:
        external_login = await authenticate_external_login(
            req.username,
            req.password,
        )
    except ExternalLoginDenied as exc:
        rate_limiter.record_login_attempt(
            client_ip, req.username, success=False
        )
        raise HTTPException(status_code=403, detail=exc.detail) from exc

    if not external_login or not external_login.token:
        rate_limiter.record_login_attempt(
            client_ip, req.username, success=False
        )
        raise HTTPException(
            status_code=401, detail="Invalid username or password"
        )

    rate_limiter.record_login_attempt(client_ip, req.username, success=True)
    return LoginResponse(
        token=external_login.token, username=external_login.identity
    )


@router.get("/status")
async def auth_status():
    """Report auth mode. Users are owned by the external provider."""
    return AuthStatusResponse(enabled=is_auth_enabled(), mode="nocobase")


@router.get("/verify")
async def verify(request: Request):
    """Verify that the caller's external token is still valid."""
    if not is_auth_enabled():
        return {"valid": True, "username": ""}
    identity = await resolve_external_identity(request)
    if identity is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"valid": True, "username": identity.sender_id}
