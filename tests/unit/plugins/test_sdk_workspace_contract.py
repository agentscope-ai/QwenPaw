# -*- coding: utf-8 -*-
"""Public workspace delegation retains identity and owns finite call scopes."""

import asyncio

import pytest

from .sdk_author_fixture import make_plugin

from .timing import WAIT_TIMEOUT

SOURCE = """
import asyncio
from pathlib import Path
from qwenpaw.plugins import SDKError
from qwenpaw.plugins.apps import PawApp, ChatRequest
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import Message, ContentBlock


class Plugin:
    def register(self, plugin):
        app = PawApp("Scoped app", app_id="workspace-probe")
        saved = None

        def identity(ctx):
            return {
                "app": ctx.app_id,
                "workspace": ctx.workspace_id,
                "user": ctx.user_id,
                "channel": ctx.channel,
                "cancelled": ctx.cancelled,
                "closed": ctx.resources.closed,
            }

        @app.route("/identity")
        async def who(ctx, request):
            return identity(ctx)

        @app.route("/workspaces")
        async def workspaces(ctx, request):
            return {
                "items": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "enabled": item.enabled,
                    }
                    for item in await ctx.workspaces()
                ]
            }

        @app.route("/capture/{workspace}")
        async def capture(ctx, request):
            nonlocal saved
            async with ctx.for_workspace(
                request.path_params["workspace"]
            ) as target:
                saved = target
                self.saved = target
                return identity(target)

        @app.route("/use/{action}", methods=("POST",))
        async def use(ctx, request):
            try:
                action = request.path_params["action"]
                if action == "storage":
                    saved.storage.write_json(
                        "must-not-write.json", True
                    )
                elif action == "chat":
                    await saved.chat("/scopeprobe")
                elif action == "task":
                    await saved.start_task("/scopeprobe")
                elif action == "approval":
                    await saved.request_approval(
                        "must-not-pend",
                        session_id="closed",
                        timeout=0.02,
                    )
                return {"rejected": False}
            except SDKError as error:
                return {
                    "rejected": True,
                    "error": type(error).__name__,
                }

        @app.route("/delegate", methods=("POST",))
        async def delegate(ctx, request):
            async def run():
                await asyncio.sleep(0.01)
                async with saved.for_workspace("two") as target:
                    result = await target.chat("/scopeprobe")
                    plugin.storage.write_json(
                        "delegated.json",
                        {**identity(target), "text": result.text},
                    )

            plugin.resources.task(run(), "delegated test call")
            return {"started": True}

        @app.route("/holding")
        async def holding(ctx, request):
            async with ctx.for_workspace("two") as target:

                async def child():
                    plugin.storage.write_json(
                        "child-entered.json", True
                    )
                    try:
                        await asyncio.Event().wait()
                    finally:
                        plugin.storage.write_json(
                            "child-finished.json", True
                        )

                target.resources.task(
                    child(), "request-owned child"
                )
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    rejected = []
                    try:
                        target.storage.write_json(
                            "cancel-must-not-write.json", True
                        )
                    except SDKError as error:
                        rejected.append(type(error).__name__)
                    try:
                        await target.start_task("/scopeprobe")
                    except SDKError as error:
                        rejected.append(type(error).__name__)
                    plugin.storage.write_json(
                        "cancel-rejections.json", rejected
                    )

                    async def resume():
                        async with target.for_workspace(
                            "two"
                        ) as fresh:
                            result = await fresh.chat("/scopeprobe")
                            plugin.storage.write_json(
                                "cancel-delegated.json",
                                {
                                    **identity(fresh),
                                    "text": result.text,
                                },
                            )

                    plugin.resources.task(
                        resume(), "explicit recovery delegation"
                    )
                    raise
                finally:
                    plugin.storage.write_json(
                        "cancel-observed.json", target.cancelled
                    )

        @app.route("/task", methods=("POST",))
        async def start_task(ctx, request):
            task = await ctx.start_task(
                ChatRequest("/scopewait", session_id="retained")
            )
            return {"id": task.run_id}

        @app.route("/task/{id}")
        async def task(ctx, request):
            return {
                "status": (
                    await ctx.task(request.path_params["id"])
                ).status
            }

        async def reply(call, args):
            return CommandResult(
                "reply",
                Message(
                    "assistant",
                    (ContentBlock(text="scoped-reply"),),
                ),
            )

        async def wait(call, args):
            while not (
                Path(plugin.config.get("directory")) / "release"
            ).exists():
                await asyncio.sleep(0.01)
            return await reply(call, args)

        plugin.register_command(CommandSpec("scopeprobe", reply))
        plugin.register_command(CommandSpec("scopewait", wait))
        plugin.register_app(app)


plugin = Plugin()
"""


