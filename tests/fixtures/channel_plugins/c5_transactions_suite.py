# -*- coding: utf-8 -*-
# pylint: disable=protected-access,redefined-outer-name
# pylint: disable=wrong-import-position,too-many-statements,use-a-generator
"""C5 finite transaction acceptance through real child and framework state."""

import asyncio
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace as NS

import psutil
import pytest

from ownership_helpers import channel_leases, channel_owner

pytest.register_assert_rewrite("c5_support")
from c5_support import KEY, eventually, rows, wheelhouse  # noqa: E402

pytest_plugins = ["c5_support"]


@pytest.mark.asyncio
async def test_first_install_runs_only_installed_source(transaction):
    ws = await transaction.workspace("first")
    source = transaction.artifact()
    record = await transaction.loader.load_plugin_from_path(source)
    assert record.status == "active" and record.enabled
    channel, evidence = await transaction.identity(ws)
    assert evidence["version"] == "1.0.0"
    assert Path(evidence["source"]).is_relative_to(transaction.installed)
    assert channel._launch_spec.code_root == transaction.installed
    assert source.exists() and transaction.installed.exists()
    assert len(rows(transaction.network, "connected")) == 1
    assert not any(
        lease.key.kind == "preparation"
        for lease in transaction.registry.runtime_owners.leases()
    )


@pytest.mark.asyncio
async def test_active_update_swaps_all_workspaces_after_old_exit(transaction):
    from qwenpaw.plugins.updates import marker_path

    workspaces = [await transaction.workspace(name) for name in ("one", "two")]
    await transaction.seed(config={"custom": "preserved"})
    old = [await transaction.identity(ws) for ws in workspaces]
    incoming = transaction.artifact("2.0.0")
    barrier = Path(str(transaction.network) + ".probe-block")
    barrier.touch()
    update = asyncio.create_task(
        transaction.loader.lifecycle.reload(KEY, new_source=incoming),
    )
    try:
        await eventually(
            lambda: rows(transaction.network, "imported", "2.0.0")
            or update.done(),
        )
        if update.done():
            report = await update
            assert report.ok, report.errors
        assert not rows(transaction.network, "connected", "2.0.0")
        assert all(
            [
                (await transaction.identity(ws))[1]["pid"] == prior["pid"]
                for ws, (_, prior) in zip(workspaces, old)
            ],
        )
    finally:
        barrier.unlink(missing_ok=True)
    report = await update
    assert report.ok, report.errors
    fresh = [await transaction.identity(ws) for ws in workspaces]
    assert all(not psutil.pid_exists(value["pid"]) for _, value in old)
    assert all(value["version"] == "2.0.0" for _, value in fresh)
    assert all(
        Path(value["source"]).is_relative_to(transaction.installed)
        for _, value in fresh
    )
    assert all(
        new._launch_spec.generation > prior._launch_spec.generation
        for (prior, _), (new, _) in zip(old, fresh)
    )
    assert max(
        row["time"] for row in rows(transaction.network, "stopped", "1.0.0")
    ) < min(
        row["time"] for row in rows(transaction.network, "connected", "2.0.0")
    )
    assert len(rows(transaction.network, "connected", "1.0.0")) == 2
    assert len(rows(transaction.network, "connected", "2.0.0")) == 2
    assert not marker_path(KEY).exists()
    assert {path.name for path in transaction.installed.parent.iterdir()} == {
        KEY,
    }


