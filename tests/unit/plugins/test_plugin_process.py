# -*- coding: utf-8 -*-
"""Normal generic plugin supervision through actual OS workers and IPC."""

import asyncio
import base64
import logging
from dataclasses import replace
from pathlib import Path
import os
import sys
import threading

import pytest
import pytest_asyncio

import csv
from contextlib import contextmanager
import py_compile
import shutil
import stat
import subprocess
from types import SimpleNamespace
import zipfile

from packaging.markers import default_environment
from qwenpaw.plugins import dependency_maintenance as maintenance
from qwenpaw.plugins.dependency_context import DependencyEnvironmentContext
from qwenpaw.plugins.dependency_gate import SharedDependencyError
from qwenpaw.plugins.dependency_transaction import (
    _owned,
    publish,
    rollback,
    verify_payload,
)
from qwenpaw.plugins.dependency_upgrade import DependencyUpgradeManager
from qwenpaw.plugins.execution.dependencies import (
    DependencySnapshot,
    _installed_metadata,
)
from tests.channel_support.host import (
    Host,
    _local_dependency_wheel,
    local_certifi_wheel,
    local_wheel,
)

from qwenpaw.plugins.execution import CallUnknown, PluginProcess
from tests.channel_support.process import (
    ROOT,
    alive,
    dependency_site,
    digest,
    eventually,
    launch,
    runtime_layout,
)


@pytest_asyncio.fixture
async def process():
    worker = PluginProcess()
    yield worker
    result = await worker.stop(timeout=0.5)
    assert result.exited and not result.residual


@pytest.fixture
def worker_logs(caplog, monkeypatch):
    logger = logging.getLogger("qwenpaw.plugins.worker")
    monkeypatch.setattr(logger, "propagate", False)
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.WARNING, logger=logger.name):
            yield caplog
    finally:
        logger.removeHandler(caplog.handler)


@pytest.mark.asyncio
async def test_lifecycle_bidirectional_ipc_logs_and_repeated_stop(
    tmp_path,
    process,
    worker_logs,
):
    spec, _ = launch(tmp_path)
    notices = []
    process.register_method(
        "sample.host",
        lambda params, _request: {"received": params},
    )
    process.register_notification(
        "sample.notice",
        lambda params, _request: notices.append(params),
    )
    health = await process.start(spec)
    assert health["state"] == "ready"
    probe = await process.call("sample.probe", {})
    assert (
        probe["pid"] == health["pid"] != os.getpid() and probe["isolated"] == 1
    )
    assert probe["identity"] == {
        "plugin_id": spec.plugin_id,
        "instance_id": spec.instance_id,
        "generation": 1,
    }
    assert await process.call("sample.echo", {"text": "hello"}) == {
        "text": "hello",
    }
    assert await process.call("sample.reverse", {"notice": 7}) == {
        "received": probe["identity"],
    }
    await eventually(lambda: notices == [{"notice": 7}])
    await eventually(lambda: process.health_snapshot()["log_bytes"] > 0)
    stopped = await process.stop()
    assert stopped.exited and not stopped.forced and stopped.returncode == 0
    assert not alive(probe["pid"])
    assert (await process.stop()).exited
    for marker in ("sample SDK connected", "sample SDK diagnostic"):
        await eventually(lambda: marker in worker_logs.text)
        record = next(r for r in worker_logs.records if marker in r.message)
        assert record.name == "qwenpaw.plugins.worker"
        assert record.levelno == logging.WARNING
        for value in (
            spec.plugin_id,
            spec.instance_id,
            "generation=1",
            "mode=run",
            "stderr",
        ):
            assert value in record.getMessage()


@pytest.mark.asyncio
async def test_log_flood_is_bounded_redacted_and_keeps_ipc_responsive(
    tmp_path,
    process,
    worker_logs,
    monkeypatch,
):
    from qwenpaw.plugins.execution import worker_logs as log_bridge

    # Keep one rate window even when a CI machine reads the pipe slowly.
    monkeypatch.setattr(log_bridge, "monotonic", lambda: 1.0)
    spec, _ = launch(tmp_path)
    health = await process.start(spec)
    await eventually(lambda: "sample SDK diagnostic" in worker_logs.text)
    worker_logs.clear()
    baseline = process.health_snapshot()["log_bytes"]
    cleaned = []
    clean = log_bridge._clean

    def observe_clean(text):
        cleaned.append(text)
        return clean(text)

    monkeypatch.setattr(log_bridge, "_clean", observe_clean)
    complex_line = "a-b." * 1024
    diagnostic = (
        "credential-check \x1b[31mAuthorization: Bearer bearer-secret\x1b[0m\r\n"
        "https://api.telegram.org/bot123456:telegram-secret/sendMessage\n"
        "https://example.test/?token=query-secret&ok=yes\n"
        "Authorization: token ghp_secretvalue\n"
        "Cookie: session=first_secret; auth=second_secret\n"
    )
    diagnostic += complex_line + "\n"
    diagnostic += "a-b." * 900 + ' api_token="complex-secret"\n'
    text = diagnostic + "long-line " + "x" * (128 * 1024) + "\n"
    text += ("flood-line " + "y" * 120 + "\n") * 2048
    progress = []

    async def heartbeat():
        while True:
            progress.append(process.health_snapshot()["log_bytes"])
            await asyncio.sleep(0)

    beating = asyncio.create_task(heartbeat())
    try:
        size = await asyncio.wait_for(
            process.call("sample.logs", {"text": text}),
            3,
        )
        await eventually(
            lambda: process.health_snapshot()["log_bytes"] == baseline + size,
        )
    finally:
        beating.cancel()
        await asyncio.gather(beating, return_exceptions=True)
    assert size == len(text.encode())
    assert any(baseline < count < baseline + size for count in progress)
    assert complex_line in cleaned
    # Exhausted windows must reject before decoding/redacting more records.
    cleaned_before = len(cleaned)
    rejected = (complex_line + "\n") * 8
    size += await asyncio.wait_for(
        process.call("sample.logs", {"text": rejected}),
        3,
    )
    await eventually(
        lambda: process.health_snapshot()["log_bytes"] == baseline + size,
    )
    assert len(cleaned) == cleaned_before
    assert cleaned_before <= 31
    assert await asyncio.wait_for(
        process.call("sample.echo", {"ok": 1}),
        1,
    ) == {
        "ok": 1,
    }
    await eventually(
        lambda: process.health_snapshot()["log_bytes"] == baseline + size,
    )
    stopped = await asyncio.wait_for(process.stop(), 3)
    assert stopped.exited and not stopped.forced and stopped.returncode == 0
    assert not alive(health["pid"])
    await eventually(lambda: "omitted" in worker_logs.text.lower())
    messages = [r.getMessage() for r in worker_logs.records]
    output = "\n".join(messages)
    assert "credential-check" in output and "long-line" in output
    assert "api.telegram.org" in output and "example.test" in output
    assert "a-b." * 32 in output and "api_token=" in output
    assert "truncated" in output.lower()
    assert len(messages) <= 32
    assert sum(len(message.encode()) for message in messages) <= 64 * 1024
    assert max(len(message.encode()) for message in messages) <= 4096
    for secret in (
        "bearer-secret",
        "123456:telegram-secret",
        "query-secret",
        "ghp_secretvalue",
        "first_secret",
        "second_secret",
        "complex-secret",
    ):
        assert secret not in output
    assert "\x1b" not in output and "\r" not in output


