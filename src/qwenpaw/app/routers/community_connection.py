# -*- coding: utf-8 -*-
"""Community connection via local PKCE or deployment-protected password login."""

from __future__ import annotations

import os
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, SecretStr, ValidationError

from ..community_connection import (
    CommunityConnectionError,
    CommunityConnectionService,
)

router = APIRouter(prefix="/community/connection", tags=["community"])


def get_service(request: Request) -> CommunityConnectionService:
    """Share a single service with the runtime lifespan polling task."""
    service = getattr(request.app.state, "community_connection_service", None)
    if service is None:
        service = CommunityConnectionService()
        request.app.state.community_connection_service = service
    return service


def is_local_request(request: Request) -> bool:
    """Do not mistake a Hub proxy or arbitrary web origin for loopback UI."""
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if (
        os.getenv("QWENPAW_RUNTIME_INTERNAL_TOKEN")
        or not request.client
        or request.client.host not in local_hosts
        or request.url.hostname not in local_hosts
    ):
        return False
    origin = request.headers.get("origin")
    if origin:
        try:
            parsed = urlsplit(origin)
        except ValueError:
            return False
        if parsed.hostname not in local_hosts and origin not in {
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        }:
            return False
        if parsed.scheme not in {"http", "https", "tauri"}:
            return False
    return True


async def call(awaitable):
    try:
        return await awaitable
    except CommunityConnectionError as exc:
        raise HTTPException(
            # A Platform session is independent of QwenPaw's local login.
            # Do not let an upstream 401 log the user out of QwenPaw.
            status_code=409 if exc.status_code == 401 else exc.status_code,
            detail=exc.code,
        ) from exc


class PasswordConnection(BaseModel):
    account: str
    password: SecretStr = SecretStr("")


@router.post("/password")
async def connect_with_password(request: Request):
    # Access is controlled by the deployment and existing app middleware,
    # rather than a second community-specific owner/proxy check.
    # request.json() also parses text/plain bodies. Require a non-safelisted
    # media type so cross-origin browser writes must pass CORS preflight.
    # CORS (including the gateway's policy) must allow only trusted frontends.
    content_type = request.headers.get("content-type", "")
    if content_type.partition(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, detail="json_content_type_required")
    try:
        body = PasswordConnection.model_validate(await request.json())
    except (ValueError, ValidationError) as exc:
        # Default validation errors include rejected input, possibly secrets.
        raise HTTPException(422, detail="credentials_required") from exc
    return await call(
        get_service(request).connect_password(
            body.account,
            body.password.get_secret_value(),
        ),
    )


@router.delete("/password")
async def clear_saved_password(request: Request):
    return await call(get_service(request).clear_credentials())


@router.get("")
async def get_connection_status(request: Request):
    return await call(
        get_service(request).status(
            local=is_local_request(request),
        ),
    )


@router.post("/start")
async def start_connection(request: Request):
    return await call(
        get_service(request).start(local=is_local_request(request)),
    )


@router.get("/authorization/{flow_id}")
async def get_authorization_status(flow_id: str, request: Request):
    return await call(get_service(request).authorization_status(flow_id))


@router.delete("/authorization/{flow_id}")
async def cancel_authorization(flow_id: str, request: Request):
    await call(get_service(request).cancel(flow_id))
    return {"cancelled": True}


@router.delete("")
async def disconnect_community(request: Request):
    return await call(get_service(request).disconnect())


class SyncSettings(BaseModel):
    enabled: bool | None = None
    message_types: (
        list[
            Literal[
                "comments",
                "mentions",
                "interactions",
                "feedback",
                "notifications",
            ]
        ]
        | None
    ) = None


@router.patch("/sync")
async def update_sync_settings(body: SyncSettings, request: Request):
    return await call(
        get_service(request).set_sync(body.enabled, body.message_types),
    )


@router.post("/sync")
async def sync_community(request: Request):
    return await call(get_service(request).sync_once())
