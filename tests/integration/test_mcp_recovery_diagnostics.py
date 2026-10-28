# -*- coding: utf-8 -*-
"""Real upgrade coordinator outcomes remain visible through passive status."""

# The imported autouse fixture forbids network and installer activity.
# pylint: disable=protected-access,unused-import
import json
from types import SimpleNamespace

import pytest

from qwenpaw.drivers.capabilities import DriverInvocation
from qwenpaw.app.mcp.plugin_service import plugin_state
from qwenpaw.app.mcp_plugin_upgrade import MARKER, prepare_startup_plugins
from qwenpaw.plugins.testing import PluginTestHost
from tests.integration.test_mcp_plugin_upgrade import (
    SECRET,
    seed,
    inventory,
    bytes_under,
    prohibit_network_and_installers,  # noqa: F401
)
from tests.unit.plugins.mcp.fixtures import card


async def prepare(host, root):
    outcome = await prepare_startup_plugins(
        host._loader,
        host._workspace_manager,
        app=host._http_app,
        snapshot=inventory(root),
    )
    await host._loader.activate_all_loaded()
    return outcome


async def status(host, workspace="test"):
    request = SimpleNamespace(
        app=host._http_app,
        state=SimpleNamespace(agent_id=workspace),
        headers={"X-Agent-Id": workspace},
    )
    return await plugin_state(request)


async def passive_status(host, root, workspace="test"):
    before = bytes_under(root)
    result = await status(host, workspace)
    assert bytes_under(root) == before
    assert not host._workspaces
    assert SECRET not in json.dumps(result)
    assert "snapshot" not in result and "config" not in result
    return result


async def test_invalid_marker_reaches_status_and_real_retry_clears_error(
    tmp_path,
):
    root = tmp_path / "host"
    seed(
        root,
        [("test", root / "workspaces/test", {}, [card(enabled=False)], True)],
    )
    marker = root / "plugins" / MARKER
    marker.parent.mkdir(parents=True)
    marker.write_text('{"private":"' + SECRET)
    damaged = marker.read_bytes()
    async with PluginTestHost(root) as host:
        result = await prepare(host, root)
        assert result.status == "needs_review"
        response = await passive_status(host, root)
        assert "invalid_upgrade_record" in response["diagnostics"]
        assert response["upgrade"]["status"] == "needs_review"
        assert marker.read_bytes() == damaged
        # Retry the production coordinator against repaired on-disk evidence.
        marker.unlink()
        assert (await prepare(host, root)).status == "installed"
        response = await passive_status(host, root)
        assert response["status"] == "active"
        assert "invalid_upgrade_record" not in response["diagnostics"]
        assert response["upgrade"]["status"] == "installed"


@pytest.mark.parametrize("failure", ["dependencies", "copy"])
async def test_preload_offline_failure_is_sanitized_visible_and_retryable(
    tmp_path,
    monkeypatch,
    failure,
):
    from qwenpaw.plugins.loader import PluginLoader
    from qwenpaw.plugins.dependency_gate import GateDecision

    root = tmp_path / "host"
    workspace = root / "workspaces/test"
    seed(root, [("test", workspace, {}, [card(enabled=False)], True)])
    preserved = bytes_under(workspace)
    async with PluginTestHost(root) as host:
        with monkeypatch.context() as patch:
            if failure == "dependencies":

                async def unavailable(
                    _self,
                    _path,
                    _id,
                    *,
                    allow_install=False,
                ):
                    assert allow_install is False
                    return GateDecision(
                        allow_install=False,
                        already_satisfied=False,
                        missing=[SECRET],
                        reason="credential error " + SECRET,
                    )

                patch.setattr(
                    PluginLoader,
                    "_ensure_dependencies_installed",
                    unavailable,
                )
            else:

                async def fail_copy(*_args, **_kwargs):
                    raise OSError("credential error " + SECRET)

                patch.setattr(host._loader, "install_plugin_files", fail_copy)
            result = await prepare(host, root)
        assert result.status == "failed"
        assert host._loader.get_loaded_plugin("qwenpaw-mcp") is None
        response = await passive_status(host, root)
        assert (
            "offline_upgrade_failed_check_dependencies_and_storage"
            in response["diagnostics"]
        )
        assert response["upgrade"]["status"] == "failed"
        assert bytes_under(workspace) == preserved
        from qwenpaw.app.routers.mcp_plugin import install_mcp_plugin

        retried = await install_mcp_plugin(
            SimpleNamespace(
                app=host._http_app,
                state=SimpleNamespace(agent_id="test"),
                headers={"X-Agent-Id": "test"},
            ),
        )
        assert retried["status"] == "active"
        response = await passive_status(host, root)
        assert response["status"] == "active"
        assert not response["diagnostics"]


