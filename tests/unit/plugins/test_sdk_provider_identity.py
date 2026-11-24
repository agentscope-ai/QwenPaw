# -*- coding: utf-8 -*-
"""Production Runtime provider identity survives awaits without leaking out."""

import asyncio

import pytest

from qwenpaw.plugins._identity import request_identity
from qwenpaw.plugins.testing import PluginTestHost
from .sdk_author_fixture import make_plugin

SOURCE = """
import asyncio
from dataclasses import asdict
from qwenpaw.plugins.providers import ProviderSpec, ModelInfo, ModelChunk
from qwenpaw.plugins.messages import ContentBlock
class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            key = call.identity.user_id
            before = asdict(call.identity)
            ctx.storage.write_json(key + "-entered.json", before)
            try:
                if key == "cancel":
                    await asyncio.Event().wait()
                await asyncio.sleep(0.05)
                assert asdict(call.identity) == before
                yield ModelChunk((ContentBlock(text=key),), is_last=True)
            finally:
                ctx.storage.write_json(key + "-exited.json", asdict(call.identity))
        ctx.register_provider(ProviderSpec("identity-provider", "Identity provider", generate,
            models=(ModelInfo("identity", "Identity"),), require_api_key=False))
plugin = Plugin()
"""


@pytest.mark.asyncio
async def test_provider_trusted_identity_concurrency_cancel_and_consumer_scope(
    tmp_path,
):
    async with PluginTestHost(tmp_path / "host") as host:
        provider = await host.load(
            make_plugin(tmp_path, SOURCE, ["providers", "storage"]),
        )
        for workspace in ("one", "two"):
            await host.configure_chat_model(
                "identity-provider",
                "identity",
                workspace_id=workspace,
            )

        async def run(user, workspace):
            iterator = host.stream_chat(
                "Identify",
                user_id=user,
                workspace_id=workspace,
                session_id="same-session",
            )
            try:
                async for _ in iterator:
                    assert (
                        request_identity.get() is None
                    ), "Identity leaked into stream consumer"
            finally:
                await iterator.aclose()

        await asyncio.gather(run("alice", "one"), run("bob", "two"))
        for user, workspace in (("alice", "one"), ("bob", "two")):
            expected = {
                "workspace_id": workspace,
                "session_id": "same-session",
                "channel": "console",
                "user_id": user,
            }
            assert (
                provider.storage.read_json(user + "-entered.json") == expected
            )
            assert (
                provider.storage.read_json(user + "-exited.json") == expected
            )
        task = asyncio.create_task(run("cancel", "one"))
        async with asyncio.timeout(15):
            while not provider.storage.read_json("cancel-entered.json", None):
                await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert provider.storage.read_json("cancel-exited.json") == {
            "workspace_id": "one",
            "session_id": "same-session",
            "channel": "console",
            "user_id": "cancel",
        }
        assert request_identity.get() is None
