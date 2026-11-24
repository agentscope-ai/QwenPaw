# -*- coding: utf-8 -*-
"""Local command results and cancellation at the download worker boundary."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from click.testing import CliRunner
import pytest

from llamacpp.cli import build_cli, download_model
from llamacpp.model_types import DownloadSource


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_download_command_preserves_source_and_reports_result(status):
    manager = SimpleNamespace(
        get_model_download_progress=lambda: {
            "status": status,
            "downloaded_bytes": 1024 * 1024,
            "local_path": "/models/example",
            "error": "worker failed" if status == "failed" else None,
        },
    )
    provider = SimpleNamespace(
        start_model_download=AsyncMock(),
        manager=AsyncMock(return_value=manager),
        cancel_model_download=AsyncMock(),
    )
    command = build_cli("download", provider, SimpleNamespace(run=asyncio.run))
    result = CliRunner().invoke(command, ["example/model", "-s", "modelscope"])
    provider.start_model_download.assert_awaited_once_with(
        "example/model",
        source=DownloadSource.MODELSCOPE,
    )
    provider.cancel_model_download.assert_not_awaited()
    assert result.exit_code == (0 if status == "completed" else 1)
    assert (
        "Size: 1.0 MB"
        if status == "completed"
        else "Download failed: worker failed"
    ) in result.output


@pytest.mark.parametrize("interruption", ["startup", "polling", "timeout"])
async def test_interrupted_download_waits_for_worker_cancellation(
    interruption,
):
    started = asyncio.Event()
    release = asyncio.Event()
    polling = asyncio.Event()
    closed = []

    async def start(*_args, **_kwargs):
        started.set()
        await release.wait()

    async def cancel():
        await asyncio.sleep(0)
        closed.append(True)

    def progress():
        polling.set()
        return {"status": "downloading"}

    provider = SimpleNamespace(
        start_model_download=start,
        manager=AsyncMock(
            return_value=SimpleNamespace(get_model_download_progress=progress),
        ),
        cancel_model_download=cancel,
    )
    timeout = interruption == "timeout"
    task = asyncio.create_task(
        download_model(
            provider,
            "example/model",
            DownloadSource.HUGGINGFACE,
            timeout=0 if timeout else 60,
        ),
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        if interruption == "startup":
            task.cancel()
        release.set()
        if interruption == "polling":
            await asyncio.wait_for(polling.wait(), timeout=5)
            task.cancel()
        done, _ = await asyncio.wait({task}, timeout=5)
        assert task in done, "download did not finish after interruption"
        expected = TimeoutError if timeout else asyncio.CancelledError
        with pytest.raises(expected):
            task.result()
    finally:
        release.set()
        if not task.done():
            task.cancel()
            await asyncio.wait({task}, timeout=5)
        assert task.done(), "download did not stop during cleanup"
        if not task.cancelled():
            task.exception()
    assert closed == [True]
