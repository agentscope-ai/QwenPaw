# -*- coding: utf-8 -*-
"""Authentication API endpoints."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..auth import (
    authenticate,
    has_registered_users,
    is_auth_enabled,
    register_user,
    update_credentials,
    verify_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    username: str


class RegisterRequest(BaseModel):
    username: str
    password: str


class AuthStatusResponse(BaseModel):
    enabled: bool
    has_users: bool


@router.post("/login")
async def login(req: LoginRequest):
    """Authenticate with username and password."""
    if not is_auth_enabled():
        return LoginResponse(token="", username="")

    token = authenticate(req.username, req.password)
    if token is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return LoginResponse(token=token, username=req.username)


@router.post("/register")
async def register(req: RegisterRequest):
    """Register the single user account (only allowed once)."""
    env_flag = os.environ.get("COPAW_AUTH_ENABLED", "").strip().lower()
    if env_flag not in ("true", "1", "yes"):
        raise HTTPException(
            status_code=403,
            detail="Authentication is not enabled",
        )

    if has_registered_users():
        raise HTTPException(
            status_code=403,
            detail="User already registered",
        )

    if not req.username.strip() or not req.password.strip():
        raise HTTPException(
            status_code=400,
            detail="Username and password are required",
        )

    token = register_user(req.username.strip(), req.password)
    if token is None:
        raise HTTPException(
            status_code=409,
            detail="Registration failed",
        )

    return LoginResponse(token=token, username=req.username.strip())


@router.get("/status")
async def auth_status():
    """Check if authentication is enabled and whether a user exists."""
    return AuthStatusResponse(
        enabled=is_auth_enabled(),
        has_users=has_registered_users(),
    )


@router.get("/verify")
async def verify(request: Request):
    """Verify that the caller's Bearer token is still valid."""
    if not is_auth_enabled():
        return {"valid": True, "username": ""}

    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="No token provided")

    username = verify_token(token)
    if username is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
        )

    return {"valid": True, "username": username}


class UpdateProfileRequest(BaseModel):
    current_password: str
    new_username: str | None = None
    new_password: str | None = None


@router.post("/update-profile")
async def update_profile(req: UpdateProfileRequest, request: Request):
    """Update username and/or password for the authenticated user."""
    if not is_auth_enabled():
        raise HTTPException(
            status_code=403,
            detail="Authentication is not enabled",
        )

    if not has_registered_users():
        raise HTTPException(
            status_code=403,
            detail="No user registered",
        )

    # Verify caller is authenticated
    auth_header = request.headers.get("Authorization", "")
    caller_token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
    if not caller_token or verify_token(caller_token) is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not req.new_username and not req.new_password:
        raise HTTPException(
            status_code=400,
            detail="Nothing to update",
        )

    if req.new_username is not None and not req.new_username.strip():
        raise HTTPException(
            status_code=400,
            detail="Username cannot be empty",
        )

    if req.new_password is not None and not req.new_password.strip():
        raise HTTPException(
            status_code=400,
            detail="Password cannot be empty",
        )

    token = update_credentials(
        current_password=req.current_password,
        new_username=req.new_username,
        new_password=req.new_password,
    )
    if token is None:
        raise HTTPException(
            status_code=401,
            detail="Current password is incorrect",
        )

    username = req.new_username.strip() if req.new_username else ""
    return LoginResponse(token=token, username=username)