@pytest.mark.asyncio
async def test_crash_restarts_generation_and_retains_host_handler(
    tmp_path,
    process,
    worker_logs,
):
    spec, _ = launch(tmp_path, restart_limit=1, restart_backoff=0.02)
    seen = []
    process.register_method(
        "sample.host",
        lambda params, _request: seen.append(params) or params,
    )
    process.register_notification(
        "sample.notice",
        lambda _params, _request: None,
    )
    first = await process.start(spec)
    with pytest.raises(CallUnknown):
        await process.call("sample.crash", {})
    await eventually(
        lambda: process.health_snapshot()["state"] == "ready"
        and process.health_snapshot()["generation"] == 2,
    )
    fresh = await process.call("sample.probe", {})
    assert fresh["pid"] != first["pid"] and not alive(first["pid"])
    assert (await process.call("sample.reverse", {}))["generation"] == 2
    assert seen == [fresh["identity"]]
    for generation in (1, 2):
        await eventually(
            lambda: any(
                "sample SDK diagnostic" in r.getMessage()
                and f"generation={generation}" in r.getMessage()
                and spec.instance_id in r.getMessage()
                for r in worker_logs.records
            ),
        )


@pytest.mark.asyncio
async def test_blocked_sdk_start_keeps_parent_loop_responsive(
    tmp_path,
    process,
):
    spec, marker = launch(tmp_path, mode="blocked")
    ticks = []

    async def heartbeat():
        while not marker.exists():
            ticks.append(1)
            await asyncio.sleep(0.01)

    beating = asyncio.create_task(heartbeat())
    health = await process.start(spec)
    await eventually(marker.exists)
    await beating
    # A parent request/task can run while the child SDK blocks its own loop.
    assert (
        ticks
        and await asyncio.wait_for(asyncio.sleep(0, result="responsive"), 0.1)
        == "responsive"
    )
    assert int(marker.read_text()) == health["pid"]
    stopped = await asyncio.wait_for(process.stop(timeout=0.3), 3)
    assert stopped.exited and stopped.forced and not alive(health["pid"])


@pytest.mark.asyncio
async def test_forced_stop_reaps_uncooperative_process_tree(tmp_path, process):
    spec, marker = launch(tmp_path, mode="tree", restart_limit=2)
    health = await process.start(spec)
    await eventually(marker.exists)
    descendant = int(marker.read_text())
    assert alive(descendant) and alive(health["pid"])
    result = await process.stop(timeout=0.3)
    assert result.exited and result.forced and result.residual == ()
    assert not alive(descendant) and not alive(health["pid"])
    assert process.health_snapshot()["state"] == "stopped"


@pytest.mark.asyncio
async def test_cancel_inflight_call_cleans_up_and_next_request_succeeds(
    tmp_path,
    process,
):
    spec, marker = launch(tmp_path)
    await process.start(spec)
    pending = asyncio.create_task(process.call("sample.slow", {}))
    await eventually(Path(str(marker) + ".pending").exists)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert await process.call("sample.echo", {"after": "cancel"}) == {
        "after": "cancel",
    }
    unknown = process.health_snapshot()["unknown_outcomes"]
    assert len(unknown) == 1 and unknown[0]["method"] == "sample.slow"
    assert unknown[0]["reason_code"] == "PLATFORM_RESULT_UNKNOWN"


@pytest.mark.asyncio
async def test_large_text_and_attachment_payload_roundtrip_is_exact(
    tmp_path,
    process,
):
    spec, _ = launch(tmp_path)
    await process.start(spec)
    binary = bytes(range(256)) * 3300
    value = {
        "text": "  原文\n⟦ unchanged ⟧  ",
        "attachments": [
            "data:application/octet-stream;base64,"
            + base64.b64encode(binary).decode(),
        ],
    }
    assert len(value["attachments"][0]) > 1024 * 1024
    received = await process.call("sample.echo", value)
    assert received == value
    assert (
        base64.b64decode(received["attachments"][0].split(",", 1)[1]) == binary
    )


@pytest.mark.asyncio
async def test_cancelled_payload_write_retains_cleanup_until_retry(
    monkeypatch,
):
    from qwenpaw.plugins.execution.payloads import PayloadStore

    store = await PayloadStore.acreate()
    process = PluginProcess()
    process._payloads = store
    assert process._process is None and process._spawn_task is None
    loop = asyncio.get_running_loop()
    entered, release = threading.Event(), threading.Event()
    original_open = store._open
    opened = []

    def blocked_open(*args, **kwargs):
        entered.set()
        assert release.wait(3)
        fd = original_open(*args, **kwargs)
        opened.append(fd)
        return fd

    monkeypatch.setattr(store, "_open", blocked_open)
    pending = asyncio.create_task(
        store.stage(
            '"' + "x" * (1024 * 1024) + '"',
            max_frame_bytes=64,
            deadline=loop.time() + 5,
        ),
    )
    try:
        await eventually(entered.is_set)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        stopped = await process.stop(timeout=0.02)
        assert not stopped.exited
        stopped = await asyncio.shield(process._cleanup_task)
        assert stopped.residual == ("PAYLOAD_STORE_REMAINING",)
        assert process._payloads is store
        assert store.root.is_dir()
        assert store.pending_snapshot()["pending_files"] == 1
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        try:
            stopped = await process.stop(timeout=3)
            assert stopped.exited and not stopped.residual
            assert process._payloads is None
            assert not store.root.exists()
            repeated = await process.stop(timeout=0.1)
            assert repeated.exited and not repeated.residual
        finally:
            assert await store.cleanup(deadline=loop.time() + 3)
    assert opened  # The late write still had a valid directory handle.
    assert not store.root.exists()
    assert store.pending_snapshot()["pending_files"] == 0


