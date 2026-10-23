# -*- coding: utf-8 -*-
"""G3 generic real-child fixture; service/launch seams await production freeze.

The sample has no platform SDK and performs actual local HTTP in static manage.
Nothing imports the sample in the parent. Audit/probe tests use shipped public
APIs; no guessed launch packet or fabricated Loader/runtime stands in for G3.
"""

import asyncio
from dataclasses import replace
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import psutil
import pytest
import pytest_asyncio

ROOT = Path(__file__).resolve().parents[3]
KEY = "management_sample"


class ParentManagementImportGuard(importlib.abc.MetaPathFinder):
    def __init__(self):
        self.attempts = []

    @staticmethod
    def blocks(name):
        return name.startswith(
            (
                "management_sample.",
                "feishu.",
                "dingtalk.",
                "wechat.",
                "qq.",
                "wecom.",
                "mattermost.",
                "mqtt.",
                "qwenpaw.app.channels.feishu",
                "qwenpaw.app.channels.dingtalk",
                "qwenpaw.app.channels.wechat",
                "qwenpaw.app.channels.qq",
                "qwenpaw.app.channels.wecom",
                "qwenpaw.app.channels.mattermost",
                "qwenpaw.app.channels.mqtt",
                "qwenpaw.app.channels.qrcode",
            )
        ) or name.split(".")[0] in {
            "lark_oapi",
            "dingtalk_stream",
            "wecom_aibot_sdk",
            "wecom_aibot",
            "paho",
            "nio",
            "discord",
            "telegram",
            "slack_bolt",
            "Tea",
            "aibot",
        }

    def find_spec(self, fullname, path=None, target=None):
        if self.blocks(fullname):
            self.attempts.append(fullname)
            raise AssertionError(
                "Management sample/SDK imported in host: " + fullname
            )


GUARD = ParentManagementImportGuard()
assert not any(GUARD.blocks(name) for name in sys.modules), [
    name for name in sys.modules if GUARD.blocks(name)
]
sys.meta_path.insert(0, GUARD)


@pytest.fixture(autouse=True)
def parent_import_boundary():
    yield
    assert not GUARD.attempts
    assert not any(GUARD.blocks(name) for name in sys.modules)


DRIVER = """import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

Path(IMPORT_MARKER).write_text(str(os.getpid()), encoding="utf-8")

class Driver:
    def __init__(self):
        raise AssertionError("management constructed Driver")

    def bind(self, context):
        raise AssertionError("management bound Driver")

    async def start(self, config):
        raise AssertionError("management started consumer")

    async def stop(self):
        raise AssertionError("management invoked instance stop")

    @staticmethod
    async def manage(request):
        data = request.to_mapping()
        config = data["parameters"]["config"]
        if config.get("behavior") == "raise":
            raise RuntimeError("SDK leaked fixture-secret-and-password")
        if config.get("behavior") == "descendant":
            child = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"])
            Path(DESCENDANT_MARKER).write_text(str(child.pid), encoding="utf-8")
        reader, writer = await asyncio.open_connection(config["host"], config["port"])
        try:
            body = json.dumps({
                "operation": data["operation"],
                "continuation": data["parameters"].get("continuation"),
                "level": data["parameters"].get("level"),
                "request_id": data["request_id"],
                "workspace_id": data["workspace_id"],
                "instance_id": data["instance_id"],
                "config": config,
            }).encode()
            headers = (
                "POST /manage HTTP/1.1\\r\\nHost: fixture\\r\\n"
                "X-Fixture-Pid: %s\\r\\nContent-Length: %s\\r\\n"
                "Connection: close\\r\\n\\r\\n" % (os.getpid(), len(body))
            ).encode()
            writer.write(headers + body)
            await writer.drain()
            if config.get("behavior") == "blocking":
                import time
                time.sleep(60)
            try:
                header = await reader.readuntil(b"\\r\\n\\r\\n")
                if not header.startswith(b"HTTP/1.1 200 "):
                    raise RuntimeError("FIXTURE_HTTP_FAILED")
                response = json.loads(await reader.read())
            except asyncio.CancelledError:
                if config.get("behavior") != "swallow":
                    raise
                while True:
                    try:
                        await asyncio.sleep(1)
                    except asyncio.CancelledError:
                        continue
            if response.pop("__exit_worker", False):
                os._exit(0)
            envelope = {name: data[name] for name in (
                "request_id", "plugin_id", "workspace_id", "channel_key",
                "instance_id", "generation", "source_revision", "operation",
            )}
            identity_override = response.pop("__identity_override", {})
            return {
                **envelope, "outcome": "ok", "reason_code": None,
                "result": response, **identity_override,
            }
        finally:
            writer.close()
            await writer.wait_closed()
"""


