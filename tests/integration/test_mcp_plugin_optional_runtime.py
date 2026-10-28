# -*- coding: utf-8 -*-
"""Cold process acceptance uses the actual optional plugin and local peers."""
# Test-only observation of actual loader ownership.
# pylint: disable=protected-access

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

PROBE = (
    Path(__file__).resolve().parents[1]
    / "fixtures/mcp/optional_runtime_probe.py"
)


def cold(mode, root):
    result = subprocess.run(
        [sys.executable, "-B", str(PROBE), mode, str(root)],
        env=dict(os.environ),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / (mode + ".stdout.log")).write_text(result.stdout)
    (root / (mode + ".stderr.log")).write_text(result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads((root / "observations.json").read_text())


@pytest.mark.parametrize("fixture", ["none", "v0", "v1", "v2"])
def test_unused_cold_restart_twice_has_no_runtime(tmp_path, fixture):
    root = tmp_path / "host"
    for _ in range(2):
        observations = cold("unused-" + fixture, root)
        assert observations["manager_constructions"] == 0
        assert observations["snapshots"] == 0
        assert observations["project_mcp_imports"] == []
        assert observations["tasks_after_stop"] == []
        assert observations["children_after_stop"] == []
    assert (root / "fixture-before.json").is_file()


@pytest.mark.parametrize("transport", ["stdio", "sse", "streamable_http"])
def test_cold_plugin_real_transport_and_reconnect(tmp_path, transport):
    observations = cold("transport-" + transport, tmp_path / "host")
    assert observations["real_rpc"] and observations["reconnected"]
    assert observations["cross_workspace_disabled"]


def test_cold_legacy_conversion_real_call_and_deleted_source_restart(tmp_path):
    root = tmp_path / "host"
    first = cold("legacy", root)
    assert first["migration_version"] == 2 and first["real_rpc"]
    assert first["retained_tools"] == []
    (root / "workspaces/test/drivers/mcp/legacy.yaml").unlink()
    before = (root / "workspaces/test/agent.json").read_bytes()
    restarted = cold("legacy", root)
    assert restarted["deleted_not_resurrected"]
    assert (root / "workspaces/test/agent.json").read_bytes() == before


def test_cold_real_auth_middleware_management_and_local_oauth(tmp_path):
    result = cold("auth-oauth", tmp_path / "host")
    assert result["unauthenticated"] == 401
    assert result["authenticated_workspaces"] == ["test", "other"]
    assert result["manager_constructions"] == 0
    assert (
        result["local_oauth_exchange"] and result["cross_workspace_rejected"]
    )


def test_cold_mixed_transports_and_same_name_workspace_isolation(tmp_path):
    result = cold("mixed", tmp_path / "host")
    assert result["mixed_transports"] == ["stdio", "sse", "streamable_http"]
    assert result["same_name_workspace_isolation"]
    assert result["config_bytes_preserved"]


def test_cold_unused_workspace_later_installs_disable_enable_update_uninstall(
    tmp_path,
):
    result = cold("late-install", tmp_path / "host")
    assert result["same_workspace_late_install"]
    assert result["disable_enable_update"]
    assert result["uninstall_restart_preserves_intent_and_data"]


async def test_driver_plugin_rejected_by_sdk_1_0_before_entry_import(
    tmp_path,
    monkeypatch,
):
    from qwenpaw.plugins import SDKCompatibilityError, sdk_version
    from qwenpaw.plugins.testing import PluginTestHost
    from tests.unit.plugins.sdk_author_fixture import make_plugin

    marker = tmp_path / "entry-imported"
    plugin = make_plugin(
        tmp_path,
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).touch()\n"
        "class Plugin:\n"
        "    def register(self, context):\n"
        "        pass\n"
        "plugin = Plugin()\n",
        ["drivers"],
    )
    monkeypatch.setattr(sdk_version, "SDK_VERSION", "1.0.0")
    monkeypatch.setattr(
        sdk_version,
        "SDK_CAPABILITIES",
        sdk_version.SDK_CAPABILITIES - {"drivers"},
    )
    async with PluginTestHost(tmp_path / "host") as host:
        with pytest.raises(SDKCompatibilityError, match="drivers"):
            await host.load(plugin)
        assert not marker.exists()
        assert not host._loader.get_all_loaded_plugins()
