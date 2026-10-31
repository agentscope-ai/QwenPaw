# -*- coding: utf-8 -*-
"""Controlled real TaskTracker cancellation; author callback remains public."""

# Inspect host ownership and cleanup state at the tested bridge boundary.
# pylint: disable=protected-access

import asyncio

import pytest

from qwenpaw.plugins import PluginBusyError, activity
from qwenpaw.plugins.testing import PluginTestHost
from .test_sdk_channel_routing_contract import (
    CHANNEL,
    incoming,
    setup,
    wait_for,
)

from .timing import WAIT_TIMEOUT


async def test_host_close_during_model_run_finishes_queue_consumer(
    tmp_path,
):
    import json

    root = tmp_path / "host"
    async with PluginTestHost(root) as host:
        ctx = await setup(host, tmp_path)
        await host.receive_channel(CHANNEL, incoming("hold-first", "one"))
        await wait_for(lambda: bool(ctx.storage.read_json("model.json", [])))
        consumers = [
            task
            for task in asyncio.all_tasks()
            if task.get_name().startswith("consumer_" + CHANNEL)
        ]
        assert len(consumers) == 1
    assert all(task.done() for task in consumers), consumers
    assert json.loads(
        (
            root / "plugin-data/extension-contract/model-finished.json"
        ).read_text(),
    ) == ["hold-first"]
    async with PluginTestHost(tmp_path / "next-host"):
        pass


async def test_repeated_cancellation_preserves_queued_terminal_callback(
    tmp_path,
):
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await setup(host, tmp_path)
        ctx.storage.write_json("callback-fault.json", "gate")
        await host.receive_channel(CHANNEL, incoming("hold-first", "one"))
        try:
            async with asyncio.timeout(WAIT_TIMEOUT):
                while not ctx.storage.read_json("model.json", []):
                    await asyncio.sleep(0.01)
            tracker = (await host._workspace("test")).task_tracker
            tasks = await tracker.snapshot_active_tasks()
            assert len(tasks) == 1
            producer = next(iter(tasks.values()))
            producer.cancel()
            await wait_for(
                lambda: bool(ctx.storage.read_json("model-finished.json", [])),
            )
            # First cancellation finishes the real model and queues end behind
            # the still-running start callback. Cancel the same native owner
            # again while end is waiting, rather than cancelling a fake task.
            await asyncio.sleep(0.05)
            assert not producer.done()
            producer.cancel()
            await asyncio.sleep(0.05)
            with pytest.raises(PluginBusyError):
                await host.reload("extension-contract")
        finally:
            ctx.storage.write_json("release.json", True)
            ctx.storage.write_json("callback-release.json", True)
        await wait_for(
            lambda: len(ctx.storage.read_json("events.json", [])) == 2,
        )
        events = ctx.storage.read_json("events.json")
        assert [(row["phase"], row["status"]) for row in events] == [
            ("start", "running"),
            ("end", "cancelled"),
        ]
        assert events[0]["run_id"] == events[1]["run_id"]
        await host.stop_channel(CHANNEL)


async def test_stop_retains_terminal_task_queued_before_callback_admission(
    tmp_path,
    monkeypatch,
):
    # Keep this ownership/cleanup scenario and its assertions together.
    # pylint: disable=too-many-statements
    from qwenpaw.plugins.resources import ResourceScope

    queued, release = asyncio.Event(), asyncio.Event()
    cancelled = []
    notifications = []
    original = ResourceScope.task

    def gate_terminal(scope, coroutine, label="task"):
        if label != "channel run notification":
            return original(scope, coroutine, label)
        notifications.append(label)
        if len(notifications) != 2:
            return original(scope, coroutine, label)

        async def before_admission():
            entered = False
            queued.set()
            try:
                await release.wait()
                entered = True
                await coroutine
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
            finally:
                if not entered:
                    coroutine.close()

        return original(scope, before_admission(), label)

    monkeypatch.setattr(ResourceScope, "task", gate_terminal)
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await setup(host, tmp_path)
        channel = await (
            await host._workspace("test")
        ).channel_manager.get_channel(
            CHANNEL,
        )
        requests = []
        original_before = channel._before_consume_process

        async def remember_request(request):
            requests.append(request)
            await original_before(request)

        monkeypatch.setattr(
            channel,
            "_before_consume_process",
            remember_request,
        )
        await host.receive_channel(CHANNEL, incoming("empty-output", "queued"))
        await asyncio.wait_for(queued.wait(), WAIT_TIMEOUT)
        assert len(notifications) == 2
        stopping = asyncio.create_task(host.stop_channel(CHANNEL))
        try:
            assert len(requests) == 1
            assert id(requests[0]) in channel._run_states, (
                "Pending terminal must retain the actual run state "
                "until delivery finishes"
            )
            await asyncio.wait_for(channel._end_run(requests[0]), WAIT_TIMEOUT)
            assert (
                len(notifications) == 2
            ), "Repeated end must not enqueue a duplicate terminal"
            await asyncio.sleep(0.05)
            assert (
                not stopping.done()
            ), "Queued terminal custody must precede callback admission"
            assert not cancelled
            assert [
                event["phase"]
                for event in ctx.storage.read_json("events.json")
            ] == ["start"]
        finally:
            release.set()
            await asyncio.wait_for(stopping, WAIT_TIMEOUT)
        assert not cancelled
        events = ctx.storage.read_json("events.json")
        assert [event["phase"] for event in events] == ["start", "end"]
        assert events[-1]["status"] == "completed"
        assert events[0]["run_id"] == events[1]["run_id"]

        assert channel._run_states == {}


