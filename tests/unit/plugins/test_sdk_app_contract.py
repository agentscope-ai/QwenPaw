# -*- coding: utf-8 -*-
"""Public PawApp HTTP, stream and WebSocket lifecycle contracts."""

import asyncio
import json

import pytest

from .sdk_author_fixture import make_plugin

SOURCE = """
import asyncio
from pathlib import Path
from qwenpaw.plugins.apps import (
    PawApp,
    HttpResponse,
    StreamingResponse,
)
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, plugin):
        app = PawApp("Author app", app_id="sdk-app")
        app.enable_standard_capabilities()

        @app.route("/identity")
        async def identity(ctx, request):
            assert not hasattr(ctx, "workspace") and not hasattr(
                ctx, "agent"
            )
            return {
                "app": ctx.app_id,
                "workspace": ctx.workspace_id,
                "user": ctx.user_id,
                "channel": ctx.channel,
            }

        @app.route("/slow-stream")
        async def slow(ctx, request):
            async def chunks():
                try:
                    yield "data: first\\n\\n"
                    await asyncio.sleep(100)
                finally:
                    plugin.storage.write_json(
                        "stream-closed.json", True
                    )

            return StreamingResponse(chunks())

        @app.websocket("/socket")
        async def socket(ctx, connection):
            try:
                while (
                    message := await connection.receive()
                ) is not None:
                    await connection.send(message)
            finally:
                plugin.storage.write_json(
                    "socket-closed.json", True
                )

        async def reply(ctx, args):
            return CommandResult(
                "reply",
                Message(
                    "assistant",
                    (ContentBlock(text="app reply:" + args),),
                ),
            )

        async def wait(ctx, args):
            plugin.storage.write_json("task-entered.json", True)
            try:
                while not (
                    Path(plugin.config.get("directory"))
                    / "task-release"
                ).exists():
                    await asyncio.sleep(0.01)
            finally:
                plugin.storage.write_json("task-stopped.json", True)
            return CommandResult(
                "reply",
                Message(
                    "assistant", (ContentBlock(text="released"),)
                ),
            )

        @app.route("/need-approval", methods=("POST",))
        async def approval(ctx, request):
            approved = await ctx.request_approval(
                "app approval",
                session_id=request.json()["session_id"],
            )
            return {"approved": approved}

        plugin.register_command(CommandSpec("appwait", wait))
        plugin.register_command(CommandSpec("appprobe", reply))
        plugin.register_app(app)


plugin = Plugin()
"""


def app_plugin(tmp_path):
    return make_plugin(tmp_path, SOURCE, ["apps", "commands", "storage"])