async def test_blocked_workspace_is_visible_beside_healthy_global_plugin(
    tmp_path,
):
    root = tmp_path / "host"
    blocked = root / "workspaces/blocked"
    seed(
        root,
        [
            (
                "safe",
                root / "workspaces/safe",
                {},
                [card(enabled=False)],
                True,
            ),
            (
                "blocked",
                blocked,
                {"mcp": {"unknown": SECRET}},
                [card(enabled=False)],
                True,
            ),
        ],
    )
    preserved = bytes_under(blocked)
    async with PluginTestHost(root) as host:
        outcome = await prepare(host, root)
        assert outcome.status == "installed"
        response = await passive_status(host, root, "blocked")
        assert response["status"] == "active"
        assert response["workspace"]["id"] == "blocked"
        assert response["workspace"]["status"] == "needs_review"
        assert response["workspace"]["eligible"] is False
        assert "workspace_needs_review" in response["workspace"]["diagnostics"]
        healthy = await passive_status(host, root, "safe")
        assert healthy["workspace"]["eligible"] is True
        assert not healthy["workspace"]["diagnostics"]
        assert bytes_under(blocked) == preserved


@pytest.mark.parametrize("off", [False, True])
async def test_ordinary_unused_and_explicit_off_are_not_blocked_recovery(
    tmp_path,
    off,
):
    root = tmp_path / "host"
    seed(
        root,
        [("test", root / "workspaces/test", {}, [], True)],
        plugins={"qwenpaw-mcp": {"enabled": False}} if off else None,
    )
    async with PluginTestHost(root) as host:
        assert (await prepare(host, root)).status == "skipped"
        response = await passive_status(host, root)
        assert not response["diagnostics"]
        assert response["workspace"]["status"] == "unused"
        assert not response["workspace"]["diagnostics"]


async def test_loaded_record_diagnostics_never_expose_raw_errors(tmp_path):
    root = tmp_path / "host"
    seed(
        root,
        [("test", root / "workspaces/test", {}, [card(enabled=False)], True)],
    )
    async with PluginTestHost(root) as host:
        assert (await prepare(host, root)).status == "installed"
        record = host._loader.get_loaded_plugin("qwenpaw-mcp")
        record.diagnostics.append("credential parser error " + SECRET)
        response = await passive_status(host, root)
        assert response["status"] == "active"
        assert "plugin_runtime_failed" not in response["diagnostics"]
        record.status = "failed"
        response = await passive_status(host, root)
        assert response["status"] == "failed"
        assert "plugin_runtime_failed" in response["diagnostics"]


async def assert_recovered_live_runtime(
    host,
    peer,
    blocked_runtime,
    safe_runtime,
    still_runtime,
    still_before,
    healthy_ownership,
    source_enabled,
):
    healthy_manager, healthy_watcher, healthy_task = healthy_ownership
    # Eligibility alone cannot prove a live facade actually recovered.
    if source_enabled:
        assert blocked_runtime.manager is not None
    else:
        assert blocked_runtime.manager is None
    assert blocked_runtime.watcher is not None
    assert blocked_runtime.watcher._poll_interval == 2.0
    assert blocked_runtime.watcher._task is not None
    assert not blocked_runtime.watcher._task.done()
    expected_opens = ["synthetic-safe"]
    if source_enabled:
        expected_opens.append("synthetic-blocked")
    assert [
        parameters.command for _, parameters in peer.opens
    ] == expected_opens
    assert set(host._workspaces) == {
        "safe",
        "blocked",
        "still-blocked",
    }
    assert still_runtime.manager is None
    assert still_runtime.watcher is None
    assert bytes_under(still_runtime._workspace.workspace_dir) == still_before
    assert not (await status(host, "still-blocked"))["workspace"]["eligible"]
    saved = await blocked_runtime.card_store.load(
        "blocked",
        protocol="mcp",
    )
    assert saved.enabled is source_enabled
    assert safe_runtime.manager is healthy_manager
    assert safe_runtime.watcher is healthy_watcher
    assert healthy_watcher._task is healthy_task
    assert not peer.closes
    if source_enabled:
        result = await blocked_runtime.invoke_capability(
            DriverInvocation(
                "driver://mcp/blocked/tools/echo#invoke",
                {"recovered": True},
                {
                    "agent_id": "blocked",
                    "session_id": "test",
                    "user_id": "alice",
                },
            ),
        )
        assert result.ok and result.value.content[0].text == "ok"
        assert peer.calls == [
            ("echo", {}),
            ("echo", {"recovered": True}),
        ]
    else:
        assert await blocked_runtime.list_capabilities() == []
        assert peer.calls == [("echo", {})]