@pytest.mark.asyncio
async def test_bad_candidate_is_probed_before_any_old_teardown(
    transaction,
    tmp_path,
    monkeypatch,
):
    ws = await transaction.workspace("candidate-failure")
    await transaction.seed()
    channel, old = await transaction.identity(ws)
    retained_row = transaction.registry.get_channel_registration(KEY)
    usage = transaction.registry.dependency_usage
    native_refine = usage.refine
    borrowed_old_token = []

    def refine(token, snapshot, **kwargs):
        if token is retained_row.dependency_token:
            borrowed_old_token.append(snapshot)
        return native_refine(token, snapshot, **kwargs)

    monkeypatch.setattr(usage, "refine", refine)
    candidate = transaction.artifact("2.0.0", broken=True)
    (candidate / "requirements.txt").write_text("c5-transaction-sdk==1.0\n")
    local = wheelhouse(tmp_path / "candidate-wheelhouse")

    def local_wheel(command, **_kwargs):
        assert command[1:5] == ["-I", "-m", "pip", "wheel"]
        assert not {"install", "download", "--dest", "--target"}.intersection(
            command,
        )
        staging = Path(command[command.index("--wheel-dir") + 1])
        assert staging != transaction.site
        assert Path(command[command.index("--constraint") + 1]).is_file()
        assert Path(command[command.index("-r") + 1]).read_text() == (
            "c5-transaction-sdk==1.0\n"
        )
        for path in local.glob("*.whl"):
            shutil.copyfile(path, staging / path.name)
        return NS(returncode=0)

    monkeypatch.setattr(
        transaction.loader,
        "_run_subprocess_with_streaming_log",
        local_wheel,
    )
    report = await transaction.loader.lifecycle.reload(
        KEY,
        new_source=candidate,
        allow_install=True,
    )
    assert not report.ok
    assert (
        not borrowed_old_token
    ), "different-source candidate borrowed retained registration token"
    assert transaction.registry.get_channel_registration(KEY) is retained_row
    assert rows(
        transaction.network,
        "imported",
        "2.0.0",
    ), "Candidate was refused without actual-child probe"
    same, evidence = await transaction.identity(ws)
    assert same is channel and evidence["pid"] == old["pid"]
    assert psutil.pid_exists(old["pid"])
    assert not rows(transaction.network, "stopped", "1.0.0")
    assert not rows(transaction.network, "connected", "2.0.0")
    assert (
        json.loads((transaction.installed / "plugin.json").read_text())[
            "version"
        ]
        == "1.0.0"
    )
    site = transaction.registry.channel_runtime.dependency_install_target
    assert (
        site / "c5_transaction_sdk.py"
    ).read_bytes() == b"VALUE = 'offline-c5-sdk'\n"
    assert (site / "c5_transaction_sdk-1.0.dist-info/METADATA").is_file()


@pytest.mark.asyncio
async def test_in_place_descriptor_update_refuses_before_old_stop(transaction):
    ws = await transaction.workspace("in-place")
    await transaction.seed()
    old, evidence = await transaction.identity(ws)
    report = await transaction.loader.lifecycle.reload(KEY)
    assert not report.ok and report.unchanged
    assert "in-place" in " ".join(report.errors).lower()
    same, after = await transaction.identity(ws)
    assert same is old and after["pid"] == evidence["pid"]
    assert not rows(transaction.network, "stopped")


@pytest.mark.asyncio
@pytest.mark.parametrize("residual", [False, True])
async def test_partial_new_activation_obeys_quiescence_before_restore(
    transaction,
    monkeypatch,
    residual,
):
    from qwenpaw.plugins.execution.process_tree import ProcessTree
    from qwenpaw.plugins.updates import marker_path

    good = await transaction.workspace("first-success")
    bad = await transaction.workspace("second-failure", fail_new=True)
    await transaction.seed(config={"retained": "old-config"})
    before = [await transaction.identity(ws) for ws in (good, bad)]
    incoming = transaction.artifact("2.0.0")
    hold = Path(str(transaction.network) + ".hold-new")
    signal = ProcessTree.signal

    def controlled_signal(tree, *, force):
        if hold.exists() and any(
            row["pid"] == tree.pid
            for row in rows(transaction.network, "connected", "2.0.0")
        ):
            return
        signal(tree, force=force)

    if residual:
        hold.touch()
        monkeypatch.setattr(ProcessTree, "signal", controlled_signal)
    try:
        report = await transaction.loader.lifecycle.reload(
            KEY,
            new_source=incoming,
        )
        assert not report.ok
        assert rows(
            transaction.network,
            "failed-start",
            "2.0.0",
        ), "New workspace startup never reached"
        assert all(not psutil.pid_exists(value["pid"]) for _, value in before)
        if residual:
            assert report.needs_restart
            assert (
                json.loads(
                    (transaction.installed / "plugin.json").read_text(),
                )["version"]
                == "2.0.0"
            )
            marker = json.loads(marker_path(KEY).read_text())
            assert marker["status"] in {"prepared", "updating"}
            assert Path(marker["backup_path"]).exists()
            assert channel_leases(transaction.registry)
            connected = rows(transaction.network, "connected", "2.0.0")
            assert connected and any(
                psutil.pid_exists(row["pid"]) for row in connected
            )
            assert len(rows(transaction.network, "connected", "1.0.0")) == 2
        else:
            restored = [await transaction.identity(ws) for ws in (good, bad)]
            assert all(value["version"] == "1.0.0" for _, value in restored)
            assert all(
                channel._launch_spec.generation > old._launch_spec.generation
                for (old, _), (channel, _) in zip(before, restored)
            )
            assert all(
                not psutil.pid_exists(row["pid"])
                for row in rows(transaction.network, "connecting", "2.0.0")
            )
            assert transaction.loader.lifecycle.get_instance(KEY).config == {
                "retained": "old-config",
            }
            assert (
                json.loads(
                    (transaction.installed / "plugin.json").read_text(),
                )["version"]
                == "1.0.0"
            )
            assert not marker_path(KEY).exists()
    finally:
        hold.unlink(missing_ok=True)
        monkeypatch.setattr(ProcessTree, "signal", signal)


