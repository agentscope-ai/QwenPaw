# -*- coding: utf-8 -*-
"""Task status streams reconnect without cancelling the owned run."""

import asyncio
import json

import pytest

from .sdk_author_fixture import make_plugin

from .timing import WAIT_TIMEOUT

SOURCE = """
import asyncio
from pathlib import Path
from qwenpaw.plugins.apps import PawApp
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.messages import Message, ContentBlock


class Plugin:
    def register(self, plugin):
        async def wait(call, args):
            plugin.storage.write_json("started.json", True)
            while not Path(plugin.config.get("release")).exists():
                await asyncio.sleep(0.01)
            return CommandResult(
                "reply",
                Message(
                    "assistant",
                    (ContentBlock(text="task result:" + args),),
                ),
            )

        plugin.register_command(CommandSpec("statuswait", wait))
        plugin.register_app(
            PawApp(
                app_id="status-app"
            ).enable_standard_capabilities()
        )


plugin = Plugin()
"""


async def read_status(chunks):
    buffer = ""
    for _ in range(20):
        buffer += (
            await asyncio.wait_for(anext(chunks), WAIT_TIMEOUT)
        ).decode()
        for part in buffer.split("\n\n")[:-1]:
            for line in part.splitlines():
                if line.startswith("data:"):
                    value = json.loads(line[5:].strip())
                    if "status" in value:
                        return value
    pytest.fail("Task SSE did not provide a status snapshot")


