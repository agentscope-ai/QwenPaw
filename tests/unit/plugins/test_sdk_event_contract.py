# -*- coding: utf-8 -*-
"""Observation failures must not change real Runtime command output."""

import asyncio

import pytest

from .sdk_author_fixture import make_plugin

SOURCE = """
import asyncio
import time
from pathlib import Path
from qwenpaw.plugins.commands import CommandSpec, CommandResult
from qwenpaw.plugins.events import EventSubscription
from qwenpaw.plugins.messages import ContentBlock, Message


class Plugin:
    def register(self, ctx):
        async def command(call, args):
            return CommandResult(
                "reply",
                Message(
                    "assistant",
                    (ContentBlock(text="command answer:" + args),),
                ),
            )

        ctx.register_command(CommandSpec("observeprobe", command))

        async def observe(call, event):
            if ctx.config.get("observer") == "queue":
                directory = Path(ctx.config.get("directory"))
                (directory / "observer-entered").touch()
                while not (directory / "observer-release").exists():
                    await asyncio.sleep(0.005)
            trace = ctx.storage.read_json("events.json", [])
            trace.append(
                {
                    "kind": event.kind,
                    "sequence": getattr(event, "sequence", 0),
                    "run": getattr(event, "run_id", ""),
                    "workspace": getattr(event, "workspace_id", ""),
                    "session": getattr(event, "session_id", ""),
                    "lost": getattr(event, "lost", 0),
                    "disconnected": getattr(
                        event, "disconnected", False
                    ),
                }
            )
            ctx.storage.write_json("events.json", trace)
            if ctx.config.get("observer") == "raise":
                raise RuntimeError("observer-only-failure")
            if ctx.config.get("observer") == "cancel":
                raise asyncio.CancelledError()

        def blocked(call, event):
            directory = Path(ctx.config.get("directory"))
            (directory / "observer-entered").touch()
            while not (directory / "observer-release").exists():
                time.sleep(0.005)

        async def activate(active):
            if ctx.config.get("observer") != "none":
                active.subscribe_events(
                    EventSubscription(
                        (
                            blocked
                            if ctx.config.get("observer")
                            == "blocked"
                            else observe
                        ),
                        capacity=ctx.config.get("capacity", 128),
                        workspace_id=ctx.config.get(
                            "workspace_filter"
                        ),
                    )
                )

        ctx.on_activate(activate)


plugin = Plugin()
"""


def business_events(events):
    return [
        (
            event.object,
            event.type,
            event.status,
            tuple(block.text for block in event.content),
            tuple(
                (
                    message.type,
                    message.role,
                    message.status,
                    tuple(block.text for block in message.content),
                )
                for message in event.output
            ),
        )
        for event in events
    ]


@pytest.mark.parametrize("observer", ["normal", "raise", "cancel", "blocked"])
async def test_observer_failure_or_blocking_preserves_real_runtime_output(
    tmp_path,
    observer,
):
    from qwenpaw.plugins import PluginBusyError
    from qwenpaw.plugins.testing import PluginTestHost

    source = make_plugin(
        tmp_path,
        SOURCE,
        ["commands", "events", "storage", "config"],
    )
    async with PluginTestHost(tmp_path / "baseline") as host:
        await host.load(source, config={"observer": "none"})
        baseline = [
            item
            async for item in host.stream_chat(
                "/observeprobe same",
                workspace_id="one",
                session_id="chat",
            )
        ]
    assert "command answer:same" in str(business_events(baseline))
    async with PluginTestHost(tmp_path / "candidate") as host:
        ctx = await host.load(
            source,
            config={"observer": observer, "directory": str(tmp_path)},
        )
        try:

            async def consume():
                return [
                    item
                    async for item in host.stream_chat(
                        "/observeprobe same",
                        workspace_id="one",
                        session_id="chat",
                    )
                ]

            candidate = await asyncio.wait_for(consume(), 2)
            assert business_events(candidate) == business_events(baseline)
            if observer == "blocked":
                for _ in range(100):
                    if (tmp_path / "observer-entered").exists():
                        break
                    await asyncio.sleep(0.01)
                assert (tmp_path / "observer-entered").exists()
                with pytest.raises(PluginBusyError):
                    await host.reload("extension-contract")
            else:
                for _ in range(100):
                    events = ctx.storage.read_json("events.json", [])
                    if events and (
                        observer == "cancel"
                        or events[-1]["kind"] == "run.completed"
                    ):
                        break
                    await asyncio.sleep(0.01)
                assert events
                if observer != "cancel":
                    assert (
                        sum(
                            event["kind"] == "run.completed"
                            for event in events
                        )
                        == 1
                    )
                    assert all(
                        event["workspace"] == "one"
                        and event["session"] == "chat"
                        for event in events
                    )
                    sequences = [event["sequence"] for event in events]
                    assert sequences == sorted(set(sequences))
        finally:
            (tmp_path / "observer-release").touch()
            for _ in range(100):
                if (
                    host.resource_snapshot("extension-contract")[
                        "active_calls"
                    ]
                    == 0
                ):
                    break
                await asyncio.sleep(0.01)
            assert (
                host.resource_snapshot("extension-contract")["active_calls"]
                == 0
            )


