# -*- coding: utf-8 -*-
"""继承型 Agent 全局模型重载的文件保真集成测试。"""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from qwenpaw.app.utils import reload_inherited_agents
from qwenpaw.config.config import (
    AgentProfileConfig,
    AgentProfileRef,
    ModelSlotConfig,
)


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_inherited_reload_keeps_all_agent_json_bytes_unchanged(
    tmp_path,
) -> None:
    profiles = {}
    paths = {}
    configs = {
        "inherited": AgentProfileConfig(
            id="inherited",
            name="Inherited",
            active_model=None,
        ),
        "explicit": AgentProfileConfig(
            id="explicit",
            name="Explicit",
            active_model=ModelSlotConfig(
                provider_id="global",
                model="fixed-model",
            ),
        ),
    }
    for agent_id, agent_config in configs.items():
        workspace = tmp_path / agent_id
        workspace.mkdir()
        path = workspace / "agent.json"
        path.write_text(
            json.dumps(
                agent_config.model_dump(exclude_none=True),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        profiles[agent_id] = AgentProfileRef(
            id=agent_id,
            workspace_dir=str(workspace),
        )
        paths[agent_id] = path

    root_config = SimpleNamespace(
        agents=SimpleNamespace(profiles=profiles),
    )
    manager = SimpleNamespace(
        agents={"inherited": object(), "explicit": object()},
        reload_agent=AsyncMock(return_value=True),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=manager),
        ),
    )
    before = {agent_id: _sha256(path) for agent_id, path in paths.items()}

    with patch("qwenpaw.config.utils.load_config", return_value=root_config):
        result = await reload_inherited_agents(request)

    after = {agent_id: _sha256(path) for agent_id, path in paths.items()}
    assert result.applied_agent_ids == ["inherited"]
    assert result.pending_reload_agent_ids == []
    assert before == after
    manager.reload_agent.assert_awaited_once_with("inherited")
