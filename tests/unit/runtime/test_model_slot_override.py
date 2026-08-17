# -*- coding: utf-8 -*-
"""Per-request model selection in the shared runtime builder."""

from types import SimpleNamespace

import pytest

from qwenpaw.config.config import ModelSlotConfig
from qwenpaw.runtime.builder import AgentBuilder


class _ModelBuildReached(Exception):
    """Stop the build after proving the override reached model creation."""


@pytest.mark.parametrize(
    ("agent_model", "override"),
    [
        (
            None,
            ModelSlotConfig(provider_id="openai", model="gpt-4o-mini"),
        ),
        (
            ModelSlotConfig(provider_id="default", model="default-model"),
            ModelSlotConfig(),
        ),
    ],
    ids=["valid-request-override", "invalid-override-agent-fallback"],
)
@pytest.mark.asyncio
async def test_request_model_selection_does_not_require_a_global_default(
    monkeypatch,
    tmp_path,
    agent_model,
    override,
):
    agent_config = SimpleNamespace(
        id="default",
        active_model=agent_model,
        coding_mode=None,
    )
    ctx = SimpleNamespace(
        agent_id="default",
        request=SimpleNamespace(model_slot_override=override),
        workspace_dir=str(tmp_path),
        workspace=None,
        extras={},
    )
    builder = AgentBuilder()

    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: agent_config,
    )
    monkeypatch.setattr(
        "qwenpaw.providers.provider_manager.ProviderManager.get_instance",
        lambda: SimpleNamespace(get_active_model=lambda: None),
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.ensure_skills_initialized",
        lambda _workspace_dir: None,
    )
    monkeypatch.setattr(
        "qwenpaw.agents.skill_system.resolve_effective_skills",
        lambda _workspace_dir, _channel: [],
    )
    monkeypatch.setattr(builder, "_build_request_context", lambda _ctx: {})
    monkeypatch.setattr(
        builder,
        "_apply_request_project",
        lambda config, _request_context: config,
    )
    monkeypatch.setattr(builder, "_init_governor", lambda *_args: None)
    monkeypatch.setattr(builder, "_get_local_workspace", lambda _ctx: None)
    monkeypatch.setattr(
        builder,
        "_collect_coding_mode_tools",
        lambda *_args: [],
    )
    monkeypatch.setattr(
        builder,
        "_collect_visual_compression_tools",
        lambda *_args: [],
    )

    async def _collect_driver_tools(*_args):
        return [], []

    monkeypatch.setattr(
        builder,
        "_collect_driver_tools_and_prompts",
        _collect_driver_tools,
    )

    def _build_model(_agent_config, model_slot_override=None):
        assert model_slot_override is override
        raise _ModelBuildReached

    monkeypatch.setattr(builder, "build_model", _build_model)

    with pytest.raises(_ModelBuildReached):
        await builder.build(ctx)