async def test_full_observer_queue_reports_gap_without_changing_chat_results(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = make_plugin(
        tmp_path,
        SOURCE,
        ["commands", "events", "storage", "config"],
    )
    async with PluginTestHost(tmp_path / "host") as host:
        ctx = await host.load(
            source,
            config={
                "observer": "queue",
                "directory": str(tmp_path),
                "capacity": 2,
            },
        )
        try:
            runs = []
            for _ in range(5):
                runs.append(
                    [
                        event
                        async for event in host.stream_chat(
                            "/observeprobe same",
                        )
                    ],
                )
            assert all(
                business_events(run) == business_events(runs[0])
                for run in runs
            )
            assert "command answer:same" in str(business_events(runs[0]))
        finally:
            (tmp_path / "observer-release").touch()
            for _ in range(100):
                events = ctx.storage.read_json("events.json", [])
                if (
                    any(event["kind"] == "gap" for event in events)
                    and host.resource_snapshot("extension-contract")[
                        "active_calls"
                    ]
                    == 0
                ):
                    break
                await asyncio.sleep(0.01)
        gaps = [event for event in events if event["kind"] == "gap"]
        assert gaps and sum(event["lost"] for event in gaps) > 0
        terminal_runs = [
            event["run"]
            for event in events
            if event["kind"]
            in {"run.completed", "run.failed", "run.cancelled"}
        ]
        assert len(terminal_runs) == len(set(terminal_runs))


async def test_observer_workspace_filter_and_reload_do_not_duplicate_events(
    tmp_path,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = make_plugin(
        tmp_path,
        SOURCE,
        ["commands", "events", "storage", "config"],
    )
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(
            source,
            config={"observer": "normal", "workspace_filter": "one"},
        )
        for index in range(4):
            if index:
                assert (await host.reload("extension-contract")).ok
            async for _ in host.stream_chat(
                "/observeprobe ignored",
                workspace_id="two",
            ):
                pass
            async for _ in host.stream_chat(
                "/observeprobe tracked",
                workspace_id="one",
            ):
                pass
            ctx = host.context("extension-contract")
            for _ in range(100):
                events = ctx.storage.read_json("events.json", [])
                if (
                    sum(event["kind"] == "run.completed" for event in events)
                    == index + 1
                    and host.resource_snapshot("extension-contract")[
                        "active_calls"
                    ]
                    == 0
                ):
                    break
                await asyncio.sleep(0.01)
            assert (
                sum(event["kind"] == "run.completed" for event in events)
                == index + 1
            )
            assert all(event["workspace"] == "one" for event in events)


@pytest.mark.parametrize(
    "shape",
    ["terminal_stream", "terminal_return", "delta_then_end"],
)
async def test_observer_exception_preserves_real_model_runtime_output(
    tmp_path,
    shape,
):
    from qwenpaw.plugins.testing import PluginTestHost

    source = """
from qwenpaw.plugins.providers import (
    ProviderSpec,
    ModelInfo,
    ModelChunk,
    ModelUsage,
)
from qwenpaw.plugins.messages import ContentBlock
from qwenpaw.plugins.events import EventSubscription


class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            assert any(
                message.role == "user"
                and any(
                    block.text == "real model probe"
                    for block in message.content
                )
                for message in request.messages
            )
            ctx.storage.write_json("model-ran.json", True)
            if ctx.config.get("shape") == "terminal_return":
                return ModelChunk(
                    (ContentBlock(text="model answer"),),
                    is_last=True,
                    usage=ModelUsage(4, 2),
                )

            async def stream():
                if ctx.config.get("shape") == "delta_then_end":
                    yield ModelChunk(
                        (ContentBlock(text="model answer"),)
                    )
                    yield ModelChunk(
                        (), is_last=True, usage=ModelUsage(4, 2)
                    )
                else:
                    yield ModelChunk(
                        (ContentBlock(text="model answer"),),
                        is_last=True,
                        usage=ModelUsage(4, 2),
                    )

            return stream()

        async def observe(call, event):
            ctx.storage.write_json("observer-ran.json", True)
            raise RuntimeError("observer-model-path-error")

        ctx.register_provider(
            ProviderSpec(
                "sdk-event-model",
                "Event model",
                generate,
                models=(ModelInfo("event-model", "Event model"),),
                require_api_key=False,
            )
        )

        async def activate(active):
            if ctx.config.get("observe"):
                active.subscribe_events(EventSubscription(observe))

        ctx.on_activate(activate)


plugin = Plugin()
"""
    plugin = make_plugin(
        tmp_path,
        source,
        ["providers", "events", "storage", "config"],
    )
    outputs = []
    for observe in (False, True):
        async with PluginTestHost(tmp_path / str(observe)) as host:
            ctx = await host.load(
                plugin,
                config={"observe": observe, "shape": shape},
            )
            await host.configure_chat_model("sdk-event-model", "event-model")
            events = [
                event async for event in host.stream_chat("real model probe")
            ]
            assert ctx.storage.read_json("model-ran.json", False)
            assert "model answer" in str(business_events(events))
            outputs.append(business_events(events))
            if observe:
                for _ in range(100):
                    if (
                        ctx.storage.read_json("observer-ran.json", False)
                        and host.resource_snapshot("extension-contract")[
                            "active_calls"
                        ]
                        == 0
                    ):
                        break
                    await asyncio.sleep(0.01)
                assert ctx.storage.read_json("observer-ran.json", False)
    assert outputs[0] == outputs[1]
