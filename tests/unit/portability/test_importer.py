# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from qwenpaw.app.chats.manager import ChatManager
from qwenpaw.app.chats.repo import JsonChatRepository
from qwenpaw.app.chats.session import SafeJSONSession
from qwenpaw.app.crons.manager import CronManager
from qwenpaw.app.driver_config_service import DriverConfigService
from qwenpaw.drivers.adapters.mcp_legacy_config import (
    legacy_mcp_client_to_driver,
)
from qwenpaw.harnesses.events import HarnessHistoryItem, HarnessHistoryKind
from qwenpaw.portability.importer import ProviderImportService
from qwenpaw.portability.import_support import (
    _create_memory_project as create_memory_project,
    _prepare_memory_payloads,
)
from qwenpaw.portability.adaptation_loop import AdaptationResult
from qwenpaw.portability.compatibility import (
    CompatibilityStore,
    load_manifest,
)
from qwenpaw.portability.models import (
    ImportSelection,
    ProviderInventory,
    SourceMarketplace,
    SourceMCPServer,
    SourceMemoryFile,
    SourceMemoryProject,
    SourcePlugin,
    SourceSession,
    SourceSkill,
    SourceScheduledTask,
)
from qwenpaw.plugins.marketplace_registry import ExternalMarketplaceRegistry


class _Provider:
    provider_id = "codex"

    def __init__(self, inventory: ProviderInventory) -> None:
        self._inventory = inventory

    async def inventory(
        self,
        *,
        limit: int,
        progress=None,
        include_sessions=True,
        session_ids=None,
    ) -> ProviderInventory:
        assert limit >= 1
        del include_sessions, session_ids
        if progress is not None:
            await progress("provider inventory")
        return self._inventory


def _bind_inventory(monkeypatch, inventory: ProviderInventory) -> None:
    monkeypatch.setattr(
        "qwenpaw.portability.import_planning.create_migration_provider",
        lambda _source, _workspace, **_kwargs: _Provider(inventory),
    )


def _mock_adaptation(
    monkeypatch,
    workspace,
    inventory: ProviderInventory,
    *,
    zone: str = "repair",
    status: str = "completed",  # pylint: disable=unused-argument
) -> None:
    keys = {
        **{f"skills:{item.source_id}": zone for item in inventory.skills},
        **{f"mcp:{item.source_id}": zone for item in inventory.mcp_servers},
        **{f"plugins:{item.source_id}": zone for item in inventory.plugins},
        **{
            f"scheduled_tasks:{item.source_id}": zone
            for item in inventory.scheduled_tasks
        },
    }

    async def result(
        _workspace,
        _inventory,
        migration_id,
        _progress=None,
        **_kwargs,
    ):
        manifest_path = (
            workspace.workspace_dir
            / ".qwenpaw/imports"
            / migration_id
            / "test-adaptation-manifest.json"
        )
        store = CompatibilityStore(manifest_path)
        store.prepare(
            migration_id=migration_id,
            source=inventory.provider_id,
            skills=inventory.skills,
            mcp_servers=inventory.mcp_servers,
            plugins=inventory.plugins,
            scheduled_tasks=inventory.scheduled_tasks,
        )
        if zone == "migrate":
            for key in keys:
                store.finalize(
                    key,
                    passed=True,
                    summary="test fixture",
                    reason="test fixture",
                )
            store.finish()
        else:
            store.finish(stopped=True, reason="test fixture")
        return AdaptationResult(
            manifest=load_manifest(manifest_path),
            summary_path=workspace.workspace_dir / "missing-summary.md",
        )

    monkeypatch.setattr(
        "qwenpaw.portability.importer.run_adaptation_loop",
        result,
    )


def _workspace(tmp_path: Path):
    root = tmp_path / "workspace"
    root.mkdir()
    return SimpleNamespace(
        workspace_dir=root,
        agent_id="agent-1",
        session=SafeJSONSession(str(root / "sessions")),
        chat_manager=ChatManager(
            repo=JsonChatRepository(root / "chats.json"),
        ),
    )


