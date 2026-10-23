"""Official archive, platform transport and owned-stop migration contracts."""

import asyncio
import csv
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import ssl
import subprocess
import time
import zipfile

import psutil
import pytest

from extension_process_suite import runtime, eventually, identity
from extension_sample import ROOT
from g2_mqtt_broker import Broker
from g2_fault_runtime import fault_runtime
from g2_official_process_suite import (
    broker,
    mattermost,
    forbid_host_sdk_import,
    official_source,
    mqtt,
    mm,
    request_text,
)


def certificate_files(tmp_path):
    certificate, key = tmp_path / "ca.pem", tmp_path / "client.key"
    result = subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
            "-keyout",
            str(key),
            "-out",
            str(certificate),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, key)
    context.load_verify_locations(certificate)
    context.verify_mode = ssl.CERT_REQUIRED
    return certificate, key, context


@pytest.fixture
def tls_certificate(tmp_path):
    return certificate_files(tmp_path)


def copied_sdk(tmp_path, name, package, module, appended, *, site=None):
    """Only the SDK boundary changes; copy its real distribution and metadata."""
    distribution = importlib.metadata.distribution(name)
    site = site or tmp_path / "sdk-site"
    site.mkdir(exist_ok=True)
    source = Path(distribution.locate_file(package))
    shutil.copytree(
        source,
        site / package,
        ignore=shutil.ignore_patterns("__pycache__"),
        dirs_exist_ok=True,
    )
    metadata = next(
        file for file in distribution.files if file.name == "METADATA"
    )
    info = Path(distribution.locate_file(metadata)).parent
    shutil.copytree(info, site / info.name, dirs_exist_ok=True)
    path = site / module
    with path.open("a") as stream:
        stream.write(appended)
    # Keep the copied distribution's RECORD consistent with the SDK fixture.
    import base64

    record = site / info.name / "RECORD"
    with record.open(newline="") as stream:
        rows = list(csv.reader(stream))
    data = path.read_bytes()
    digest = "sha256=" + base64.urlsafe_b64encode(
        hashlib.sha256(data).digest()
    ).decode().rstrip("=")
    for row in rows:
        if row[0] == module:
            row[1:] = [digest, str(len(data))]
    with record.open("w", newline="") as stream:
        csv.writer(stream).writerows(rows)
    return site


def residual_child_code(tmp_path, enabled):
    return f"""
def _g2_retain_child():
    if {enabled!r}:
        from pathlib import Path
        import subprocess, sys
        marker = Path({str(tmp_path / 'sdk-retained-child-pid')!r})
        if not marker.exists():
            child = subprocess.Popen([sys.executable, '-I', '-c',
                'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(3600)'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            marker.write_text(str(child.pid))
"""


def copied_paho_with_close_fault(
    tmp_path, *, late_callback=False, residual=False, site=None
):
    fault = tmp_path / "sdk-loop-stop-failure"
    entered = tmp_path / "sdk-loop-stop-entered"
    site = copied_sdk(
        tmp_path,
        "paho-mqtt",
        "paho",
        "paho/mqtt/client.py",
        residual_child_code(tmp_path, residual)
        + f"""\n_g2_loop_stop = Client.loop_stop
def _g2_faulting_loop_stop(self, *args, **kwargs):
    from pathlib import Path
    Path({str(entered)!r}).write_text(str(id(self)))
    if Path({str(fault)!r}).exists():
        _g2_retain_child()
        raise OSError("controlled external SDK loop_stop failure")
    result = _g2_loop_stop(self, *args, **kwargs)
    if {late_callback!r} and self.on_message:
        message = MQTTMessage(mid=73)
        message._topic = b"in/late-device"
        message.payload = b"late old callback"
        self.on_message(self, self._userdata, message)
    return result
Client.loop_stop = _g2_faulting_loop_stop
""",
        site=site,
    )
    return site, fault, entered


