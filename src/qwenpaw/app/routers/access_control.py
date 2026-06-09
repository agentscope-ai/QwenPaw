# -*- coding: utf-8 -*-
"""API router for channel access control (whitelist / blacklist / pending)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..channels.access_control import get_access_control_store

router = APIRouter(prefix="/access-control", tags=["access-control"])


async def _get_store(request: Request):
    """Get the AccessControlStore for the current workspace."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    workspace_dir = Path(workspace.workspace_dir)
    return get_access_control_store(workspace_dir)


# ── Request / Response schemas ──────────────────────────────────────────────


class UserInfoResponse(BaseModel):
    remark: str = ""
    username: str = ""


class ACLResponse(BaseModel):
    whitelist: Dict[str, UserInfoResponse] = Field(default_factory=dict)
    blacklist: Dict[str, UserInfoResponse] = Field(default_factory=dict)
    pending: List[dict] = Field(default_factory=list)


class ACLActionEntry(BaseModel):
    """Entry for whitelist/blacklist/pending batch operations."""

    channel: str
    user_id: str
    remark: str = ""
    username: str = ""


class ACLActionBody(BaseModel):
    """Unified body for single or batch ACL operations."""

    entries: List[ACLActionEntry]


class UpdateRemarkBody(BaseModel):
    channel: str
    user_id: str
    remark: str


class UpdateUsernameBody(BaseModel):
    channel: str
    user_id: str
    username: str


class PendingEntry(BaseModel):
    user_id: str
    channel: str
    timestamp: float
    first_message: str = ""
    remark: str = ""
    username: str = ""


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get(
    "",
    summary="Get all access control lists",
    response_model=dict,
)
async def get_all_acls(request: Request):
    """Return channels that have data OR have access control enabled."""
    from ..agent_context import get_agent_for_request

    workspace = await get_agent_for_request(request)
    store = get_access_control_store(Path(workspace.workspace_dir))
    raw_acls = store.get_all_acls()

    # Collect enabled channel names
    enabled_channels: set = set()
    service_manager = getattr(workspace, "_service_manager", None)
    if service_manager:
        cm = service_manager.services.get("channel_manager")
        if cm:
            for ch in cm.channels:
                if ch.access_control_enabled:
                    enabled_channels.add(ch.channel)

    # Only return channels that are non-empty OR have access control on
    result = {}
    for key, data in raw_acls.items():
        has_data = (
            data.get("whitelist")
            or data.get("blacklist")
            or data.get("pending")
        )
        if has_data or key in enabled_channels:
            result[key] = data

    # Add enabled channels not yet in file
    for ch_name in enabled_channels:
        if ch_name not in result:
            result[ch_name] = {"whitelist": {}, "blacklist": {}, "pending": []}

    return result


# ── Pending routes MUST come before /{channel} to avoid path conflicts ──────


@router.get(
    "/pending/all",
    summary="Get all pending approval entries",
    response_model=List[PendingEntry],
)
async def get_all_pending(request: Request):
    store = await _get_store(request)
    return store.get_all_pending()


@router.post(
    "/pending/approve",
    summary="Approve one or more pending users (add to whitelist)",
)
async def approve_pending(request: Request, body: ACLActionBody):
    store = await _get_store(request)
    for entry in body.entries:
        store.approve_pending(
            entry.channel,
            entry.user_id,
            entry.remark,
        )
    return {"status": "ok", "count": len(body.entries)}


@router.post(
    "/pending/deny",
    summary="Deny one or more pending users (add to blacklist)",
)
async def deny_pending(request: Request, body: ACLActionBody):
    store = await _get_store(request)
    for entry in body.entries:
        store.deny_pending(
            entry.channel,
            entry.user_id,
            entry.remark,
        )
    return {"status": "ok", "count": len(body.entries)}


@router.post(
    "/pending/dismiss",
    summary="Dismiss one or more pending users (remove w/o action)",
)
async def dismiss_pending(request: Request, body: ACLActionBody):
    store = await _get_store(request)
    for entry in body.entries:
        store.dismiss_pending(entry.channel, entry.user_id)
    return {"status": "ok", "count": len(body.entries)}


@router.post(
    "/pending/remark",
    summary="Update remark on a pending entry",
)
async def update_pending_remark(
    request: Request,
    body: UpdateRemarkBody,
):
    store = await _get_store(request)
    found = store.update_pending_remark(
        body.channel,
        body.user_id,
        body.remark,
    )
    if not found:
        raise HTTPException(
            status_code=404,
            detail="Pending entry not found",
        )
    return {"status": "ok"}


# ── Whitelist / Blacklist unified batch endpoints ───────────────────────────


@router.post(
    "/whitelist/add",
    summary="Add one or more users to whitelist",
)
async def add_to_whitelist(request: Request, body: ACLActionBody):
    store = await _get_store(request)
    for entry in body.entries:
        store.add_to_whitelist(
            entry.channel,
            entry.user_id,
            entry.remark,
            username=entry.username,
        )
    return {"status": "ok", "count": len(body.entries)}


@router.post(
    "/whitelist/remove",
    summary="Remove one or more users from whitelist",
)
async def remove_from_whitelist(
    request: Request,
    body: ACLActionBody,
):
    store = await _get_store(request)
    for entry in body.entries:
        store.remove_from_whitelist(entry.channel, entry.user_id)
    return {"status": "ok", "count": len(body.entries)}


@router.post(
    "/blacklist/add",
    summary="Add one or more users to blacklist",
)
async def add_to_blacklist(request: Request, body: ACLActionBody):
    store = await _get_store(request)
    for entry in body.entries:
        store.add_to_blacklist(
            entry.channel,
            entry.user_id,
            entry.remark,
            username=entry.username,
        )
    return {"status": "ok", "count": len(body.entries)}


@router.post(
    "/blacklist/remove",
    summary="Remove one or more users from blacklist",
)
async def remove_from_blacklist(
    request: Request,
    body: ACLActionBody,
):
    store = await _get_store(request)
    for entry in body.entries:
        store.remove_from_blacklist(entry.channel, entry.user_id)
    return {"status": "ok", "count": len(body.entries)}


@router.post(
    "/remark",
    summary="Update remark for a user in whitelist or blacklist",
)
async def update_remark(request: Request, body: UpdateRemarkBody):
    store = await _get_store(request)
    found = store.update_remark(
        body.channel,
        body.user_id,
        body.remark,
    )
    if not found:
        raise HTTPException(
            status_code=404,
            detail="User not found in any list",
        )
    return {"status": "ok"}


@router.post(
    "/username",
    summary="Update username for a user in any list",
)
async def update_username(request: Request, body: UpdateUsernameBody):
    store = await _get_store(request)
    found = store.update_username(
        body.channel,
        body.user_id,
        body.username,
    )
    if not found:
        raise HTTPException(
            status_code=404,
            detail="User not found in any list",
        )
    return {"status": "ok"}


# ── Channel-specific routes (/{channel} is a catch-all path param) ──────────


@router.get(
    "/{channel}",
    summary="Get access control list for a channel",
    response_model=ACLResponse,
)
async def get_channel_acl(request: Request, channel: str):
    store = await _get_store(request)
    return store.get_acl(channel)
