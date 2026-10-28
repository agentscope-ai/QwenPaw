# -*- coding: utf-8 -*-
# Imported pytest fixtures are explicit re-exports for fixture discovery.
# pylint: disable=redefined-outer-name
from pathlib import Path

import pytest

from qwenpaw.app.workspace import Workspace
from qwenpaw.drivers.contracts import DriverCard
from qwenpaw.drivers.storage import card_path, dump_card
from tests.integration.driver_mcp_fakes import (
    mcp_runtime_host as _mcp_runtime_host,
    patch_mcp_runtime_clients,
)

mcp_runtime_host = _mcp_runtime_host


def _mcp_card(name: str) -> DriverCard:
    return DriverCard(
        name=name,
        protocol="mcp",
        endpoint={"transport": "stdio", "command": "fake-mcp"},
    )


async def _start_driver_service(workspace: Workspace, host):
    # pylint: disable=protected-access
    host._workspaces[workspace.agent_id] = workspace
    descriptor = workspace._service_manager.descriptors["driver_manager"]
    await workspace._service_manager._start_service(descriptor)
    host.test_driver_managers.append(workspace.driver_manager)
    return workspace.driver_manager


async def _active_driver_names(manager) -> list[str]:
    infos = await manager.list_drivers()
    return [info.name for info in infos if info.status == "active"]


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.p1
async def test_driver_manager_uses_per_workspace_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mcp_runtime_host,
) -> None:
    patch_mcp_runtime_clients(monkeypatch)
    workspace_one = Workspace("agent-one", str(tmp_path / "one"))
    workspace_two = Workspace("agent-two", str(tmp_path / "two"))
    dump_card(
        _mcp_card("driver-one"),
        card_path(
            workspace_one.workspace_dir / "drivers",
            "driver-one",
            protocol="mcp",
        ),
    )
    dump_card(
        _mcp_card("driver-two"),
        card_path(
            workspace_two.workspace_dir / "drivers",
            "driver-two",
            protocol="mcp",
        ),
    )

    manager_one = await _start_driver_service(workspace_one, mcp_runtime_host)
    manager_two = await _start_driver_service(workspace_two, mcp_runtime_host)

    assert await _active_driver_names(manager_one) == ["driver-one"]
    assert await _active_driver_names(manager_two) == ["driver-two"]
