# -*- coding: utf-8 -*-
"""App-scoped browser reads without exposing credentials in resource URLs."""

from __future__ import annotations

import re
import time
from urllib.parse import unquote

from fastapi import HTTPException, Request, Response

from .auth import HubAuthService, HubUser
from .models import RuntimeRecord

SESSION_SECONDS = 900
COOKIE_PREFIX = "qwenpaw_app_"
_RESERVED = {
    "hub",
    "auth",
    "frontend_plugin",
    "pawapps",
    "plugins",
    "models",
    "files",
}
_APP_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")


def validate_app_id(app_id: str) -> None:
    """Allow only one unambiguous URL and cookie component."""
    if not _APP_ID.fullmatch(app_id) or app_id in _RESERVED:
        raise HTTPException(status_code=400, detail="Invalid PawApp ID")


def resource_app_id(path: str) -> str | None:
    """Reject encoded routing tricks rather than normalizing scopes away."""
    decoded = unquote(unquote(path))
    if decoded != path or "\\" in path:
        return None
    parts = path.split("/")
    if any(part in {".", "..", ""} for part in parts):
        return None
    if len(parts) >= 4 and parts[0] == "frontend_plugin":
        return parts[1] if parts[2] == "files" else None
    if len(parts) >= 4 and parts[0] == "pawapps":
        return parts[1] if parts[2] == "static" else None
    # Core API namespaces must never be granted through an app session.
    if len(parts) >= 2:
        return parts[0]
    return None


def issue_session(
    auth: HubAuthService,
    user: HubUser,
    record: RuntimeRecord,
    app_id: str,
    response: Response,
    *,
    secure: bool,
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
            "exp": int(time.time()) + SESSION_SECONDS,
        },
    )
    response.set_cookie(
        f"{COOKIE_PREFIX}{app_id}",
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
    app_id = resource_app_id(path)
    if not app_id or not _APP_ID.fullmatch(app_id):
        return None
    token = request.cookies.get(f"{COOKIE_PREFIX}{app_id}", "")
    payload = auth.read_token_payload(token)
    if not payload or payload.get("purpose") != "pawapp-read":
        return None
    if payload.get("app") != app_id:
        return None
    user = auth.token_user(payload)
    return (user, payload) if user else None


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
