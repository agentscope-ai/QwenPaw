# -*- coding: utf-8 -*-
"""全局模型变更对继承型 Agent 的受控重载测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.app.routers.providers import set_active_model
from qwenpaw.app.utils import reload_inherited_agents
from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.identity.models import PlatformRole


def _request(manager):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(multi_agent_manager=manager),
        ),
    )


def _member_request(manager):
    request = _request(manager)
    request.state = SimpleNamespace(
        actor=ActorContext(
            user_id=uuid4(),
            actor_type=ActorType.USER,
            platform_role=PlatformRole.MEMBER,
            admin_mode=False,
            request_id="test-model-member",
        ),
    )
    return request


@pytest.mark.asyncio
async def test_member_cannot_change_global_model() -> None:
    provider_manager = MagicMock()
    provider_manager.activate_model = AsyncMock()

    with (
        patch(
            "qwenpaw.app.routers.providers.is_multi_user_enabled",
            return_value=True,
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await set_active_model(
            request=_member_request(SimpleNamespace(agents={})),
            manager=provider_manager,
            body=SimpleNamespace(
                scope="global",
                provider_id="global",
                model="new-model",
                agent_id=None,
            ),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "forbidden"
    provider_manager.activate_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_global_model_change_reloads_only_loaded_inherited_agents() -> None:
    runtime_manager = SimpleNamespace(
        agents={"inherited": object(), "explicit": object()},
        reload_agent=AsyncMock(return_value=True),
    )
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

    with patch(
        "qwenpaw.app.utils.load_agent_config",
        side_effect=lambda agent_id: configs[agent_id],
    ):
        result = await reload_inherited_agents(_request(runtime_manager))

    assert result.applied_agent_ids == ["inherited"]
    assert result.pending_reload_agent_ids == []
    runtime_manager.reload_agent.assert_awaited_once_with("inherited")


@pytest.mark.asyncio
async def test_partial_reload_failure_returns_retryable_agent_ids() -> None:
    async def reload(agent_id: str) -> bool:
        if agent_id == "failed":
            raise RuntimeError("reload failed")
        return agent_id == "applied"

    runtime_manager = SimpleNamespace(
        agents={
            "applied": object(),
            "failed": object(),
            "not-running": object(),
        },
        reload_agent=AsyncMock(side_effect=reload),
    )

    with patch(
        "qwenpaw.app.utils.load_agent_config",
        side_effect=lambda agent_id: AgentProfileConfig(
            id=agent_id,
            name=agent_id,
            active_model=None,
        ),
    ):
        result = await reload_inherited_agents(_request(runtime_manager))

    assert result.applied_agent_ids == ["applied"]
    assert result.pending_reload_agent_ids == ["failed", "not-running"]


@pytest.mark.asyncio
async def test_global_change_returns_reload_summary_without_writing_agent_json() -> None:
    provider_manager = MagicMock()
    provider_manager.activate_model = AsyncMock()
    provider_manager.get_active_model.return_value = ModelSlotConfig(
        provider_id="global",
        model="new-model",
    )
    provider_manager.get_provider.return_value = None
    request = _request(
        SimpleNamespace(
            agents={"inherited": object()},
            reload_agent=AsyncMock(return_value=True),
        ),
    )

    with (
        patch(
            "qwenpaw.app.routers.providers.reload_inherited_agents",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    applied_agent_ids=["inherited"],
                    pending_reload_agent_ids=[],
                ),
            ),
        ) as reload_agents,
        patch("qwenpaw.app.routers.providers.save_agent_config") as save_agent,
    ):
        result = await set_active_model(
            request=request,
            manager=provider_manager,
            body=SimpleNamespace(
                scope="global",
                provider_id="global",
                model="new-model",
                agent_id=None,
            ),
        )

    assert result.active_llm == ModelSlotConfig(
        provider_id="global",
        model="new-model",
    )
    assert result.applied_agent_ids == ["inherited"]
    assert result.pending_reload_agent_ids == []
    reload_agents.assert_awaited_once_with(request)
    save_agent.assert_not_called()


@pytest.mark.asyncio
async def test_global_change_keeps_saved_model_when_reload_is_pending() -> None:
    provider_manager = MagicMock()
    provider_manager.activate_model = AsyncMock()
    provider_manager.get_active_model.return_value = ModelSlotConfig(
        provider_id="global",
        model="new-model",
    )
    provider_manager.get_provider.return_value = None
    request = _request(SimpleNamespace(agents={}))

    with patch(
        "qwenpaw.app.routers.providers.reload_inherited_agents",
        new=AsyncMock(
            return_value=SimpleNamespace(
                applied_agent_ids=["healthy"],
                pending_reload_agent_ids=["retry-me"],
            ),
        ),
    ):
        result = await set_active_model(
            request=request,
            manager=provider_manager,
            body=SimpleNamespace(
                scope="global",
                provider_id="global",
                model="new-model",
                agent_id=None,
            ),
        )

    provider_manager.activate_model.assert_awaited_once_with(
        "global",
        "new-model",
    )
    assert result.active_llm.model == "new-model"
    assert result.applied_agent_ids == ["healthy"]
    assert result.pending_reload_agent_ids == ["retry-me"]