@pytest.mark.asyncio
async def test_payload_quota_waits_for_confirmed_discard(monkeypatch):
    from qwenpaw.plugins.execution.errors import FrameLimitError
    from qwenpaw.plugins.execution.payloads import PayloadLimits, PayloadStore

    message = '"' + "原" * (400 * 1024) + '"'
    size = len(message.encode("utf-8"))
    store = await PayloadStore.acreate(
        PayloadLimits(max_pending_files=1, max_pending_bytes=size),
    )
    loop = asyncio.get_running_loop()
    entered, release = threading.Event(), threading.Event()
    original_unlink = store._unlink

    async def stage():
        return await store.stage(
            message,
            max_frame_bytes=64,
            deadline=loop.time() + 5,
        )

    try:
        results = await asyncio.gather(
            stage(),
            stage(),
            return_exceptions=True,
        )
        assert sum(isinstance(row, FrameLimitError) for row in results) == 1
        reference, token = next(
            row for row in results if isinstance(row, tuple)
        )
        assert len(reference.encode("utf-8")) < 1024

        def blocked_unlink(direction, name):
            if name == token + ".json":
                entered.set()
                assert release.wait(3)
            return original_unlink(direction, name)

        monkeypatch.setattr(store, "_unlink", blocked_unlink)
        store.discard(token)
        await eventually(entered.is_set)
        snapshot = store.pending_snapshot()
        assert snapshot["pending_files"] == 1
        assert snapshot["pending_bytes"] == size
        with pytest.raises(FrameLimitError):
            await stage()
        release.set()
        await store.adiscard(token)
        assert store.pending_snapshot()["pending_bytes"] == 0
        _, replacement = await stage()
        await store.adiscard(replacement)
    finally:
        release.set()
        assert await store.cleanup(deadline=loop.time() + 3)
    assert not store.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("layout", ["source", "frozen"])
async def test_runtime_roots_interpreter_and_dependency_visible_in_worker(
    tmp_path,
    monkeypatch,
    process,
    layout,
):
    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )

    monkeypatch.setattr(
        "qwenpaw.config.utils.get_config_path",
        lambda: tmp_path / "config.json",
    )
    if layout == "frozen":
        expected_support, site = runtime_layout(tmp_path, monkeypatch)
        runtime = resolve_default_channel_runtime()
    else:
        site = dependency_site(tmp_path / "dependencies")
        runtime = resolve_default_channel_runtime()
        expected_support = ROOT / "src"
        runtime = replace(runtime, dependency_paths=(site,))
    assert runtime.support_root == expected_support
    assert site in runtime.dependency_paths
    spec, _ = launch(
        tmp_path,
        python_executable=runtime.python_executable,
        support_root=runtime.support_root,
        dependency_paths=runtime.dependency_paths,
    )
    requirements = spec.code_root / "requirements.txt"
    requirements.write_text("sample-shared-sdk==1.0\n")
    spec = replace(
        spec,
        config={**spec.config, "sdk": True},
        requirements_path=requirements,
        source_revision=digest(spec.code_root),
    )
    from qwenpaw.envs import store
    from qwenpaw.plugins import dependency_maintenance as maintenance

    selected_root = maintenance.state_root()
    key = "QWENPAW_DEPENDENCY_STATE_DIR"
    store._apply_to_environ({key: str(tmp_path / "untrusted-state")})
    assert maintenance.state_root() == selected_root
    monkeypatch.setenv(key, str(tmp_path / "direct-mutation"))
    await process.start(spec)
    probe = await process.call("sample.probe", {})
    assert Path(probe["dependency_state"]) == selected_root
    assert any(
        row["pid"] == probe["pid"] for row in maintenance.live_readers([site])
    )
    with pytest.raises(RuntimeError, match="BUSY"):
        with maintenance.maintenance([site], "test", "token"):
            pytest.fail("active worker allowed maintenance")
    assert probe["sdk"] == "offline-sdk" and probe["isolated"] == 1
    assert (
        Path(probe["executable"]).resolve()
        == Path(runtime.python_executable).resolve()
    )
    assert Path(probe["source"]).parent == spec.code_root
    assert "sample_shared_sdk" not in sys.modules


@pytest.mark.parametrize(
    ("layout", "allowed"),
    [
        ("conda-overlay", True),
        ("conda-native", False),
        ("venv-native", True),
        ("system", False),
        ("conda-overlap", False),
        ("conda-symlink", False),
        ("conda-native-alias", False),
        ("immutable-alias", False),
        ("explicit-target", True),
        ("sibling-target", False),
        ("bundle", False),
        ("bundle-alias", False),
        ("sibling-target-alias", False),
    ],
)
def test_dependency_site_permission_follows_real_target(
    tmp_path,
    layout,
    allowed,
):
    from qwenpaw.plugins.dependency_transaction import (
        dependency_site_is_mutable,
    )

    prefix, managed = tmp_path / "python", tmp_path / "plugin_runtime"
    native, overlay = prefix / "lib/site-packages", managed / "site"
    native.mkdir(parents=True)
    overlay.mkdir(parents=True)
    if layout.startswith("conda"):
        (prefix / "conda-meta").mkdir()
    elif layout == "venv-native":
        (prefix / "pyvenv.cfg").write_text("home = /synthetic\n")
    site = (
        overlay if layout in {"conda-overlay", "immutable-alias"} else native
    )
    if layout.startswith(("explicit-target", "sibling-target", "bundle")):
        site = tmp_path / "host-selected/site"
        site.mkdir(parents=True)
    if layout == "conda-overlap":
        managed = prefix
    elif layout == "conda-symlink":
        site = managed / "linked"
        site.symlink_to(native, target_is_directory=True)
    target = site.parent / "other" if layout.startswith("sibling") else site
    immutable = (site,) if layout.startswith(("immutable", "bundle")) else ()
    if layout.endswith("-alias"):
        root = prefix if layout.startswith("conda") else site.parent
        alias = root.with_name(root.name.upper())
        if not alias.exists() or not alias.samefile(root):
            pytest.skip("filesystem has no case aliases")
        if layout.startswith("conda"):
            prefix = alias
        else:
            target = alias / target.name
            immutable = (alias,) if immutable else ()
    context = DependencyEnvironmentContext(
        str(prefix / "bin/python"),
        ROOT / "src",
        (site,),
        target,
        immutable,
    ).to_mapping()
    assert (
        dependency_site_is_mutable(site, prefix, managed, context) is allowed
    )


