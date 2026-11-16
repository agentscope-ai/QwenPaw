# -*- coding: utf-8 -*-
"""Real Runtime + disk persistence; only model text is deterministic."""

import asyncio
import hashlib
import json

import pytest

from qwenpaw.plugins.compliance import check_plugin
from qwenpaw.plugins.testing import PluginTestHost
from .sdk_author_fixture import make_plugin

OBSERVER = """
import json, hashlib
from dataclasses import asdict
from qwenpaw.plugins.hooks import HookSpec, HookPhase, HookResult
class Plugin:
    def register(self, ctx):
        async def saved(call):
            identity = asdict(call.identity)
            key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
            await ctx.storage.awrite_json(f'session-save/{key}/{call.phase.value}.json',
                {'identity': identity, 'session_saved': call.session_saved})
            return HookResult()
        for phase in (HookPhase.PRE_EXECUTE, HookPhase.POST_RESPONSE):
            ctx.register_hook(HookSpec(phase.value, phase, saved))
plugin = Plugin()
"""
MODEL = """
import asyncio
from qwenpaw.plugins.providers import ProviderSpec, ModelInfo, ModelChunk
from qwenpaw.plugins.messages import ContentBlock
class Plugin:
    def register(self, ctx):
        async def generate(call, request):
            await ctx.storage.awrite_json("entered.json", True)
            while await ctx.storage.aread_json("hold.json", False):
                await asyncio.sleep(0.01)
            yield ModelChunk((ContentBlock(text="Saved-state acceptance"),), is_last=True)
        ctx.register_provider(ProviderSpec("save-fixture", "Save fixture", generate,
            models=(ModelInfo("model", "Model"),), require_api_key=False))
plugin = Plugin()
"""


@pytest.mark.asyncio
async def test_session_save_signal_tracks_actual_disk_failure_and_recovery(
    tmp_path,
):
    source = make_plugin(
        tmp_path,
        OBSERVER,
        ["hooks", "storage"],
        plugin_id="save-observer",
        sdk_version="1.2",
    )
    assert check_plugin(source).ok
    async with PluginTestHost(tmp_path / "host") as host:
        provider = await host.load(
            make_plugin(tmp_path, MODEL, ["providers", "storage"]),
        )
        inspector = await host.load(source)
        await host.configure_chat_model("save-fixture", "model")
        identity = {
            "workspace_id": "test",
            "session_id": "saved",
            "user_id": "alice",
            "channel": "console",
        }
        key = hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode(),
        ).hexdigest()

        async def run():
            return [
                event
                async for event in host.stream_chat(
                    "Persist this turn",
                    session_id="saved",
                    user_id="alice",
                )
            ]

        def signal(phase):
            return inspector.storage.read_json(
                f"session-save/{key}/{phase}.json",
            )

        await run()
        assert signal("pre_execute")["session_saved"] is None
        assert signal("post_response") == {
            "identity": identity,
            "session_saved": True,
        }
        files = list(
            (host.root / "workspaces/test/sessions/console").glob("*.json"),
        )
        assert len(files) == 1
        target = files[0]
        saved = target.read_bytes()
        assert "Saved-state acceptance" in saved.decode()
        backup = target.with_suffix(".saved")

        provider.storage.write_json("entered.json", False)
        provider.storage.write_json("hold.json", True)
        task = asyncio.create_task(run())
        try:
            async with asyncio.timeout(20):
                while not provider.storage.read_json("entered.json"):
                    await asyncio.sleep(0.01)
            # Loading has finished. Make the real atomic destination invalid;
            # no save hook, storage method or SDK signal is replaced.
            target.rename(backup)
            target.mkdir()
            provider.storage.write_json("hold.json", False)
            await task
            assert signal("post_response") == {
                "identity": identity,
                "session_saved": False,
            }
            assert target.is_dir() and backup.read_bytes() == saved
        finally:
            provider.storage.write_json("hold.json", False)
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if target.is_dir():
                target.rmdir()
            if backup.exists():
                backup.rename(target)
        await run()
        assert signal("post_response")["session_saved"] is True
        assert target.read_bytes() != saved
        assert (await host.unload("save-observer")).clean
        host.assert_quiescent("save-observer")
