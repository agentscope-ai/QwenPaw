"""Installed-wheel loader, real paho SDK, local MQTT transport acceptance."""

import asyncio
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sys

import psutil
import qwenpaw
from qwenpaw.app.channels.isolated_proxy import IsolatedChannelProxy
from qwenpaw.app.channels.process_supervisor import ChannelProcess, LaunchSpec
from qwenpaw.app.channels.unified_queue_manager import EnqueueResult
from qwenpaw.config.utils import get_config_path, load_config
from qwenpaw.plugins.channel_bootstrap import resolve_default_channel_runtime
from qwenpaw.plugins.loader import PluginLoader
from qwenpaw.plugins.official_channels import provision_bundled_channels
from qwenpaw.schemas import TextContent


def tree(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


async def main():
    installed = Path(sys.prefix).resolve()
    assert Path(qwenpaw.__file__).resolve().is_relative_to(installed)
    assert not any("QwenPaw-main_new/src" in item for item in sys.path)
    runtime = resolve_default_channel_runtime()
    root = get_config_path().parent
    dependencies = tree(runtime.dependency_install_target)
    loader = PluginLoader([root / "plugins"], channel_runtime=runtime)
    await loader.load_all_plugins(
        configs=load_config().plugins, types=["channel"], activate=False
    )
    assert await provision_bundled_channels(loader) == {}
    record = loader.get_loaded_plugin("mqtt")
    assert record is not None and record.enabled
    await loader.lifecycle.prepare_backend(
        record.backend_binding, allow_install=False, probe=True
    )
    assert "channel_validation_passed" in record.diagnostics
    description = record.backend_binding.description.payload
    snapshot = await record.backend_binding.backend.audit_dependencies(
        record.backend_binding.description
    )
    sdk = snapshot.distributions["paho-mqtt"]
    sdk_origin = Path(sdk["metadata_path"]).resolve()
    assert sdk_origin.is_relative_to(installed) or sdk_origin.is_relative_to(
        runtime.dependency_install_target
    )
    source = tree(description.code_root)
    received, queued, broker_errors = [], [], []

    async def broker(reader, writer):
        try:
            while True:
                header = (await reader.readexactly(1))[0]
                length, multiplier = 0, 1
                while True:
                    byte = (await reader.readexactly(1))[0]
                    length += (byte & 127) * multiplier
                    if byte < 128:
                        break
                    multiplier *= 128
                body = await reader.readexactly(length)
                kind = header >> 4
                if kind == 1:
                    writer.write(b"\x20\x02\x00\x00")
                elif kind == 8:
                    writer.write(b"\x90\x03" + body[:2] + b"\x00")
                    topic = b"qwenpaw/in/client17"
                    payload = json.dumps(
                        {
                            "text": "historic inbound",
                            "redirect_client_id": "client17",
                        }
                    ).encode()
                    packet = len(topic).to_bytes(2, "big") + topic + payload
                    assert len(packet) < 128
                    writer.write(b"\x30" + bytes([len(packet)]) + packet)
                elif kind == 3:
                    topic_length = int.from_bytes(body[:2], "big")
                    received.append(
                        (
                            body[2 : 2 + topic_length].decode(),
                            body[2 + topic_length :].decode(),
                        )
                    )
                elif kind == 12:
                    writer.write(b"\xd0\x00")
                elif kind == 14:
                    return
                await writer.drain()
        except asyncio.IncompleteReadError:
            return
        except Exception as exc:
            broker_errors.append(repr(exc))
            raise
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(broker, "127.0.0.1", 0)
    config = load_config().channels.mqtt.model_dump()
    config.update(
        host="127.0.0.1", port=server.sockets[0].getsockname()[1], qos=0
    )
    spec = LaunchSpec(
        python_executable=runtime.python_executable,
        support_root=runtime.support_root,
        code_root=description.code_root,
        descriptor_path=description.descriptor_path,
        source_revision=description.source_revision,
        channel_key="mqtt",
        instance_id="upgraded",
        generation=1,
        qwenpaw_version=runtime.qwenpaw_version,
        config=config,
        dependency_paths=runtime.dependency_paths,
    )
    previous_pid = None

    async def admit(payload):
        queued.append(payload)
        return EnqueueResult(True)

    try:
        for generation in (1, 2):
            process = ChannelProcess()
            channel = IsolatedChannelProxy(
                None,
                launch_spec=replace(spec, generation=generation),
                channel_process=process,
                workspace_dir=root / "workspace",
            )
            channel.set_enqueue_async(admit)
            pid = None
            try:
                try:
                    await channel.start()
                except Exception as exc:
                    raise AssertionError(process.health_snapshot()) from exc
                assert (await channel.health_check())[
                    "platform_state"
                ] == "connected"
                pid = process.health_snapshot()["pid"]
                assert pid != os.getpid() and pid != previous_pid
                async with asyncio.timeout(5):
                    while len(queued) < generation:
                        await asyncio.sleep(0.01)
                assert queued[-1]["content_parts"] == [
                    TextContent(text="historic inbound")
                ], queued[-1]
                assert queued[-1]["session_id"] == "mqtt:client17"
                await channel.send("client17", f"upgraded-{generation}")
                async with asyncio.timeout(5):
                    while len(received) < generation:
                        await asyncio.sleep(0.01)
            finally:
                await channel.stop()
                assert process.health_snapshot()["pid"] is None
                assert pid is None or not psutil.pid_exists(pid)
            previous_pid = pid
    finally:
        server.close()
        await server.wait_closed()
    assert received == [
        ("qwenpaw/out/client17", "upgraded-1"),
        ("qwenpaw/out/client17", "upgraded-2"),
    ]
    assert broker_errors == []
    assert tree(description.code_root) == source
    assert tree(runtime.dependency_install_target) == dependencies
    assert load_config().channels.mqtt.enabled
    print(json.dumps({"sdk_origin": str(sdk_origin), "sent": received}))


asyncio.run(main())
