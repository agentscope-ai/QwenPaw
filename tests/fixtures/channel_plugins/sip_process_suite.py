"""Actual ChannelProcess/worker/Driver/native loop; no Core Agent claim."""
import asyncio
import hashlib
from importlib.metadata import PackageNotFoundError, distribution
import json
import os
from pathlib import Path
import shutil
import sys

from qwenpaw.app.channels.process_supervisor import ChannelProcess, LaunchSpec
from qwenpaw.channel_protocol.errors import RpcError
from sip_artifact_suite import CONFIG_DEFAULTS

ROOT = Path(__file__).resolve().parents[3]


async def until(check):
    async with asyncio.timeout(5):
        while not check():
            await asyncio.sleep(0.01)


def digest(directory):
    value = hashlib.sha256()
    for path in sorted(directory.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            name, data = (
                path.relative_to(directory).as_posix().encode(),
                path.read_bytes(),
            )
            value.update(len(name).to_bytes(8, "big"))
            value.update(name)
            value.update(len(data).to_bytes(8, "big"))
            value.update(data)
    return value.hexdigest()


async def test_actual_worker_native_sender_retry_and_unknown_receipt(tmp_path):
    code, work, site = (
        tmp_path / name for name in ("code", "work", "vendor-site")
    )
    work.mkdir()
    site.mkdir()
    shutil.copytree(
        ROOT / "plugins/channel/sip",
        code,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    ns = code / "qwenpaw_channel_sip"
    fixtures = Path(__file__).parent
    (ns / "vendor_boundary.py").write_bytes(
        (fixtures / "sip_vendor_boundary.py").read_bytes()
    )
    (ns / "test_boundary.py").write_text(
        "WORK = "
        + repr(str(work))
        + "\n"
        + (fixtures / "sip_process_boundary.py").read_text()
    )
    descriptor = json.loads((code / "channel.json").read_text())
    descriptor["entrypoint"]["module"] = "qwenpaw_channel_sip.test_boundary"
    (code / "channel.json").write_text(json.dumps(descriptor))
    # Explicit installed substitute distributions; no dependency audit bypass.
    for name, version in [
        ("pyVoIP", "1.6.0"),
        ("dashscope", "1.0.0"),
        ("dashscope-realtime", "0.1.0"),
    ]:
        # The selected interpreter may already supply a real SDK. Retain
        # that origin and its dependency closure instead of duplicating it.
        try:
            distribution(name)
        except PackageNotFoundError:
            pass
        else:
            continue
        metadata = site / (
            name.replace("-", "_") + "-" + version + ".dist-info"
        )
        metadata.mkdir()
        (metadata / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
        )
    # Audio conversion stays native in the selected interpreter. Never
    # manufacture metadata for its conditional extension dependency.
    if sys.version_info >= (3, 13):
        assert distribution("audioop-lts").read_text("RECORD")
    config = {
        **CONFIG_DEFAULTS,
        "enabled": True,
        "sip_server": "registrar.test",
        "sip_port": 25061,
        "dashscope_api_key": "explicit-child-key",
        "welcome_greeting": "",
    }
    spec = LaunchSpec(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        code_root=code,
        descriptor_path=code / "channel.json",
        source_revision=digest(code),
        channel_key="sip",
        instance_id="sip-real-child",
        generation=1,
        qwenpaw_version="2.2.2b4",
        config=config,
        dependency_paths=(site,),
    )
    process = ChannelProcess()
    batches, state = [], {}

    async def get(params, request):
        return {"value": state.get(params.key)}

    async def put(params, request):
        parsed = params
        state[parsed.key] = parsed.value
        return {}

    async def events(params, request):
        batches.append(params)
        if len(batches) == 1:
            raise RpcError(-32000, "controlled host ACK loss")
        return {
            "batch_id": params.batch_id,
            "accepted_event_ids": [event.event_id for event in params.events],
        }

    process.register_method("host.state.get", get)
    process.register_method("host.state.put", put)
    from qwenpaw.channel_protocol.response_receipts import ResponseReceiptStore

    receipts = ResponseReceiptStore(tmp_path / "receipts.sqlite3")

    async def get_receipt(params, request):
        return {"value": receipts.get(params.key)}

    async def put_receipt(params, request):
        receipts.put(params.key, params.value)
        return {"stored": True}

    process.register_method("host.receipt.get", get_receipt)
    process.register_method("host.receipt.put", put_receipt)
    process.register_method("event.batch", events)

    def rows(kind):
        path = work / "ledger.jsonl"
        return (
            [
                row
                for row in map(json.loads, path.read_text().splitlines())
                if row["kind"] == kind
            ]
            if path.exists()
            else []
        )

    def emit(**value):
        with (work / "inbox.jsonl").open("a") as stream:
            stream.write(json.dumps(value) + "\n")

    try:
        await process.start(spec)
        await until(
            lambda: process.health_snapshot()["platform_state"] == "connected"
        )
        child_pid = process.health_snapshot()["pid"]
        assert child_pid and child_pid != os.getpid()
        assert rows("loaded")[0]["pid"] == child_pid
        emit(
            kind="incoming",
            call_id="native-call",
            sender="sip:real-sender@example.test",
        )
        await until(lambda: rows("asr"))
        assert rows("asr")[0]["key"] == "explicit-child-key"
        emit(kind="transcript", text="one prompt")
        await until(lambda: len(batches) >= 2)
        assert (
            batches[0] == batches[1]
        ), "IPC retry must preserve event, batch and reply route"
        event = batches[-1].events[0]
        assert (
            event.sender_id
            == event.acl_sender_id
            == "sip:real-sender@example.test"
        )
        assert event.conversation["id"] == "sip:native-call"
        assert event.content_parts == ({"type": "text", "text": "one prompt"},)
        emit(kind="fail_write", value=True)
        await until(lambda: len(rows("command")) == 3)
        params = {
            **{
                key: event.to_mapping()[key]
                for key in ("channel_key", "instance_id", "generation")
            },
            "delivery_id": "child-delivery",
            "to_handle": event.response_handle,
            "operation": "message.create",
            "content_parts": [{"type": "text", "text": "answer"}],
        }
        first = await process.call("channel.send", params)
        assert first["state"] == "unknown"
        assert await process.call("channel.send", params) == first
        await until(lambda: rows("audio"))
        assert len(rows("audio")) == 1
        assert rows("audio")[0]["pid"] == child_pid
        assert rows("audio")[0]["hex"] == (bytes([128]) * 160).hex()
        await process.call(
            "channel.response.finish",
            {
                **{
                    key: event.to_mapping()[key]
                    for key in ("channel_key", "instance_id", "generation")
                },
                "response_handle": event.response_handle,
                "outcome": "failed",
            },
        )
    finally:
        (work / "stop-boundary").touch()
        result = await process.stop()
        assert result.exited and not result.residual