def copied_httpx_with_close_fault(tmp_path, *, residual=False, site=None):
    fault, entered = (
        tmp_path / "sdk-http-close-failure",
        tmp_path / "sdk-http-close-entered",
    )
    site = copied_sdk(
        tmp_path,
        "httpx",
        "httpx",
        "httpx/_client.py",
        residual_child_code(tmp_path, residual)
        + f"""\n_g2_aclose = AsyncClient.aclose
async def _g2_faulting_aclose(self):
    from pathlib import Path
    Path({str(entered)!r}).write_text(str(id(self)))
    if Path({str(fault)!r}).exists():
        _g2_retain_child()
        raise OSError("controlled external HTTP close failure")
    return await _g2_aclose(self)
AsyncClient.aclose = _g2_faulting_aclose
""",
        site=site,
    )
    return site, fault, entered


def copied_websockets_with_close_fault(tmp_path, *, residual=False, site=None):
    fault, entered = (
        tmp_path / "sdk-ws-close-failure",
        tmp_path / "sdk-ws-close-entered",
    )
    site = copied_sdk(
        tmp_path,
        "websockets",
        "websockets",
        "websockets/asyncio/client.py",
        residual_child_code(tmp_path, residual) + f"""
_g2_ws_close = ClientConnection.close
async def _g2_faulting_ws_close(self, *args, **kwargs):
    from pathlib import Path
    Path({str(entered)!r}).write_text(str(id(self)))
    if Path({str(fault)!r}).exists():
        _g2_retain_child()
        raise OSError("controlled external WebSocket close failure")
    return await _g2_ws_close(self, *args, **kwargs)
ClientConnection.close = _g2_faulting_ws_close
""",
        site=site,
    )
    return site, fault, entered


