# -*- coding: utf-8 -*-
"""Tests for runtime prompt contributors."""

from types import SimpleNamespace

import pytest

from qwenpaw.config.config import AgentProfileConfig, ModelSlotConfig
from qwenpaw.providers.model_info import ModelInfo
from qwenpaw.providers.provider_manager import ProviderManager
from qwenpaw.runtime.builder import AgentBuilder
from qwenpaw.runtime.prompt_contributors import (
    WorkspacePromptFilesContributor,
    build_default_prompt_manager,
)


def _ctx(tmp_path, system_prompt_files):
    return SimpleNamespace(
        workspace_dir=str(tmp_path),
        agent_id="test_agent",
        extras={
            "agent_config": SimpleNamespace(
                system_prompt_files=system_prompt_files,
                language="en",
            ),
            "heartbeat_enabled": False,
            "language": "en",
            "memory_manager": None,
        },
    )


def test_workspace_prompt_files_respects_disabled_files(tmp_path):
    """Configured prompt file list gates SOUL.md and PROFILE.md."""
    (tmp_path / "AGENTS.md").write_text("agents body", encoding="utf-8")
    (tmp_path / "SOUL.md").write_text("soul body", encoding="utf-8")
    (tmp_path / "PROFILE.md").write_text("profile body", encoding="utf-8")

    prompt = build_default_prompt_manager().build_sync(
        _ctx(tmp_path, ["AGENTS.md"]),
    )

    assert "# AGENTS.md" in prompt
    assert "agents body" in prompt
    assert "# SOUL.md" not in prompt
    assert "soul body" not in prompt
    assert "# PROFILE.md" not in prompt
    assert "profile body" not in prompt


def test_workspace_prompt_files_empty_list_disables_workspace_markdown(
    tmp_path,
):
    """An empty configured list is meaningful and disables markdown files."""
    (tmp_path / "AGENTS.md").write_text("agents body", encoding="utf-8")
    (tmp_path / "SOUL.md").write_text("soul body", encoding="utf-8")
    (tmp_path / "PROFILE.md").write_text("profile body", encoding="utf-8")

    fragment = WorkspacePromptFilesContributor().contribute_sync(
        _ctx(tmp_path, []),
    )

    assert fragment is None


def test_workspace_prompt_files_preserves_configured_order_and_custom_files(
    tmp_path,
):
    """Configured file order is the rendered prompt order."""
    (tmp_path / "AGENTS.md").write_text("agents body", encoding="utf-8")
    (tmp_path / "PROFILE.md").write_text("profile body", encoding="utf-8")
    (tmp_path / "CUSTOM.md").write_text("custom body", encoding="utf-8")

    fragment = WorkspacePromptFilesContributor().contribute_sync(
        _ctx(tmp_path, ["PROFILE.md", "CUSTOM.md", "AGENTS.md"]),
    )

    assert fragment is not None
    assert fragment.index("# PROFILE.md") < fragment.index("# CUSTOM.md")
    assert fragment.index("# CUSTOM.md") < fragment.index("# AGENTS.md")


def test_workspace_prompt_files_skips_parent_traversal(tmp_path):
    """Configured prompt files cannot escape the workspace via ``..``."""
    outside = tmp_path.parent / f"{tmp_path.name}_secret.md"
    outside.write_text("secret body", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("agents body", encoding="utf-8")

    fragment = WorkspacePromptFilesContributor().contribute_sync(
        _ctx(tmp_path, [f"../{outside.name}", "AGENTS.md"]),
    )

    assert fragment is not None
    body = str(fragment)
    assert "secret body" not in body
    assert "agents body" in body


def test_workspace_prompt_files_skips_symlink_escape(tmp_path):
    """Configured prompt files cannot escape through symlinks."""
    outside = tmp_path.parent / f"{tmp_path.name}_symlink_secret.md"
    outside.write_text("secret body", encoding="utf-8")
    link = tmp_path / "LINK.md"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available on this platform")

    fragment = WorkspacePromptFilesContributor().contribute_sync(
        _ctx(tmp_path, ["LINK.md"]),
    )

    assert fragment is None


TEXT_ONLY = ModelInfo(
    id="legacy-text",
    name="Legacy Text",
    supports_multimodal=False,
    supports_image=False,
    supports_video=False,
)
VISION = ModelInfo(
    id="vision-pro",
    name="Vision Pro",
    supports_multimodal=True,
    supports_image=True,
    supports_video=False,
)
TEXT_ONLY_SLOT = ModelSlotConfig(provider_id="p", model=TEXT_ONLY.id)
VISION_SLOT = ModelSlotConfig(provider_id="p", model=VISION.id)

STALE_HINT = "You can only understand text content"


def _stub_capabilities(monkeypatch):
    """Disk pointer is text-only; the provider serves both models."""
    provider = SimpleNamespace(id="p", all_models=lambda: [TEXT_ONLY, VISION])
    monkeypatch.setattr(
        ProviderManager,
        "_instance",
        SimpleNamespace(
            get_provider=lambda provider_id: (
                provider if provider_id == "p" else None
            ),
            get_active_model=lambda: None,
        ),
    )
    monkeypatch.setattr(
        "qwenpaw.config.config.load_agent_config",
        lambda _agent_id: SimpleNamespace(active_model=TEXT_ONLY_SLOT),
    )
    monkeypatch.setattr(
        "qwenpaw.app.agent_context.get_current_agent_id",
        lambda: "agent",
    )


def _prompt_ctx(tmp_path, effective_model):
    """Mirror the namespace AgentBuilder.build_prompt constructs."""
    return SimpleNamespace(
        workspace_dir=str(tmp_path),
        agent_id="agent",
        session_id="s1",
        extras={
            "effective_model": effective_model,
            "preloaded_skills": (),
        },
        request=SimpleNamespace(
            channel="console",
            user_id="u",
            request_context={},
        ),
    )


def _session_config(slot):
    return AgentProfileConfig(
        id="agent",
        name="Agent",
        active_model=slot,
    )


def test_build_prompt_prefers_effective_model(monkeypatch, tmp_path):
    """A request-level override wins over the passed agent config."""
    _stub_capabilities(monkeypatch)

    prompt = AgentBuilder().build_prompt(
        _prompt_ctx(tmp_path, VISION_SLOT),
        _session_config(TEXT_ONLY_SLOT),
    )

    assert STALE_HINT not in prompt


def test_build_prompt_uses_passed_config_over_disk(monkeypatch, tmp_path):
    """The session-resolved config is authoritative over agent.json."""
    _stub_capabilities(monkeypatch)

    prompt = AgentBuilder().build_prompt(
        _prompt_ctx(tmp_path, None),
        _session_config(VISION_SLOT),
    )

    assert STALE_HINT not in prompt


def test_build_prompt_reports_text_only_config(monkeypatch, tmp_path):
    """Control: a text-only turn still gets the capability warning."""
    _stub_capabilities(monkeypatch)

    prompt = AgentBuilder().build_prompt(
        _prompt_ctx(tmp_path, None),
        _session_config(TEXT_ONLY_SLOT),
    )

    assert STALE_HINT in prompt