@pytest.mark.asyncio
async def test_disabled_reinstall_then_enable_preserves_saved_config(
    transaction,
    monkeypatch,
):
    from qwenpaw.config.utils import load_config
    from qwenpaw.plugins.settings import persist_plugin_settings

    ws = await transaction.workspace("disabled")
    persist_plugin_settings(KEY, enabled=False, config={"custom": "saved"})
    first = await transaction.loader.load_plugin_from_path(
        transaction.artifact(),
    )
    assert first.status == "inactive" and not first.enabled
    second = await transaction.loader.load_plugin_from_path(
        transaction.artifact("2.0.0"),
        force=True,
    )
    assert second.status == "inactive" and not second.enabled
    assert "channel_validation_pending" in second.diagnostics
    assert not rows(transaction.network)
    assert load_config().plugins[KEY] == {"enabled": False, "custom": "saved"}

    def no_download(*_args, **_kwargs):
        raise AssertionError("Enable attempted dependency acquisition")

    monkeypatch.setattr(
        transaction.loader,
        "_run_subprocess_with_streaming_log",
        no_download,
    )
    result = await transaction.loader.lifecycle.set_enabled(KEY, True)
    assert result.status == "active" and result.enabled
    _, evidence = await transaction.identity(ws)
    assert evidence["version"] == "2.0.0"
    assert transaction.loader.lifecycle.get_instance(KEY).config == {
        "custom": "saved",
    }
    assert load_config().plugins[KEY] == {"enabled": True, "custom": "saved"}
    assert len(rows(transaction.network, "connected")) == 1


@pytest.mark.asyncio
async def test_config_save_failure_restores_runtime_and_recovery_file(
    transaction,
    monkeypatch,
):
    from qwenpaw.config.utils import load_config
    from qwenpaw.plugins.settings import persist_plugin_settings

    ws = await transaction.workspace("config-rollback")
    recovery = ws.workspace_dir / "channel_state" / "reply.json"
    recovery.parent.mkdir()
    recovery.write_text('{"reply":"sent"}')
    persist_plugin_settings(KEY, enabled=True, config={"custom": "old"})
    await transaction.seed(config={"custom": "old"})
    old, before = await transaction.identity(ws)

    def failed_write(*_args, **_kwargs):
        raise PermissionError("controlled config persistence failure")

    monkeypatch.setattr(
        "qwenpaw.plugins.settings.persist_plugin_settings",
        failed_write,
    )
    report = await transaction.loader.lifecycle.update_config(
        KEY,
        {"custom": "new"},
    )
    assert not report.ok and not report.needs_restart
    assert "controlled config persistence failure" in " ".join(report.errors)
    restored, after = await transaction.identity(ws)
    assert after["pid"] != before["pid"] and not psutil.pid_exists(
        before["pid"],
    )
    assert restored._launch_spec.generation >= old._launch_spec.generation + 2
    assert len(rows(transaction.network, "connected")) == 3
    assert transaction.loader.lifecycle.get_instance(KEY).config == {
        "custom": "old",
    }
    assert load_config().plugins[KEY] == {"enabled": True, "custom": "old"}
    assert recovery.read_text() == '{"reply":"sent"}'


