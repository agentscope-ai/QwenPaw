# -*- coding: utf-8 -*-
"""Authentication API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ...constant import EnvVarLoader
from ...identity.models import PlatformRole, UserRecord
from ...identity.runtime import get_identity_runtime, is_multi_user_enabled
from ...identity.sessions import AuthenticatedSession, IssuedSession, SessionRecord
from ..auth import (
    authenticate,
    has_registered_users,
    is_auth_enabled,
    register_user,
    resolve_client_ip,
    revoke_all_tokens,
    revoke_token,
    update_credentials,
    verify_token,
)
from ..rate_limiter import rate_limiter

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str
    expires_in: int | None = None  # Token expiry in seconds, -1/0 for permanent


class LoginResponse(BaseModel):
    token: str
    username: str
    user: dict[str, object] | None = None
    session: dict[str, object] | None = None
    access_expires_at: str | None = None


class RegisterRequest(BaseModel):
    username: str
    password: str
    expires_in: int | None = None  # Token expiry in seconds, -1/0 for permanent


class AuthStatusResponse(BaseModel):
    enabled: bool
    has_users: bool
    mode: str = "legacy"


REFRESH_COOKIE = "qwenpaw_refresh_token"


def _cookie_secure() -> bool:
    return EnvVarLoader.get_bool("QWENPAW_SESSION_COOKIE_SECURE", True)


def _user_payload(user: UserRecord) -> dict[str, object]:
    return {
        "id": str(user.id),
        "username": user.username,
        "platform_role": user.platform_role.value,
        "status": user.status,
        "display_name": user.display_name,
        "email": user.email,
        "phone": user.phone,
        "department": user.department,
        "job_title": user.job_title,
        "remark": user.remark,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }


def _session_payload(session: SessionRecord) -> dict[str, object]:
    return {
        "id": str(session.id),
        "client_info": session.client_info,
        "created_at": session.created_at.isoformat(),
        "last_seen_at": (
            session.last_seen_at.isoformat() if session.last_seen_at else None
        ),
        "expires_at": session.refresh_expires_at.isoformat(),
        "revoked_at": (session.revoked_at.isoformat() if session.revoked_at else None),
    }


def _set_refresh_cookie(response: Response, issued: IssuedSession) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=issued.refresh_token,
        path="/api/auth",
        secure=_cookie_secure(),
        httponly=True,
        samesite="lax",
        expires=issued.refresh_expires_at,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE,
        path="/api/auth",
        secure=_cookie_secure(),
        httponly=True,
        samesite="lax",
    )


def _login_response(issued: IssuedSession) -> LoginResponse:
    user = issued.authenticated.user
    return LoginResponse(
        token=issued.access_token,
        username=user.username,
        user=_user_payload(user),
        session=_session_payload(issued.authenticated.session),
        access_expires_at=issued.access_expires_at.isoformat(),
    )


def _client_info(request: Request) -> dict[str, str]:
    return {
        "user_agent": request.headers.get("user-agent", "")[:512],
        "client_ip": resolve_client_ip(request)[:128],
    }


def _authenticated(request: Request) -> AuthenticatedSession:
    value = getattr(request.state, "authenticated_session", None)
    if not isinstance(value, AuthenticatedSession):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return value


@router.post("/login")
async def login(request: Request, req: LoginRequest, response: Response):
    """Authenticate with username and password.

    Optional `expires_in` field:
    - Positive integer: token expires in N seconds
    - 0 or -1: permanent token (100 years)
    - None/omitted: default 7 days
    """
    if not is_multi_user_enabled() and not is_auth_enabled():
        return LoginResponse(token="", username="")

    # Get client IP for rate limiting
    client_ip = resolve_client_ip(request)

    # Check if user account is locked
    if rate_limiter.is_user_locked(req.username):
        raise HTTPException(
            status_code=423,
            detail="Account temporarily locked. Please try again later",
        )

    # Check if IP is locked or rate-limited
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

    # Attempt authentication
    user = None
    if is_multi_user_enabled():
        user = await get_identity_runtime().users.authenticate(
            req.username,
            req.password,
        )
        token = "multi-user" if user is not None else None
    else:
        token = authenticate(req.username, req.password, req.expires_in)
    if token is None:
        # Record failed attempt
        rate_limiter.record_login_attempt(
            client_ip,
            req.username,
            success=False,
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password",
        )

    # Record successful attempt
    rate_limiter.record_login_attempt(client_ip, req.username, success=True)

    if user is not None:
        issued = await get_identity_runtime().sessions.issue(
            user,
            _client_info(request),
        )
        _set_refresh_cookie(response, issued)
        return _login_response(issued)
    return LoginResponse(token=token, username=req.username)


@router.post("/register")
async def register(req: RegisterRequest, request: Request, response: Response):
    """Register the single user account (only allowed once).

    Optional `expires_in` field:
    - Positive integer: token expires in N seconds
    - 0 or -1: permanent token (100 years)
    - None/omitted: default 7 days
    """
    if is_multi_user_enabled():
        runtime = get_identity_runtime()
        if await runtime.users.has_users():
            raise HTTPException(status_code=403, detail="User already registered")
        if not req.username.strip() or not req.password.strip():
            raise HTTPException(
                status_code=400,
                detail="Username and password are required",
            )
        user = await runtime.users.create_user(
            req.username,
            req.password,
            PlatformRole.ADMIN,
        )
        issued = await runtime.sessions.issue(user, _client_info(request))
        _set_refresh_cookie(response, issued)
        return _login_response(issued)

    env_flag = EnvVarLoader.get_str("QWENPAW_AUTH_ENABLED", "").strip().lower()
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

    token = register_user(req.username.strip(), req.password, req.expires_in)
    if token is None:
        raise HTTPException(
            status_code=409,
            detail="Registration failed",
        )

    return LoginResponse(token=token, username=req.username.strip())


@router.get("/status")
async def auth_status():
    """Check if authentication is enabled and whether a user exists."""
    if is_multi_user_enabled():
        return AuthStatusResponse(
            enabled=True,
            has_users=await get_identity_runtime().users.has_users(),
            mode="multi_user",
        )
    return AuthStatusResponse(
        enabled=is_auth_enabled(),
        has_users=has_registered_users(),
    )


@router.post("/refresh")
async def refresh_session(request: Request, response: Response):
    if not is_multi_user_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    issued = await get_identity_runtime().sessions.refresh(
        request.cookies.get(REFRESH_COOKIE, "")
    )
    if issued is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Invalid refresh session")
    _set_refresh_cookie(response, issued)
    return _login_response(issued)


@router.post("/logout")
async def logout_session(request: Request, response: Response):
    if not is_multi_user_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    await get_identity_runtime().sessions.revoke_current(
        request.cookies.get(REFRESH_COOKIE, "")
    )
    _clear_refresh_cookie(response)
    return {"revoked": True}


@router.get("/sessions")
async def list_sessions(request: Request):
    authenticated = _authenticated(request)
    sessions = await get_identity_runtime().sessions.list_sessions(
        authenticated.user.id
    )
    return [_session_payload(session) for session in sessions]


@router.get("/verify")
async def verify(request: Request):
    """Verify that the caller's Bearer token is still valid."""
    if is_multi_user_enabled():
        authenticated = _authenticated(request)
        return {"valid": True, "username": authenticated.user.username}

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
    expires_in: int | None = None  # Token expiry in seconds, -1/0 for permanent


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
        expiry_seconds=req.expires_in,
    )
    if token is None:
        raise HTTPException(
            status_code=401,
            detail="Current password is incorrect",
        )

    username = req.new_username.strip() if req.new_username else ""
    return LoginResponse(token=token, username=username)