def _all_selection(plan) -> ImportSelection:
    values = {
        name: [] for name in ("memory", "cron", "skills", "mcp", "plugins")
    }
    fields = {
        "memory": "memory",
        "scheduled_task": "cron",
        "skill": "skills",
        "mcp": "mcp",
        "plugin": "plugins",
    }
    for item in plan.actions:
        if item.asset_type in fields:
            values[fields[item.asset_type]].append(item.source_id)
    return ImportSelection(sessions=True, **values)


async def _import_from(
    service,
    source: str,
    *,
    progress=None,
):
    plan = await service.plan_from(
        source,
        progress=progress,
    )
    return await service.apply_selection(
        plan.plan_id,
        _all_selection(plan),
        progress=progress,
    )


async def _apply_plan(service, plan):
    return await service.apply_selection(plan.plan_id, _all_selection(plan))


class _CronManager:
    def __init__(self) -> None:
        self.jobs = {}

    async def list_jobs(self):
        return list(self.jobs.values())

    async def create_or_replace_job(self, spec):
        self.jobs[spec.id] = spec

    async def create_job_if_absent(self, spec):
        if spec.id in self.jobs:
            return False
        self.jobs[spec.id] = spec
        return True

    def validate_job_spec(self, spec):
        if spec.schedule.cron == "99 99 * * *":
            raise ValueError("invalid persisted cron")

    async def delete_job(self, job_id):
        return self.jobs.pop(job_id, None) is not None

    canonicalize_imported_job_for_review = staticmethod(
        CronManager.canonicalize_imported_job_for_review,
    )