async def test_app_http_identity_storage_and_reload(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(app_plugin(tmp_path))
        identity = await host.request(
            "GET",
            "/api/sdk-app/identity",
            workspace_id="one",
            user_id="alice",
        )
        assert identity.status == 200
        assert identity.json() == {
            "app": "sdk-app",
            "workspace": "one",
            "user": "alice",
            "channel": "console",
        }
        forged = await host.request(
            "GET",
            "/api/sdk-app/identity",
            workspace_id="one",
            user_id="alice",
            headers={"X-User-Id": "bob"},
        )
        assert forged.status == 403
        channel = await host.request(
            "GET",
            "/api/sdk-app/identity",
            user_id="alice",
            headers={"X-Channel": "dingtalk"},
        )
        assert channel.status == 403
        app_claim = await host.request(
            "GET",
            "/api/sdk-app/identity",
            user_id="alice",
            headers={"X-PawApp-Id": "sdk-other"},
        )
        assert app_claim.json()["app"] == "sdk-app"
        stored = await host.request(
            "PUT",
            "/api/sdk-app/storage/item.json",
            workspace_id="one",
            user_id="alice",
            json={"value": "alice-one"},
        )
        assert stored.status == 200 and stored.json()["ok"] is True
        for workspace, user in (("one", "bob"), ("two", "alice")):
            value = await host.request(
                "GET",
                "/api/sdk-app/storage/item.json",
                workspace_id=workspace,
                user_id=user,
            )
            assert value.json()["value"] is None
        assert (await host.reload("extension-contract")).ok
        value = await host.request(
            "GET",
            "/api/sdk-app/storage/item.json",
            workspace_id="one",
            user_id="alice",
        )
        assert value.json()["value"] == "alice-one"
        await host.unload("extension-contract")
        assert (
            await host.request("GET", "/api/sdk-app/identity")
        ).status == 404


async def test_app_sessions_and_chat_use_real_scoped_services(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(app_plugin(tmp_path))
        created = await host.request(
            "POST",
            "/api/sdk-app/chat/sessions",
            user_id="alice",
            json={"name": "Author session"},
        )
        assert created.status == 200
        session = created.json()
        assert session["name"] == "Author session"
        other_sessions = (
            await host.request(
                "GET",
                "/api/sdk-app/chat/sessions",
                user_id="bob",
            )
        ).json()["sessions"]
        assert all(row["id"] != session["id"] for row in other_sessions)
        assert all(row["name"] != "Author session" for row in other_sessions)
        renamed = await host.request(
            "PATCH",
            f'/api/sdk-app/chat/sessions/{session["id"]}',
            user_id="alice",
            json={"name": "Renamed"},
        )
        assert renamed.status == 200 and renamed.json()["name"] == "Renamed"
        reply = await host.request(
            "POST",
            "/api/sdk-app/chat",
            user_id="alice",
            json={
                "message": "/appprobe hello",
                "session_id": session["session_id"],
            },
        )
        assert (
            reply.status == 200 and reply.json()["text"] == "app reply:hello"
        )
        assert (await host.reload("extension-contract")).ok
        rows = (
            await host.request(
                "GET",
                "/api/sdk-app/chat/sessions",
                user_id="alice",
            )
        ).json()["sessions"]
        assert any(
            row["id"] == session["id"] and row["name"] == "Renamed"
            for row in rows
        )
        deleted = await host.request(
            "DELETE",
            f'/api/sdk-app/chat/sessions/{session["id"]}',
            user_id="alice",
        )
        assert deleted.status == 200 and deleted.json()["ok"] is True
        remaining = (
            await host.request(
                "GET",
                "/api/sdk-app/chat/sessions",
                user_id="alice",
            )
        ).json()["sessions"]
        assert all(row["id"] != session["id"] for row in remaining)


async def test_http_stream_holds_lifecycle_until_disconnect(tmp_path):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(app_plugin(tmp_path))
        async with host.open_http(
            "GET",
            "/api/sdk-app/slow-stream",
        ) as response:
            assert response.status == 200
            chunks = response.chunks()
            first = asyncio.create_task(anext(chunks))
            assert await asyncio.wait_for(first, 2) == b"data: first\n\n"
            assert first.done()
            with pytest.raises(PluginBusyError):
                await host.reload("extension-contract")
        assert ctx.storage.read_json("stream-closed.json") is True
        assert (
            host.resource_snapshot("extension-contract")["active_calls"] == 0
        )
        assert (await host.reload("extension-contract")).ok


async def test_websocket_holds_lifecycle_and_releases_after_disconnect(
    tmp_path,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(app_plugin(tmp_path))
        async with host.websocket("/api/sdk-app/socket") as connection:
            await connection.send("hello")
            assert await connection.receive() == "hello"
            with pytest.raises(PluginBusyError):
                await host.reload("extension-contract")
        assert ctx.storage.read_json("socket-closed.json") is True
        assert (
            host.resource_snapshot("extension-contract")["active_calls"] == 0
        )
        assert (await host.reload("extension-contract")).ok


async def test_app_task_ownership_cancel_and_actual_callback_stop(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            app_plugin(tmp_path),
            config={"directory": str(tmp_path)},
        )
        started = await host.request(
            "POST",
            "/api/sdk-app/tasks",
            workspace_id="one",
            user_id="alice",
            json={"message": "/appwait", "session_id": "task-session"},
        )
        assert started.status == 200
        task = started.json()
        assert (
            task["status"] == "running"
            and task["run_id"] != task["session_id"]
        )
        try:
            for _ in range(100):
                if ctx.storage.read_json("task-entered.json", False):
                    break
                await asyncio.sleep(0.01)
            assert ctx.storage.read_json("task-entered.json", False)
            for workspace, user in (("one", "bob"), ("two", "alice")):
                foreign = await host.request(
                    "GET",
                    f'/api/sdk-app/tasks/{task["run_id"]}',
                    workspace_id=workspace,
                    user_id=user,
                )
                assert foreign.status != 200
            cancelled = await host.request(
                "POST",
                f'/api/sdk-app/tasks/{task["run_id"]}/cancel',
                workspace_id="one",
                user_id="alice",
            )
            assert cancelled.status == 200
            assert cancelled.json() == {
                "requested": True,
                "stopped": True,
                "timed_out": False,
            }
            assert ctx.storage.read_json("task-stopped.json") is True
            state = await host.request(
                "GET",
                f'/api/sdk-app/tasks/{task["run_id"]}',
                workspace_id="one",
                user_id="alice",
            )
            assert state.json()["status"] == "cancelled"
        finally:
            (tmp_path / "task-release").touch()
            for _ in range(100):
                if (
                    host.resource_snapshot("extension-contract")[
                        "active_calls"
                    ]
                    == 0
                ):
                    break
                await asyncio.sleep(0.01)
        assert (await host.reload("extension-contract")).ok


@pytest.mark.parametrize("approved", [False, True])
async def test_app_approval_is_bound_to_authenticated_scope(
    tmp_path,
    approved,
):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(app_plugin(tmp_path))
        other_root = tmp_path / "other"
        other_root.mkdir()
        other = make_plugin(
            other_root,
            (
                "from qwenpaw.plugins.apps import PawApp\nclass "
                "Plugin:\n    def register(self, ctx):\n        "
                "ctx.register_app(PawApp(app_id='sdk-other').enable_s"
                "tandard_capabilities())\nplugin = Plugin()\n"
            ),
            ["apps"],
        )
        manifest = json.loads((other / "plugin.json").read_text())
        manifest["id"] = "other-app-contract"
        (other / "plugin.json").write_text(json.dumps(manifest))
        await host.load(other)
        waiting = asyncio.create_task(
            host.request(
                "POST",
                "/api/sdk-app/need-approval",
                workspace_id="one",
                user_id="alice",
                json={"session_id": "approval-session"},
            ),
        )
        try:
            for _ in range(100):
                response = await host.request(
                    "GET",
                    "/api/sdk-app/approvals?session_id=approval-session",
                    workspace_id="one",
                    user_id="alice",
                )
                assert response.status == 200
                approvals = response.json()["approvals"]
                if approvals:
                    break
                await asyncio.sleep(0.01)
            assert len(approvals) == 1
            request_id = approvals[0]["request_id"]
            other_list = await host.request(
                "GET",
                "/api/sdk-other/approvals?session_id=approval-session",
                workspace_id="one",
                user_id="alice",
            )
            assert other_list.json()["approvals"] == []
            other_resolve = await host.request(
                "POST",
                f"/api/sdk-other/approvals/{request_id}",
                workspace_id="one",
                user_id="alice",
                json={"approved": True},
            )
            assert other_resolve.status != 200 and not waiting.done()
            for workspace, user in (("one", "bob"), ("two", "alice")):
                foreign = await host.request(
                    "GET",
                    "/api/sdk-app/approvals?session_id=approval-session",
                    workspace_id=workspace,
                    user_id=user,
                )
                assert foreign.json()["approvals"] == []
                rejected = await host.request(
                    "POST",
                    f"/api/sdk-app/approvals/{request_id}",
                    workspace_id=workspace,
                    user_id=user,
                    json={"approved": True},
                )
                assert rejected.status != 200
                assert not waiting.done()
            malformed = await host.request(
                "POST",
                f"/api/sdk-app/approvals/{request_id}",
                workspace_id="one",
                user_id="alice",
                json={"approved": "false"},
            )
            assert malformed.status in (400, 422) and not waiting.done()
            pending = await host.request(
                "GET",
                "/api/sdk-app/approvals?session_id=approval-session",
                workspace_id="one",
                user_id="alice",
            )
            assert [
                row["request_id"] for row in pending.json()["approvals"]
            ] == [
                request_id,
            ]
            resolved = await host.request(
                "POST",
                f"/api/sdk-app/approvals/{request_id}",
                workspace_id="one",
                user_id="alice",
                json={"approved": approved},
            )
            assert (
                resolved.status == 200 and resolved.json()["resolved"] is True
            )
            answer = await asyncio.wait_for(waiting, 2)
            assert answer.json() == {"approved": approved}
        finally:
            if not waiting.done():
                waiting.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiting


async def test_cancelled_app_approval_request_leaves_no_actionable_approval(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(app_plugin(tmp_path))
        waiting = asyncio.create_task(
            host.request(
                "POST",
                "/api/sdk-app/need-approval",
                user_id="alice",
                json={"session_id": "cancelled-request"},
            ),
        )
        try:
            for _ in range(100):
                response = await host.request(
                    "GET",
                    "/api/sdk-app/approvals?session_id=cancelled-request",
                    user_id="alice",
                )
                if response.json()["approvals"]:
                    break
                await asyncio.sleep(0.01)
            assert response.json()["approvals"]
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            response = await host.request(
                "GET",
                "/api/sdk-app/approvals?session_id=cancelled-request",
                user_id="alice",
            )
            assert response.json()["approvals"] == []
            assert (
                host.resource_snapshot("extension-contract")["active_calls"]
                == 0
            )
        finally:
            if not waiting.done():
                waiting.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiting


async def test_websocket_handler_return_closes_connection(tmp_path):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.apps import PawApp
class Plugin:
    def register(self, ctx):
        app = PawApp(app_id="sdk-return-app")
        @app.websocket("/once")
        async def once(call, connection):
            await connection.send("done")
        ctx.register_app(app)
plugin = Plugin()
"""
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, source, ["apps"]))
        async with host.websocket("/api/sdk-return-app/once") as socket:
            assert await socket.receive() == "done"
            assert await asyncio.wait_for(socket.receive(), 1) is None
        assert (
            host.resource_snapshot("extension-contract")["active_calls"] == 0
        )


async def test_complete_http_response_waits_for_actual_scope_cleanup(tmp_path):
    import threading
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import threading
import time
from pathlib import Path
from qwenpaw.plugins.apps import PawApp
class Plugin:
    def register(self, plugin):
        app = PawApp("Cleanup", app_id="cleanup")
        @app.route("/thread")
        async def route(ctx, request):
            directory = Path(plugin.config.get("directory"))
            stop = threading.Event()
            def worker():
                stop.wait()
                (directory / "stopping").touch()
                while not (directory / "release").exists():
                    time.sleep(.005)
                (directory / "finished").touch()
            ctx.resources.thread(worker, stop=stop, description="HTTP worker")
            return {"ok": True}
        plugin.register_app(app)
plugin = Plugin()
"""
    release = tmp_path / "release"
    timer = threading.Timer(0.3, release.touch)
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(tmp_path, source, ["apps", "resources"]),
            config={"directory": str(tmp_path)},
        )
        initial = ctx.resources.snapshot()["resources"]
        timer.start()
        try:
            response = await host.request("GET", "/api/cleanup/thread")
            assert response.status == 200 and response.json() == {"ok": True}
            assert (tmp_path / "stopping").exists()
            assert (
                tmp_path / "finished"
            ).exists(), "Normal response cancelled cleanup"
            assert ctx.resources.snapshot()["resources"] == initial
        finally:
            release.touch()
            timer.cancel()
            timer.join(1)


async def test_http_cleanup_failure_reported_once_then_host_retries(
    tmp_path,
):
    from qwenpaw.plugins import SDKError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from pathlib import Path
from qwenpaw.plugins.apps import PawApp
class Plugin:
    def register(self, plugin):
        app = PawApp("Cleanup retry", app_id="cleanup-retry")
        @app.route("/fail-once")
        async def route(ctx, request):
            async def cleanup():
                marker = Path(plugin.config.get("marker"))
                count = int(marker.read_text()) + 1 if marker.exists() else 1
                marker.write_text(str(count))
                if count == 1:
                    raise RuntimeError("one cleanup failure")
            ctx.resources.defer(cleanup)
            return {"ok": True}
        plugin.register_app(app)
plugin = Plugin()
"""
    marker = tmp_path / "cleanup-count"
    host = PluginTestHost(tmp_path / "host")
    await host.__aenter__()
    try:
        ctx = await host.load(
            make_plugin(tmp_path, source, ["apps", "resources"]),
            config={"marker": str(marker)},
        )
        with pytest.raises(SDKError, match="one cleanup failure"):
            await host.request("GET", "/api/cleanup-retry/fail-once")
        assert marker.read_text() == "1"
        assert ctx.resources.snapshot()["resources"]
        await host.close()
        assert marker.read_text() == "2"
        host.assert_quiescent(ctx.plugin_id)
    finally:
        await host.close()
    # Successful close must restore global host ownership, not just drop the
    # error.
    async with PluginTestHost(tmp_path / "another-host"):
        pass