@pytest.mark.asyncio
@pytest.mark.parametrize("committed", [False, True])
async def test_boot_recovery_uses_marker_commit_and_never_downloads(
    transaction,
    monkeypatch,
    committed,
):
    from qwenpaw.plugins import updates
    from qwenpaw.plugins.updates import marker_path, write_updating_marker

    ws = await transaction.workspace("recovery")
    target = transaction.artifact(installed_source=True)
    backup = target.with_name(".c5-old-backup")
    target.rename(backup)
    shutil.copytree(transaction.artifact("2.0.0"), target)
    write_updating_marker(
        KEY,
        backup_path=backup,
        target_path=target,
        status="committed" if committed else "prepared",
    )

    def no_download(*_args, **_kwargs):
        raise AssertionError("Recovery attempted dependency acquisition")

    monkeypatch.setattr(
        transaction.loader,
        "_run_subprocess_with_streaming_log",
        no_download,
    )
    remove = updates.safe_remove

    def blocked_remove(path, *, purpose):
        if Path(path) == (backup if committed else target):
            raise PermissionError("controlled recovery cleanup denied")
        return remove(path, purpose=purpose)

    monkeypatch.setattr(updates, "safe_remove", blocked_remove)
    await transaction.loader.load_all_plugins(activate=True)
    assert backup.exists() and marker_path(KEY).exists()
    if committed:
        _, live = await transaction.identity(ws)
        assert live["version"] == "2.0.0"
        assert any(
            "controlled recovery cleanup denied" in item
            for item in transaction.loader.get_loaded_plugin(KEY).diagnostics
        )
    else:
        assert await ws.channel_manager.get_channel(KEY) is None
        assert not rows(transaction.network, "connected")
        assert transaction.loader.get_loaded_plugin(KEY).status == "failed"
    monkeypatch.setattr(updates, "safe_remove", remove)
    if committed:
        updates.recover_interrupted_updates()
        _, after = await transaction.identity(ws)
        assert after["pid"] == live["pid"]
    else:
        await transaction.loader.load_all_plugins(activate=True)
    _, evidence = await transaction.identity(ws)
    assert evidence["version"] == ("2.0.0" if committed else "1.0.0")
    assert Path(evidence["source"]).is_relative_to(target)
    assert not backup.exists() and not marker_path(KEY).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["prepared", "committed"])
async def test_cancel_update_restores_only_before_commit(
    transaction,
    monkeypatch,
    phase,
):
    from qwenpaw.plugins.updates import marker_path

    ws = await transaction.workspace("cancel-" + phase)
    await transaction.seed()
    old, before = await transaction.identity(ws)
    source = transaction.artifact("2.0.0")
    entered = asyncio.Event()
    hook = (
        "_swap_plugin_dir"
        if phase == "prepared"
        else "_finish_committed_reload"
    )
    original = getattr(transaction.loader, hook)

    async def paused(*args, **kwargs):
        if phase == "prepared":
            result = await original(*args, **kwargs)
            entered.set()
            await asyncio.Event().wait()
            return result
        entered.set()
        await asyncio.Event().wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(transaction.loader, hook, paused)
    update = asyncio.create_task(
        transaction.loader.lifecycle.reload(KEY, new_source=source),
    )
    try:
        await eventually(lambda: entered.is_set() or update.done())
        assert (
            entered.is_set()
        ), "Update refused before the transaction boundary"
        marker = json.loads(marker_path(KEY).read_text())
        assert marker["status"] == phase
        update.cancel()
        with pytest.raises(asyncio.CancelledError):
            await update
        fresh, after = await transaction.identity(ws)
        assert not psutil.pid_exists(before["pid"])
        assert fresh._launch_spec.generation > old._launch_spec.generation
        assert after["version"] == (
            "1.0.0" if phase == "prepared" else "2.0.0"
        )
        assert (
            json.loads((transaction.installed / "plugin.json").read_text())[
                "version"
            ]
            == after["version"]
        )
    finally:
        monkeypatch.setattr(transaction.loader, hook, original)
        if not update.done():
            update.cancel()
            await asyncio.gather(update, return_exceptions=True)


@pytest.mark.asyncio
async def test_no_record_uninstall_respects_owner_and_workspace_assets(
    transaction,
):
    from qwenpaw.config.utils import load_config
    from qwenpaw.plugins.settings import persist_plugin_settings

    ws = await transaction.workspace("retained-owner")
    assets = [
        ws.workspace_dir / name
        for name in (
            "credentials.json",
            "chats.json",
            "media.bin",
            "reply-recovery.json",
        )
    ]
    for path in assets:
        path.write_text("preserve:" + path.name)
    persist_plugin_settings(
        KEY,
        enabled=True,
        config={"custom": "keep-until-uninstall"},
    )
    await transaction.seed()
    channel, before = await transaction.identity(ws)
    record = transaction.loader._loaded_plugins.pop(KEY)
    instance = transaction.loader.lifecycle._instances.pop(KEY)
    try:
        report = await transaction.loader._uninstall_without_instance(KEY)
        assert not report.quiescent and report.needs_restart
        assert transaction.installed.exists()
        assert KEY in load_config().plugins
        assert psutil.pid_exists(before["pid"])
        assert (
            channel_owner(
                transaction.registry,
                channel._launch_spec.instance_id,
            )
            is channel
        )
    finally:
        transaction.loader._loaded_plugins[KEY] = record
        transaction.loader.lifecycle._instances[KEY] = instance
    report = await transaction.loader.unload_plugin(KEY, delete_files=True)
    assert report.quiescent and not transaction.installed.exists()
    assert KEY not in load_config().plugins
    assert not psutil.pid_exists(before["pid"])
    assert all(path.read_text() == "preserve:" + path.name for path in assets)