@pytest.mark.asyncio
async def test_provider_imports_scheduled_tasks_disabled_and_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.cron_manager = _CronManager()
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        scheduled_tasks=[
            SourceScheduledTask(
                source_id="automation-1",
                name="Daily report",
                schedule_type="cron",
                cron="30 9 * * *",
                timezone="Asia/Shanghai",
                prompt="Summarize yesterday's work",
                enabled=True,
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    _mock_adaptation(monkeypatch, workspace, inventory)

    await _import_from(ProviderImportService(workspace), "codex")
    await _import_from(ProviderImportService(workspace), "codex")

    assert not list((tmp_path / ".qwenpaw/imports/transactions").glob("*"))
    assert len(workspace.cron_manager.jobs) == 1
    job = next(iter(workspace.cron_manager.jobs.values()))
    assert job.enabled is False
    assert job.runtime.tool_safety is True
    assert job.runtime.share_session is False
    assert job.meta["portability"]["source_enabled"] is True
    assert job.meta["portability"]["requires_review"] is True


@pytest.mark.asyncio
async def test_migrate_zone_materializes_assets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.cron_manager = _CronManager()
    source = tmp_path / "portable-skill"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\nname: portable-skill\ndescription: Portable\n---\n\n"
        "Use QwenPaw tools.\n",
        encoding="utf-8",
    )
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        skills=[
            SourceSkill(
                source_id="portable-skill",
                name="portable-skill",
                directory=source,
            ),
        ],
        mcp_servers=[
            SourceMCPServer(
                source_id="portable-mcp",
                name="portable-mcp",
                command=sys.executable,
            ),
        ],
        scheduled_tasks=[
            SourceScheduledTask(
                source_id="portable-task",
                name="Portable task",
                schedule_type="cron",
                cron="30 9 * * *",
                prompt="Create the daily report",
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    _mock_adaptation(monkeypatch, workspace, inventory)

    async def _approved(*_args, **_kwargs):
        manifest_path = workspace.workspace_dir / "approved-manifest.json"
        store = CompatibilityStore(manifest_path)
        store.prepare(
            migration_id="approved",
            source=inventory.provider_id,
            skills=inventory.skills,
            mcp_servers=inventory.mcp_servers,
            scheduled_tasks=inventory.scheduled_tasks,
        )
        for key in (
            [f"skills:{item.source_id}" for item in inventory.skills]
            + [f"mcp:{item.source_id}" for item in inventory.mcp_servers]
            + [
                f"scheduled_tasks:{item.source_id}"
                for item in inventory.scheduled_tasks
            ]
        ):
            store.finalize(
                key,
                passed=True,
                summary="approved",
                reason="approved",
            )
        summary = workspace.workspace_dir / "compatibility-summary.md"
        summary.write_text("approved", encoding="utf-8")
        return AdaptationResult(
            manifest=load_manifest(manifest_path),
            summary_path=summary,
        )

    monkeypatch.setattr(
        "qwenpaw.portability.importer.run_adaptation_loop",
        _approved,
    )

    progress: list[str] = []

    async def record(message: str) -> None:
        progress.append(message)

    await _import_from(
        ProviderImportService(workspace),
        "codex",
        progress=record,
    )

    assert {
        "\x1easset\tskill\tsucceeded\t0\tportable-skill",
        "\x1easset\tmcp\tsucceeded\t1\tportable-mcp",
        "\x1easset\tcron\tsucceeded\t0\tportable-task",
    } <= set(progress)

    skill_manifest = json.loads(
        (workspace.workspace_dir / "skill.json").read_text(encoding="utf-8"),
    )
    assert skill_manifest["skills"]["portable-skill"]["enabled"] is False
    cards = await DriverConfigService(workspace).list_cards()
    assert len(cards) == 1 and cards[0].enabled is False
    assert cards[0].config["requires_review"] is True
    job = next(iter(workspace.cron_manager.jobs.values()))
    assert job.enabled is False
    assert job.meta["portability"]["requires_review"] is True
    assert (
        job.meta["portability"]["safety"]
        == "disabled_until_explicit_promotion"
    )
    assert (workspace.workspace_dir / "compatibility-summary.md").is_file()


@pytest.mark.asyncio
async def test_provider_import_is_additive_and_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        locator="/usr/local/bin/codex",
        sessions=[
            SourceSession(
                source_id="thread-1",
                title="Imported thread",
                history=[
                    HarnessHistoryItem(
                        kind=HarnessHistoryKind.USER,
                        text="Fix the test",
                        item_id="user-1",
                    ),
                    HarnessHistoryItem(
                        kind=HarnessHistoryKind.MESSAGE,
                        text="Done",
                        item_id="assistant-1",
                    ),
                ],
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    progress: list[str] = []

    async def record(message: str) -> None:
        progress.append(message)

    first = await _import_from(
        ProviderImportService(workspace),
        "codex",
        progress=record,
    )
    second = await _import_from(ProviderImportService(workspace), "codex")

    assert "\x1esessions\t1\t1\t1\t0" in progress
    assert first == ["thread-1"]
    assert second == []
    chats = await workspace.chat_manager.list_chats(archived=None)
    assert len(chats) == 1
    portability = chats[0].meta["portability"]
    assert portability["source_id"] == "thread-1"
    assert portability["import_mode"] == "historical_archive"
    assert portability["read_only_enforced"] is False
    assert portability["continuation_fidelity"] == "not_guaranteed"
    state = await workspace.session.get_session_state_dict(
        chats[0].session_id,
        chats[0].user_id,
        chats[0].channel,
    )
    context = state["agent"]["state"]["context"]
    assert [message["role"] for message in context] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_dry_run_plan_can_be_revalidated_and_applied(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        sessions=[
            SourceSession(
                source_id="planned-thread",
                title="Planned migration",
                history=[
                    HarnessHistoryItem(
                        kind=HarnessHistoryKind.USER,
                        text="Continue the planned task",
                    ),
                ],
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    service = ProviderImportService(workspace)

    plan = await service.plan_from("codex")

    assert plan.state == "ready"
    assert sum(item.asset_type == "session" for item in plan.actions) == 1
    assert await workspace.chat_manager.list_chats(archived=None) == []
    imported_sessions = await _apply_plan(service, plan)

    assert imported_sessions == ["planned-thread"]
    persisted = json.loads(
        (
            workspace.workspace_dir
            / ".qwenpaw/imports/plans"
            / f"{plan.plan_id}.json"
        ).read_text(encoding="utf-8"),
    )
    assert persisted["state"] == "applied"


@pytest.mark.asyncio
async def test_apply_plan_refuses_changed_source_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    memory = tmp_path / "source-memory" / "fact.md"
    memory.parent.mkdir()
    memory.write_text("version one", encoding="utf-8")
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        memory_projects=[
            SourceMemoryProject(
                source_id="memory-scope",
                project_key="project",
                files=[
                    SourceMemoryFile(
                        source_path=memory,
                        relative_path=Path("fact.md"),
                    ),
                ],
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    service = ProviderImportService(workspace)
    plan = await service.plan_from("codex")
    memory.write_text("version two", encoding="utf-8")

    with pytest.raises(ValueError, match="来源数据.*发生了变化"):
        await _apply_plan(service, plan)

    assert await workspace.chat_manager.list_chats(archived=None) == []
    persisted = json.loads(
        (
            workspace.workspace_dir
            / ".qwenpaw/imports/plans"
            / f"{plan.plan_id}.json"
        ).read_text(encoding="utf-8"),
    )
    assert persisted["state"] == "ready"


@pytest.mark.asyncio
async def test_concurrent_imports_are_serialized_and_do_not_duplicate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        sessions=[
            SourceSession(
                source_id="same-thread",
                history=[
                    HarnessHistoryItem(
                        kind=HarnessHistoryKind.USER,
                        text="One copy only",
                    ),
                ],
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)

    first, second = await asyncio.gather(
        _import_from(ProviderImportService(workspace), "codex"),
        _import_from(ProviderImportService(workspace), "codex"),
    )

    assert sum(bool(item) for item in (first, second)) == 1
    assert len(await workspace.chat_manager.list_chats(archived=None)) == 1


@pytest.mark.asyncio
async def test_provider_skill_symbolic_link_is_skipped(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    target = tmp_path / "provider-skill"
    target.mkdir()
    (target / "SKILL.md").write_text(
        "---\nname: linked\n---\n",
        encoding="utf-8",
    )
    linked = tmp_path / "linked-skill"
    try:
        linked.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are unavailable on this platform")
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        skills=[
            SourceSkill(
                source_id="linked",
                name="linked",
                directory=linked,
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)

    await _import_from(ProviderImportService(workspace), "codex")

    assert not (workspace.workspace_dir / "skills/linked").exists()


@pytest.mark.asyncio
async def test_provider_skill_uses_existing_scanner_and_stays_disabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    source = tmp_path / "provider-demo"
    source.mkdir()
    (source / "SKILL.md").write_text(
        "---\n"
        "name: provider-demo\n"
        "description: Imported provider skill\n"
        "---\n\n"
        "# Provider demo\n\nUse only when explicitly requested.\n",
        encoding="utf-8",
    )
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        skills=[
            SourceSkill(
                source_id="provider-demo",
                name="provider-demo",
                directory=source,
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    _mock_adaptation(monkeypatch, workspace, inventory)

    await _import_from(ProviderImportService(workspace), "codex")

    skill_path = workspace.workspace_dir / "skills/provider-demo/SKILL.md"
    assert skill_path.is_file()
    manifest = json.loads(
        (workspace.workspace_dir / "skill.json").read_text(encoding="utf-8"),
    )
    assert manifest["skills"]["provider-demo"]["enabled"] is False


@pytest.mark.asyncio
async def test_provider_import_persists_disabled_mcp_with_encrypted_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        mcp_servers=[
            SourceMCPServer(
                source_id="filesystem",
                name="filesystem",
                transport="stdio",
                enabled=True,
                command="npx",
                args=["server-filesystem"],
                env={"API_TOKEN": "test-token"},
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    _mock_adaptation(monkeypatch, workspace, inventory)

    await _import_from(ProviderImportService(workspace), "codex")
    await _import_from(ProviderImportService(workspace), "codex")

    card_path = workspace.workspace_dir / "drivers/mcp/filesystem.yaml"
    assert card_path.is_file()
    card_text = card_path.read_text(encoding="utf-8")
    assert "enabled: false" in card_text
    assert "test-token" not in card_text
    credential_text = (workspace.workspace_dir / "credentials.yaml").read_text(
        encoding="utf-8",
    )
    assert "test-token" not in credential_text


@pytest.mark.asyncio
async def test_mcp_retry_reuses_its_prepared_credential(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    server = SourceMCPServer(
        source_id="filesystem",
        name="filesystem",
        transport="stdio",
        command="npx",
        args=["server-filesystem"],
        env={"API_TOKEN": "test-token"},
    )
    _card, credential = legacy_mcp_client_to_driver(
        server.name,
        server,
        force_encrypt_bindings=True,
    )
    assert credential is not None
    owner = {
        "owner": "pawport",
        "provider": "codex",
        "source_id": server.source_id,
    }
    await DriverConfigService(workspace).credential_store.put(
        replace(
            credential,
            meta={
                **credential.meta,
                "pawport": {**owner, "state": "prepared"},
            },
        ),
    )
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        mcp_servers=[server],
    )
    _bind_inventory(monkeypatch, inventory)
    _mock_adaptation(monkeypatch, workspace, inventory)

    await _import_from(ProviderImportService(workspace), "codex")

    restored = await DriverConfigService(workspace).credential_store.get(
        credential.ref,
    )
    assert restored.meta["pawport"] == {**owner, "state": "committed"}


@pytest.mark.asyncio
async def test_provider_import_encrypts_even_public_named_mcp_bindings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    env_secret = "sk-debug-field-secret-123456789"
    header_secret = "sk-user-agent-field-secret-123456789"
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        mcp_servers=[
            SourceMCPServer(
                source_id="stdio-public-name",
                name="stdio-public-name",
                transport="stdio",
                command="npx",
                args=["server-package"],
                env={"DEBUG": env_secret},
            ),
            SourceMCPServer(
                source_id="http-public-name",
                name="http-public-name",
                transport="streamable_http",
                url="https://example.test/mcp",
                headers={"User-Agent": header_secret},
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    _mock_adaptation(monkeypatch, workspace, inventory)

    await _import_from(ProviderImportService(workspace), "codex")

    assert len(await DriverConfigService(workspace).list_cards()) == 2
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in workspace.workspace_dir.rglob("*")
        if path.is_file()
    )
    assert env_secret not in persisted
    assert header_secret not in persisted
    assert "source: credential" in persisted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("server", "secret"),
    [
        (
            SourceMCPServer(
                source_id="unsafe-inline",
                name="unsafe-inline",
                transport="stdio",
                command="npx",
                args=["server", "--api-key", "sk-inline-secret-123456789"],
            ),
            "sk-inline-secret-123456789",
        ),
        (
            SourceMCPServer(
                source_id="unsafe-password",
                name="unsafe-password",
                transport="stdio",
                command="mysql",
                args=["-phunter2"],
            ),
            "hunter2",
        ),
        (
            SourceMCPServer(
                source_id="unsafe-jdbc",
                name="unsafe-jdbc",
                transport="stdio",
                command="java",
                args=["jdbc:postgresql://alice:hunter2@example.test/prod"],
            ),
            "hunter2",
        ),
        (
            SourceMCPServer(
                source_id="unsafe-webhook",
                name="unsafe-webhook",
                transport="streamable_http",
                url=(
                    "https://hooks.slack.com/services/T000/B000/"
                    "correct-horse-battery-staple"
                ),
            ),
            "correct-horse-battery-staple",
        ),
    ],
)
async def test_provider_import_rejects_inline_mcp_argument_secret(
    tmp_path: Path,
    monkeypatch,
    server: SourceMCPServer,
    secret: str,
) -> None:
    workspace = _workspace(tmp_path)
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        mcp_servers=[server],
    )
    _bind_inventory(monkeypatch, inventory)

    await _import_from(ProviderImportService(workspace), "codex")

    assert not (
        workspace.workspace_dir / f"drivers/mcp/{server.name}.yaml"
    ).exists()
    persisted = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in workspace.workspace_dir.rglob("*")
        if path.is_file()
    )
    assert secret not in persisted


@pytest.mark.asyncio
async def test_provider_memory_is_scoped_exact_and_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    source = tmp_path / "source-memory/MEMORY.md"
    source.parent.mkdir()
    source.write_text("# Source memory\n\nExact bytes.\n", encoding="utf-8")
    project = SourceMemoryProject(
        source_id="project-a",
        project_key="Project A",
        cwd="/source/project-a",
        files=[
            SourceMemoryFile(
                source_path=source,
                relative_path=Path("MEMORY.md"),
            ),
        ],
    )
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        memory_projects=[project],
    )
    _bind_inventory(monkeypatch, inventory)

    await _import_from(ProviderImportService(workspace), "codex")
    await _import_from(ProviderImportService(workspace), "codex")
    imported = list(
        (workspace.workspace_dir / "memory/imports/codex").glob(
            "*/MEMORY.md",
        ),
    )
    assert len(imported) == 1
    assert imported[0].read_bytes() == source.read_bytes()
    scope = json.loads((imported[0].parent / "_scope.json").read_text())
    assert scope["cwd"] == "/source/project-a"
    assert scope["trust"] == "source_material_not_instructions"
    assert not (workspace.workspace_dir / "MEMORY.md").exists()


def test_memory_snapshot_is_verified_then_written_without_rereading(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    source = tmp_path / "source-memory/fact.md"
    source.parent.mkdir()
    source.write_text("verified", encoding="utf-8")
    project = SourceMemoryProject(
        source_id="project-a",
        project_key="Project A",
        files=[
            SourceMemoryFile(
                source_path=source,
                relative_path=Path("fact.md"),
            ),
        ],
    )

    payloads, source_payloads = _prepare_memory_payloads("codex", [project])
    source.write_text("changed after snapshot", encoding="utf-8")
    target, changed = create_memory_project(
        workspace,
        "codex",
        project,
        payloads[project.source_id],
    )

    assert changed is True
    assert source_payloads[source] == b"verified"
    assert (target / "fact.md").read_bytes() == b"verified"


def test_memory_snapshot_rejects_symbolic_link(tmp_path: Path) -> None:
    secret = tmp_path / "secret.md"
    secret.write_text("do not import", encoding="utf-8")
    source = tmp_path / "source-memory/fact.md"
    source.parent.mkdir()
    source.symlink_to(secret)
    project = SourceMemoryProject(
        source_id="project-a",
        project_key="Project A",
        files=[
            SourceMemoryFile(
                source_path=source,
                relative_path=Path("fact.md"),
            ),
        ],
    )

    with pytest.raises(ValueError, match="Memory source is unavailable"):
        _prepare_memory_payloads("codex", [project])


@pytest.mark.asyncio
async def test_skill_retry_never_deletes_the_existing_skill(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    source = tmp_path / "source-skill"
    source.mkdir()
    skill_file = source / "SKILL.md"
    skill_file.write_text(
        "---\nname: portable-skill\ndescription: test\n---\n\nbefore\n",
        encoding="utf-8",
    )
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        skills=[
            SourceSkill(
                source_id="portable-skill",
                name="portable-skill",
                directory=source,
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    _mock_adaptation(monkeypatch, workspace, inventory, zone="migrate")
    service = ProviderImportService(workspace)
    plan = await service.plan_from("codex")
    selection = ImportSelection(sessions=False, skills=["portable-skill"])
    await service.apply_selection(plan.plan_id, selection)
    skill_file.write_text(
        "---\nname: portable-skill\ndescription: test\n---\n\nafter\n",
        encoding="utf-8",
    )
    await service.retry_selection(plan.plan_id, selection)

    assert (
        (workspace.workspace_dir / "skills/portable-skill/SKILL.md")
        .read_text(encoding="utf-8")
        .endswith("before\n")
    )


@pytest.mark.asyncio
async def test_provider_plugin_restores_marketplace_then_native_installs(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.marketplace_registry_path = tmp_path / "marketplaces.json"
    plugin_source = tmp_path / "marketplace/plugins/demo"
    plugin_source.mkdir(parents=True)
    (plugin_source / "plugin.json").write_text(
        json.dumps({"id": "qwen-demo", "entry": {}}),
        encoding="utf-8",
    )
    calls = []

    async def _install(source, *, app, force, reload_agents, **_kwargs):
        calls.append((source, app, force, reload_agents))
        return SimpleNamespace(
            manifest=SimpleNamespace(id="qwen-demo"),
        )

    app = SimpleNamespace(state=SimpleNamespace(plugin_loader=object()))
    monkeypatch.setattr(
        "qwenpaw.plugins.registry.PluginRegistry.get_plugin_http_app",
        lambda _self: app,
    )
    plugins_router = ModuleType("qwenpaw.app.routers.plugins")
    plugins_router.install_plugin_source = _install
    monkeypatch.setitem(
        sys.modules,
        "qwenpaw.app.routers.plugins",
        plugins_router,
    )
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        marketplaces=[
            SourceMarketplace(
                source_id="codex:local",
                name="local",
                source=str(plugin_source.parent.parent),
                source_type="directory",
            ),
        ],
        plugins=[
            SourcePlugin(
                source_id="demo@local",
                name="demo",
                marketplace="local",
                install_source=str(plugin_source),
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    _mock_adaptation(monkeypatch, workspace, inventory)

    await _import_from(ProviderImportService(workspace), "codex")

    assert not calls
    registry = json.loads(workspace.marketplace_registry_path.read_text())
    assert registry["sources"]["codex:codex:local"]["source"] == str(
        plugin_source.parent.parent,
    )


@pytest.mark.asyncio
async def test_marketplace_conflict_does_not_prepare_its_plugin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.marketplace_registry_path = tmp_path / "marketplaces.json"
    await ExternalMarketplaceRegistry(
        workspace.marketplace_registry_path,
    ).register_if_absent(
        provider="codex",
        source_id="codex:local",
        name="local",
        source="/existing-marketplace",
        source_type="directory",
    )
    plugin_source = tmp_path / "marketplace/plugins/demo"
    plugin_source.mkdir(parents=True)
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        marketplaces=[
            SourceMarketplace(
                source_id="codex:local",
                name="local",
                source=str(plugin_source.parent.parent),
                source_type="directory",
            ),
        ],
        plugins=[
            SourcePlugin(
                source_id="demo@local",
                name="demo",
                marketplace="local",
                install_source=str(plugin_source),
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    _mock_adaptation(monkeypatch, workspace, inventory)

    await _import_from(ProviderImportService(workspace), "codex")

    assert not (workspace.workspace_dir / "plugins").exists()


@pytest.mark.asyncio
async def test_provider_plugin_never_falls_back_to_installed_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.marketplace_registry_path = tmp_path / "marketplaces.json"
    inventory = ProviderInventory(
        provider_id="qoder",
        provider_name="Qoder",
        detected=True,
        marketplaces=[
            SourceMarketplace(
                source_id="qoder:qoder-bundler",
                name="qoder-bundler",
                source_type="builtin",
            ),
        ],
        plugins=[
            SourcePlugin(
                source_id="demo@qoder-bundler",
                name="demo",
                marketplace="qoder-bundler",
                install_source="",
                metadata={"install_path": "/provider/cache/demo"},
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)

    await _import_from(ProviderImportService(workspace), "qoder")

    assert not (workspace.workspace_dir / "plugins").exists()


@pytest.mark.asyncio
async def test_qoder_custom_skill_plugin_uses_native_adapter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    workspace.marketplace_registry_path = tmp_path / "marketplaces.json"
    custom_root = tmp_path / ".qoder/plugins/custom"
    source = custom_root / "test-report-0.1.0"
    skill = source / "skills/test-report"
    manifest_dir = source / ".qoder-plugin"
    skill.mkdir(parents=True)
    manifest_dir.mkdir()
    (skill / "SKILL.md").write_text(
        "Read ~/.qoder/mcp.json",
        encoding="utf-8",
    )
    (manifest_dir / "plugin.json").write_text(
        json.dumps(
            {
                "name": "test-report",
                "displayName": "Test Report",
                "version": "0.1.0",
                "author": {"name": "User"},
                "skills": "./skills/",
            },
        ),
        encoding="utf-8",
    )
    captured = {}
    installed_plugins_root = tmp_path / "installed-plugins"
    installed_plugins_root.mkdir()

    async def _install(source_path, *, app, force, reload_agents, **_kwargs):
        del app, force, reload_agents
        staged = Path(source_path)
        captured["manifest"] = json.loads(
            (staged / "plugin.json").read_text(encoding="utf-8"),
        )
        captured["backend"] = (staged / "plugin.py").read_text(
            encoding="utf-8",
        )
        captured["skill"] = (staged / "skills/test-report/SKILL.md").read_text(
            encoding="utf-8",
        )
        installed = installed_plugins_root / "test-report"
        installed.mkdir()
        (installed / "plugin.json").write_text(
            json.dumps({"id": "test-report"}),
            encoding="utf-8",
        )
        return SimpleNamespace(
            manifest=SimpleNamespace(id="test-report"),
        )

    app = SimpleNamespace(state=SimpleNamespace(plugin_loader=object()))
    monkeypatch.setattr(
        "qwenpaw.plugins.registry.PluginRegistry.get_plugin_http_app",
        lambda _self: app,
    )
    plugins_router = ModuleType("qwenpaw.app.routers.plugins")
    plugins_router.install_plugin_source = _install
    monkeypatch.setitem(
        sys.modules,
        "qwenpaw.app.routers.plugins",
        plugins_router,
    )
    inventory = ProviderInventory(
        provider_id="qoder",
        provider_name="Qoder",
        detected=True,
        marketplaces=[
            SourceMarketplace(
                source_id="qoder:local-custom",
                name="local-custom",
                source=str(custom_root),
                source_type="local_custom",
            ),
        ],
        plugins=[
            SourcePlugin(
                source_id="test-report-0.1.0@local-custom",
                name="test-report-0.1.0",
                marketplace="local-custom",
                version="0.1.0",
                install_source=str(source),
                metadata={
                    "adapter": "qoder_skill_only_v1",
                    "canonical_custom_root": str(custom_root.resolve()),
                    "skills_relative_path": "skills",
                    "harness_bound": True,
                    "skills_enabled_by_default": False,
                },
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    _mock_adaptation(monkeypatch, workspace, inventory)

    await _import_from(ProviderImportService(workspace), "qoder")

    assert captured["manifest"]["id"] == "test-report"
    assert captured["manifest"]["meta"]["migration"]["harness_bound"] is True
    assert "enabled_by_default=False" in captured["backend"]
    assert captured["skill"] == "Read ~/.qoder/mcp.json"


@pytest.mark.asyncio
async def test_codex_content_plugin_registers_skills_and_owned_mcp(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = _workspace(tmp_path)
    source = tmp_path / "creative-production"
    manifest = source / ".codex-plugin/plugin.json"
    skill = source / "skills/produce/SKILL.md"
    server = source / "mcp/server.mjs"
    manifest.parent.mkdir(parents=True)
    skill.parent.mkdir(parents=True)
    server.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "name": "creative-production",
                "version": "1.0.0",
                "skills": "./skills/",
                "mcpServers": "./.mcp.json",
            },
        ),
        encoding="utf-8",
    )
    skill.write_text(
        "---\nname: produce\ndescription: Produce visuals\n---\n",
        encoding="utf-8",
    )
    server.write_text("// bundled MCP", encoding="utf-8")
    (source / ".mcp.json").write_text(
        '{"mcpServers":{}}',
        encoding="utf-8",
    )
    installed_root = tmp_path / "installed-plugins"
    installed_root.mkdir()

    async def _install(source_path, *, app, force, reload_agents, **_kwargs):
        del app, force, reload_agents
        staged = Path(source_path)
        installed = installed_root / "creative-production"
        shutil.copytree(staged, installed)
        return SimpleNamespace(
            manifest=SimpleNamespace(id="creative-production"),
            source_path=installed,
        )

    app = SimpleNamespace(state=SimpleNamespace(plugin_loader=object()))
    monkeypatch.setattr(
        "qwenpaw.plugins.registry.PluginRegistry.get_plugin_http_app",
        lambda _self: app,
    )
    plugins_router = ModuleType("qwenpaw.app.routers.plugins")
    plugins_router.install_plugin_source = _install
    monkeypatch.setitem(
        sys.modules,
        "qwenpaw.app.routers.plugins",
        plugins_router,
    )
    plugin_id = "creative-production@openai-curated-remote"
    inventory = ProviderInventory(
        provider_id="codex",
        provider_name="Codex",
        detected=True,
        plugins=[
            SourcePlugin(
                source_id=plugin_id,
                name="Creative Production",
                marketplace="openai-curated-remote",
                install_source=str(source),
                metadata={"adapter": "codex_content_bundle_v1"},
            ),
        ],
        mcp_servers=[
            SourceMCPServer(
                source_id=f"codex:plugin-mcp:{plugin_id}:creative",
                name="creative",
                command="node",
                args=["./mcp/server.mjs"],
                metadata={
                    "source_plugin": plugin_id,
                    "source_plugin_relative_cwd": ".",
                },
            ),
        ],
    )
    _bind_inventory(monkeypatch, inventory)
    _mock_adaptation(monkeypatch, workspace, inventory, zone="migrate")

    await _import_from(ProviderImportService(workspace), "codex")

    backend = (installed_root / "creative-production/plugin.py").read_text()
    assert "register_skill_provider" in backend
    assert "enabled_by_default=False" in backend
    card = (workspace.workspace_dir / "drivers/mcp/creative.yaml").read_text()
    assert str(installed_root / "creative-production") in card
