# -*- coding: utf-8 -*-
"""App-scoped browser reads without exposing credentials in resource URLs."""

from __future__ import annotations

import hashlib
import time
from urllib.parse import unquote

from fastapi import HTTPException, Request, Response

from .auth import HubAuthService, HubUser
from .models import RuntimeRecord

SESSION_SECONDS = 900
COOKIE_PREFIX = "qwenpaw_app_"


def validate_app_id(app_id: str) -> None:
    """Require a single URL segment without restricting manifest spelling."""
    if (
        not app_id
        or app_id in {".", ".."}
        or any(char in app_id for char in "/\\%")
        or any(ord(char) < 32 or ord(char) == 127 for char in app_id)
    ):
        raise HTTPException(status_code=400, detail="Invalid PawApp ID")


def cookie_name(app_id: str) -> str:
    """Encode arbitrary manifest IDs as a fixed-size cookie component."""
    digest = hashlib.sha256(app_id.encode("utf-8")).hexdigest()
    return f"{COOKIE_PREFIX}{digest}"


def _allows_path(payload: dict, path: str) -> bool:
    if unquote(unquote(path)) != path or "\\" in path:
        return False
    if any(part in {".", "..", ""} for part in path.split("/")):
        return False
    app_id = payload.get("app")
    prefixes = [
        f"frontend_plugin/{app_id}/files",
        f"pawapps/{app_id}/static",
        *payload.get("prefixes", []),
    ]
    return any(
        path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes
    )


def issue_session(
    auth: HubAuthService,
    user: HubUser,
    record: RuntimeRecord,
    app_id: str,
    response: Response,
    *,
    secure: bool,
    prefixes: list[str],
) -> None:
    """Bind the browser grant to an installed app and runtime generation."""
    validate_app_id(app_id)
    token = auth.sign_token_payload(
        {
            "purpose": "pawapp-read",
            "sub": user.user_id,
            "ver": user.token_version,
            "runtime": record.runtime_id,
            "created": record.created_at,
            "app": app_id,
            "prefixes": prefixes,
            "exp": int(time.time()) + SESSION_SECONDS,
        },
    )
    response.set_cookie(
        cookie_name(app_id),
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/api/",
    )
    response.headers["Cache-Control"] = "no-store"


def read_session(
    auth: HubAuthService,
    request: Request,
    path: str,
) -> tuple[HubUser, dict[str, object]] | None:
    """Authorize native browser reads, never mutations or bearer fallback."""
    if request.method not in {"GET", "HEAD"}:
        return None
    for name, token in request.cookies.items():
        if not name.startswith(COOKIE_PREFIX):
            continue
        payload = auth.read_token_payload(token)
        if not payload or payload.get("purpose") != "pawapp-read":
            continue
        app_id = payload.get("app")
        if not isinstance(app_id, str) or name != cookie_name(app_id):
            continue
        if not _allows_path(payload, path):
            continue
        user = auth.token_user(payload)
        if user:
            return user, payload
    return None


def clear_sessions(request: Request, response: Response) -> None:
    """Remove all browser grants when the Console clears its account."""
    for name in request.cookies:
        if name.startswith(COOKIE_PREFIX):
            response.delete_cookie(name, path="/api/")
    response.headers["Cache-Control"] = "no-store"


def require_session_runtime(request: Request, record: RuntimeRecord) -> None:
    """Reject grants from a deleted or replaced personal runtime."""
    session = getattr(request.state, "pawapp_session", None)
    if session is not None and (
        session.get("runtime") != record.runtime_id
        or session.get("created") != record.created_at
    ):
        raise HTTPException(status_code=401, detail="Not authenticated")