@pytest.fixture
def dependency_files(tmp_path):
    """Small installed tree shared by preparation and transaction checks."""

    prefix, site = tmp_path / "python", tmp_path / "plugin_runtime/site"
    prefix.mkdir()
    (prefix / "pyvenv.cfg").write_text("home = /synthetic\n")
    site.mkdir(parents=True)
    module = site / "sample_shared_sdk.py"
    module.write_bytes(b"VALUE = '0.5'\n")
    module.chmod(0o640)
    for name, version in (
        ("sample_shared_sdk", "0.5"),
        ("certifi", "2026.10.19"),
    ):
        metadata = site / f"{name}-{version}.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        )
        paths = [f"{metadata.name}/METADATA", f"{metadata.name}/RECORD"]
        if name == "sample_shared_sdk":
            paths.append(module.name)
        (metadata / "RECORD").write_text(
            "".join(f"{path},,\n" for path in paths),
        )
    (site / "neighbor.txt").write_bytes(b"unowned\x00")
    (site / "neighbor.txt").chmod(0o604)
    directory = tmp_path / "operations/reviewed"
    directory.mkdir(parents=True)
    wheel = _local_dependency_wheel(
        tmp_path / "new",
        "sample-shared-sdk",
        "1.0",
        {"sample_shared_sdk.py": b"VALUE = '1.0'\n"},
    )
    return SimpleNamespace(
        prefix=prefix,
        site=site,
        module=module,
        directory=directory,
        wheel=wheel,
    )


def _dependency_snapshot(files):
    site = str(maintenance.canonical(files.site))
    rows, invalid, _ = _installed_metadata((site,))
    assert not invalid
    snapshot = DependencySnapshot(
        str(files.prefix / "bin/python"),
        str(files.prefix),
        (site,),
        default_environment(),
        ("py3-none-any",),
        rows,
        (site,),
    )
    # Exercise the worker's wire contract, including native path identity.
    return DependencySnapshot.from_mapping(snapshot.to_mapping())


def _inventory(root):
    return {
        path.relative_to(root).as_posix(): (
            path.read_bytes() if path.is_file() else None,
            stat.S_IMODE(path.stat().st_mode),
        )
        for path in root.rglob("*")
    }


