"""QQ native QR → actual GUI-shaped authenticated config save."""

import asyncio
from importlib import import_module
import os
from urllib.parse import urlsplit

from fastapi import FastAPI
import httpx
import psutil
import pytest

from g3fd_dd_native_support import g3_host_import_boundary, native_qr

__all__ = ["g3_host_import_boundary", "native_qr"]


@pytest.mark.asyncio
@pytest.mark.parametrize("openid", ["native-user", None])
async def test_native_qq_gui_credentials_save_without_inventing_acl(
    native_qr, openid
):
    from qwenpaw.app.multi_agent_manager import MultiAgentManager
    from qwenpaw.config.config import load_agent_config

    native_qr.qq_openid = openid
    qr = await native_qr("qq")
    fetched = await qr.sessions.fetch(qr.scope, {})
    result = await qr.sessions.poll(qr.scope, fetched.poll_token)
    credentials = {
        "app_id": "native-app",
        "client_secret": "native-secret",
        "user_openid": openid or "",
    }
    assert result.status == "success"
    assert result.credentials == credentials
    assert len(qr.requests) == 2
    assert [urlsplit(row["url"]).path for row in qr.requests] == [
        "/lite/create_bind_task",
        "/lite/poll_bind_result",
    ]
    assert qr.requests[1]["fields"] == {"task_id": "native-task"}
    assert len({row["pid"] for row in qr.requests}) == 2
    assert all(
        row["pid"] != os.getpid() and not psutil.pid_exists(row["pid"])
        for row in qr.requests
    )
    manager = MultiAgentManager()
    manager.channel_qrcode_sessions = qr.sessions
    app = FastAPI()
    app.include_router(import_module("qwenpaw.app.routers.config").router)
    app.state.plugin_loader = qr.loader
    app.state.channel_management = qr.service
    app.state.channel_qrcode_sessions = qr.sessions
    app.state.multi_agent_manager = manager
    before = load_agent_config("A").channels.model_dump()["qq"]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.put(
            "/config/channels/qq",
            json={**qr.scope.config, **credentials},
            headers={
                "X-Agent-Id": "A",
                "X-Channel-Auth-Session": fetched.poll_token,
            },
        )
    await asyncio.sleep(0)
    assert response.status_code == 200, response.text
    saved = load_agent_config("A").channels.model_dump()["qq"]
    assert saved["app_id"] == "native-app"
    assert saved["client_secret"] == "native-secret"
    assert saved["allow_from"] == before["allow_from"]
    assert saved["access_control_dm"] == before["access_control_dm"]
    assert saved["access_control_group"] == before["access_control_group"]
    assert len(qr.requests) == 2