@pytest.mark.parametrize("timeout_then_retry", [False, True])
async def test_host_close_retains_native_tracker_completion_callback(
    tmp_path,
    monkeypatch,
    timeout_then_retry,
):
    from qwenpaw.plugins import SDKError

    entered, release, finished = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    callback_tasks = []
    callback_results = []
    async with PluginTestHost(tmp_path / "host") as host:
        await setup(host, tmp_path)
        workspace = await host._workspace("test")
        original = workspace.chat_manager.mark_chat_finished

        async def held_completion(chat_id, finished_at):
            callback_tasks.append(asyncio.current_task())
            entered.set()
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    # The controlled persistence operation is genuinely
                    # unfinished.
                    # Keep the real native owner alive until explicitly
                    # released.
                    pass
            result = await original(chat_id, finished_at)
            callback_results.append(result)
            finished.set()
            return result

        monkeypatch.setattr(
            workspace.chat_manager,
            "mark_chat_finished",
            held_completion,
        )
        await host.receive_channel(
            CHANNEL,
            incoming("empty-output", "native-tail"),
        )
        await asyncio.wait_for(entered.wait(), WAIT_TIMEOUT)
        native = callback_tasks[0]
        active = await workspace.task_tracker.snapshot_active_tasks(
            owner=workspace,
        )
        assert len(active) == 1 and native in active.values()
        assert "_producer" in native.get_coro().__qualname__
        closing = asyncio.create_task(host.close())
        try:
            if timeout_then_retry:
                with pytest.raises(SDKError):
                    await asyncio.wait_for(
                        asyncio.shield(closing),
                        WAIT_TIMEOUT,
                    )
            else:
                await asyncio.sleep(0.05)
                assert not closing.done(), (
                    "Host closed while its real tracker completion was "
                    "still running"
                )
            assert not native.done() and not finished.is_set()
            # Environment ownership cannot transfer to a new host while cleanup
            # remains.
            with pytest.raises(SDKError):
                async with PluginTestHost(tmp_path / "premature-next"):
                    pass
        finally:
            release.set()
            await asyncio.wait_for(asyncio.shield(native), WAIT_TIMEOUT)
            await asyncio.gather(closing, return_exceptions=True)
            await host.close()
        assert finished.is_set() and native.done()
        assert len(callback_results) == 1
        assert callback_results[0].last_finished_at is not None
    async with PluginTestHost(tmp_path / "next"):
        pass


async def test_rejected_stream_admission_does_not_create_or_replace_state(
    tmp_path,
):
    from qwenpaw.schemas import AgentRequest
    from .sdk_author_fixture import make_plugin
    from .test_sdk_channel_routing_contract import SOURCE

    source = SOURCE.replace(
        "            async def on_run(self, ctx, event):",
        (
            "            async def on_stream(self, ctx, event): "
            "pass\n            async def on_run(self, ctx, event):"
        ),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            make_plugin(
                tmp_path,
                source,
                ["channels", "providers", "storage"],
            ),
        )
        await host.start_channel(CHANNEL, {})
        channel = await (
            await host._workspace("test")
        ).channel_manager.get_channel(
            CHANNEL,
        )
        activity = host._loader.lifecycle.get_instance(
            "extension-contract",
        ).activity
        first = AgentRequest(input=[], session_id="first", user_id="author")
        rejected = AgentRequest(
            input=[],
            session_id="rejected",
            user_id="author",
        )
        event = {"object": "message", "status": "in_progress", "content": []}
        await channel._stream(
            "start",
            first,
            "original",
            event,
            {},
            "text",
            "original",
        )
        key = (id(first), "text")
        original = channel._stream_contexts[key]
        try:
            async with activity.mutation():
                with pytest.raises(PluginBusyError):
                    await channel._stream(
                        "start",
                        rejected,
                        "new",
                        event,
                        {},
                        "text",
                        "new",
                    )
                assert (id(rejected), "text") not in channel._stream_contexts
                with pytest.raises(PluginBusyError):
                    await channel._stream(
                        "delta",
                        first,
                        "changed",
                        event,
                        {},
                        "text",
                        "changed",
                    )
                assert channel._stream_contexts[key] is original
        finally:
            await channel._stream(
                "end",
                first,
                "original",
                {"object": "message", "status": "cancelled", "content": []},
                {},
                "text",
                "original",
            )
        assert channel._stream_contexts == {}