async def setup(host, tmp_path):
    ctx = await host.load(
        make_plugin(
            tmp_path,
            SOURCE,
            ["apps", "commands", "storage", "config"],
        ),
        config={"directory": str(tmp_path)},
    )
    for workspace in ("one", "two"):
        assert (
            await host.request(
                "GET",
                "/api/workspace-probe/identity",
                workspace_id=workspace,
                user_id="alice",
            )
        ).status == 200
    return ctx


async def test_workspace_delegation_identity_unknown_and_closed_scope(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await setup(host, tmp_path)
        response = await host.request(
            "GET",
            "/api/workspace-probe/workspaces",
            workspace_id="one",
            user_id="alice",
        )
        items = response.json()["items"]
        assert {item["id"] for item in items} >= {"one", "two"}
        assert all(set(item) == {"id", "name", "enabled"} for item in items)
        unknown = await host.request(
            "GET",
            "/api/workspace-probe/capture/missing",
            workspace_id="one",
            user_id="alice",
        )
        assert unknown.status == 403
        captured = await host.request(
            "GET",
            "/api/workspace-probe/capture/two",
            workspace_id="one",
            user_id="alice",
        )
        assert captured.json() == {
            "app": "workspace-probe",
            "workspace": "two",
            "user": "alice",
            "channel": "console",
            "cancelled": False,
            "closed": False,
        }
        for action in ("storage", "chat", "task", "approval"):
            response = await host.request(
                "POST",
                "/api/workspace-probe/use/" + action,
                workspace_id="one",
                user_id="alice",
            )
            assert response.json() == {
                "rejected": True,
                "error": "StaleContextError",
            }, action


async def test_explicit_background_delegation_and_started_task_survive_request(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await setup(host, tmp_path)
        assert (
            await host.request(
                "GET",
                "/api/workspace-probe/capture/two",
                user_id="alice",
            )
        ).status == 200
        assert (
            await host.request(
                "POST",
                "/api/workspace-probe/delegate",
                user_id="alice",
            )
        ).status == 200
        async with asyncio.timeout(WAIT_TIMEOUT):
            while True:
                value = ctx.storage.read_json("delegated.json", None)
                if value is not None:
                    break
                await asyncio.sleep(0.01)
        assert value == {
            "app": "workspace-probe",
            "workspace": "two",
            "user": "alice",
            "channel": "console",
            "cancelled": False,
            "closed": False,
            "text": "scoped-reply",
        }
        started = await host.request(
            "POST",
            "/api/workspace-probe/task",
            user_id="alice",
        )
        assert started.status == 200
        path = "/api/workspace-probe/task/" + started.json()["id"]
        try:
            assert (await host.request("GET", path, user_id="alice")).json()[
                "status"
            ] == "running"
            assert (
                await host.request("GET", path, user_id="bob")
            ).status == 403
            (tmp_path / "release").touch()
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    status = (
                        await host.request("GET", path, user_id="alice")
                    ).json()["status"]
                    if status != "running":
                        break
                    await asyncio.sleep(0.01)
            assert status == "completed"
        finally:
            (tmp_path / "release").touch()


async def test_request_cancellation_finishes_delegated_resources(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await setup(host, tmp_path)
        pending = asyncio.create_task(
            host.request(
                "GET",
                "/api/workspace-probe/holding",
                user_id="alice",
            ),
        )
        try:
            async with asyncio.timeout(WAIT_TIMEOUT):
                while not ctx.storage.read_json("child-entered.json", False):
                    await asyncio.sleep(0.01)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert ctx.storage.read_json("cancel-observed.json") is True
            assert ctx.storage.read_json("child-finished.json") is True
            assert ctx.storage.read_json("cancel-rejections.json") == [
                "StaleContextError",
                "StaleContextError",
            ]
            async with asyncio.timeout(WAIT_TIMEOUT):
                while (
                    ctx.storage.read_json("cancel-delegated.json", None)
                    is None
                ):
                    await asyncio.sleep(0.01)
            recovered = ctx.storage.read_json("cancel-delegated.json")
            assert recovered == {
                "app": "workspace-probe",
                "workspace": "two",
                "user": "alice",
                "channel": "console",
                "cancelled": False,
                "closed": False,
                "text": "scoped-reply",
            }
            host.assert_quiescent("extension-contract")
        finally:
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