@pytest.mark.asyncio
async def test_shutdown_stops_real_worker_and_preserves_installed_code(
    transaction,
):
    from qwenpaw.config.utils import load_config
    from qwenpaw.plugins.lifecycle import UnloadMode
    from qwenpaw.plugins.settings import persist_plugin_settings

    ws = await transaction.workspace("shutdown")
    persist_plugin_settings(KEY, enabled=True, config={"custom": "keep"})
    await transaction.seed()
    _, before = await transaction.identity(ws)
    reports = await transaction.loader.lifecycle.unload_all(
        UnloadMode.SHUTDOWN,
    )
    assert all(report.quiescent for report in reports)
    assert not psutil.pid_exists(before["pid"])
    assert (transaction.installed / KEY / "c5_driver.py").exists()
    assert load_config().plugins[KEY] == {"enabled": True, "custom": "keep"}


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_instance", [False, True])
async def test_shutdown_drains_registry_owner_without_loader_record(
    transaction,
    missing_instance,
):
    from qwenpaw.config.utils import load_config
    from qwenpaw.plugins.lifecycle import UnloadMode
    from qwenpaw.plugins.settings import persist_plugin_settings

    ws = await transaction.workspace("shutdown-retained")
    asset = ws.workspace_dir / "reply-recovery.json"
    asset.write_text('{"reply":"preserve"}')
    persist_plugin_settings(KEY, enabled=True, config={"custom": "keep"})
    await transaction.seed()
    channel, before = await transaction.identity(ws)
    record = transaction.loader._loaded_plugins.pop(KEY)
    instance = transaction.loader.lifecycle.get_instance(KEY)
    if missing_instance:
        transaction.loader.lifecycle._instances.pop(KEY)
    try:
        assert transaction.registry.has_channel_owners(KEY)
        reports = await transaction.loader.lifecycle.unload_all(
            UnloadMode.SHUTDOWN,
        )
        assert reports, "Shutdown did not enumerate the retained owner"
        assert any(report.plugin_id == KEY for report in reports)
        assert all(report.quiescent for report in reports)
        assert not psutil.pid_exists(before["pid"])
        assert not transaction.registry.has_channel_owners(KEY)
        assert await ws.channel_manager.get_channel(KEY) is not channel
        assert (transaction.installed / KEY / "c5_driver.py").exists()
        assert load_config().plugins[KEY] == {
            "enabled": True,
            "custom": "keep",
        }
        assert asset.read_text() == '{"reply":"preserve"}'
    finally:
        transaction.loader._loaded_plugins[KEY] = record
        transaction.loader.lifecycle._instances[KEY] = instance


@pytest.mark.asyncio
async def test_disabled_no_record_commit_survives_cleanup_cancellation(
    transaction,
    monkeypatch,
):
    from qwenpaw.config.utils import load_config
    from qwenpaw.plugins.settings import persist_plugin_settings
    from qwenpaw.plugins.updates import (
        mark_update_committed,
        update_is_committed,
    )

    persist_plugin_settings(KEY, enabled=False, config={"custom": "keep"})
    first = await transaction.loader.load_plugin_from_path(
        transaction.artifact(),
    )
    assert not first.enabled and first.status == "inactive"
    assert transaction.loader.get_loaded_plugin(KEY) is None
    assert transaction.loader.lifecycle.get_instance(KEY) is None
    commit_seen = False

    async def cancel_after_commit(plugin_id, _backup):
        nonlocal commit_seen
        mark_update_committed(plugin_id)
        assert update_is_committed(plugin_id)
        commit_seen = True
        raise asyncio.CancelledError

    monkeypatch.setattr(
        transaction.loader,
        "_finish_committed_reload",
        cancel_after_commit,
    )
    with pytest.raises(asyncio.CancelledError):
        await transaction.loader.load_plugin_from_path(
            transaction.artifact("2.0.0"),
            force=True,
        )
    assert commit_seen
    assert (
        json.loads((transaction.installed / "plugin.json").read_text())[
            "version"
        ]
        == "2.0.0"
    )
    assert load_config().plugins[KEY] == {"enabled": False, "custom": "keep"}
    assert not rows(transaction.network)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["install", "repair"])