@pytest.mark.parametrize("placement", ["batch", "target", "sibling"])
@pytest.mark.parametrize(
    "conflict",
    [None, "file", "module", "package", "nested_package"],
)
def test_namespace_additions_preserve_file_ownership(
    tmp_path,
    placement,
    conflict,
):
    import hashlib

    from qwenpaw.plugins.dependency_transaction import prepare_payload
    from qwenpaw.plugins.dependency_gate import _write_additions
    from qwenpaw.plugins.execution.errors import ProtocolValidationError
    from qwenpaw.plugins.wheel_additions import (
        WheelAddition,
        validate_additions,
    )

    site = tmp_path / "plugin_runtime/site"
    site.mkdir(parents=True)
    first = _local_dependency_wheel(
        tmp_path / "wheels",
        "namespace-one",
        "1.0",
        {
            (
                "sample_namespace/nested/one.py"
                if conflict == "nested_package"
                else "sample_namespace/one.py"
            ): b"VALUE = 1\n",
        },
    )
    second_path = {
        None: "sample_namespace/two.py",
        "file": "sample_namespace/one.py",
        "module": "sample_namespace.py",
        "package": "sample_namespace/__init__.py",
        "nested_package": "sample_namespace/nested/__init__.py",
    }[conflict]
    second = _local_dependency_wheel(
        first.parent,
        "namespace-two",
        "1.0",
        {second_path: b"VALUE = 2\n"},
    )
    wheels = [first, second]
    installed = placement != "batch"
    old_site = tmp_path / "sibling" if placement == "sibling" else site
    if installed:
        with zipfile.ZipFile(first) as archive:
            archive.extractall(old_site)
        wheels.remove(first)
    sites = tuple(dict.fromkeys(map(str, (site, old_site))))
    snapshot = DependencySnapshot(
        sys.executable,
        sys.prefix,
        sites,
        default_environment(),
        ("py3-none-any",),
        _installed_metadata((old_site,))[0] if installed else {},
    )
    additions = tuple(
        WheelAddition(path, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in wheels
    )
    before = {root: _inventory(Path(root)) for root in sites}
    if conflict:
        with pytest.raises(
            ProtocolValidationError,
            match=(
                "^DEPENDENCY_RESTART_REQUIRED$"
                if installed
                else "^DEPENDENCY_PLAN_UNVERIFIED$"
            ),
        ):
            validate_additions(additions, snapshot, site)
        if installed:
            # Upgrade planning omits mutable sites; payload custody must still
            # protect every unchanged namespace owner at publication time.
            files, _ = validate_additions(
                additions,
                replace(snapshot, sites=()),
                site,
            )
            operation = tmp_path / "operations/current"
            operation.mkdir(parents=True)
            with pytest.raises(
                RuntimeError,
                match="DEPENDENCY_PLAN_UNVERIFIED",
            ):
                prepare_payload(
                    operation,
                    snapshot.to_mapping(),
                    (),
                    {"namespace-two": site},
                    files,
                    [{"path": str(second)}],
                )
    else:
        files, proposed = validate_additions(additions, snapshot, site)
        operation = tmp_path / "operations/current"
        operation.mkdir(parents=True)
        payload = prepare_payload(
            operation,
            snapshot.to_mapping(),
            (),
            {name: site for name in proposed.distributions},
            files,
            [{"path": str(wheel)} for wheel in wheels],
        )
        assert set(payload["new"]) == {str(site / path) for path in files}
        for path, row in payload["new"].items():
            assert (operation / row["payload"]).read_bytes() == files[
                Path(path).relative_to(site).as_posix()
            ]
        publication = tmp_path / "publication"
        real = publication / "real"
        real.mkdir(parents=True)
        (publication / "sample_namespace").symlink_to(
            real,
            target_is_directory=True,
        )
        with pytest.raises(RuntimeError, match="DEPENDENCY_REPAIR_REQUIRED"):
            _write_additions(publication, {second_path: files[second_path]})
        assert not list(real.iterdir())
    assert {root: _inventory(Path(root)) for root in sites} == before


def _prepare_dependency_operation(files, context=None):
    """Prepare the same reviewed payload for the separate publish checks."""

    snapshot = _dependency_snapshot(files)
    context = context or DependencyEnvironmentContext(
        snapshot.executable,
        ROOT / "src",
        (files.site,),
        files.site,
        (),
    )
    requirements = files.directory.parent / "requirements.txt"
    requirements.write_text("sample-shared-sdk==1.0\n")
    args = files.directory, snapshot, ["sample-shared-sdk==1.0"], []
    DependencyUpgradeManager._prepare_resolution(*args, requirements, context)
    shutil.copy2(files.wheel, files.directory / "wheels" / files.wheel.name)
    _, changes, proposed, payload = DependencyUpgradeManager._prepare_payload(
        *args,
        files.site,
        context,
    )
    return {
        "id": files.directory.name,
        "environment": snapshot.to_mapping(),
        "dependency_context": context.to_mapping(),
        "changes": changes,
        "proposed": proposed,
        "payload": payload,
    }


@pytest.mark.parametrize(
    "layout",
    [
        "sibling-target",
        "conda-native",
        "system",
        "bundle",
        "immutable-provider",
    ],
)
def test_dependency_preparation_rejects_protected_environment(
    tmp_path,
    dependency_files,
    layout,
):
    files = dependency_files
    if layout == "sibling-target":
        files.site.rename(tmp_path / "host-selected")
        files.site = tmp_path / "host-selected"
    if layout in {"conda-native", "system"}:
        files.site.rename(files.prefix / "site-packages")
        files.site = files.prefix / "site-packages"
        (files.prefix / "pyvenv.cfg").unlink()
        if layout == "conda-native":
            (files.prefix / "conda-meta").mkdir()
    immutable = ()
    if layout == "bundle":
        immutable = (files.site,)
    elif layout == "immutable-provider":
        bundled = tmp_path / "bundle/site"
        shutil.copytree(files.site, bundled)
        immutable = (bundled,)
    snapshot = _dependency_snapshot(files)
    context = DependencyEnvironmentContext(
        snapshot.executable,
        ROOT / "src",
        (files.site,),
        (
            files.site.parent / "other"
            if layout == "sibling-target"
            else files.site
        ),
        immutable,
    )
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("sample-shared-sdk==1.0\n")
    args = files.directory, snapshot, ["sample-shared-sdk==1.0"], []
    before = _inventory(tmp_path)
    with pytest.raises(
        SharedDependencyError,
        match="bundled|environment-managed",
    ) as error:
        DependencyUpgradeManager._prepare_resolution(
            *args,
            requirements,
            context,
        )
    assert error.value.reason_code == "DEPENDENCY_ENVIRONMENT_PROTECTED"
    assert _inventory(tmp_path) == before
    wheels = files.directory / "wheels"
    wheels.mkdir()
    shutil.copy2(files.wheel, wheels / files.wheel.name)
    before = _inventory(tmp_path)
    with pytest.raises(
        RuntimeError,
        match="DEPENDENCY_ENVIRONMENT_PROTECTED|bundled",
    ):
        DependencyUpgradeManager._prepare_payload(*args, files.site, context)
    assert _inventory(tmp_path) == before


@pytest.mark.parametrize("scripts", ["bin", "Scripts"])
def test_overlay_rejects_record_outside_target(
    tmp_path,
    dependency_files,
    scripts,
):
    files = dependency_files
    launcher = files.prefix / scripts / "sdk"
    launcher.parent.mkdir()
    launcher.write_bytes(b"old launcher\x00")
    record = files.site / "sample_shared_sdk-0.5.dist-info/RECORD"
    with record.open("a") as stream:
        stream.write(
            Path(os.path.relpath(launcher, files.site)).as_posix() + ",,\n",
        )
    snapshot = _dependency_snapshot(files)
    context = DependencyEnvironmentContext(
        snapshot.executable,
        ROOT / "src",
        (files.site,),
        files.site,
        (),
    )
    wheels = files.directory / "wheels"
    wheels.mkdir()
    shutil.copy2(files.wheel, wheels / files.wheel.name)
    before = _inventory(tmp_path)
    with pytest.raises(RuntimeError, match="DEPENDENCY_PLAN_UNVERIFIED"):
        DependencyUpgradeManager._prepare_payload(
            files.directory,
            snapshot,
            ["sample-shared-sdk==1.0"],
            [],
            files.site,
            context,
        )
    assert _inventory(tmp_path) == before


def test_conda_overlay_replaces_provider(dependency_files):
    files = dependency_files
    (files.prefix / "conda-meta").mkdir()
    operation = _prepare_dependency_operation(files)
    publish(files.directory, operation)
    assert files.module.read_text() == "VALUE = '1.0'\n"
    assert not (files.site / "sample_shared_sdk-0.5.dist-info").exists()
    assert (files.site / "sample_shared_sdk-1.0.dist-info/RECORD").is_file()
    assert (files.site / "neighbor.txt").read_bytes() == b"unowned\x00"


def test_explicit_target_prepares_payload(tmp_path, dependency_files):
    files = dependency_files
    files.site.rename(tmp_path / "host-selected")
    files.site = tmp_path / "host-selected"
    operation = _prepare_dependency_operation(files)
    assert (
        operation["payload"]
        and operation["changes"][0]["name"] == "sample-shared-sdk"
    )


def test_policy_change_blocks_verify_and_publish(tmp_path, dependency_files):
    files = dependency_files
    files.site.rename(files.prefix / "site-packages")
    files.site = files.prefix / "site-packages"
    operation = _prepare_dependency_operation(files)
    (files.prefix / "conda-meta").mkdir()
    before = _inventory(tmp_path)
    assert not maintenance.repair_marker(files.site).exists()
    for write in (verify_payload, publish):
        with pytest.raises(
            RuntimeError,
            match="DEPENDENCY_ENVIRONMENT_PROTECTED",
        ):
            write(files.directory, operation)
        assert _inventory(tmp_path) == before
        assert not maintenance.repair_marker(files.site).exists()


@pytest.mark.parametrize("scripts", ["bin", "Scripts"])
def test_native_launcher_publish_and_exact_rollback(
    tmp_path,
    dependency_files,
    scripts,
):
    files = dependency_files
    files.site.rename(files.prefix / "site-packages")
    files.site = files.prefix / "site-packages"
    files.module = files.site / files.module.name
    launcher = files.prefix / scripts / "sdk.py"
    launcher.parent.mkdir()
    launcher.write_bytes(b"#!/synthetic/python\nprint('old launcher')\n")
    launcher.chmod(0o751)
    launcher_mode = stat.S_IMODE(launcher.stat().st_mode)
    record = files.site / "sample_shared_sdk-0.5.dist-info/RECORD"
    with record.open("a") as stream:
        stream.write(
            Path(os.path.relpath(launcher, files.site)).as_posix() + ",,\n",
        )
    precache = launcher.parent / "__pycache__/sdk.cpython-313.pyc"
    py_compile.compile(str(launcher), cfile=str(precache), doraise=True)
    precache.chmod(0o600)
    # Case alias ownership must pass a real aliased prefix into the resolver.
    alias = files.prefix.with_name("PYTHON")
    if scripts == "bin" and alias.exists() and alias.samefile(files.prefix):
        owned = _owned(
            _dependency_snapshot(files).distributions["sample-shared-sdk"],
            alias,
        )
        assert str(launcher.resolve()) in owned
        files.prefix = alias
    operation = _prepare_dependency_operation(files)
    cache = launcher.parent / "__pycache__/sdk.cpython-313.opt-1.pyc"
    py_compile.compile(
        str(launcher),
        cfile=str(cache),
        doraise=True,
        optimize=1,
    )
    cache.chmod(0o640)
    before = _inventory(files.prefix)
    publish(files.directory, operation)
    assert files.module.read_text() == "VALUE = '1.0'\n"
    assert not (files.site / "sample_shared_sdk-0.5.dist-info").exists()
    assert (
        launcher.read_bytes()
        == b"#!/synthetic/python\nprint('old launcher')\n"
    )
    assert stat.S_IMODE(launcher.stat().st_mode) == launcher_mode
    record = files.site / "sample_shared_sdk-1.0.dist-info/RECORD"
    assert (
        sum(
            (files.site / row[0]).samefile(launcher)
            for row in csv.reader(record.read_text().splitlines())
        )
        == 1
    )
    assert not cache.exists() and not precache.exists()
    assert (files.site / "neighbor.txt").read_bytes() == b"unowned\x00"
    rollback(files.directory)
    assert _inventory(files.prefix) == before


@pytest.mark.parametrize("late_cache", [False, True])
def test_pip_record_cache_publish_and_exact_rollback(
    tmp_path,
    dependency_files,
    late_cache,
):
    files = dependency_files
    files.site.rename(files.prefix / "site-packages")
    files.site = files.prefix / "site-packages"
    (files.site / "sample_shared_sdk.py").unlink()
    shutil.rmtree(files.site / "sample_shared_sdk-0.5.dist-info")
    module_path = "sample_shared_sdk/__init__.py"
    old = _local_dependency_wheel(
        tmp_path / "old",
        "sample-shared-sdk",
        "0.5",
        {module_path: b"VALUE = '0.5'\n"},
    )
    installed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--disable-pip-version-check",
            "--target",
            str(files.site),
            str(old),
        ],
        capture_output=True,
        text=True,
    )
    assert installed.returncode == 0, installed.stderr
    record = files.site / "sample_shared_sdk-0.5.dist-info/RECORD"
    pip_record = record.read_bytes()
    cache_rows = [
        row
        for row in csv.reader(pip_record.decode().splitlines())
        if row[0].endswith(".pyc")
    ]
    assert len(cache_rows) == 1
    cache = files.site / cache_rows[0][0]
    assert cache.is_file()
    if late_cache:
        cache.unlink()
    else:
        cache.chmod(0o600)
    files.module = files.site / module_path
    files.module.chmod(0o640)
    files.wheel = _local_dependency_wheel(
        tmp_path / "package-new",
        "sample-shared-sdk",
        "1.0",
        {module_path: b"VALUE = '1.0'\n"},
    )
    neighbor_mode = stat.S_IMODE((files.site / "neighbor.txt").stat().st_mode)
    operation = _prepare_dependency_operation(files)
    if late_cache:
        py_compile.compile(str(files.module), doraise=True)
        cache.chmod(0o600)
    assert cache.is_file() and record.read_bytes() == pip_record
    before = _inventory(files.prefix)
    publish(files.directory, operation)
    assert files.module.read_text() == "VALUE = '1.0'\n"
    assert not (files.site / "sample_shared_sdk-0.5.dist-info").exists()
    assert (files.site / "sample_shared_sdk-1.0.dist-info/RECORD").is_file()
    assert not cache.exists()
    assert (files.site / "neighbor.txt").read_bytes() == b"unowned\x00"
    assert (
        stat.S_IMODE((files.site / "neighbor.txt").stat().st_mode)
        == neighbor_mode
    )
    rollback(files.directory)
    assert _inventory(files.prefix) == before


