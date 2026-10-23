"""Pending public freeze: actual native relative-path compatibility only."""
import asyncio
import base64
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys

import pytest

from imessage_native_support import (
    ROOT,
    SOURCE,
    native_fixture,
    commands,
    insert,
)


@asynccontextmanager
async def relative_runtime(tmp_path, monkeypatch, *, relative_db):
    # This existing metadata constructor is a private test, not owner/catalog admission.
    from qwenpaw.plugins.channel_adapter import ChannelDescription
    from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
    from qwenpaw.plugins.execution.bootstrap import _hash_code_root
    from qwenpaw.config.config import Config
    from qwenpaw.app.channels.unified_queue_manager import EnqueueResult

    monkeypatch.setattr("qwenpaw.app.channels.base.load_config", Config)
    host = tmp_path / "host"
    directory, absolute = native_fixture(host, monkeypatch)
    monkeypatch.chdir(host)
    code = tmp_path / "separate-plugin-code"
    shutil.copytree(SOURCE, code, ignore=shutil.ignore_patterns("__pycache__"))
    config = {
        key: value for key, value in absolute.items() if key != "workspace_dir"
    }
    config["db_path"] = (
        "messages.sqlite" if relative_db else absolute["db_path"]
    )
    config["media_dir"] = "relative-media"
    snapshot = deepcopy(config)
    saved = directory / "saved-config.json"
    saved.write_text(json.dumps(config, sort_keys=True))
    saved_bytes = saved.read_bytes()
    insert(absolute, "startup history must not replay")
    desc = ChannelDescription(
        plugin_id="imessage",
        version="2.0.0",
        descriptor=SharedChannelDescriptor.load(code / "channel.json"),
        descriptor_path=code / "channel.json",
        code_root=code,
        requirements_path=code / "requirements.txt",
        requirements=(),
        source_revision=_hash_code_root(code),
        name="iMessage",
        description="Actual path compatibility fixture",
    )

    async def no_agent(request):
        raise AssertionError(
            "This test only observes admission; no Agent claim"
        )
        yield

    queue = asyncio.Queue()

    async def enqueue(event):
        await queue.put(event)
        return EnqueueResult(True)

    from qwenpaw.plugins.official_execution_context import (
        project_official_execution,
    )

    projected, private_env = project_official_execution(
        "imessage",
        config,
        working_dir=Path.cwd(),
        legacy_state_dir=directory / "legacy",
        environment=os.environ,
        workspace_dir=directory / "workspace",
    )
    channel = desc.create_proxy(
        no_agent,
        projected,
        private_env=private_env,
        python_executable=sys.executable,
        support_root=ROOT / "src",
        instance_id="imessage-relative-context",
        generation=1,
        qwenpaw_version="2.2.2b4",
        workspace_dir=directory / "workspace",
    )
    channel.set_enqueue_async(enqueue)
    try:
        await channel.start()
        assert channel.channel_process.health_snapshot()["pid"] != os.getpid()
        yield channel, directory, absolute, code, queue
    finally:
        receipt = await channel.stop()
        assert receipt.exited and not receipt.residual
        assert config == snapshot and saved.read_bytes() == saved_bytes


@pytest.mark.asyncio
async def test_relative_database_uses_host_cwd_with_distinct_child_code_root(
    tmp_path, monkeypatch
):
    async with relative_runtime(tmp_path, monkeypatch, relative_db=True) as (
        channel,
        directory,
        config,
        code,
        queue,
    ):
        insert(config, "host database input")
        async with asyncio.timeout(5):
            payload = await queue.get()
        request = channel.build_agent_request_from_native(payload)
        assert [
            part.text for message in request.input for part in message.content
        ] == ["host database input"]
        assert not (code / "messages.sqlite").exists()


@pytest.mark.asyncio
async def test_relative_media_uses_host_cwd_for_actual_tiny_native_send(
    tmp_path, monkeypatch
):
    async with relative_runtime(tmp_path, monkeypatch, relative_db=False) as (
        channel,
        directory,
        config,
        code,
        queue,
    ):
        await channel.send_media(
            "+15550002222",
            {"type": "image", "image_url": "data:image/png;base64,YWJj"},
        )
        record = commands(directory)[-1]
        assert base64.b64decode(record["file_bytes"]) == b"abc"
        actual = Path(record["argv"][record["argv"].index("--file") + 1])
        print(
            json.dumps(
                {
                    "actual_native_media": str(actual),
                    "expected_parent": str(directory / "relative-media"),
                    "child_code_root": str(code),
                }
            )
        )
        assert actual.parent == directory / "relative-media"
        assert not (code / "relative-media").exists()
