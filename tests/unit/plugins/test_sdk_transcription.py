# -*- coding: utf-8 -*-
"""SDK transcription registration and live worker teardown."""

import asyncio
from pathlib import Path

import pytest

from qwenpaw.plugins import PluginBusyError
from qwenpaw.plugins.testing import PluginTestHost

from .sdk_author_fixture import make_plugin

SOURCE = """
from pathlib import Path
import time
from qwenpaw.plugins.transcription import (
    TranscriptionSpec, TranscriptionResult, TranscriptionStatus,
)

class Plugin:
    def register(self, ctx):
        ctx.register_transcription(TranscriptionSpec(
            "sample", "Sample", self.transcribe, self.status,
        ))

    def status(self, call):
        return TranscriptionStatus(True)

    def transcribe(self, call, path):
        if path == "context":
            return TranscriptionResult(
                call.workspace_id + ":" + call.session_id
            )
        started, release = Path(path + ".started"), Path(path + ".release")
        started.touch()
        end = time.monotonic() + 5
        while not release.exists() and time.monotonic() < end:
            time.sleep(0.005)
        return TranscriptionResult("finished")

plugin = Plugin()
"""


async def test_public_backend_context_and_registration_release(tmp_path):
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, SOURCE, ["transcription"]))
        assert (await host.transcription_status("sample")).available
        result = await host.transcribe(
            "sample",
            "context",
            workspace_id="workspace",
            session_id="session",
        )
        assert result.text == "workspace:session"
        assert (
            host.resource_snapshot("extension-contract")["active_calls"] == 0
        )
        assert (await host.unload("extension-contract")).quiescent
        with pytest.raises(
            RuntimeError,
            match="Unknown transcription backend",
        ):
            await host.transcribe("sample", "context")


async def test_cancelled_worker_blocks_unload_until_thread_finishes(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "qwenpaw.plugins.activity.INTERRUPT_TIMEOUT_SECONDS",
        0.02,
    )
    async with PluginTestHost(tmp_path / "host") as host:
        await host.load(make_plugin(tmp_path, SOURCE, ["transcription"]))
        path = str(tmp_path / "audio")
        task = asyncio.create_task(host.transcribe("sample", path))
        try:
            async with asyncio.timeout(3):
                while not Path(path + ".started").exists():
                    await asyncio.sleep(0.005)
            with pytest.raises(PluginBusyError):
                await host.unload("extension-contract")
            with pytest.raises(PluginBusyError) as caught:
                await host.unload("extension-contract", interrupt_tasks=True)
            assert caught.value.detail["quiescent"] is False
            assert (
                host.resource_snapshot("extension-contract")["active_calls"]
                > 0
            )
            assert not task.done()
            with pytest.raises(PluginBusyError):
                await host.transcribe("sample", "context")
        finally:
            Path(path + ".release").touch()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert (await host.unload("extension-contract")).quiescent