def test_record_rejects_duplicate_installed_ownership(dependency_files):
    files = dependency_files
    row = _dependency_snapshot(files).distributions["sample-shared-sdk"]
    with (files.site / "sample_shared_sdk-0.5.dist-info/RECORD").open(
        "a",
    ) as stream:
        stream.write("sample_shared_sdk.py,,\n")
    with pytest.raises(RuntimeError, match="duplicate installed ownership"):
        _owned(row, files.prefix)


@pytest_asyncio.fixture
async def staged_upgrade(tmp_path, monkeypatch, request):
    broken_source = getattr(request, "param", False)
    host = await Host.create(tmp_path, monkeypatch)
    site = tmp_path / "plugin_runtime/site"
    site.mkdir(parents=True)
    alias = site.with_name("SITE")
    if alias.exists() and alias.samefile(site):
        site = alias
    host.site = site
    monkeypatch.setattr(sys, "path", sys.path.copy())
    monkeypatch.setenv("QWENPAW_PLUGIN_SITE", str(site))
    host.registry.channel_runtime = replace(
        host.registry.channel_runtime,
        dependency_paths=(site,),
        dependency_install_target=site,
    )
    # An installed Python backend has roots disjoint from the channel worker.
    # Its real audit must remain covered when maintenance observes consumers.
    import json
    from qwenpaw.plugins import python_backend

    independent_site = tmp_path / "independent-site"
    independent_site.mkdir()
    monkeypatch.setattr(
        python_backend,
        "_host_paths",
        lambda cwd: (str(independent_site),),
    )
    independent = host.installed.parent / "independent-consumer"
    independent.mkdir(parents=True)
    (independent / "plugin.json").write_text(
        json.dumps(
            {
                "id": "independent-consumer",
                "version": "1.0.0",
                "type": "tool",
                "entry": {"backend": "main.py"},
            },
        ),
    )
    (independent / "main.py").write_text(
        "class Plugin:\n    def register(self, api):\n        pass\n"
        "plugin = Plugin()\n",
    )
    assert independent_site.resolve() != site.resolve()
    old = local_wheel(tmp_path / "old", version="0.5", value="0.5")
    with zipfile.ZipFile(next(old.glob("*.whl"))) as archive:
        archive.extractall(site)
    module = site / "sample_shared_sdk.py"
    module.chmod(0o640)
    (site / "neighbor.txt").write_bytes(b"preserve unrelated bytes\x00")
    before, mode = digest(site), module.stat().st_mode
    source = host.artifact(sdk=True)
    published = tmp_path / "published-sdk"
    if broken_source:
        (source / "sample.py").write_text(
            "from pathlib import Path\n"
            "import sample_shared_sdk as sdk\n"
            f"Path({str(published)!r}).write_text(\n"
            "    sdk.VALUE + '\\n' + Path(sdk.__file__).read_text())\n"
            "raise RuntimeError('new source cannot initialize')\n",
        )
    wheel = next(local_wheel(tmp_path / "new", value="1.0").glob("*.whl"))
    certifi_wheel = local_certifi_wheel(wheel.parent)

    def resolve(command, **kwargs):
        assert "wheel" in command and "install" not in command
        target = Path(command[command.index("--wheel-dir") + 1])
        shutil.copy2(wheel, target / wheel.name)
        shutil.copy2(certifi_wheel, target / certifi_wheel.name)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(
        host.loader,
        "_run_subprocess_with_streaming_log",
        resolve,
    )
    try:
        manager = DependencyUpgradeManager(host.loader)
        operation = await manager.stage(source)
        yield SimpleNamespace(
            host=host,
            manager=manager,
            operation=operation,
            site=site,
            module=module,
            before=before,
            mode=mode,
            source=source,
            published=published,
            broken_source=broken_source,
        )
    finally:
        await host.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("staged_upgrade", [False, True], indirect=True)
