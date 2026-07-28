# -*- coding: utf-8 -*-
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qwenpaw.app.workspace.service_factories import create_channel_service


@pytest.mark.asyncio
async def test_channel_service_prewarms_registry_in_thread(tmp_path: Path):
    channels = object()
    workspace = SimpleNamespace(
        _config=SimpleNamespace(channels=channels, language="zh"),
        _service_manager=SimpleNamespace(services={}),
        workspace_dir=tmp_path,
        stream_query=MagicMock(),
        agent_id="default",
    )
    manager = MagicMock(channels=[])
    approval_service = MagicMock()
    offload = AsyncMock(return_value={})

    with (
        patch(
            "qwenpaw.app.workspace.service_factories.asyncio.to_thread",
            offload,
        ),
        patch("qwenpaw.config.Config", return_value=MagicMock()),
        patch(
            "qwenpaw.config.load_config",
            return_value=SimpleNamespace(show_tool_details=True),
        ),
        patch(
            "qwenpaw.app.channels.manager.ChannelManager.from_config",
            return_value=manager,
        ),
        patch(
            "qwenpaw.app.channels.access_control.init_access_control_store",
        ),
        patch(
            "qwenpaw.app.approvals.get_approval_service",
            return_value=approval_service,
        ),
    ):
        result = await create_channel_service(workspace, None)

    assert result is manager
    offload.assert_awaited_once()
    assert offload.await_args.args[0].__name__ == "get_channel_registry"
    manager.set_workspace.assert_called_once_with(workspace)