def official_zip_source(directory, key, **_ignored):
    """Build and authenticate the actual private official ZIP before Loader."""
    from qwenpaw.__version__ import __version__

    spec = importlib.util.spec_from_file_location(
        "g2_bundle_builder", ROOT / "scripts/pack/generate_plugin_metadata.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bundle = Path(directory).parent / "official-bundle"
    module.build_official_channel_bundle(ROOT, bundle, host_version=__version__)
    from qwenpaw.plugins import official_channels

    original = official_channels._resource_root
    official_channels._resource_root = lambda: bundle
    try:
        with official_channels.bundled_channel_source(key) as extracted:
            destination = Path(directory) / key
            shutil.copytree(extracted, destination)
    finally:
        official_channels._resource_root = original
    return destination


def record_worker_metrics(rt, started):
    """Measure real fixture parent and every owned channel worker together."""
    from qwenpaw.plugins.registry import PluginRegistry

    owners = PluginRegistry().runtime_owners
    workers = []
    for lease in owners.leases():
        if lease.key.kind != "channel":
            continue
        channel = owners.resource(lease)
        pid = channel.channel_process.health_snapshot()["pid"]
        assert pid and pid != os.getpid()
        process = psutil.Process(pid)
        workers.append(
            {
                "channel_key": lease.key.name,
                "instance_id": lease.instance_id,
                "generation": lease.generation,
                "pid": pid,
                "rss_bytes": process.memory_info().rss,
                "threads": process.num_threads(),
            }
        )
    parent = psutil.Process()
    parent_rss = parent.memory_info().rss
    row = {
        "scope": "enabled real localhost platform fixture; includes test service in parent, not whole WebApp/Docker",
        "python_executable": rt.channel._launch_spec.python_executable,
        "workspace": str(rt.ws.workspace_dir),
        "channel_key": rt.key,
        "install_and_connect_ms": (time.perf_counter() - started) * 1000,
        "parent_pid": parent.pid,
        "parent_rss_bytes": parent_rss,
        "parent_threads": parent.num_threads(),
        "workers": workers,
        "parent_plus_workers_rss_bytes": parent_rss
        + sum(worker["rss_bytes"] for worker in workers),
        "worker_count": len(workers),
    }
    return row


@pytest.mark.asyncio
async def test_mqtt_tls_client_certificate_auth_and_clean_session_survive(
    runtime, tls_certificate
):
    certificate, key, context = tls_certificate
    broker = Broker(tls_context=context)
    try:
        rt = await mqtt(
            runtime,
            broker,
            tls_enabled=True,
            tls_ca_certs=str(certificate),
            tls_certfile=str(certificate),
            tls_keyfile=str(key),
            username="robot",
            password="secret",
            clean_session=False,
        )
        await rt.channel.send_content_parts(
            "device", [{"type": "text", "text": "TLS"}], {}
        )
        assert broker.peer_certificates and all(broker.peer_certificates)
        assert broker.connect_packets[0]["username"] == "robot"
        assert broker.connect_packets[0]["password"] == "secret"
        assert broker.connect_packets[0]["clean_session"] is False
        assert broker.publishes == [("out/device", "TLS", 2)]
    finally:
        broker.close()


@pytest.mark.asyncio
async def test_mqtt_websocket_transport_uses_same_reply_contract(runtime):
    broker = Broker(websocket=True)
    try:
        rt = await mqtt(runtime, broker, transport="websockets")
        broker.emit("in/device", "websocket message")
        await eventually(
            lambda: len(rt.ws.requests) == 1 and len(broker.publishes) == 1
        )
        assert rt.ws.requests[0].session_id == "mqtt:device"
        assert broker.publishes == [("out/device", "host answer", 2)]
    finally:
        broker.close()


@pytest.mark.asyncio
async def test_mqtt_tls_rejection_does_not_break_healthy_mattermost(
    runtime, tls_certificate, mattermost, tmp_path
):
    # Prove a real certificate failure, rather than accepting missing-plugin errors.
    assert (ROOT / "plugins/channel/mqtt").is_dir()
    healthy = await mm(runtime, mattermost)
    certificate, key, context = tls_certificate
    untrusted = tmp_path / "untrusted"
    untrusted.mkdir()
    wrong_ca, _key, _context = certificate_files(untrusted)
    broker = Broker(tls_context=context)
    try:
        with pytest.raises(RuntimeError):
            await mqtt(
                runtime,
                broker,
                tls_enabled=True,
                tls_ca_certs=str(wrong_ca),
                tls_certfile=str(certificate),
                tls_keyfile=str(key),
            )
        assert broker.handshake_errors and broker.publishes == []
        mattermost.push_dm_post(
            text="healthy after TLS rejection",
            user_id="human",
            post_id="healthy",
        )
        await eventually(lambda: len(mattermost.posts) == 1)
        assert "healthy after TLS rejection" in request_text(
            healthy.ws.requests[0]
        )
    finally:
        broker.close()


@pytest.mark.asyncio
async def test_mattermost_ready_does_not_claim_connected_before_auth_confirmation(
    runtime, mattermost
):
    from qwenpaw.plugins.registry import PluginRegistry

    mattermost.auth_reply = False
    setup = asyncio.create_task(mm(runtime, mattermost))
    try:
        await eventually(
            lambda: any(
                row.get("action") == "authentication_challenge"
                for row in mattermost.ws_messages
            )
            or setup.done()
        )
        if setup.done():
            await setup  # Preserve a concrete artifact/activation failure.
        owners = PluginRegistry().runtime_owners
        leases = [
            lease
            for lease in owners.leases("mattermost")
            if lease.key.kind == "channel"
        ]
        assert len(leases) == 1
        channel = owners.resource(leases[0])
        await eventually(
            lambda: channel.channel_process.health_snapshot()["state"]
            == "ready"
        )
        assert (
            channel.channel_process.health_snapshot()["platform_state"]
            != "connected"
        )
        assert (
            not setup.done()
        ), "Proxy start reported connected before the auth result"
        mattermost.accept_authentication()
        rt = await setup
        assert rt.process.health_snapshot()["platform_state"] == "connected"
    finally:
        setup.cancel()
        await asyncio.gather(setup, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,sdk",
    [("mqtt", "paho"), ("mattermost", "websockets"), ("mattermost", "httpx")],
)
@pytest.mark.parametrize("residual", [False, True])
async def test_sdk_close_failure_distinguishes_forced_exit_from_real_residual(
    runtime,
    broker,
    mattermost,
    tmp_path,
    monkeypatch,
    key,
    sdk,
    residual,
    fault_runtime,
):
    from qwenpaw.plugins.execution.process_tree import ProcessTree
    from qwenpaw.plugins.registry import PluginRegistry
    from qwenpaw.channel_protocol.errors import RpcError

    factory = {
        "paho": copied_paho_with_close_fault,
        "websockets": copied_websockets_with_close_fault,
        "httpx": copied_httpx_with_close_fault,
    }[sdk]
    site, fault, entered = factory(
        tmp_path, residual=residual, site=fault_runtime.site
    )
    settings = dict(
        dependency_paths=(site,),
        python_executable=fault_runtime.python,
        runtime_identity=fault_runtime.identity,
    )
    rt = await (
        mqtt(runtime, broker, **settings)
        if key == "mqtt"
        else mm(runtime, mattermost, **settings)
    )
    pid, before = rt.process.health_snapshot()["pid"], identity(rt)
    child_marker = tmp_path / "sdk-retained-child-pid"
    child_pid = None
    fault.touch()
    try:
        with monkeypatch.context() as boundary:
            if residual:
                original_signal = ProcessTree.signal

                def blocked_os_signal(tree, *, force):
                    if tree.pid != pid:
                        original_signal(tree, force=force)

                boundary.setattr(ProcessTree, "signal", blocked_os_signal)
            # Existing public lifecycle RPC must report the SDK close failure.
            # A second attempt cannot silently succeed after losing references.
            with pytest.raises(RpcError):
                await rt.process.call("shared.stop", before)
            assert entered.exists() and psutil.pid_exists(pid)
            resource_id = entered.read_text()
            with pytest.raises(RpcError):
                await rt.process.call("shared.stop", before)
            assert entered.read_text() == resource_id
            receipt = await rt.manager.stop_one(key)
            assert (
                entered.exists()
            ), "The actual worker never exercised its SDK close"
            if residual:
                assert receipt.forced
                assert child_marker.exists()
                child_pid = int(child_marker.read_text())
                assert psutil.pid_exists(child_pid)
                assert (
                    not receipt.stopped
                    and not receipt.exited
                    and receipt.residual
                )
                assert await rt.manager.get_channel(key) is rt.channel
                assert identity(rt) == before
                assert any(
                    lease.generation == before["generation"]
                    for lease in PluginRegistry().runtime_owners.leases(key)
                )
                with pytest.raises(
                    RuntimeError, match="not stopped|STOPPING|OWNED"
                ):
                    await rt.manager.start_one(key, rt.ws.config)
            else:
                assert (
                    receipt.stopped and receipt.exited and not receipt.residual
                )
                assert not psutil.pid_exists(pid)
                assert await rt.manager.get_channel(key) is None
                assert not PluginRegistry().runtime_owners.leases(key)
        fault.unlink()
        if residual:
            retry = await rt.manager.stop_one(key)
            assert retry.stopped and retry.exited and not retry.residual
            assert not psutil.pid_exists(child_pid)
        fresh = await rt.manager.start_one(key, rt.ws.config)
        fresh_pid = fresh.channel.channel_process.health_snapshot()["pid"]
        assert fresh_pid != pid and psutil.pid_exists(fresh_pid)
        assert fresh.channel._launch_spec.generation > before["generation"]
    finally:
        fault.unlink(missing_ok=True)
        if child_pid is None and child_marker.exists():
            child_pid = int(child_marker.read_text())
        if child_pid and psutil.pid_exists(child_pid):
            os.kill(child_pid, signal.SIGKILL)


@pytest.mark.asyncio
async def test_mqtt_callback_after_loop_stop_never_enters_host(
    runtime, broker, tmp_path, fault_runtime
):
    site, _fault, entered = copied_paho_with_close_fault(
        tmp_path, late_callback=True, site=fault_runtime.site
    )
    rt = await mqtt(
        runtime,
        broker,
        dependency_paths=(site,),
        python_executable=fault_runtime.python,
        runtime_identity=fault_runtime.identity,
    )
    broker.emit("in/accepted", "accepted before stop")
    await eventually(
        lambda: len(rt.ws.requests) == 1 and len(broker.publishes) == 1
    )
    pid = rt.process.health_snapshot()["pid"]
    assert (await rt.manager.stop_one("mqtt")).stopped
    assert entered.exists() and not psutil.pid_exists(pid)
    assert len(rt.ws.requests) == 1
    assert broker.publishes == [("out/accepted", "host answer", 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["mqtt", "mattermost"])
async def test_official_zip_installs_into_same_real_worker_chain(
    runtime, broker, mattermost, key
):
    settings = (
        {
            "host": "127.0.0.1",
            "port": broker.port,
            "transport": "tcp",
            "subscribe_topic": "in/+",
            "publish_topic": "out/{client_id}",
        }
        if key == "mqtt"
        else {"url": mattermost.url, "bot_token": "local-test-token"}
    )
    rt = await runtime(key, source_factory=official_zip_source, **settings)
    assert rt.channel._launch_spec.code_root == rt.record.source_path
    assert rt.source.is_relative_to(rt.loader.plugin_dirs[0])
    assert rt.source != ROOT / "plugins/channel" / key
    if key == "mqtt":
        await eventually(lambda: bool(broker.subscriptions))
        broker.emit("in/zip-device", "archive ingress")
        await eventually(
            lambda: len(rt.ws.requests) == 1 and len(broker.publishes) == 1
        )
        assert broker.publishes == [("out/zip-device", "host answer", 2)]
    else:
        await eventually(lambda: mattermost.has_connection)
        mattermost.push_dm_post(
            text="archive ingress",
            channel_id="zip-dm",
            user_id="human",
            post_id="zip-post",
        )
        await eventually(
            lambda: len(rt.ws.requests) == 1 and len(mattermost.posts) == 1
        )
        assert mattermost.posts[0]["channel_id"] == "zip-dm"


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["mqtt", "mattermost"])
async def test_disable_enable_uninstall_keeps_channel_config_and_business_files(
    runtime, broker, mattermost, key
):
    from qwenpaw.config.utils import load_config, save_config

    rt = await (
        mqtt(runtime, broker) if key == "mqtt" else mm(runtime, mattermost)
    )
    config = load_config()
    setattr(config.channels, key, getattr(rt.ws.config.channels, key))
    save_config(config)
    before_config = load_config().channels.model_dump()[key]
    assets = [
        rt.ws.workspace_dir / name
        for name in (
            "credentials.json",
            "sessions.json",
            "media.bin",
            "business.db",
        )
    ]
    for asset in assets:
        asset.write_bytes(b"keep:" + asset.name.encode())
    pid = rt.process.health_snapshot()["pid"]
    await rt.loader.lifecycle.set_enabled(key, False)
    assert not psutil.pid_exists(pid)
    assert await rt.manager.get_channel(key) is None
    assert rt.source.is_dir()
    await rt.loader.lifecycle.set_enabled(key, True)
    current = await rt.manager.get_channel(key)
    assert current is not None and current is not rt.channel
    fresh_pid = current.channel_process.health_snapshot()["pid"]
    assert fresh_pid != pid and psutil.pid_exists(fresh_pid)
    report = await rt.loader.unload_plugin(key, delete_files=True)
    assert report.quiescent and not rt.source.exists()
    assert not psutil.pid_exists(fresh_pid)
    assert key not in load_config().plugins
    assert load_config().channels.model_dump()[key] == before_config
    assert all(
        asset.read_bytes() == b"keep:" + asset.name.encode()
        for asset in assets
    )
    assert key in load_config().channel_plugin_state.uninstalled


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["mqtt", "mattermost"])
async def test_bad_official_update_preserves_live_worker_and_installed_payload(
    runtime, broker, mattermost, tmp_path, key
):
    rt = await (
        mqtt(runtime, broker) if key == "mqtt" else mm(runtime, mattermost)
    )
    before_pid, before_identity = rt.process.health_snapshot()[
        "pid"
    ], identity(rt)
    original = (rt.source / f"qwenpaw_channel_{key}/driver.py").read_bytes()
    candidate = official_source(tmp_path / "bad-update", key)
    manifest_path = candidate / "plugin.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["version"] = "99.0.0"
    manifest_path.write_text(json.dumps(manifest))
    with (candidate / f"qwenpaw_channel_{key}/driver.py").open("a") as stream:
        stream.write("\nraise RuntimeError('controlled invalid candidate')\n")
    report = await rt.loader.lifecycle.reload(key, new_source=candidate)
    assert not report.ok and report.errors
    assert await rt.manager.get_channel(key) is rt.channel
    assert rt.process.health_snapshot()["pid"] == before_pid
    assert identity(rt) == before_identity
    assert (
        rt.source / f"qwenpaw_channel_{key}/driver.py"
    ).read_bytes() == original


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["mqtt", "mattermost"])
@pytest.mark.parametrize("activation_fails", [False, True])
async def test_official_zip_update_and_activation_rollback_recover_business(
    runtime, broker, mattermost, tmp_path, key, activation_fails
):
    from qwenpaw.plugins.archive import safe_extract_zip
    from qwenpaw.plugins.registry import PluginRegistry

    rt = await (
        mqtt(runtime, broker) if key == "mqtt" else mm(runtime, mattermost)
    )
    old_pid = rt.process.health_snapshot()["pid"]
    old_version = rt.record.manifest.version
    old_config = rt.ws.config.channels.model_dump()[key]
    asset = rt.ws.workspace_dir / "business-auth.db"
    asset.write_bytes(b"preserved credential and business state")
    candidate = official_source(tmp_path / "update-input", key)
    path = candidate / "plugin.json"
    manifest = json.loads(path.read_text())
    manifest["version"] = "99.0.0"
    path.write_text(json.dumps(manifest))
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as packed:
        for file in candidate.rglob("*"):
            if file.is_file():
                packed.write(
                    file, key + "/" + file.relative_to(candidate).as_posix()
                )
    extracted = tmp_path / "candidate-extracted"
    with zipfile.ZipFile(archive) as packed:
        safe_extract_zip(packed, extracted)
    observations = []

    def observe_activation():
        version = json.loads((rt.source / "plugin.json").read_text())[
            "version"
        ]
        live = []
        owners = PluginRegistry().runtime_owners
        for lease in owners.leases(key):
            if lease.key.kind != "channel":
                continue
            channel = owners.resource(lease)
            process = channel.channel_process if channel is not None else None
            if (
                process is not None
                and (pid := process.health_snapshot().get("pid"))
                and psutil.pid_exists(pid)
            ):
                live.append(pid)
        observations.append((version, psutil.pid_exists(old_pid), live))
        return version == "99.0.0" and activation_fails

    if key == "mqtt":
        broker.connect_code_provider = lambda: 4 if observe_activation() else 0
    else:
        mattermost.response_callbacks["/api/v4/users/me"] = lambda: (
            (503, {"message": "candidate authentication refused"})
            if observe_activation()
            else (
                200,
                {
                    "id": "integmockbotid00000000000",
                    "username": "integ-mock-bot",
                },
            )
        )
    report = await rt.loader.lifecycle.reload(key, new_source=extracted / key)
    assert report.ok is not activation_fails, report.errors
    if activation_fails:
        assert report.errors and not report.needs_restart
    candidate_rows = [row for row in observations if row[0] == "99.0.0"]
    assert (
        candidate_rows
    ), "Candidate never reached the actual platform startup"
    assert all(
        not old_alive and len(pids) <= 1 for _, old_alive, pids in observations
    )
    current = await rt.manager.get_channel(key)
    assert current is not None and current is not rt.channel
    current_pid = current.channel_process.health_snapshot()["pid"]
    assert current_pid != old_pid and not psutil.pid_exists(old_pid)
    assert psutil.pid_exists(current_pid)
    assert json.loads((rt.source / "plugin.json").read_text())["version"] == (
        old_version if activation_fails else "99.0.0"
    )
    if activation_fails:
        assert all(
            not psutil.pid_exists(pid)
            for _, _, pids in candidate_rows
            for pid in pids
        )
    assert rt.ws.config.channels.model_dump()[key] == old_config
    assert asset.read_bytes() == b"preserved credential and business state"
    if key == "mqtt":
        broker.emit("in/after-update", "restored business")
        await eventually(lambda: len(broker.publishes) == 1)
        assert broker.publishes == [("out/after-update", "host answer", 2)]
        assert rt.ws.requests[0].session_id == "mqtt:after-update"
    else:
        mattermost.push_dm_post(
            text="restored business",
            channel_id="dm-update",
            post_id="after-update",
        )
        await eventually(lambda: len(mattermost.posts) == 1)
        assert mattermost.posts[0]["channel_id"] == "dm-update"
        assert rt.ws.requests[0].session_id == "mattermost_dm:dm-update"
    assert "restored business" in request_text(rt.ws.requests[0])


