# -*- coding: utf-8 -*-
"""PawApp chat and tasks use the Agent's configured model."""

import asyncio

from qwenpaw.plugins.apps import PawApp
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.providers import ModelChunk, ModelInfo, ProviderSpec


async def test_pawapp_routes_use_the_configured_agent_model(sdk_component):
    def declare(ctx):
        async def generate(call, request):
            yield ModelChunk(
                (ContentBlock(text=f"chosen:{request.model_id}"),),
                is_last=True,
            )

        ctx.register_provider(
            ProviderSpec(
                "selection",
                "Selection",
                generate,
                models=(
                    ModelInfo("first", "First"),
                    ModelInfo("second", "Second"),
                ),
                require_api_key=False,
            ),
        )
        app = PawApp(app_id="model-selection")
        app.enable_standard_capabilities()
        ctx.register_app(app)

    async with sdk_component(declare, capabilities=("providers", "apps")) as (
        host,
        _,
    ):
        await host.configure_chat_model("selection", "first")
        base = "/api/model-selection"
        payload = {
            "message": "hello",
            "model": {"provider_id": "selection", "model_id": "second"},
        }
        for path in ("chat", "chat/stream"):
            response = await host.request(
                "POST",
                f"{base}/{path}",
                json=payload,
            )
            assert response.status == 200, response.text
            assert "chosen:first" in response.text
            assert "chosen:second" not in response.text

        started = await host.request("POST", f"{base}/tasks", json=payload)
        assert started.status == 200, started.text
        task_url = f"{base}/tasks/{started.json()['run_id']}"
        async with asyncio.timeout(5):
            while True:
                response = await host.request("GET", task_url)
                assert response.status == 200, response.text
                task = response.json()
                if task["status"] != "running":
                    break
                await asyncio.sleep(0.02)
        assert task["status"] == "completed", task
        assert task["result"] == "chosen:first"