@pytest.mark.parametrize(
    "boundary",
    ["normal", "call-recovery", "stream-recovery", "blocked-close"],
)
async def test_channel_stop_closes_actual_overflow_stream_before_owner_exit(
    tmp_path,
    monkeypatch,
    boundary,
):
    # Keep this ownership/cleanup scenario and its assertions together.
    # pylint: disable=too-many-statements
    from qwenpaw.agents import react_agent
    from .sdk_author_fixture import make_plugin
    from .test_sdk_channel_routing_contract import SOURCE

    streams = []
    closing, release, closed = (
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )
    recoveries = []
    original = react_agent.call_with_overflow_recovery

    async def remember_actual_stream(call_model, recover, **kwargs):
        async def actual_model(**arguments):
            response = await call_model(**arguments)
            if boundary != "blocked-close":
                return response

            async def controlled_source():
                try:
                    async for chunk in response:
                        yield chunk
                finally:
                    closing.set()
                    while not release.is_set():
                        try:
                            await release.wait()
                        except asyncio.CancelledError:
                            pass
                    await response.aclose()
                    closed.set()

            return controlled_source()

        async def failed_call(**_arguments):
            if boundary == "call-recovery":
                raise RuntimeError("controlled pre-output failure")

            async def failed_source():
                raise RuntimeError("controlled pre-output failure")
                # Required to model a stream that raises before its first item.
                yield  # pylint: disable=unreachable

            return failed_source()

        async def recover_actual_model(exc):
            recoveries.append(str(exc))
            return await actual_model(**kwargs)

        # Only the transport failure is injected. The original overflow
        # algorithm and actual configured model / Runtime still execute.
        stream = await original(
            failed_call if boundary.endswith("recovery") else actual_model,
            recover_actual_model if boundary.endswith("recovery") else recover,
            **kwargs,
        )
        # A strong reference suppresses GC cleanup. The real run must close
        # the exact returned overflow iterator itself before it exits.
        streams.append(stream)
        return stream

    monkeypatch.setattr(
        react_agent,
        "call_with_overflow_recovery",
        remember_actual_stream,
    )
    source = SOURCE.replace(
        "            async def send(self, ctx, message):",
        """            async def on_stream(self, ctx, event):
                if event.phase == 'start':
                    plugin.storage.write_json('stream-started.json', True)
                    await asyncio.Event().wait()
            async def send(self, ctx, message):""",
    ).replace(
        '"Routing contract",\n                Backend,\n            )',
        (
            '"Routing contract",\n                Backend, '
            "streaming=True,\n            )"
        ),
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            make_plugin(
                tmp_path,
                source,
                ["channels", "providers", "storage"],
            ),
        )
        await host.configure_chat_model("routing-provider", "routing-model")
        await host.start_channel(CHANNEL)
        try:
            await host.receive_channel(
                CHANNEL,
                incoming("stop-at-content", "overflow"),
            )
            await wait_for(
                lambda: ctx.storage.read_json("stream-started.json", False),
            )
            assert len(streams) == 1
            assert streams[0].ag_frame is not None
            if boundary == "blocked-close":
                with monkeypatch.context() as patch:
                    patch.setattr(activity, "INTERRUPT_TIMEOUT_SECONDS", 0.2)
                    with pytest.raises(PluginBusyError):
                        await host.reload(
                            "extension-contract",
                            interrupt_tasks=True,
                        )
                assert closing.is_set() and not closed.is_set()
                assert (
                    host.resource_snapshot("extension-contract")[
                        "active_calls"
                    ]
                    > 0
                )
                release.set()
                result = await host.reload(
                    "extension-contract",
                    interrupt_tasks=True,
                )
                assert result.ok
                assert closed.is_set()
            else:
                await host.stop_channel(CHANNEL)
            assert recoveries == (
                ["controlled pre-output failure"]
                if boundary.endswith("recovery")
                else []
            )
            assert (
                streams[0].ag_frame is None
            ), "Run exited with its actual overflow stream still open"
            assert (
                host.resource_snapshot("extension-contract")["active_calls"]
                == 0
            )
        finally:
            release.set()
            # Failed assertions still close the test-held real stream; this is
            # cleanup only and never part of the passing ownership assertion.
            for stream in streams:
                await stream.aclose()
