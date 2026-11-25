# -*- coding: utf-8 -*-
"""SDK stop advice runs through the host chain and cannot reset its limit."""

import asyncio

from qwenpaw.plugins.messages import ContentBlock, Message
from qwenpaw.plugins.stops import StopResult, StopSpec


async def test_stop_advice_identity_active_mode_and_host_limit(sdk_component):
    seen, handles = [], []

    def declare(ctx):
        async def decide(call):
            seen.append((call.identity, call.iteration, call.final_message))
            if call.has_tool_calls:
                return StopResult()
            if call.iteration >= 3:
                return StopResult("stop", reason="QA passed")
            return StopResult(
                "continue",
                "Run another QA cycle",
                "QA not complete",
            )

        handles.append(
            ctx.register_stop(
                StopSpec(
                    "qa",
                    decide,
                    lambda identity: identity.user_id == "alice",
                ),
            ),
        )

    async with sdk_component(declare, capabilities=("stops",)) as (host, ctx):
        final = Message("assistant", (ContentBlock(text="checked"),))
        continuing = await host.evaluate_stop(
            user_id="alice",
            iteration=1,
            final_message=final,
        )
        assert continuing == StopResult(
            "continue",
            "Run another QA cycle",
            "QA not complete",
        )
        assert seen[0][0].user_id == "alice"
        received = seen[0][2]
        assert received.role == final.role
        assert received.content[0].text == "checked"
        assert received.content[0].id, "Host message conversion assigns an ID"
        before = len(seen)
        assert (await host.evaluate_stop(user_id="bob")).action == "stop"
        assert (
            len(seen) == before
        ), "Inactive modes must not run their callback"
        assert (
            await host.evaluate_stop(user_id="alice", iteration=3)
        ).reason == "QA passed"
        before = len(seen)
        limited = await host.evaluate_stop(
            user_id="alice",
            iteration=2,
            max_iterations=2,
        )
        assert (
            limited.action == "stop"
            and limited.reason == "Host iteration limit reached"
        )
        assert len(seen) == before
        assert (
            await host.evaluate_stop(user_id="alice", cancelled=True)
        ).reason == "User cancelled"
        assert len(seen) == before
        await handles[0].close()
        assert (await host.evaluate_stop(user_id="alice")).action == "stop"
        assert len(seen) == before


async def test_stop_timeout_cleans_callback_before_return(sdk_component):
    finished = asyncio.Event()

    def declare(ctx):
        async def never(call):
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()

        ctx.register_stop(
            StopSpec("slow", never, lambda identity: True, timeout=0.02),
        )

    async with sdk_component(declare, capabilities=("stops",)) as (host, ctx):
        result = await host.evaluate_stop()
        assert result.action == "stop"
        assert finished.is_set()
        assert not host.resource_snapshot("resource-contract")["resources"]
