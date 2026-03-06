# -*- coding: utf-8 -*-
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from copaw.app.routers.wecom import sync_wecom_callback_routes, wecom_router


class _DummyChannel:
    def __init__(self, channel: str, webhook_path: str) -> None:
        self.channel = channel
        self.webhook_path = webhook_path

    async def handle_callback(
        self,
        *,
        method: str,
        request_url: str,
        body_text: str,
    ) -> tuple[int, str, str]:
        del body_text
        return (
            200,
            "text/plain; charset=utf-8",
            (f"{self.channel}:{method}:{request_url}"),
        )


def _build_app(*channels: _DummyChannel) -> FastAPI:
    app = FastAPI()
    app.include_router(wecom_router)
    app.state.channel_manager = SimpleNamespace(channels=list(channels))
    sync_wecom_callback_routes(app, app.state.channel_manager)
    return app


def test_sync_wecom_callback_routes_registers_alias_path() -> None:
    app = _build_app(_DummyChannel("wecom", "/custom-wecom"))
    client = TestClient(app)

    resp = client.get("/custom-wecom?timestamp=1&nonce=2&msg_signature=3")

    assert resp.status_code == 200
    assert resp.text.startswith("wecom:GET:")


def test_sync_wecom_callback_routes_replaces_old_alias_path() -> None:
    app = _build_app(_DummyChannel("wecom_app", "/old-wecom-app"))
    client = TestClient(app)
    assert client.get("/old-wecom-app").status_code == 200

    app.state.channel_manager = SimpleNamespace(
        channels=[_DummyChannel("wecom_app", "/new-wecom-app")],
    )
    sync_wecom_callback_routes(app, app.state.channel_manager)

    assert client.get("/old-wecom-app").status_code == 404
    assert client.get("/new-wecom-app").status_code == 200