class RevokeTokenRequest(BaseModel):
    token: str | None = None  # Optional: revoke specific token, or current if omitted


@router.post("/revoke-token")
async def revoke_single_token(req: RevokeTokenRequest, request: Request):
    """Revoke a single token by adding it to the blacklist.

    If `token` is provided in the request body, revokes that token.
    If `token` is omitted, revokes the token used for authentication
    (current token).

    This allows you to:
    - Revoke a leaked token from another device
    - Logout from the current session
    """
    if not is_auth_enabled():
        raise HTTPException(
            status_code=403,
            detail="Authentication is not enabled",
        )

    # Get current token for authentication
    auth_header = request.headers.get("Authorization", "")
    caller_token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
    if not caller_token or verify_token(caller_token) is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Determine which token to revoke
    token_to_revoke = req.token if req.token else caller_token
    is_current_token = token_to_revoke == caller_token

    success = revoke_token(token_to_revoke)
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to revoke token",
        )

    message = (
        "Current token has been revoked. Please login again."
        if is_current_token
        else "Specified token has been revoked."
    )

    return {
        "message": message,
        "revoked": True,
        "revoked_current_token": is_current_token,
    }


@router.post("/revoke-all-tokens")
async def revoke_all_sessions(request: Request):
    """Revoke all existing tokens by rotating the JWT secret.

    This endpoint requires authentication. After calling this endpoint,
    all previously issued tokens will be invalidated, and you will need
    to login again to get a new token.

    This is more efficient than revoking tokens individually when you
    want to invalidate all sessions (e.g., password reset, security incident).
    """
    if is_multi_user_enabled():
        authenticated = _authenticated(request)
        count = await get_identity_runtime().sessions.revoke_all(authenticated.user.id)
        return {"revoked": True, "revoked_sessions": count}

    if not is_auth_enabled():
        raise HTTPException(
            status_code=403,
            detail="Authentication is not enabled",
        )

    # Verify caller is authenticated
    auth_header = request.headers.get("Authorization", "")
    caller_token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
    if not caller_token or verify_token(caller_token) is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    success = revoke_all_tokens()
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to revoke tokens",
        )

    return {
        "message": "All tokens have been revoked. Please login again.",
        "revoked": True,
    }
