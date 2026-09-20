# -*- coding: utf-8 -*-
"""Authenticated terminal control over the existing HTTP/Hub boundary."""

import asyncio
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..agent_context import get_agent_for_request, get_project_dir_for_request
from ..auth import (
    has_registered_users,
    is_auth_enabled,
    runtime_token_matches,
    verify_token,
)
from ...services.terminal import TerminalManager, terminal_unavailable_reason
from ...constant import CORS_ORIGINS


@asynccontextmanager
async def lifespan(app):
    """Own terminal processes and the detached-session reaper per app."""
    manager = TerminalManager()
    app.state.terminal_manager = manager

    async def reap():
        while True:
            await asyncio.sleep(60)
            await asyncio.to_thread(manager.reap)

    task = asyncio.create_task(reap())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(manager.shutdown)


async def context(request: Request, group: UUID):
    """Bind every operation to the validated Agent and authenticated user."""
    if not is_auth_enabled():
        raise HTTPException(
            403,
            "Terminal requires QWENPAW_AUTH_ENABLED=true",
        )
    origin = request.headers.get("origin")
    runtime_token = os.environ.get("QWENPAW_RUNTIME_INTERNAL_TOKEN", "")
    trusted_runtime = runtime_token_matches(
        runtime_token,
        request.headers.get("x-qwenpaw-runtime-token", ""),
    )
    if trusted_runtime:
        # Hub authenticates the user before forwarding to their runtime.
        user = "hub-runtime"
    else:
        authorization = request.headers.get("authorization", "")
        token = (
            authorization[7:] if authorization.startswith("Bearer ") else ""
        )
        user = (
            verify_token(token) if token and has_registered_users() else None
        )
        if not user:
            raise HTTPException(401, "Terminal requires authentication")
    configured_origins = {value.strip() for value in CORS_ORIGINS.split(",")}
    if origin and not trusted_runtime and origin not in configured_origins:
        parsed = urlsplit(origin)
        # Local Vite and the local runtime use different ports. Both ends
        # must be literal loopback hosts; arbitrary DNS names do not qualify.
        loopback = {"localhost", "127.0.0.1", "::1"}
        local_console = (
            parsed.scheme == "http"
            and request.url.scheme == "http"
            and parsed.hostname in loopback
            and request.url.hostname in loopback
        )
        if (
            parsed.scheme != request.url.scheme
            or parsed.netloc != request.url.netloc
        ) and not local_console:
            raise HTTPException(403, "Cross-site terminal request rejected")
    if await asyncio.to_thread(terminal_unavailable_reason):
        raise HTTPException(
            503,
            "Terminal unavailable: install pywinpty in the backend "
            "Python environment and restart the service",
        )
    workspace = await get_agent_for_request(request)
    owner = (
        user,
        workspace.agent_id,
        str(group),
    )
    return request.app.state.terminal_manager, owner, workspace


router = APIRouter(prefix="/terminals", tags=["terminals"], lifespan=lifespan)


@router.get("/status")
async def terminal_status():
    """Advertise the runtime's mandatory terminal authentication switch."""
    if not is_auth_enabled():
        return {"enabled": False}
    reason = await asyncio.to_thread(terminal_unavailable_reason)
    if reason:
        return {"enabled": False, "reason": reason}
    return {"enabled": True}


class TerminalInput(BaseModel):
    """Bound input frames so paste cannot exhaust the server."""

    data: str = Field(min_length=1, max_length=16384)


class TerminalSize(BaseModel):
    """Bound terminal dimensions before calling OS APIs."""

    rows: int = Field(ge=2, le=500)
    cols: int = Field(ge=2, le=500)


class TerminalTitle(BaseModel):
    """A short, plain-text user label for a terminal tab."""

    title: str = Field(min_length=1, max_length=64)


async def owned(ctx, terminal_id):
    """Return an owned terminal or a non-disclosing 404."""
    manager, owner, _ = ctx
    try:
        return await asyncio.to_thread(manager.get, owner, str(terminal_id))
    except KeyError as exc:
        raise HTTPException(404, "Terminal not found") from exc


@router.get("/{group}")
async def list_terminals(ctx=Depends(context)):
    """List the conversation's terminal tabs."""
    manager, owner, _ = ctx
    return await asyncio.to_thread(manager.list, owner)


@router.post("/{group}")
async def create_terminal(request: Request, ctx=Depends(context)):
    """Start a real shell in the same directory used by Files and Git."""
    manager, owner, workspace = ctx
    cwd = await get_project_dir_for_request(request, workspace)
    if not await asyncio.to_thread(cwd.is_dir):
        raise HTTPException(400, "Project directory is unavailable")
    try:
        return await asyncio.to_thread(
            manager.create,
            owner,
            cwd,
            asyncio.get_running_loop(),
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{group}/{terminal_id}/output")
async def terminal_output(
    terminal_id: UUID,
    after: int = Query(default=0, ge=0),
    ctx=Depends(context),
):
    """Long-poll output with a resumable, bounded character cursor."""
    session = await owned(ctx, terminal_id)
    return await session.output(after)


@router.post("/{group}/{terminal_id}/input")
async def terminal_input(
    terminal_id: UUID,
    body: TerminalInput,
    ctx=Depends(context),
):
    """Write raw terminal input including control keys."""
    session = await owned(ctx, terminal_id)
    try:
        await asyncio.to_thread(session.write, body.data)
    except (EOFError, OSError, ValueError) as exc:
        raise HTTPException(409, "Terminal has exited") from exc
    return {"ok": True}


@router.post("/{group}/{terminal_id}/resize")
async def terminal_resize(
    terminal_id: UUID,
    body: TerminalSize,
    ctx=Depends(context),
):
    """Apply terminal dimensions without blocking the event loop."""
    session = await owned(ctx, terminal_id)
    await asyncio.to_thread(
        session.resize,
        body.rows,
        body.cols,
    )
    return {"ok": True}


@router.delete("/{group}/{terminal_id}")
async def close_terminal(terminal_id: UUID, ctx=Depends(context)):
    """Explicitly stop this terminal and its children."""
    session = await owned(ctx, terminal_id)
    manager, owner, _ = ctx
    try:
        await asyncio.to_thread(manager.close, owner, session.id)
    except KeyError:
        pass
    return {"ok": True}


@router.patch("/{group}/{terminal_id}")
async def rename_terminal(
    terminal_id: UUID,
    body: TerminalTitle,
    ctx=Depends(context),
):
    """Rename a terminal without recreating its process."""
    session = await owned(ctx, terminal_id)
    if not body.title.strip():
        raise HTTPException(422, "Terminal title must not be empty")
    session.title = body.title.strip()
    return session.info()
