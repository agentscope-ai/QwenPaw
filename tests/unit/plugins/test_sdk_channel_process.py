# -*- coding: utf-8 -*-
"""Real process, SDK-only driver, native handshake and stop acknowledgment."""

import json
import sys
from pathlib import Path

import pytest

from qwenpaw.__version__ import __version__
from qwenpaw.app.channels.process_supervisor import ChannelProcess, LaunchSpec
from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
from qwenpaw.plugins.channel_workers import ChannelDefinition
from tests.channel_support.driver import HostPeer
from tests.channel_support.process import alive, digest, eventually

SOURCE = """
import json
import os
import threading
from pathlib import Path
from qwenpaw.plugins.channel_workers import ChannelDriver, ChannelSendResult
from qwenpaw.plugins.channels import ChannelMessage
from qwenpaw.plugins.messages import ContentBlock


class Driver(ChannelDriver):
    async def start(self, ch):
        self.path = Path(ch.config["ledger"])
        self.record(
            "identity",
            plugin=ch.plugin_id,
            workspace=ch.workspace_id,
            pid=os.getpid(),
        )
        await ch.auth.required("https://example.test/scan")
        await ch.storage.awrite_json(
            "state.json", {"workspace": ch.workspace_id}
        )
        assert await ch.storage.aread_json("state.json") == {
            "workspace": ch.workspace_id
        }
        media = await ch.media.awrite(
            "sample.txt", b"sample", mime_type="text/plain"
        )
        ch.logger.info(
            "SDK channel storage ready", fields={"workspace": ch.workspace_id}
        )
        self.record("media", url=media.url)
        stop = threading.Event()

        def wait():
            stop.wait()
            self.record("thread-exited")

        ch.resources.thread(wait, stop=stop)
        await ch.report_status("connected")
        result = await ch.receive(
            ChannelMessage(
                "alice",
                (ContentBlock(text="hello"),),
                session_id="room",
                message_id="incoming",
            )
        )
        self.record("received", status=result.status)

    def record(self, kind, **values):
        with self.path.open("a") as output:
            output.write(json.dumps({"kind": kind, **values}) + "\\n")

    async def send(self, ch, response):
        self.record(
            "sent", text=response.content[0].text, target=response.target.key
        )
        return ChannelSendResult("platform-id")

    async def stop(self, ch):
        await ch.storage.awrite_json("stopped.json", {"saved": True})
        self.record("stop")
"""


@pytest.mark.asyncio
async def test_sdk_driver_in_actual_worker_process(tmp_path):
    code = tmp_path / "code"
    code.mkdir()
    (code / "driver.py").write_text(SOURCE)
    definition = ChannelDefinition(
        "example",
        {"en": "Example", "zh": "示例"},
        "driver:Driver",
        {"type": "object", "properties": {}},
        (),
        ("channel.auth.qrcode.v1", "channel.generic.v1"),
    )
    (code / "channel.json").write_text(json.dumps(definition.to_dict()))
    (code / "requirements.txt").write_text("")
    ledger = tmp_path / "ledger.jsonl"
    spec = LaunchSpec(
        python_executable=sys.executable,
        support_root=Path(__file__).resolve().parents[3] / "src",
        code_root=code,
        descriptor_path=code / "channel.json",
        source_revision=digest(code),
        descriptor=SharedChannelDescriptor.load(code / "channel.json"),
        requirements=(),
        channel_key="example",
        instance_id="instance",
        generation=1,
        qwenpaw_version=__version__,
        config={"ledger": str(ledger), "workspace_id": "forged"},
        plugin_id="sdk-example",
        workspace_id=str(tmp_path / "workspace-directory"),
        sdk_workspace_id="workspace-one",
        startup_timeout=10,
        shutdown_timeout=5,
        sdk_storage_root=tmp_path / "storage",
        sdk_media_root=tmp_path / "media",
    )
    peer = HostPeer(tmp_path)
    process = ChannelProcess()
    auth = []

    async def on_auth(params, _notification):
        auth.append(params.to_mapping())

    process.register_notification("channel.auth.required", on_auth)
    for name in (
        "host.state.get",
        "host.state.put",
        "host.receipt.get",
        "host.receipt.put",
        "event.batch",
    ):

        async def call(params, request, name=name):
            return await peer.call(name, params.to_mapping())

        process.register_method(name, call)
    result = None
    pid = None
    try:
        await process.probe(spec)
        assert (
            not ledger.exists()
        ), "Probe must not instantiate or connect a driver"
        await process.stop()
        await process.start(spec)
        await eventually(lambda: bool(peer.batches), timeout=10)
        identity = json.loads(ledger.read_text().splitlines()[0])
        pid = identity["pid"]
        assert identity["workspace"] == "workspace-one"
        assert identity["plugin"] == "sdk-example"
        await eventually(lambda: bool(auth), timeout=5)
        assert auth == [
            {
                "channel_key": "example",
                "instance_id": "instance",
                "generation": 1,
                "scan_url": "https://example.test/scan",
            },
        ]
        assert pid != __import__("os").getpid() and alive(pid)
        event = peer.batches[0]["events"][0]
        params = {
            "channel_key": "example",
            "instance_id": "instance",
            "generation": 1,
            "delivery_id": "out",
            "to_handle": event["response_handle"],
            "operation": "message.create",
            "content_parts": [{"type": "text", "text": "worker answer"}],
        }
        assert (await process.call("channel.send", params))[
            "state"
        ] == "acknowledged"
        assert (await process.call("channel.send", params))[
            "state"
        ] == "acknowledged"
        rows = [json.loads(line) for line in ledger.read_text().splitlines()]
        assert len([r for r in rows if r["kind"] == "sent"]) == 1
    finally:
        result = await process.stop()
    assert result.exited and not result.forced and not result.residual
    assert pid is not None and not alive(pid)
    assert "thread-exited" in ledger.read_text()
    assert (
        json.loads((tmp_path / "storage/state.json").read_text())["workspace"]
        == "workspace-one"
    )
    assert (tmp_path / "media/sample.txt").read_bytes() == b"sample"
    assert json.loads((tmp_path / "storage/stopped.json").read_text()) == {
        "saved": True,
    }
