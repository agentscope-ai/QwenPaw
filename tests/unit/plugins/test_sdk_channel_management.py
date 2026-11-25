# -*- coding: utf-8 -*-
"""Public management callbacks exercised across a real worker boundary."""

import asyncio
import json
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from qwenpaw.__version__ import __version__
from qwenpaw.app.channels.process_supervisor import ChannelProcess, LaunchSpec
from qwenpaw.channel_protocol.shared import SharedChannelDescriptor
from qwenpaw.channel_protocol.errors import RpcError
from qwenpaw.plugins.channel_workers import ChannelDefinition
from tests.channel_support.process import alive, digest, eventually

SOURCE = """
import asyncio
import json
import os
from pathlib import Path
from qwenpaw.plugins.channel_workers import ChannelDriver
from qwenpaw.plugins.channel_management import (
    ChannelQRCode, ChannelAuthorization, ChannelVerification,
    ChannelManagementFailure,
)

class Driver(ChannelDriver):
    def __init__(self):
        raise AssertionError("Management must not instantiate a runtime driver")

    async def start(self, ch):
        raise AssertionError("Management must not start a channel")

    async def send(self, ch, response):
        raise AssertionError("Management must not send messages")

    @staticmethod
    async def manage(request):
        path = Path(request.config["ledger"])
        request.resources.defer(lambda: path.with_suffix(".closed").write_text("closed"))
        path.write_text(json.dumps({"pid": os.getpid(), "workspace": request.workspace_id,
            "plugin": request.plugin_id, "operation": request.operation}))
        request.check_cancelled()
        assert 0 < request.remaining_timeout() <= 10
        try:
            request.config["forged"] = True
        except TypeError:
            pass
        else:
            raise AssertionError("Config must be immutable")
        mode = request.config.get("mode")
        if mode in {"timeout", "cancel"}:
            await asyncio.Event().wait()
        if mode == "mismatch":
            return ChannelQRCode("https://example.test/scan", "opaque")
        if mode == "failure":
            return ChannelManagementFailure("PLATFORM_REJECTED")
        if request.operation == "qrcode.fetch":
            return ChannelQRCode("https://example.test/scan", "opaque", 60)
        if request.operation == "qrcode.poll":
            assert request.continuation == "opaque"
            field = "forbidden" if mode == "credential" else "token"
            return ChannelAuthorization("authorized", {field: "secret"})
        return ChannelVerification(request.verification_level, "passed")
"""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation,mode,error",
    [
        ("qrcode.fetch", "", None),
        ("qrcode.poll", "", None),
        ("connection.verify", "", None),
        ("connection.verify", "failure", None),
        ("connection.verify", "mismatch", "MANAGEMENT_INVALID_RESULT"),
        ("qrcode.poll", "credential", "MANAGEMENT_INVALID_RESULT"),
        ("connection.verify", "timeout", "MANAGEMENT_TIMEOUT"),
        ("connection.verify", "cancel", "cancel"),
    ],
)
async def test_management_one_shot_identity_cleanup(
    tmp_path,
    operation,
    mode,
    error,
):
    code = tmp_path / "code"
    code.mkdir()
    (code / "driver.py").write_text(SOURCE)
    (code / "requirements.txt").write_text("")
    definition = ChannelDefinition(
        "sdk-managed",
        {"en": "Managed", "zh": "管理验证"},
        "driver:Driver",
        {"type": "object", "properties": {"token": {"type": "string"}}},
        ("token",),
        (
            "channel.generic.v1",
            "channel.management.qrcode.v1",
            "channel.management.verify.v1",
        ),
        authorization_fields=("token",),
    )
    (code / "channel.json").write_text(json.dumps(definition.to_dict()))
    spec = LaunchSpec(
        python_executable=sys.executable,
        support_root=Path(__file__).resolve().parents[3] / "src",
        code_root=code,
        descriptor_path=code / "channel.json",
        source_revision=digest(code),
        descriptor=SharedChannelDescriptor.load(code / "channel.json"),
        requirements=(),
        channel_key="sdk-managed",
        instance_id="management",
        generation=1,
        qwenpaw_version=__version__,
        config={},
        plugin_id="sdk-managed",
        workspace_id=str(tmp_path / "workspace"),
        sdk_workspace_id="workspace-public",
        startup_timeout=10,
        shutdown_timeout=5,
    )
    ledger = tmp_path / "call.json"
    parameters = {
        "config": {
            "ledger": str(ledger),
            "mode": mode,
            "workspace_id": "forged",
        },
    }
    if operation == "connection.verify":
        parameters["level"] = "credentials"
    elif operation == "qrcode.poll":
        parameters["continuation"] = "opaque"
    request = {
        name: getattr(spec, name)
        for name in (
            "plugin_id",
            "workspace_id",
            "channel_key",
            "instance_id",
            "generation",
            "source_revision",
        )
    }
    request.update(
        request_id=str(uuid4()),
        operation=operation,
        parameters=parameters,
        timeout_ms=100 if mode == "timeout" else 10000,
    )
    process = ChannelProcess()
    try:
        await process.start_management(spec)
        with pytest.raises(Exception, match="IDENTITY_MISMATCH"):
            await process.call(
                "channel.management.execute",
                {**request, "workspace_id": "other"},
            )
        assert (
            not ledger.exists()
        ), "Rejected identity must not invoke the plugin"
        if mode == "cancel":
            call = asyncio.create_task(
                process.call("channel.management.execute", request),
            )
            await eventually(ledger.exists, timeout=5)
            call.cancel()
            with pytest.raises(asyncio.CancelledError):
                await call
            await eventually(ledger.with_suffix(".closed").exists, timeout=5)
        elif error:
            with pytest.raises(RpcError) as failure:
                await process.call("channel.management.execute", request)
            assert failure.value.data["reason_code"] == error
        else:
            result = await process.call("channel.management.execute", request)
            assert result["workspace_id"] == spec.workspace_id
            assert result["request_id"] == request["request_id"]
            assert result["outcome"] == (
                "failed" if mode == "failure" else "ok"
            )
        with pytest.raises(Exception, match="MANAGEMENT_UNSUPPORTED"):
            await process.call("channel.management.execute", request)
        recorded = json.loads(ledger.read_text())
        assert recorded["workspace"] == "workspace-public"
        assert recorded["plugin"] == "sdk-managed"
        assert ledger.with_suffix(".closed").read_text() == "closed"
    finally:
        stopped = await process.stop()
    assert stopped.exited and not stopped.residual and not stopped.forced
    assert not alive(recorded["pid"])