async def test_shared_upgrade_replaces_provider_or_restores_exact_old_tree(
    staged_upgrade,
):
    prepared = staged_upgrade
    host, manager, operation = (
        prepared.host,
        prepared.manager,
        prepared.operation,
    )
    site, module, before = prepared.site, prepared.module, prepared.before
    mode, source, published = (
        prepared.mode,
        prepared.source,
        prepared.published,
    )
    broken_source = prepared.broken_source
    assert operation["status"] == "needs_confirmation"
    assert operation["changes"] == [
        {
            "name": "sample-shared-sdk",
            "current_version": "0.5",
            "target_version": "1.0",
        },
    ]
    assert digest(site) == before and not operation["requires_restart"]
    assert not published.exists()
    result = await manager.apply(operation["id"])
    if broken_source:
        assert result["status"] == "failed", result
        assert result["error"]["code"] == "DEPENDENCY_UPGRADE_FAILED", result
        assert published.read_text() == "1.0\nVALUE = '1.0'\n"
        assert digest(site) == before and module.stat().st_mode == mode
        assert not host.installed.exists()
    else:
        assert result["status"] == "succeeded", result
        assert module.read_text() == "VALUE = '1.0'\n"
        assert not (site / "sample_shared_sdk-0.5.dist-info").exists()
        assert (site / "sample_shared_sdk-1.0.dist-info/RECORD").is_file()
        assert (host.installed / "sample.py").read_bytes() == (
            source / "sample.py"
        ).read_bytes()
        assert (await manager.apply(operation["id"])) == result
    assert (site / "neighbor.txt").read_bytes() == (
        b"preserve unrelated bytes\x00"
    )