def management_sample_source(
    directory,
    *,
    capabilities=None,
    probe_socket=None,
    manage_style="static",
    run_driver=False,
    import_delay=0,
):
    """Create an installed-artifact shape without importing its Driver."""
    source = Path(directory) / KEY
    package = source / KEY
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    marker = Path(directory) / "driver-import.pid"
    descendant = Path(directory) / "descendant.pid"
    prelude = "IMPORT_MARKER = " + repr(str(marker)) + "\n"
    prelude += "DESCENDANT_MARKER = " + repr(str(descendant)) + "\n"
    if import_delay:
        prelude += "import time\ntime.sleep(" + repr(import_delay) + ")\n"
    if probe_socket is not None:
        prelude += (
            "import socket\n"
            "socket.create_connection(" + repr(probe_socket) + ")\n"
        )
    driver = DRIVER
    if manage_style == "instance":
        driver = driver.replace(
            "    @staticmethod\n    async def manage(request):",
            "    async def manage(self, request):",
        )
    elif manage_style == "sync":
        driver = (
            driver[: driver.index("    @staticmethod\n")]
            + "    @staticmethod\n    def manage(request):\n        return {}\n"
        )
    elif manage_style == "varargs":
        driver = driver.replace(
            "async def manage(request):", "async def manage(request, *args):"
        )
    if run_driver:
        driver = driver.replace(
            'raise AssertionError("management constructed Driver")',
            "self.context = None",
        )
        driver = driver.replace(
            'raise AssertionError("management bound Driver")',
            "self.context = context",
        )
        driver = driver.replace(
            'raise AssertionError("management started consumer")',
            'await self.context.set_platform_state("connected")',
        )
        driver = driver.replace(
            'raise AssertionError("management invoked instance stop")',
            "return None",
        )
    (package / "driver.py").write_text(prelude + driver, encoding="utf-8")
    descriptor = {
        "schema_version": 2,
        "channel_key": KEY,
        "label": {"en": "Management Sample", "zh": "管理测试"},
        "process_mode": "runner_process",
        "dependency_mode": "shared",
        "entrypoint": {
            "scope": "runner",
            "module": KEY + ".driver",
            "qualname": "Driver",
        },
        "requirements_file": "requirements.txt",
        "config_schema": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "default": False},
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "behavior": {"type": "string", "default": "normal"},
                "api_token": {"type": "string", "default": ""},
            },
            "additionalProperties": False,
        },
        "config_fields": ["enabled", "host", "port", "behavior", "api_token"],
        "capabilities": (
            capabilities
            if capabilities is not None
            else [
                "channel.generic.v1",
                "channel.management.qrcode.v1",
                "channel.management.verify.v1",
            ]
        ),
    }
    (source / "channel.json").write_text(
        json.dumps(descriptor), encoding="utf-8"
    )
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": KEY,
                "version": "1.0.0",
                "name": "Management Sample",
                "type": "channel",
                "entry": {"descriptor": "channel.json"},
            }
        ),
        encoding="utf-8",
    )
    (source / "requirements.txt").write_text(
        "# Standard library only\n", encoding="utf-8"
    )
    return SimpleNamespace(source=source, marker=marker, descendant=descendant)