@pytest.mark.asyncio
async def test_mattermost_same_native_post_is_isolated_across_workspaces(
    runtime, mattermost
):
    from mock_mattermost import MockMattermost

    other = MockMattermost()
    other.start()
    try:
        first = await mm(runtime, mattermost)
        second = await mm(
            runtime,
            other,
            existing_loader=first.loader,
            workspace_name="mattermost-B",
        )
        pids = [rt.process.health_snapshot()["pid"] for rt in (first, second)]
        assert len(set(pids)) == 2
        assert (
            identity(first)["instance_id"] != identity(second)["instance_id"]
        )
        for server in (mattermost, other):
            server.push_dm_post(
                text="same native post",
                channel_id="same-dm",
                user_id="human",
                post_id="same-post",
            )
        await eventually(
            lambda: len(mattermost.posts) == len(other.posts) == 1
        )
        assert len(first.ws.requests) == len(second.ws.requests) == 1
        assert (await first.manager.stop_one("mattermost")).stopped
        assert not psutil.pid_exists(pids[0]) and psutil.pid_exists(pids[1])
        other.push_dm_post(
            text="still live",
            channel_id="same-dm",
            user_id="human",
            post_id="second-post",
        )
        await eventually(lambda: len(other.posts) == 2)
        assert len(first.ws.requests) == 1 and len(second.ws.requests) == 2
    finally:
        other.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["mqtt", "mattermost"])
async def test_enabled_local_fixture_records_parent_and_worker_total(
    runtime, broker, mattermost, key
):
    started = time.perf_counter()
    rt = await (
        mqtt(runtime, broker) if key == "mqtt" else mm(runtime, mattermost)
    )
    row = record_worker_metrics(rt, started)
    assert row["worker_count"] == 1
    assert row["workers"][0]["rss_bytes"] > 0
    assert row["parent_plus_workers_rss_bytes"] > row["parent_rss_bytes"]