async def test_existing_http_entrypoints_acquire_validated_local_wheels(
    transaction,
    monkeypatch,
    tmp_path,
    operation,
):
    from starlette.requests import Request
    from qwenpaw.app.routers.plugins import (
        _load_plugin_with_optional_force_reinstall,
        repair_plugin_dependencies,
    )
    from qwenpaw.config.utils import load_config
    from qwenpaw.plugins.settings import persist_plugin_settings

    local = wheelhouse(tmp_path / "wheelhouse")
    monkeypatch.setattr(
        "qwenpaw.config.utils.get_plugins_dir",
        lambda: transaction.installed.parent,
    )
    ws = await transaction.workspace("http-" + operation)
    retained = None
    before = None
    if operation == "repair":
        retained = await transaction.seed()
        channel, before = await transaction.identity(ws)
        retained.status = "failed"
        transaction.loader.lifecycle.get_instance(KEY).mark_failed(
            "controlled retained runtime failure",
        )
        source = transaction.installed
    else:
        source = transaction.artifact()
    (source / "requirements.txt").write_text("c5-transaction-sdk==1.0\n")
    driver = source / KEY / "c5_driver.py"
    driver.write_text(driver.read_text() + "\nimport c5_transaction_sdk\n")
    request = Request(
        {
            "type": "http",
            "app": NS(state=NS(plugin_loader=transaction.loader)),
        },
    )

    def local_wheel(command, *, timeout, plugin_id):
        assert plugin_id == KEY
        assert command[1:5] == ["-I", "-m", "pip", "wheel"]
        assert not {"install", "download", "--dest", "--target"}.intersection(
            command,
        )
        staging = Path(command[command.index("--wheel-dir") + 1])
        assert staging != transaction.site
        assert Path(command[command.index("--constraint") + 1]).is_file()
        assert Path(command[command.index("-r") + 1]).read_text() == (
            "c5-transaction-sdk==1.0\n"
        )
        return subprocess.run(
            [*command, "--no-index", "--find-links", str(local)],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )

    monkeypatch.setattr(
        transaction.loader,
        "_run_subprocess_with_streaming_log",
        local_wheel,
    )
    if operation == "repair":
        persist_plugin_settings(
            KEY,
            enabled=False,
            config={"custom": "repair-retains-disabled"},
        )
        hold = Path(str(transaction.network) + ".hold-all")
        hold.touch()
        tree = channel.channel_process._tree
        signal = tree.signal
        monkeypatch.setattr(
            tree,
            "signal",
            lambda **_kwargs: None,
        )
        try:
            payload = await repair_plugin_dependencies(KEY, request)
            assert payload["status"] == "failed"
            assert "repaired" not in payload["message"].lower()
            assert transaction.loader.get_loaded_plugin(KEY) is retained
            assert (
                channel_owner(
                    transaction.registry,
                    channel._launch_spec.instance_id,
                )
                is channel
            )
            assert psutil.pid_exists(before["pid"])
            assert (
                source.exists()
                and (transaction.site / "c5_transaction_sdk.py").exists()
            )
        finally:
            hold.unlink(missing_ok=True)
            monkeypatch.setattr(tree, "signal", signal)
        payload = await repair_plugin_dependencies(KEY, request)
        assert payload["status"] == "inactive" and not payload["enabled"]
        assert "channel_validation_passed" in payload["diagnostics"]
        assert len(rows(transaction.network, "constructed")) == 1
        assert len(rows(transaction.network, "connected")) == 1
        assert not psutil.pid_exists(before["pid"])
        assert load_config().plugins[KEY] == {
            "enabled": False,
            "custom": "repair-retains-disabled",
        }
    else:
        record = await _load_plugin_with_optional_force_reinstall(
            transaction.loader,
            request,
            source,
            force=False,
        )
        assert record.status == "active" and record.enabled
        channel, evidence = await transaction.identity(ws)
        assert evidence["version"] == "1.0.0"
        assert (
            "c5-transaction-sdk"
            in channel.channel_process.dependency_snapshot.distributions
        )
    assert (
        transaction.site / "c5_transaction_sdk.py"
    ).read_text() == "VALUE = 'offline-c5-sdk'\n"
    assert (
        transaction.site / "c5_transaction_sdk-1.0.dist-info" / "METADATA"
    ).exists()
