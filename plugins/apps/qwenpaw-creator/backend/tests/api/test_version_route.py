# -*- coding: utf-8 -*-
"""``GET /version`` reports the plugin identity straight from plugin.json."""

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.router import router


def test_version_endpoint_reports_plugin_identity():
    manifest = json.loads(
        (Path(__file__).resolve().parents[3] / "plugin.json").read_text(
            encoding="utf-8",
        ),
    )
    app = FastAPI()
    app.include_router(router)

    async def scenario():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            return await client.get("/version")

    response = asyncio.run(scenario())

    assert response.status_code == 200
    assert response.json() == {
        "plugin_id": manifest["id"],
        "version": manifest["version"],
        "runtime": "creator-filesystem",
    }