@pytest.mark.asyncio
async def test_cancelled_late_maintenance_entry_clears_own_marker(
    staged_upgrade,
    monkeypatch,
):
    prepared = staged_upgrade
    manager, site, operation = (
        prepared.manager,
        prepared.site,
        prepared.operation,
    )
    original = maintenance.maintenance_barrier
    started, release = threading.Event(), threading.Event()
    requested = asyncio.Event()

    @contextmanager
    def blocked_entry(*args, **kwargs):
        with original(*args, **kwargs) as value:
            started.set()
            assert release.wait(3)
            yield value

    def slow_entry(*args, **kwargs):
        # Preparation audits precede this factory call. Measure the controlled
        # maintenance entry only after the operation actually requests it.
        requested.set()
        return blocked_entry(*args, **kwargs)

    monkeypatch.setattr(maintenance, "maintenance_barrier", slow_entry)
    task_capabilities = []

    async def apply():
        try:
            await manager.apply(operation["id"])
        finally:
            task_capabilities.append(maintenance.capability_context.get())

    pending = asyncio.create_task(apply())
    entry_requested = asyncio.create_task(requested.wait())
    try:
        done, _ = await asyncio.wait(
            (pending, entry_requested),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if pending in done:
            await pending  # Preserve an early admission failure's traceback.
            pytest.fail("apply returned before entering maintenance")
        assert await asyncio.to_thread(started.wait, 2)
        assert maintenance.marker(site).exists()
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
    finally:
        release.set()
        entry_requested.cancel()
        await asyncio.gather(entry_requested, return_exceptions=True)
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(pending, 5)
    assert task_capabilities == [""]
    assert not maintenance.marker(site).exists()
    assert manager.status(operation["id"])["retryable"] is True
    assert digest(site) == prepared.before
    assert prepared.module.stat().st_mode == prepared.mode
    assert not prepared.host.installed.exists()
    # The standalone entry still acquires its own writer gates.
    monkeypatch.setattr(maintenance, "maintenance_barrier", original)
    with maintenance.maintenance(
        [site],
        "next-operation",
        "next-capability",
    ):
        maintenance.clear_maintenance([site], operation["id"])
        assert maintenance.marker(site).exists()
    maintenance.clear_maintenance([site], "next-operation")
    assert not maintenance.marker(site).exists()


@pytest.mark.asyncio
async def test_frozen_ordinary_loader_gate_installs_missing_sdk_in_overlay(
    tmp_path,
    monkeypatch,
):
    import importlib
    import json
    import shutil

    from qwenpaw.plugins.channel_bootstrap import (
        resolve_default_channel_runtime,
    )
    from tests.channel_support.host import (
        Host,
        local_certifi_wheel,
        local_wheel,
    )

    monkeypatch.setattr(sys, "path", sys.path.copy())
    host = await Host.create(tmp_path, monkeypatch)
    support, packaged = runtime_layout(tmp_path, monkeypatch)
    (packaged / "sample_shared_sdk.py").unlink()
    shutil.rmtree(packaged / "sample_shared_sdk-1.0.dist-info")
    runtime = resolve_default_channel_runtime()
    host.registry.channel_runtime = runtime
    monkeypatch.setenv(
        "QWENPAW_PLUGIN_SITE",
        str(runtime.dependency_install_target),
    )
    source = tmp_path / "ordinary-plugin"
    source.mkdir()
    (source / "requirements.txt").write_text(
        "sample-shared-sdk==1.0\nsample-namespace-one==1.0\n"
        "sample-namespace-two==1.0\n",
    )
    (source / "plugin.json").write_text(
        json.dumps(
            {
                "id": "ordinary-plugin",
                "version": "1.0.0",
                "entry": {"backend": "main.py"},
            },
        ),
    )
    (source / "main.py").write_text(
        "import sample_shared_sdk\n"
        "from sample_namespace import one, two\n"
        "class Plugin:\n"
        "    def register(self, api): pass\n"
        "    def sdk_value(self): return sample_shared_sdk.VALUE\n"
        "    def namespace_value(self): return one.VALUE + two.VALUE\n"
        "plugin = Plugin()\n",
    )
    wheels = local_wheel(tmp_path / "wheels")
    for name in ("one", "two"):
        _local_dependency_wheel(
            wheels,
            f"sample-namespace-{name}",
            "1.0",
            {f"sample_namespace/{name}.py": f"VALUE = {name!r}\n".encode()},
        )
    local_certifi_wheel(wheels)
    for name, value in {
        "PIP_NO_INDEX": "1",
        "PIP_FIND_LINKS": str(wheels),
        "PIP_NO_CACHE_DIR": "1",
        "PIP_CONFIG_FILE": os.devnull,
    }.items():
        monkeypatch.setenv(name, value)
    from qwenpaw.plugins.dependency_maintenance import marker, repair_marker
    from qwenpaw.plugins.dependency_context import DependencyEnvironmentContext
    from qwenpaw.plugins.install_lock import environment_install_lock_path

    resources = support.parent

    def bundle_inventory():
        # Signing covers the whole resource tree, including empty directories
        # and coordination sidecars beside the packaged dependency sites.
        return {
            path.relative_to(resources).as_posix(): (
                ("symlink", os.readlink(path))
                if path.is_symlink()
                else (
                    ("directory", None)
                    if path.is_dir()
                    else ("file", path.read_bytes())
                )
            )
            for path in resources.rglob("*")
        }

    for site in runtime.dependency_paths:
        for path in (
            environment_install_lock_path(site),
            marker(site),
            repair_marker(site),
        ):
            assert not path.is_relative_to(resources)
    native_site = Path(runtime.python_executable).parent.parent / (
        "Lib/site-packages"
        if os.name == "nt"
        else f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    context = DependencyEnvironmentContext.from_runtime(runtime)
    assert context.protected(native_site)
    assert not context.protected(runtime.dependency_install_target)

    before = bundle_inventory()
    try:
        absent = await host.loader._ensure_dependencies_installed(
            source,
            "ordinary-plugin",
            allow_install=False,
        )
        assert not absent.already_satisfied and absent.missing
        record = await host.loader.load_plugin_from_path(source)
        assert record.status == "active", record.diagnostics
        assert record.instance.sdk_value() == "offline-sdk"
        assert record.instance.namespace_value() == "onetwo"
        sdk = importlib.import_module("sample_shared_sdk")
        assert sdk.VALUE == "offline-sdk"
        assert Path(sdk.__file__).parent == runtime.dependency_install_target
        assert (
            runtime.dependency_install_target
            / ("sample_shared_sdk-1.0.dist-info/RECORD")
        ).is_file()
        checked = await host.loader._ensure_dependencies_installed(
            source,
            "ordinary-plugin",
            allow_install=False,
        )
        assert checked.already_satisfied and not checked.missing
        assert bundle_inventory() == before
    finally:
        try:
            if host.loader.get_loaded_plugin("ordinary-plugin") is not None:
                await host.loader.unload_plugin("ordinary-plugin")
        finally:
            sys.modules.pop("sample_shared_sdk", None)
            for name in (
                "sample_namespace",
                "sample_namespace.one",
                "sample_namespace.two",
            ):
                sys.modules.pop(name, None)
            importlib.invalidate_caches()
            await host.close()
    assert bundle_inventory() == before


def test_executor_inspection_preserves_immutable_support_tree(tmp_path):
    import shutil
    import packaging
    from qwenpaw.plugins.dependency_context import DependencyEnvironmentContext

    support = tmp_path / "Bundle.app/Contents/Resources/site"
    support.mkdir(parents=True)
    shutil.copytree(
        Path(packaging.__file__).parent,
        support / "packaging",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    before = {
        p.relative_to(support): p.read_bytes()
        for p in support.rglob("*")
        if p.is_file()
    }
    context = DependencyEnvironmentContext(
        sys.executable,
        support,
        (support,),
        None,
        (support,),
    )
    assert context.inspect_executor()
    after = {
        p.relative_to(support): p.read_bytes()
        for p in support.rglob("*")
        if p.is_file()
    }
    assert set(after) == set(before)
    assert all(after[path] == value for path, value in before.items())
