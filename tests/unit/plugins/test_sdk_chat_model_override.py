# -*- coding: utf-8 -*-
"""Per-call model selection preserves app history and workspace defaults."""

import asyncio
import pytest

from qwenpaw.plugins.apps import ChatRequest
from qwenpaw.plugins.models import ModelSelection
from qwenpaw.plugins.testing import PluginTestHost
from qwenpaw.plugins.errors import SDKError
from .sdk_author_fixture import make_plugin

SOURCE = """
from qwenpaw.plugins.apps import PawApp, ChatRequest
from qwenpaw.plugins.models import ModelSelection
from qwenpaw.plugins.providers import ProviderSpec, ModelInfo, ModelChunk
from qwenpaw.plugins.messages import ContentBlock


class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            ctx.storage.write_json(
                request.model_id + ".json",
                [
                    block.text
                    for message in request.messages
                    if message.role == "user"
                    for block in message.content
                ],
            )
            yield ModelChunk(
                (ContentBlock(text="chosen:" + request.model_id),),
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
            )
        )
        app = PawApp(app_id="model-selection")

        @app.route("/chat", methods=("POST",))
        async def chat(call, request):
            data = request.json()
            model = (
                ModelSelection("selection", data["model"])
                if data.get("model")
                else None
            )
            reply = await call.chat(
                ChatRequest(
                    data["text"], session_id=data.get("session"), model=model
                )
            )
            configured = await call.models.configured()
            history = await call.history(data.get("session"))
            return {
                "text": reply.text,
                "configured": configured.model_id,
                "history": len(history),
            }

        ctx.register_app(app)


plugin = Plugin()
"""


async def test_standard_routes_validate_and_forward_model(tmp_path):
    import json

    async with PluginTestHost(tmp_path / "host") as host:
        source = make_plugin(
            tmp_path,
            SOURCE.replace(
                '@app.route("/chat"',
                '@app.route("/probe"',
            ).replace(
                "ctx.register_app(app)",
                "app.enable_standard_capabilities(); ctx.register_app(app)",
            ),
            ["providers", "apps", "storage", "models"],
        )
        manifest = json.loads((source / "plugin.json").read_text())
        manifest["sdk"]["version"] = "1.2.0"
        (source / "plugin.json").write_text(json.dumps(manifest))
        await host.load(source)
        await host.configure_chat_model("selection", "first")
        model = {"provider_id": "selection", "model_id": "second"}
        for path in ("chat", "chat/stream"):
            response = await host.request(
                "POST",
                f"/api/model-selection/{path}",
                json={"message": "standard override", "model": model},
            )
            assert response.status == 200, response.text
            assert "chosen:second" in response.text
        for path in ("chat", "chat/stream", "tasks"):
            for invalid in (
                "second",
                {},
                {**model, "secret": "x"},
                {**model, "model_id": 2},
            ):
                response = await host.request(
                    "POST",
                    f"/api/model-selection/{path}",
                    json={"message": "invalid", "model": invalid},
                )
                assert response.status == 422, response.text
        started = await host.request(
            "POST",
            "/api/model-selection/tasks",
            json={"message": "background override", "model": model},
        )
        assert started.status == 200, started.text
        for _ in range(100):
            task = await host.request(
                "GET",
                "/api/model-selection/tasks/" + started.json()["run_id"],
            )
            if task.json()["status"] != "running":
                break
            await asyncio.sleep(0.02)
        assert task.json()["status"] == "completed", task.text
        assert task.json()["result"] == "chosen:second"
        from qwenpaw.config.config import load_agent_config, save_agent_config
        from qwenpaw.providers.provider_manager import ProviderManager

        profile = load_agent_config("test")
        profile.active_model = None
        save_agent_config("test", profile)
        ProviderManager.get_instance().active_model = None
        response = await host.request(
            "POST",
            "/api/model-selection/chat",
            json={"message": "no default configured", "model": model},
        )
        assert response.status == 200, response.text
        assert response.json()["text"] == "chosen:second"
        assert load_agent_config("test").active_model is None
        assert ProviderManager.get_instance().get_active_model() is None


async def test_app_override_keeps_history_default_and_concurrent_choices(
    tmp_path,
):
    async with PluginTestHost(tmp_path / "host") as host:
        source = make_plugin(
            tmp_path,
            SOURCE,
            ["providers", "apps", "storage", "models"],
        )
        import json

        manifest = json.loads((source / "plugin.json").read_text())
        manifest["sdk"]["version"] = "1.2.0"
        (source / "plugin.json").write_text(json.dumps(manifest))
        plugin = await host.load(source)
        await host.configure_chat_model("selection", "first")

        async def chat(text, model=None, session="same"):
            result = await host.request(
                "POST",
                "/api/model-selection/chat",
                json={"text": text, "model": model, "session": session},
            )
            assert result.status == 200, result.text
            return result.json()

        chosen = await chat("first question", "second")
        default = await chat("follow up")
        assert (
            chosen["text"] == "chosen:second"
            and default["text"] == "chosen:first"
        )
        assert chosen["configured"] == default["configured"] == "first"
        assert default["history"] > chosen["history"]
        assert "first question" in plugin.storage.read_json("first.json")
        first, second = await asyncio.gather(
            chat("one", "first", "one"),
            chat("two", "second", "two"),
        )
        assert (
            first["text"] == "chosen:first"
            and second["text"] == "chosen:second"
        )
        with pytest.raises(SDKError, match="nonempty"):
            await host.request(
                "POST",
                "/api/model-selection/chat",
                json={"text": "bad", "model": " "},
            )
        events = [
            event
            async for event in host.stream_chat(
                ChatRequest(
                    "test host override",
                    model=ModelSelection("selection", "second"),
                ),
            )
        ]
        assert any(
            "chosen:second" in block.text
            for event in events
            for message in event.output
            for block in message.content
        )