def source_revision(root):
    """Independent digest of the real generated artifact, without bytecode."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            name = path.relative_to(root).as_posix().encode()
            data = path.read_bytes()
            digest.update(len(name).to_bytes(8, "big"))
            digest.update(name)
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
    return digest.hexdigest()


def inspection_spec(sample):
    """Only use the already frozen inspection LaunchSpec fields."""
    from qwenpaw.app.channels.process_supervisor import LaunchSpec

    return LaunchSpec(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        code_root=sample.source,
        descriptor_path=sample.source / "channel.json",
        source_revision=source_revision(sample.source),
        channel_key=KEY,
        instance_id="fixture-inspection",
        generation=1,
        qwenpaw_version="2.2.2b4",
        config={},
        startup_timeout=5,
        shutdown_timeout=2,
        restart_limit=0,
    )


@pytest_asyncio.fixture
async def local_management_http():
    """Record real child PIDs and support blocked/disconnected response cases."""
    requests = []
    tasks = set()
    reply_gate = asyncio.Event()
    reply_gate.set()
    fixture = SimpleNamespace(
        requests=requests,
        reply_gate=reply_gate,
        disconnect=False,
        response=None,
    )

    async def respond(reader, writer):
        task = asyncio.current_task()
        tasks.add(task)
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            lines = header.decode().split("\r\n")
            headers = dict(
                line.split(": ", 1) for line in lines[1:] if ": " in line
            )
            body = await reader.readexactly(int(headers["Content-Length"]))
            data = json.loads(body)
            requests.append({"pid": int(headers["X-Fixture-Pid"]), **data})
            await reply_gate.wait()
            if fixture.disconnect:
                return
            response = fixture.response
            if response is None:
                response = {
                    "qrcode.fetch": {
                        "scan_url": "https://fixture.invalid/scan",
                        "continuation": "fixture-continuation",
                    },
                    "qrcode.poll": {
                        "status": "confirmed",
                        "credentials": {"api_token": "fixture-result-secret"},
                    },
                    "connection.verify": {
                        "level": data["level"],
                        "verdict": "passed",
                        "reason_code": None,
                        "notes": ["Fixture reached"],
                    },
                }[data["operation"]]
            encoded = json.dumps(response).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nConnection: close\r\nContent-Length: "
                + str(len(encoded)).encode()
                + b"\r\n\r\n"
                + encoded
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            tasks.discard(task)

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    fixture.host, fixture.port = server.sockets[0].getsockname()[:2]
    try:
        yield fixture
    finally:
        server.close()
        for task in tuple(tasks):
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Python 3.13 Server.wait_closed also waits for existing connections.
        # Settle our held reply handlers before awaiting server closure.
        await server.wait_closed()


@pytest.mark.asyncio
async def test_management_fixture_audit_has_no_candidate_import_or_network(
    tmp_path, local_management_http
):
    from qwenpaw.app.channels.process_supervisor import ChannelProcess

    sample = management_sample_source(
        tmp_path,
        probe_socket=(local_management_http.host, local_management_http.port),
    )
    process = ChannelProcess()
    result = await process.audit(inspection_spec(sample))
    assert result.hello is None
    assert (
        Path(result.snapshot.executable).resolve()
        == Path(sys.executable).resolve()
    )
    assert result.cleanup.exited and not result.cleanup.residual
    assert not sample.marker.exists()
    assert not local_management_http.requests
    assert process.health_snapshot()["state"] == "stopped"


@pytest.mark.asyncio
async def test_management_fixture_probe_imports_without_constructing_consumer(
    tmp_path,
):
    from qwenpaw.app.channels.process_supervisor import ChannelProcess

    sample = management_sample_source(tmp_path)
    process = ChannelProcess()
    result = await process.probe(inspection_spec(sample))
    assert result.hello["channel_key"] == KEY
    assert result.cleanup.exited and not result.cleanup.residual
    pid = int(sample.marker.read_text(encoding="utf-8"))
    assert pid != os.getpid()
    assert not psutil.pid_exists(pid)
    assert process.health_snapshot()["platform_state"] != "connected"


@pytest.mark.asyncio
async def test_management_fixture_probe_denies_socket_and_confirms_cleanup(
    tmp_path, local_management_http
):
    from qwenpaw.app.channels.process_supervisor import (
        ChannelProcess,
        ChannelProcessError,
    )

    sample = management_sample_source(
        tmp_path,
        probe_socket=(local_management_http.host, local_management_http.port),
    )
    process = ChannelProcess()
    with pytest.raises(ChannelProcessError) as rejected:
        await process.probe(inspection_spec(sample))
    assert rejected.value.reason_code == "PROBE_NETWORK_OR_PROCESS_DENIED"
    assert process.last_cleanup.exited and not process.last_cleanup.residual
    assert not sample.marker.exists()
    assert not local_management_http.requests


async def eventually(predicate):
    """A sharp diagnostic bound, separate from production operation budgets."""
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


def management_spec(sample, workspace="workspace-A"):
    return replace(
        inspection_spec(sample),
        plugin_id=KEY,
        workspace_id=workspace,
        enabled=False,
        config={},
        instance_id="fixture-" + workspace,
    )


def management_request(spec, http, operation="qrcode.fetch", **changes):
    from qwenpaw.channel_protocol.management import ManagementRequest

    parameters = {
        "config": {"enabled": False, "host": http.host, "port": http.port}
    }
    if operation == "qrcode.poll":
        parameters["continuation"] = "fixture-continuation"
    if operation == "connection.verify":
        parameters["level"] = "reachability"
    data = {
        "request_id": "d095974b-e2f1-4e78-81e2-47767df96632",
        "plugin_id": spec.plugin_id,
        "workspace_id": spec.workspace_id,
        "channel_key": spec.channel_key,
        "instance_id": spec.instance_id,
        "generation": spec.generation,
        "source_revision": spec.source_revision,
        "operation": operation,
        "timeout_ms": 3000,
        "parameters": parameters,
        **changes,
    }
    return ManagementRequest.from_mapping(data)


@pytest_asyncio.fixture
async def management_runtime(tmp_path, monkeypatch):
    """Actual installed Loader plus app-lifetime Service, without Agent mocks."""
    from qwenpaw.plugins.channel_adapter import ChannelRuntimeSettings
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.app.channels.management import ChannelManagementService

    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "host/config.json",
    )
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir", lambda: tmp_path / "installed"
    )
    previous = PluginRegistry._instance
    PluginRegistry._instance = None
    loaders, services = [], []

    async def make(**source_options):
        sample = management_sample_source(
            tmp_path / ("source-" + str(len(loaders))), **source_options
        )
        loader = PluginLoader(
            [tmp_path / "installed"],
            channel_runtime=ChannelRuntimeSettings(
                python_executable=sys.executable,
                support_root=ROOT / "src",
                qwenpaw_version="2.2.2b4",
                selected_channels=None,
                startup_timeout=5,
                shutdown_timeout=2,
            ),
        )
        loaders.append(loader)
        record = await loader.load_plugin_from_path(sample.source)
        assert record.enabled and record.status in {
            "active",
            "registered",
        }, record.diagnostics
        service = ChannelManagementService(loader)
        services.append(service)
        return SimpleNamespace(
            loader=loader,
            service=service,
            sample=sample,
            record=record,
            owners=loader.registry.runtime_owners,
            usage=loader.registry.dependency_usage,
            baseline_declaration_count=sum(
                use.plugin_id == KEY and use.origin == "declaration"
                for use in loader.registry.dependency_usage.snapshot().uses
            ),
        )

    try:
        yield make
    finally:
        try:
            for service in reversed(services):
                await service.aclose()
            for loader in reversed(loaders):
                if loader.get_loaded_plugin(KEY) is not None:
                    report = await loader.unload_plugin(KEY)
                    assert (
                        report.quiescent and not report.needs_restart
                    ), report.errors
        finally:
            PluginRegistry._instance = previous


def parameters(http, operation="qrcode.fetch", **config):
    value = {
        "config": {
            "enabled": False,
            "host": http.host,
            "port": http.port,
            **config,
        }
    }
    if operation == "qrcode.poll":
        value["continuation"] = "fixture-continuation"
    if operation == "connection.verify":
        value["level"] = "reachability"
    return value


def active_management(rt):
    return tuple(
        lease
        for lease in rt.owners.leases(KEY)
        if lease.key.kind == "management"
    )


def assert_exact_use(rt, lease):
    matches = [
        use
        for use in rt.usage.snapshot().uses
        if use.active
        and use.instance_id == lease.instance_id
        and use.generation == lease.generation
    ]
    assert len(matches) == 1
    assert matches[0].source_revision


def assert_released(rt, lease, process, pid):
    assert lease not in rt.owners.leases(KEY)
    assert rt.owners.resource(lease) is None
    assert not any(
        use.active
        and use.instance_id == lease.instance_id
        and use.generation == lease.generation
        for use in rt.usage.snapshot().uses
    )
    assert process.last_cleanup.exited and not process.last_cleanup.residual
    assert not psutil.pid_exists(pid)
    if not rt.owners.leases(KEY):
        assert_no_management_declarations(rt)


def assert_no_management_declarations(rt):
    remaining = tuple(
        use for use in rt.usage.snapshot().uses if use.plugin_id == KEY
    )
    catalog = rt.loader.registry.get_channel_catalog_entry(KEY)
    if catalog is None:
        assert remaining == ()
        return
    description = catalog.description_record
    assert len(remaining) <= rt.baseline_declaration_count
    for use in remaining:
        assert use.origin == "declaration" and not use.active
        assert use.instance_id is None and use.generation is None
        assert use.source_revision == description.source_revision
        assert use.requirements == description.requirements


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation", ["qrcode.fetch", "qrcode.poll", "connection.verify"]
)
async def test_actual_management_child_does_http_without_driver_consumer(
    tmp_path, local_management_http, operation
):
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.channel_protocol.management import ManagementResult

    sample = management_sample_source(tmp_path)
    process = ChannelProcess()
    spec = management_spec(sample)
    try:
        await process.start_management(spec)
        state = process.health_snapshot()
        pid = state["pid"]
        assert pid != os.getpid()
        assert state["platform_state"] != "connected"
        request = management_request(spec, local_management_http, operation)
        mapping = await process.call(
            "channel.management.execute", request.to_mapping(), timeout=3
        )
        result = ManagementResult.from_mapping(mapping)
        assert (
            result.validate_for(request, credential_keys={"api_token"}) is None
        )
        assert result.to_mapping()["outcome"] == "ok"
        assert len(local_management_http.requests) == 1
        assert local_management_http.requests[0]["pid"] == pid
        assert local_management_http.requests[0]["config"]["enabled"] is False
    finally:
        cleanup = await process.stop()
    assert cleanup.exited and not cleanup.residual
    assert not psutil.pid_exists(pid)


@pytest.mark.asyncio
async def test_management_worker_claims_one_execution_even_after_completion(
    tmp_path, local_management_http
):
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.channel_protocol.errors import RpcError
    from qwenpaw.plugins.execution.process import PluginProcess

    sample = management_sample_source(tmp_path)
    process = ChannelProcess()
    spec = management_spec(sample)
    try:
        await process.start_management(spec)
        request = management_request(spec, local_management_http)
        await process.call(
            "channel.management.execute", request.to_mapping(), timeout=3
        )
        with pytest.raises(RpcError):
            await PluginProcess.call(
                process,
                "channel.management.execute",
                request.to_mapping(),
                timeout=3,
            )
        assert len(local_management_http.requests) == 1
    finally:
        cleanup = await process.stop()
    assert cleanup.exited and not cleanup.residual


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("plugin_id", "another-owner"),
        ("workspace_id", "workspace-B"),
        ("instance_id", "another-instance"),
        ("generation", 2),
        ("source_revision", "b" * 64),
        ("channel_key", "another_channel"),
    ],
)
async def test_management_worker_rejects_request_forgery_before_http(
    tmp_path, local_management_http, field, value
):
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.channel_protocol.errors import RpcError
    from qwenpaw.plugins.execution.process import PluginProcess

    sample = management_sample_source(tmp_path)
    process = ChannelProcess()
    spec = management_spec(sample)
    try:
        await process.start_management(spec)
        request = management_request(
            spec, local_management_http, **{field: value}
        )
        with pytest.raises(RpcError):
            await PluginProcess.call(
                process,
                "channel.management.execute",
                request.to_mapping(),
                timeout=3,
            )
        assert not local_management_http.requests
    finally:
        cleanup = await process.stop()
    assert cleanup.exited and not cleanup.residual


@pytest.mark.asyncio
@pytest.mark.parametrize("style", ["instance", "sync", "varargs"])
async def test_management_fixed_static_async_signature_is_enforced(
    tmp_path, style
):
    from qwenpaw.app.channels.process_supervisor import (
        ChannelProcess,
        ChannelProcessError,
    )

    sample = management_sample_source(tmp_path, manage_style=style)
    process = ChannelProcess()
    with pytest.raises(ChannelProcessError) as rejected:
        await process.start_management(management_spec(sample))
    assert rejected.value.reason_code == "ENTRYPOINT_INVALID"
    assert process.last_cleanup.exited and not process.last_cleanup.residual


@pytest.mark.asyncio
async def test_actual_run_still_constructs_and_connects_ordinary_driver(
    tmp_path,
):
    from qwenpaw.app.channels.process_supervisor import ChannelProcess

    sample = management_sample_source(tmp_path, run_driver=True)
    process = ChannelProcess()
    try:
        await process.start(inspection_spec(sample))
        await eventually(
            lambda: process.health_snapshot()["platform_state"] == "connected"
        )
        pid = process.health_snapshot()["pid"]
        assert int(sample.marker.read_text()) == pid != os.getpid()
    finally:
        cleanup = await process.stop()
    assert cleanup.exited and not cleanup.residual
    assert not psutil.pid_exists(pid)


@pytest.mark.asyncio
async def test_worker_capability_rejected_independently_of_host(
    tmp_path, local_management_http
):
    from qwenpaw.app.channels.process_supervisor import ChannelProcess
    from qwenpaw.channel_protocol.errors import RpcError
    from qwenpaw.plugins.execution.process import PluginProcess

    sample = management_sample_source(
        tmp_path,
        capabilities=["channel.generic.v1", "channel.management.verify.v1"],
    )
    process = ChannelProcess()
    spec = management_spec(sample)
    try:
        await process.start_management(spec)
        request = management_request(spec, local_management_http)
        with pytest.raises(RpcError):
            await PluginProcess.call(
                process,
                "channel.management.execute",
                request.to_mapping(),
                timeout=3,
            )
        assert not local_management_http.requests
    finally:
        cleanup = await process.stop()
    assert cleanup.exited and not cleanup.residual


@pytest.mark.asyncio
async def test_management_exposes_only_execute_and_control_and_disables_host_handlers(
    tmp_path, local_management_http
):
    from qwenpaw.app.channels.process_supervisor import (
        ChannelProcess,
        ChannelProcessError,
    )
    from qwenpaw.channel_protocol.errors import RpcError
    from qwenpaw.plugins.execution.process import PluginProcess

    sample = management_sample_source(tmp_path)
    process = ChannelProcess()
    spec = management_spec(sample)
    calls = []

    async def arbitrary_host_handler(params, request):
        calls.append(params)
        return {"accepted": True}

    process.register_method("fixture.host", arbitrary_host_handler)
    try:
        await process.start_management(spec)
        with pytest.raises(ChannelProcessError) as denied:
            process.register_method("host.state.write", arbitrary_host_handler)
        assert denied.value.reason_code == "MODE_METHODS_DISABLED"
        for method in (
            "event.batch",
            "channel.send",
            "channel.response.prepare",
            "host.state.write",
            "fixture.host",
        ):
            with pytest.raises(RpcError) as denied:
                await PluginProcess.call(process, method, {}, timeout=3)
            assert denied.value.code == -32601
        with pytest.raises(ChannelProcessError) as denied:
            await process.call("channel.send", {}, timeout=3)
        assert denied.value.reason_code == "MANAGEMENT_UNSUPPORTED"
        request = management_request(spec, local_management_http)
        await process.call(
            "channel.management.execute", request.to_mapping(), timeout=3
        )
        with pytest.raises(ChannelProcessError) as denied:
            await process.call(
                "channel.management.execute", request.to_mapping(), timeout=3
            )
        assert denied.value.reason_code == "MANAGEMENT_UNSUPPORTED"
        assert not calls
        assert len(local_management_http.requests) == 1
    finally:
        cleanup = await process.stop()
    assert cleanup.exited and not cleanup.residual


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", [{"plugin_id": None}, {"workspace_id": ""}, {"restart_limit": 1}]
)
async def test_management_launch_requires_trusted_scope_and_no_restart(
    tmp_path, change
):
    from qwenpaw.app.channels.process_supervisor import (
        ChannelProcess,
        ChannelProcessError,
    )

    sample = management_sample_source(tmp_path)
    process = ChannelProcess()
    with pytest.raises(ChannelProcessError) as denied:
        await process.start_management(
            replace(management_spec(sample), **change)
        )
    assert denied.value.reason_code == "MANAGEMENT_INVALID_REQUEST"
    assert process.health_snapshot()["pid"] is None
    assert not sample.marker.exists()


@pytest.mark.asyncio
async def test_plain_execution_runtime_refuses_management_hook(tmp_path):
    from qwenpaw.plugins.execution.process import (
        PluginProcess,
        PluginLaunchSpec,
        ProcessError,
    )

    sample = management_sample_source(tmp_path)
    process = PluginProcess()
    spec = PluginLaunchSpec(
        python_executable=sys.executable,
        support_root=ROOT / "src",
        code_root=sample.source,
        source_revision=source_revision(sample.source),
        plugin_id=KEY,
        instance_id="plain-management",
        generation=1,
        entrypoint=KEY + ".driver:Driver",
        config={},
        requirements_path=sample.source / "requirements.txt",
        startup_timeout=5,
        shutdown_timeout=2,
    )
    with pytest.raises(ProcessError) as denied:
        await process._start(spec, mode="manage")
    assert denied.value.reason_code == "ENTRYPOINT_INVALID"
    assert process.last_cleanup.exited and not process.last_cleanup.residual
    assert not psutil.pid_exists(int(sample.marker.read_text()))


@pytest.mark.asyncio
async def test_management_health_and_rpc_errors_do_not_expose_request_secrets(
    tmp_path, local_management_http
):
    from qwenpaw.app.channels.process_supervisor import ChannelProcess

    sample = management_sample_source(tmp_path)
    process = ChannelProcess()
    spec = management_spec(sample)
    local_management_http.reply_gate.clear()
    secrets = (
        "health-request-api-token-secret",
        "health-request-continuation-secret",
    )
    operation = None
    try:
        await process.start_management(spec)
        request = management_request(
            spec, local_management_http, "qrcode.poll"
        )
        value = request.to_mapping()
        value["parameters"]["config"]["api_token"] = secrets[0]
        value["parameters"]["continuation"] = secrets[1]
        operation = asyncio.create_task(
            process.call("channel.management.execute", value, timeout=3)
        )
        await eventually(lambda: len(local_management_http.requests) == 1)
        health = json.dumps(process.health_snapshot())
        assert all(secret not in health for secret in secrets)
        operation.cancel()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await operation
        assert all(secret not in str(cancelled.value) for secret in secrets)
    finally:
        if operation is not None and not operation.done():
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        cleanup = await process.stop()
    assert cleanup.exited and not cleanup.residual
    assert all(
        secret not in json.dumps(process.health_snapshot())
        for secret in secrets
    )
