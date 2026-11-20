# -*- coding: utf-8 -*-
"""A PawApp's run queries retain the same session boundary as its history."""

from dataclasses import asdict

from qwenpaw.plugins.apps import PawApp
from qwenpaw.plugins.commands import CommandResult, CommandSpec
from qwenpaw.plugins.messages import ContentBlock, Message
from .sdk_author_fixture import make_plugin


async def test_app_queries_do_not_list_main_chat_or_another_app(
    sdk_component,
    tmp_path,
):
    def declare(ctx):
        async def reply(call, arguments):
            return CommandResult(
                "reply",
                Message("assistant", (ContentBlock(text="done"),)),
            )

        ctx.register_command(CommandSpec("reply", reply))
        for name in ("run-one",):
            app = PawApp(app_id=name)

            @app.route("/runs")
            async def runs(call, request):
                return [asdict(item) for item in await call.runs.list()]

            @app.route("/start", methods=("POST",))
            async def start(call, request):
                await call.chat("/reply")
                return [asdict(item) for item in await call.runs.list()]

            ctx.register_app(app)

    async with sdk_component(declare, capabilities=("commands", "apps")) as (
        host,
        ctx,
    ):
        await host.load(
            make_plugin(
                tmp_path,
                """
from qwenpaw.plugins.apps import PawApp
class Plugin:
    def register(self, ctx):
        app = PawApp(app_id="run-two")
        @app.route("/start", methods=("POST",))
        async def start(call, request):
            await call.chat("/reply")
            return {"ok": True}
        ctx.register_app(app)
plugin = Plugin()
""",
                ["apps"],
            ),
        )
        foreign = await host.request(
            "POST",
            "/api/run-two/start",
            user_id="alice",
        )
        assert foreign.status == 200
        _ = [
            event
            async for event in host.stream_chat("/reply", user_id="alice")
        ]
        before = await host.request(
            "GET",
            "/api/run-one/runs",
            user_id="alice",
        )
        assert before.status == 200
        assert (
            before.json() == []
        ), "Main conversation runs are outside the app's scope"
        started = await host.request(
            "POST",
            "/api/run-one/start",
            user_id="alice",
        )
        assert started.status == 200
        assert len(started.json()) == 1
        other = await host.request("GET", "/api/run-one/runs", user_id="bob")
        assert other.status == 200 and other.json() == []
