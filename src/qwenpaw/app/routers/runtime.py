# -*- coding: utf-8 -*-
"""Shared runtime connections, independent of user login sessions."""

import asyncio
import hmac
import os
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..computer_use.runtime import HostRuntimeProvider
from ...tauri.env import RUNTIME_CONTROL_TOKEN_ENV

router = APIRouter(prefix="/api/runtime")


def authenticate(
    request: Request,
    x_qwenpaw_control_token: str = Header(default=""),
):
    """Only a local client holding this instance's secret may attach."""
    expected = os.environ.get(RUNTIME_CONTROL_TOKEN_ENV, "")
    supplied = x_qwenpaw_control_token
    if (
        bool(os.environ.get("QWENPAW_RUNTIME_ID"))
        or os.environ.get("QWENPAW_RUNTIME_MODE") != "shared"
        or not expected
        or not supplied.isascii()
        or not hmac.compare_digest(expected, supplied)
    ):
        raise HTTPException(status_code=404, detail="Not Found")
    server = getattr(request.app.state, "uvicorn_server", None)
    if server is None or server.should_exit:
        raise HTTPException(status_code=503, detail="Backend unavailable")
    return server


class ClientConnection(BaseModel):
    """A native client's optional loopback Computer Use endpoint."""

    client: str = Field(default="client", min_length=1, max_length=64)
    installation: str = Field(default="", max_length=4096)
    control_port: int | None = Field(default=None, ge=1, le=65535)
    control_token: str = Field(default="", max_length=256)


@router.post("/connect")
async def connect(
    connection: ClientConnection,
    request: Request,
    server=Depends(authenticate),
):
    """Keep one host registration alive until the native client disconnects."""
    if server.should_exit:
        raise HTTPException(status_code=503, detail="Backend unavailable")
    client_id = uuid.uuid4().hex
    clients = request.app.state.runtime_clients

    async def events():
        if server.should_exit:
            return
        try:
            clients[client_id] = (connection.client, connection.installation)
            HostRuntimeProvider.register_host(
                client_id,
                connection.control_port,
                connection.control_token,
            )
            while not server.should_exit:
                yield f": connected\n\n"
                await asyncio.sleep(5)
        finally:
            clients.pop(client_id, None)
            HostRuntimeProvider.unregister_host(client_id)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "X-QwenPaw-Instance": request.app.state.runtime_instance.instance,
            "X-QwenPaw-Client": client_id,
            "Cache-Control": "no-store",
        },
    )


@router.get("/clients")
async def connected_clients(
    request: Request,
    x_qwenpaw_client: str = Header(default=""),
    _server=Depends(authenticate),
):
    """Report other clients before presenting a last-client close choice."""
    others = request.app.state.runtime_clients.keys() - {x_qwenpaw_client}
    return {
        "other_clients": len(others),
        "clients": [
            {"client": client, "installation": installation}
            for client, installation in (
                request.app.state.runtime_clients[key] for key in others
            )
        ],
    }


@router.post("/shutdown")
async def shutdown(
    request: Request,
    x_qwenpaw_client: str = Header(default=""),
    server=Depends(authenticate),
):
    """Explicitly stop the shared runtime, including its active sessions."""
    others = request.app.state.runtime_clients.keys() - {x_qwenpaw_client}
    if others:
        raise HTTPException(
            status_code=409,
            detail={"code": "runtime_clients_connected", "count": len(others)},
        )
    # Admission and the last-client check have no intervening await.
    request.app.state.runtime_instance.request_stop()
    server.should_exit = True
    return {"ok": True}