async def test_app_task_status_disconnect_reconnect_and_cold_terminal(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    release = tmp_path / "release"
    package = make_plugin(
        tmp_path,
        SOURCE,
        ["apps", "commands", "storage", "config"],
    )
    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        ctx = await host.load(package, config={"release": str(release)})
        started = await host.request(
            "POST",
            "/api/status-app/tasks",
            user_id="alice",
            json={
                "message": "/statuswait retained",
                "session_id": "status-session",
            },
        )
        assert started.status == 200
        run_id = started.json()["run_id"]
        path = f"/api/status-app/tasks/{run_id}"
        try:
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    if ctx.storage.read_json("started.json", False):
                        break
                    await asyncio.sleep(0.01)
            assert ctx.storage.read_json("started.json", False)
            async with host.open_http(
                "GET",
                path + "/stream",
                user_id="bob",
            ) as response:
                assert response.status in (403, 404)
            async with host.open_http(
                "GET",
                path + "/stream",
                user_id="alice",
            ) as response:
                assert response.status == 200
                current = await read_status(response.chunks())
                assert (
                    current["status"] == "running"
                    and current["run_id"] == run_id
                )
            assert (await host.request("GET", path, user_id="alice")).json()[
                "status"
            ] == "running"
            async with host.open_http(
                "GET",
                path + "/stream",
                user_id="alice",
            ) as response:
                chunks = response.chunks()
                assert (await read_status(chunks))["status"] == "running"
                release.touch()
                terminal = await read_status(chunks)
                assert terminal["status"] == "completed"
                assert terminal["result"] == "task result:retained"
                assert terminal["result_truncated"] is False
                with pytest.raises(StopAsyncIteration):
                    await asyncio.wait_for(anext(chunks), WAIT_TIMEOUT)
            assert (await host.reload("extension-contract")).ok
            assert (await host.request("GET", path, user_id="alice")).json()[
                "result"
            ] == "task result:retained"
        finally:
            release.touch()
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    if (
                        host.resource_snapshot("extension-contract")[
                            "active_calls"
                        ]
                        == 0
                    ):
                        break
                    await asyncio.sleep(0.01)
    async with PluginTestHost(root) as fresh:
        await fresh.load(package, config={"release": str(release)})
        terminal = await fresh.request("GET", path, user_id="alice")
        assert (
            terminal.status == 200 and terminal.json()["status"] == "completed"
        )
        assert terminal.json()["result"] == "task result:retained"
        assert (await fresh.request("GET", path, user_id="bob")).status in (
            403,
            404,
        )


@pytest.mark.parametrize("phase", ["running", "terminal"])
async def test_task_status_storage_failure_does_not_orphan_real_run(
    tmp_path,
    monkeypatch,
    phase,
):
    from qwenpaw.plugins.testing import PluginTestHost

    release = tmp_path / "release"
    package = make_plugin(
        tmp_path,
        SOURCE,
        ["apps", "commands", "storage", "config"],
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(package, config={"release": str(release)})
        write = ctx.storage.write_json
        faults = []

        def failing_write(key, value, *args, **kwargs):
            matching = str(key).startswith("sdk-task-status/") and (
                (phase == "running") == (value.get("status") == "running")
            )
            if matching and not faults:
                faults.append(value["status"])
                raise OSError("controlled-task-status-save-failure")
            return write(key, value, *args, **kwargs)

        monkeypatch.setattr(ctx.storage, "write_json", failing_write)
        try:
            if phase == "running":
                try:
                    response = await host.request(
                        "POST",
                        "/api/status-app/tasks",
                        user_id="alice",
                        json={
                            "message": "/statuswait orphan",
                            "session_id": "write-failure",
                        },
                    )
                except OSError as error:
                    assert "controlled-task-status-save-failure" in str(error)
                else:
                    assert response.status >= 500
                assert faults == ["running"]
                await asyncio.sleep(0.05)
                host.assert_quiescent("extension-contract")
            else:
                response = await host.request(
                    "POST",
                    "/api/status-app/tasks",
                    user_id="alice",
                    json={
                        "message": "/statuswait terminal",
                        "session_id": "write-failure",
                    },
                )
                assert response.status == 200
                path = "/api/status-app/tasks/" + response.json()["run_id"]
                release.touch()
                async with asyncio.timeout(WAIT_TIMEOUT):
                    while True:
                        current = (
                            await host.request("GET", path, user_id="alice")
                        ).json()
                        if current["status"] != "running":
                            break
                        await asyncio.sleep(0.01)
                assert faults == ["completed"]
                assert current["status"] == "failed"
                assert (
                    "controlled-task-status-save-failure" in current["error"]
                )
                host.assert_quiescent("extension-contract")
        finally:
            monkeypatch.setattr(ctx.storage, "write_json", write)
            release.touch()
            async with asyncio.timeout(WAIT_TIMEOUT):
                while True:
                    if (
                        host.resource_snapshot("extension-contract")[
                            "active_calls"
                        ]
                        == 0
                    ):
                        break
                    await asyncio.sleep(0.01)


async def test_cancel_does_not_report_stopped_while_provider_is_still_running(
    tmp_path,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import asyncio
from pathlib import Path
from qwenpaw.plugins.apps import PawApp
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)


class Plugin:
    def register(self, plugin):
        async def generate(call, request):
            other = any(
                block.text == "unrelated run"
                for message in request.messages
                for block in message.content
                if block.type == "text"
            )
            suffix = "-other" if other else ""
            plugin.storage.write_json(
                "provider-entered" + suffix + ".json", True
            )
            try:
                yield ModelChunk((ContentBlock(text="started"),))
                plugin.storage.write_json(
                    "provider-waiting" + suffix + ".json", True
                )
                while not Path(
                    plugin.config.get("release") + suffix
                ).exists():
                    try:
                        await asyncio.sleep(0.01)
                    except asyncio.CancelledError:
                        plugin.storage.write_json(
                            "provider-resisted" + suffix + ".json",
                            True,
                        )
                yield ModelChunk(
                    (ContentBlock(text="finished"),), is_last=True
                )
            finally:
                plugin.storage.write_json(
                    "provider-stopped" + suffix + ".json", True
                )

        plugin.register_provider(
            ProviderSpec(
                "cancel-probe",
                "Cancellation probe",
                generate,
                models=(ModelInfo("probe-model", "Probe"),),
                require_api_key=False,
            )
        )
        app = PawApp(
            app_id="cancel-probe"
        ).enable_standard_capabilities()

        @app.route("/stop/{run_id}", methods=("POST",))
        async def stop(ctx, request):
            result = await ctx.cancel_task(
                request.path_params["run_id"], timeout=0.05
            )
            return {
                "requested": result.requested,
                "stopped": result.stopped,
                "timed_out": result.timed_out,
            }

        plugin.register_app(app)


plugin = Plugin()
"""
    release = tmp_path / "release"
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["apps", "providers", "storage", "config"],
            ),
            config={"release": str(release)},
        )
        await host.configure_chat_model("cancel-probe", "probe-model")
        started = await host.request(
            "POST",
            "/api/cancel-probe/tasks",
            user_id="alice",
            json={
                "message": "controlled cancellation",
                "session_id": "cancel-owned",
            },
        )
        assert started.status == 200
        path = "/api/cancel-probe/stop/" + started.json()["run_id"]
        other = await host.request(
            "POST",
            "/api/cancel-probe/tasks",
            user_id="bob",
            json={"message": "unrelated run", "session_id": "cancel-owned"},
        )
        assert other.status == 200
        other_path = "/api/cancel-probe/tasks/" + other.json()["run_id"]
        other_release = tmp_path / "release-other"
        try:
            async with asyncio.timeout(WAIT_TIMEOUT):
                while not all(
                    ctx.storage.read_json(key, False)
                    for key in (
                        "provider-waiting.json",
                        "provider-waiting-other.json",
                    )
                ):
                    await asyncio.sleep(0.01)
            response = await host.request("POST", path, user_id="alice")
            assert response.status == 200
            assert response.json()["stopped"] is False
            assert ctx.storage.read_json("provider-resisted.json") is True
            assert (
                ctx.storage.read_json("provider-stopped.json", False) is False
            )
            assert (
                ctx.storage.read_json("provider-resisted-other.json", False)
                is False
            )
            assert (
                await host.request("GET", other_path, user_id="bob")
            ).json()["status"] == "running"
            other_release.touch()
            async with asyncio.timeout(WAIT_TIMEOUT):
                while (
                    await host.request("GET", other_path, user_id="bob")
                ).json()["status"] == "running":
                    await asyncio.sleep(0.01)
            assert ctx.storage.read_json("provider-stopped-other.json") is True
            with pytest.raises(PluginBusyError):
                await host.reload("extension-contract")
            again = await host.request("POST", path, user_id="alice")
            assert again.json()["stopped"] is False
            assert (
                ctx.storage.read_json("provider-stopped.json", False) is False
            )
            release.touch()
            status_path = "/api/cancel-probe/tasks/" + started.json()["run_id"]
            # Provider exit precedes resource cleanup and terminal persistence.
            # Wait for the entire run without sending another cancellation.
            async with asyncio.timeout(WAIT_TIMEOUT):
                while (
                    await host.request("GET", status_path, user_id="alice")
                ).json()["status"] == "running":
                    await asyncio.sleep(0.01)
                while host.resource_snapshot("extension-contract")[
                    "active_calls"
                ]:
                    await asyncio.sleep(0.01)
            assert (
                await host.request("GET", status_path, user_id="alice")
            ).json()["status"] == "cancelled"
            assert ctx.storage.read_json("provider-stopped.json") is True
            retry = await host.request("POST", path, user_id="alice")
            assert retry.json()["stopped"] is True
        finally:
            release.touch()
            other_release.touch()
            async with asyncio.timeout(WAIT_TIMEOUT):
                while host.resource_snapshot("extension-contract")[
                    "active_calls"
                ]:
                    await asyncio.sleep(0.01)


async def test_cancel_keeps_run_owned_until_failed_thread_scope_really_stops(
    tmp_path,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
import asyncio, threading, time
from pathlib import Path
from qwenpaw.plugins.apps import PawApp
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
)
from qwenpaw.plugins.messages import ContentBlock


class Plugin:
    def register(self, plugin):
        def worker():
            tick = 0
            while not Path(plugin.config.get("release")).exists():
                tick += 1
                plugin.storage.write_json("ticks.json", tick)
                time.sleep(0.02)
            plugin.storage.write_json("thread-stopped.json", True)

        async def generate(ctx, request):
            other = any(
                b.text == "independent"
                for m in request.messages
                for b in m.content
                if b.type == "text"
            )
            if other:
                yield ModelChunk(
                    (ContentBlock(text="independent completed"),),
                    is_last=True,
                )
                return
            plugin.storage.write_json(
                "calls.json",
                plugin.storage.read_json("calls.json", 0) + 1,
            )
            ctx.resources.thread(
                worker,
                stop=threading.Event(),
                description="noncooperative run thread",
            )
            try:
                yield ModelChunk((ContentBlock(text="started"),))
                plugin.storage.write_json("waiting.json", True)
                await asyncio.sleep(100)
            finally:
                plugin.storage.write_json(
                    "handler-stopped.json", True
                )

        plugin.register_provider(
            ProviderSpec(
                "scope-probe",
                "Scope probe",
                generate,
                models=(ModelInfo("probe", "Probe"),),
                require_api_key=False,
            )
        )
        app = PawApp(
            app_id="scope-probe"
        ).enable_standard_capabilities()

        @app.route("/stop/{id}", methods=("POST",))
        async def stop(ctx, request):
            result = await ctx.cancel_task(
                request.path_params["id"], timeout=0.1
            )
            return {
                "stopped": result.stopped,
                "timed_out": result.timed_out,
            }

        plugin.register_app(app)


plugin = Plugin()
"""
    release = tmp_path / "release"
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["apps", "providers", "storage", "config"],
            ),
            config={"release": str(release)},
        )
        await host.configure_chat_model("scope-probe", "probe")
        started = await host.request(
            "POST",
            "/api/scope-probe/tasks",
            user_id="alice",
            json={"message": "controlled thread", "session_id": "owned"},
        )
        assert started.status == 200
        run_id = started.json()["run_id"]
        stop = "/api/scope-probe/stop/" + run_id
        try:
            async with asyncio.timeout(WAIT_TIMEOUT):
                while not ctx.storage.read_json("waiting.json", False):
                    await asyncio.sleep(0.01)
            assert (await host.request("POST", stop, user_id="alice")).json()[
                "stopped"
            ] is False
            # Let the real, unchanged five-second thread join budget expire.
            await asyncio.sleep(5.5)
            assert ctx.storage.read_json("handler-stopped.json") is True
            before = ctx.storage.read_json("ticks.json")
            # Disk flushes and thread scheduling have no 60 ms guarantee.
            async with asyncio.timeout(WAIT_TIMEOUT):
                while ctx.storage.read_json("ticks.json") <= before:
                    await asyncio.sleep(0.01)
            assert ctx.storage.read_json("thread-stopped.json", False) is False
            assert (await host.request("POST", stop, user_id="alice")).json()[
                "stopped"
            ] is False
            successor = await host.request(
                "POST",
                "/api/scope-probe/tasks",
                user_id="alice",
                json={
                    "message": "same session successor",
                    "session_id": "owned",
                },
            )
            assert successor.status == 200
            assert successor.json()["run_id"] == run_id
            assert ctx.storage.read_json("calls.json") == 1
            other = await host.request(
                "POST",
                "/api/scope-probe/tasks",
                user_id="bob",
                json={"message": "independent", "session_id": "other"},
            )
            assert other.status == 200
            other_path = "/api/scope-probe/tasks/" + other.json()["run_id"]
            async with asyncio.timeout(WAIT_TIMEOUT):
                while (
                    await host.request("GET", other_path, user_id="bob")
                ).json()["status"] == "running":
                    await asyncio.sleep(0.01)
            assert (
                await host.request("GET", other_path, user_id="bob")
            ).json()["status"] == "completed"
            with pytest.raises(PluginBusyError):
                await host.reload("extension-contract")
        finally:
            release.touch()
            async with asyncio.timeout(WAIT_TIMEOUT):
                while not ctx.storage.read_json("thread-stopped.json", False):
                    await asyncio.sleep(0.01)
            async with asyncio.timeout(WAIT_TIMEOUT):
                while not (
                    await host.request("POST", stop, user_id="alice")
                ).json()["stopped"]:
                    await asyncio.sleep(0.01)
        host.assert_quiescent("extension-contract")
