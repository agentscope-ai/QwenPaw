# -*- coding: utf-8 -*-
"""The tool-call output SSE must not be buffered by reverse proxies."""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from qwenpaw.app.routers.tool_calls import router


class _Stream:
    async def subscribe(self):
        if False:  # pragma: no cover - empty async generator
            yield None


def test_tool_call_stream_disables_proxy_buffering() -> None:
    entry = SimpleNamespace(
        ctx=SimpleNamespace(session_id="s1"),
        stream=_Stream(),
    )
    coordinator = SimpleNamespace(get=lambda _tool_call_id: entry)
    app = FastAPI()
    app.state.app_services = SimpleNamespace(tool_coordinator=coordinator)
    app.include_router(router)

    response = TestClient(app).get("/tool-calls/s1/tc1/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
