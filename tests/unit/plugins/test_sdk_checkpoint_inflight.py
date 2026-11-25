# -*- coding: utf-8 -*-
"""Real Runtime, TaskTracker, shadow Git and SDK approval during restoration."""

import asyncio
import json

import pytest

from qwenpaw.checkpoints.policy import session_file_path
from qwenpaw.checkpoints.runtime import RUNTIME
from qwenpaw.plugins.testing import PluginTestHost
from .sdk_checkpoint_fixture import make_checkpoint_plugin
from .sdk_author_fixture import make_plugin
from .test_sdk_checkpoints import pending

MODEL = """
import asyncio
from qwenpaw.plugins.providers import ProviderSpec, ModelInfo, ModelChunk
from qwenpaw.plugins.messages import ContentBlock
class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            session = call.identity.session_id
            count = ctx.storage.read_json(session + '-entered', 0) + 1
            ctx.storage.write_json(session + '-entered', count)
            try:
                while ctx.storage.read_json(session + '-hold', False):
                    await asyncio.sleep(.01)
                yield ModelChunk((ContentBlock(text=f'{session}-answer-{count}'),), is_last=True)
            finally:
                ctx.storage.write_json(session + '-exited', count)
        ctx.register_provider(ProviderSpec('checkpoint-probe', 'Checkpoint probe', generate,
            models=(ModelInfo('model', 'Model'),), require_api_key=False))
plugin = Plugin()
"""


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.parametrize(
    "outcome",
    ["cancel-queued", "cancel"],
)
async def test_restore_waits_for_existing_run_not_requests_at_closed_gate(
    tmp_path,
    outcome,
):
    source = make_checkpoint_plugin(tmp_path)
    async with PluginTestHost(tmp_path / "host") as host:
        provider = await host.load(
            make_plugin(tmp_path, MODEL, ["providers", "storage"]),
        )
        assert (await host.install(source)).ok
        await host.configure_chat_model("checkpoint-probe", "model")
        workspace = await host._workspace("test")
        tracker = workspace.task_tracker
        engine = await RUNTIME.get_for_workspace_async(workspace)

        async def tracked(session):
            async def stream(_):
                async for event in host.stream_chat(
                    "Write a turn",
                    session_id=session,
                    user_id="alice",
                ):
                    yield json.dumps(event.to_dict())

            queue, created = await tracker.attach_or_start(
                session,
                None,
                stream,
                owner=workspace,
            )
            assert created

            async def consume():
                return [
                    item
                    async for item in tracker.stream_from_queue(queue, session)
                ]

            return asyncio.create_task(consume())

        async def command(args):
            reply = await host.call_control_command(
                "/contract-checkpoint " + args,
                session_id="conversation",
                user_id="alice",
            )
            return json.loads(reply.content[0].text)

        await (await tracked("conversation"))
        path = session_file_path(
            workspace.workspace_dir,
            session_id="conversation",
            user_id="alice",
            channel="console",
        )
        original = path.read_bytes()
        saved = await command("snapshot before-inflight")
        provider.storage.write_json("conversation-hold", True)
        active = await tracked("conversation")
        restoring = queued = None
        try:
            await until(
                lambda: provider.storage.read_json("conversation-entered", 0)
                == 2,
            )
            restoring = asyncio.create_task(command("restore " + saved["id"]))
            approval = await pending(host)
            assert await host.resolve_approval(
                approval.request_id,
                approved=True,
            )
            await until(lambda: not engine.query_gate.is_set())
            queued = await tracked("queued")
            await asyncio.sleep(0.05)
            assert await tracker.get_status("queued") == "running"
            assert not provider.storage.read_json("queued-entered", 0)
            assert path.read_bytes() == original and not restoring.done()
            if outcome == "cancel-queued":
                assert await tracker.request_stop("queued")
                await queued
                assert not provider.storage.read_json("queued-entered", 0)
                assert not engine._query_waiters
                provider.storage.write_json("conversation-hold", False)
                await active
                result = await restoring
                assert not result["dry_run"] and path.read_bytes() == original
            else:
                restoring.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await restoring
                assert not active.done() and path.read_bytes() == original
                assert provider.storage.read_json("conversation-exited") == 1
                assert not any(
                    row["kind"] == "pre-restore"
                    for row in await command("timeline")
                )
            assert engine.query_gate.is_set()
            await queued
            if outcome != "cancel-queued":
                assert provider.storage.read_json("queued-exited") == 1
            assert not engine._query_waiters
            assert not await host.approval_requests("conversation")
        finally:
            provider.storage.write_json("conversation-hold", False)
            if restoring is not None and not restoring.done():
                restoring.cancel()
            await asyncio.gather(
                *(
                    task
                    for task in (active, restoring, queued)
                    if task is not None
                ),
                return_exceptions=True,
            )
        assert not await tracker.has_active_tasks()
        assert (await host.uninstall("checkpoint-contract")).clean
