# -*- coding: utf-8 -*-
"""Healthy delayed child under the actual default Channel launch budget."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[4]
FIXTURES = ROOT / "tests/fixtures/channel_plugins"


@pytest.mark.slow
@pytest.mark.asyncio
async def test_c7_default_budget_accepts_healthy_six_second_import(
    tmp_path: Path,
) -> None:
    """Real child protocol; only its external driver import is delayed."""
    from qwenpaw.__version__ import __version__
    from qwenpaw.app.channels.process_supervisor import (
        ChannelProcess,
        LaunchSpec,
    )
    from qwenpaw.channel_protocol.artifacts import code_root_digest
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings

    settings = ChannelRuntimeSettings(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        qwenpaw_version=__version__,
        selected_channels=frozenset({"feishu"}),
    )
    code = tmp_path / "channel-code"
    code.mkdir()
    driver = (FIXTURES / "shared_process_driver.py").read_text(
        encoding="utf-8",
    )
    (code / "driver.py").write_text(
        "import time\ntime.sleep(5.2)\n" + driver,
        encoding="utf-8",
    )
    descriptor = json.loads(
        (ROOT / "plugins/channel/feishu/channel.json").read_text(
            encoding="utf-8",
        ),
    )
    descriptor["entrypoint"].update(module="driver", qualname="Driver")
    (code / "channel.json").write_text(
        json.dumps(descriptor),
        encoding="utf-8",
    )
    (code / "requirements.txt").write_text("", encoding="utf-8")
    spec = LaunchSpec(
        python_executable=settings.python_executable,
        support_root=settings.support_root,
        code_root=code,
        descriptor_path=code / "channel.json",
        source_revision=code_root_digest(code),
        channel_key="feishu",
        instance_id="c7-default-delay",
        generation=1,
        qwenpaw_version=__version__,
        config={},
        startup_timeout=settings.startup_timeout,
    )
    process = ChannelProcess()
    try:
        health = await asyncio.wait_for(process.start(spec), timeout=15)
        assert settings.startup_timeout == 10.0
        assert health["state"] == "ready"
        assert health["pid"] is not None
    finally:
        await process.stop()
