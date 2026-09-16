# -*- coding: utf-8 -*-
"""Agent 可移植包不得携带 Secret，并且只能安全还原白名单内容。"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_membership import AgentAccessDeniedError
from qwenpaw.access.agent_repository import AgentResourceRole
from qwenpaw.app.routers import agent_portability as portability_router
from qwenpaw.agents.portable_package import (
    PortablePackageError,
    build_portable_package,
    read_portable_package,
)
from qwenpaw.config.config import AgentProfileConfig, AgentProfileRef, Config
from qwenpaw.identity.models import PlatformRole


def _source_config(workspace: Path) -> dict[str, object]:
    return {
        "id": "source-agent",
        "name": "Source Agent",
        "description": "portable",
        "workspace_dir": str(workspace),
        "active_model": {"provider_id": "openai", "model": "gpt-test"},
        "backend_settings": {"model": "gpt-test", "api_key": "backend-secret"},
        "channels": {
            "telegram": {"enabled": True, "bot_token": "telegram-secret"},
        },
        "mcp": {
            "clients": {
                "private-mcp": {
                    "name": "private-mcp",
                    "enabled": True,
                    "url": "https://mcp.example.test",
                    "headers": {"Authorization": "Bearer mcp-secret"},
                    "args": ["--api-key", "mcp-argument-secret"],
                    "env": {"ACCESS": "mcp-environment-secret"},
                }
            }
        },
        "last_dispatch_by_user": {"user-1": {"channel": "telegram"}},
    }


def test_round_trip_exports_workspace_private_skills_and_dependency_manifest(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "source"
    (workspace / "skills" / "private-skill").mkdir(parents=True)
    (workspace / "PROFILE.md").write_text("# Profile", encoding="utf-8")
    (workspace / "notes.txt").write_text("portable note", encoding="utf-8")
    (workspace / "skills" / "private-skill" / "SKILL.md").write_text(
        "# Private skill",
        encoding="utf-8",
    )

    package = build_portable_package(
        agent_config=_source_config(workspace),
        workspace_dir=workspace,
    )
    imported = read_portable_package(package)

    assert imported.config["name"] == "Source Agent"
    assert imported.files["PROFILE.md"] == b"# Profile"
    assert imported.files["notes.txt"] == b"portable note"
    assert imported.files["skills/private-skill/SKILL.md"] == b"# Private skill"
    assert imported.dependencies["models"] == ["openai/gpt-test"]
    assert imported.dependencies["skills"] == ["private-skill"]
    assert imported.dependencies["mcp_clients"] == ["private-mcp"]


def test_export_removes_effective_secrets_and_runtime_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "source"
    workspace.mkdir()
    (workspace / "credentials.yaml").write_text(
        "token: workspace-secret",
        encoding="utf-8",
    )
    (workspace / "sessions.json").write_text("private history", encoding="utf-8")
    (workspace / "agent.json").write_text("source config", encoding="utf-8")
    (workspace / ".env").write_text("KEY=dotenv-secret", encoding="utf-8")
    (workspace / "client.pem").write_text("pem-secret", encoding="utf-8")

    package = build_portable_package(
        agent_config=_source_config(workspace),
        workspace_dir=workspace,
    )

    archive_text = package.decode("latin-1")
    assert "backend-secret" not in archive_text
    assert "telegram-secret" not in archive_text
    assert "mcp-secret" not in archive_text
    assert "mcp-argument-secret" not in archive_text
    assert "mcp-environment-secret" not in archive_text
    assert "workspace-secret" not in archive_text

    imported = read_portable_package(package)
    assert imported.config["id"] == ""
    assert imported.config["workspace_dir"] == ""
    assert imported.config["last_dispatch_by_user"] == {}
    assert imported.config["channels"]["telegram"]["enabled"] is False
    assert "bot_token" not in imported.config["channels"]["telegram"]
    assert imported.config["mcp"]["clients"]["private-mcp"]["enabled"] is False
    assert "headers" not in imported.config["mcp"]["clients"]["private-mcp"]
    assert imported.config["mcp"]["clients"]["private-mcp"]["args"] == []
    assert imported.config["mcp"]["clients"]["private-mcp"]["env"] == {}
    assert "credentials.yaml" not in imported.files
    assert "sessions.json" not in imported.files
    assert "agent.json" not in imported.files
    assert ".env" not in imported.files
    assert "client.pem" not in imported.files


def test_import_rejects_path_traversal_and_oversized_entries() -> None:
    traversal = io.BytesIO()
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr(
            "manifest.json", json.dumps({"format": "qwenpaw-agent", "version": 1})
        )
        archive.writestr("config/agent.json", "{}")
        archive.writestr("workspace/../escape.txt", "escape")

    with pytest.raises(PortablePackageError, match="unsafe_path"):
        read_portable_package(traversal.getvalue())

    oversized = io.BytesIO()
    with zipfile.ZipFile(oversized, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json", json.dumps({"format": "qwenpaw-agent", "version": 1})
        )
        archive.writestr("config/agent.json", "{}")
        archive.writestr("workspace/large.bin", b"x" * (16 * 1024 * 1024 + 1))

    with pytest.raises(PortablePackageError, match="entry_too_large"):
        read_portable_package(oversized.getvalue())


class _Upload:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def read(self, _size: int = -1) -> bytes:
        return self._data


def _actor() -> ActorContext:
    from uuid import uuid4

    return ActorContext(
        user_id=uuid4(),
        actor_type=ActorType.USER,
        platform_role=PlatformRole.MEMBER,
        admin_mode=False,
        request_id="portable-test",
    )


def _request(actor: ActorContext):
    from types import SimpleNamespace

    return SimpleNamespace(state=SimpleNamespace(actor=actor))


@pytest.mark.asyncio
async def test_export_requires_owner_role(monkeypatch, tmp_path: Path) -> None:
    class CollaboratorMembership:
        async def require_role(self, **_kwargs):
            raise AgentAccessDeniedError()

    workspace = tmp_path / "agent"
    workspace.mkdir()
    config = Config()
    config.agents.profiles = {
        "shared": AgentProfileRef(id="shared", workspace_dir=str(workspace)),
    }
    monkeypatch.setattr(portability_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(portability_router, "load_config", lambda: config)
    monkeypatch.setattr(
        portability_router,
        "load_agent_config",
        lambda _agent_id: AgentProfileConfig(
            id="shared",
            name="Shared",
            workspace_dir=str(workspace),
        ),
    )
    monkeypatch.setattr(
        portability_router,
        "_get_agent_membership_service",
        lambda: CollaboratorMembership(),
    )

    with pytest.raises(portability_router.HTTPException) as exc_info:
        await portability_router.export_agent_package(
            "shared",
            request=_request(_actor()),
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_import_creates_disabled_draft_owned_by_current_user(
    monkeypatch,
    tmp_path: Path,
) -> None:
    actor = _actor()
    source = tmp_path / "source"
    source.mkdir()
    (source / "PROFILE.md").write_text("# Imported", encoding="utf-8")
    package = build_portable_package(
        agent_config=_source_config(source),
        workspace_dir=source,
    )
    config = Config()
    registered: list[tuple[str, object, str]] = []
    metadata_updates: list[tuple[str, str]] = []
    saved_profiles: list[AgentProfileConfig] = []

    class Repository:
        async def register_owner(self, *, agent, owner_user_id, status):
            registered.append((agent.key, owner_user_id, status))

        async def update_metadata(self, *, agent):
            metadata_updates.append((agent.key, agent.status))

        async def update_model_mode(self, *_args):
            return None

    monkeypatch.setattr(portability_router, "WORKING_DIR", str(tmp_path))
    monkeypatch.setattr(portability_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(portability_router, "load_config", lambda: config)
    monkeypatch.setattr(portability_router, "save_config", lambda _config: None)
    monkeypatch.setattr(
        portability_router,
        "save_agent_config",
        lambda _agent_id, profile: saved_profiles.append(profile),
    )
    monkeypatch.setattr(
        portability_router, "generate_short_agent_id", lambda: "imported"
    )
    monkeypatch.setattr(
        portability_router,
        "_get_agent_metadata_repository",
        lambda: Repository(),
    )

    result = await portability_router.import_agent_package(
        request=_request(actor),
        file=_Upload(package),
        name="Imported Agent",
    )

    assert result.agent_id == "imported"
    assert result.status == "draft"
    assert result.requires_reauthorization is True
    assert registered == [("imported", actor.user_id, "draft")]
    assert metadata_updates == [("imported", "draft")]
    assert config.agents.profiles["imported"].enabled is False
    assert saved_profiles[0].id == "imported"
    assert saved_profiles[0].name == "Imported Agent"
    assert saved_profiles[0].active_model is None
    assert (tmp_path / "workspaces" / "imported" / "PROFILE.md").read_text(
        encoding="utf-8",
    ) == "# Imported"