@pytest.mark.parametrize("source_enabled", [True, False])
async def test_real_retry_recovers_live_runtime_without_reopening_sibling(
    tmp_path,
    monkeypatch,
    source_enabled,
):
    from qwenpaw.app.routers.mcp_plugin import install_mcp_plugin
    from qwenpaw.plugins._drivers import workspace_is_current
    from tests.unit.app.test_lazy_driver_runtime import start_runtime
    from tests.unit.plugins.mcp.fixtures import Peer

    root = tmp_path / "host"
    blocked_dir = root / "workspaces/blocked"
    safe_card, blocked_card = card("safe"), card(
        "blocked",
        enabled=source_enabled,
    )
    safe_card["endpoint"]["command"] = "synthetic-safe"
    blocked_card["endpoint"]["command"] = "synthetic-blocked"
    seed(
        root,
        [
            ("safe", root / "workspaces/safe", {}, [safe_card], True),
            (
                "blocked",
                blocked_dir,
                {"mcp": {"unknown": SECRET}},
                [blocked_card],
                True,
            ),
            (
                "dormant",
                root / "workspaces/dormant",
                {},
                [card("dormant")],
                True,
            ),
            (
                "still-blocked",
                root / "workspaces/still-blocked",
                {"mcp": {"unknown": SECRET}},
                [card("still-blocked")],
                True,
            ),
        ],
    )
    peer = Peer()
    peer.install(monkeypatch)
    async with PluginTestHost(root) as host:
        assert (await prepare(host, root)).status == "installed"
        safe_workspace = await host._workspace("safe")
        safe_runtime = await start_runtime(safe_workspace)
        blocked_workspace = await host._workspace("blocked")
        blocked_runtime = await start_runtime(blocked_workspace)
        still_workspace = await host._workspace("still-blocked")
        still_runtime = await start_runtime(still_workspace)
        still_before = bytes_under(still_workspace.workspace_dir)
        try:
            # These are the exact live instances visible to production guards.
            for workspace in (safe_workspace, blocked_workspace):
                assert workspace_is_current(host._loader.registry, workspace)
            assert blocked_runtime.manager is None
            assert blocked_runtime.watcher is None
            assert [parameters.command for _, parameters in peer.opens] == [
                "synthetic-safe",
            ]
            assert (await status(host, "blocked"))["workspace"]["status"] == (
                "needs_review"
            )
            healthy_manager = safe_runtime.manager
            healthy_watcher = safe_runtime.watcher
            healthy_task = healthy_watcher._task
            assert healthy_manager is not None
            assert healthy_watcher._poll_interval == 2.0
            assert healthy_task is not None and not healthy_task.done()
            first = await safe_runtime.invoke_capability(
                DriverInvocation(
                    "driver://mcp/safe/tools/echo#invoke",
                    {},
                    {
                        "agent_id": "safe",
                        "session_id": "test",
                        "user_id": "alice",
                    },
                ),
            )
            assert first.ok and first.value.content[0].text == "ok"

            repaired = json.loads((blocked_dir / "agent.json").read_text())
            repaired["mcp"] = {"clients": {}, "migration_version": 2}
            (blocked_dir / "agent.json").write_text(json.dumps(repaired))
            response = await install_mcp_plugin(
                SimpleNamespace(
                    app=host._http_app,
                    state=SimpleNamespace(agent_id="blocked"),
                    headers={"X-Agent-Id": "blocked"},
                ),
            )
            assert response["status"] == "active"
            assert response["workspace"]["eligible"] is True
            assert not response["workspace"]["diagnostics"]
            assert blocked_workspace.driver_manager is blocked_runtime
            await assert_recovered_live_runtime(
                host,
                peer,
                blocked_runtime,
                safe_runtime,
                still_runtime,
                still_before,
                (healthy_manager, healthy_watcher, healthy_task),
                source_enabled,
            )
        finally:
            await still_runtime.shutdown_all()
            await blocked_runtime.shutdown_all()
            await safe_runtime.shutdown_all()
        assert peer.closes == ["stdio"] * (2 if source_enabled else 1)
