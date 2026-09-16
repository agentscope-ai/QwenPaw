"""Agent skill lifecycle exercises real PostgreSQL, snapshots and private files."""

from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from tests.integration.test_skill_governance_repository import skill_database
from tests.isolation.test_skill_pool_governance import actor
from qwenpaw.identity.models import PlatformRole
from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.access.service import AuthorizationDeniedError
from qwenpaw.skills.repository import PostgresSkillRepository
from qwenpaw.skills.service import SkillGovernanceService
from qwenpaw.skills.snapshots import SnapshotStore
from qwenpaw.skills.snapshots import directory_hash
from qwenpaw.agents.skill_system.store import (
    read_skill_manifest,
    mutate_json,
    default_workspace_manifest,
    get_workspace_skill_manifest_path,
)


async def save_via_route(monkeypatch, lifecycle, person, workspace, **values):
    """Use the existing save handler with only request resolution/reload isolated."""
    from types import SimpleNamespace
    from starlette.requests import Request
    from qwenpaw.app.routers import skills

    async def resolve(request):
        return SimpleNamespace(agent_id="agentA", workspace_dir=str(workspace))

    monkeypatch.setenv("QWENPAW_MULTI_USER_ENABLED", "true")
    monkeypatch.setattr("qwenpaw.app.agent_context.get_agent_for_request", resolve)
    monkeypatch.setattr(
        "qwenpaw.skills.runtime.get_skill_lifecycle_service", lambda: lifecycle
    )
    monkeypatch.setattr(skills, "schedule_agent_reload", lambda *args: None)
    request = Request({"type": "http", "state": {"actor": person}})
    return await skills.save_workspace_skill(request, skills.SaveSkillRequest(**values))


def private_tree(root):
    """Capture all fixture paths and exact bytes, including empty directories."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
        for path in root.rglob("*")
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("edit", [False, True])
async def test_round1_route_rename_keeps_binding_and_restores(
    skill_database, tmp_path, monkeypatch, edit
):
    from qwenpaw.skills.lifecycle import SkillLifecycleService

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (admin, owner, collaborator, _), item, source, workspaces, _ = (
            fixture
        )
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        loaded = await lifecycle.install(owner, "agentA", item["id"])
        ws = workspaces["agentA"]
        repo = governance.repository
        binding = (await repo.installed("agentA"))["sample"]
        runtime = dict(
            enabled=False,
            channels=[],
            tags=["local"],
            config={"fixture": 1},
            extra={"keep": True},
        )
        mutate_json(
            ws / "skill.json", {}, lambda p: p["skills"]["sample"].update(runtime)
        )
        # Grant revocation must not prevent editing an independent local copy.
        await governance.set_agent_grant(admin, item["id"], "agentA", False)
        content = (source / "SKILL.md").read_text(encoding="utf-8")
        result = await save_via_route(
            monkeypatch,
            lifecycle,
            collaborator,
            ws,
            source_name="sample",
            name="renamed",
            content=content + ("\nLocal edit" if edit else ""),
        )
        assert result == {"success": True, "mode": "rename", "name": "renamed"}
        rows = await repo.installed("agentA")
        assert set(rows) == {"renamed"}
        assert rows["renamed"]["id"] == binding["id"]
        assert rows["renamed"]["content_key"] == "skills/renamed"
        assert rows["renamed"]["source_pool_version_id"] == item["version_id"]
        entry = read_skill_manifest(ws)["skills"]["renamed"]
        assert {key: entry[key] for key in runtime} == runtime
        assert entry["source_pool_version_id"] == loaded["source_pool_version_id"]
        local = (await lifecycle.list_installed(owner, "agentA"))["items"][0]
        assert local["name"] == "renamed"
        assert local["detached"] is edit
        await governance.set_agent_grant(admin, item["id"], "agentA", True)
        outcome = await lifecycle.auto_update(item["id"], ["agentA"])
        assert outcome["results"][0]["status"] == ("skipped" if edit else "unchanged")
        assert outcome["results"][0]["reason"] == ("detached" if edit else "")
        restored = await lifecycle.restore(
            owner, "agentA", "renamed", local["content_hash"]
        )
        assert restored["detached"] is False
        assert not (ws / "skills/sample").exists()
        assert (ws / "skills/renamed/SKILL.md").read_text(encoding="utf-8") == content


@pytest.mark.asyncio
@pytest.mark.parametrize("overwrite", [False, True])
@pytest.mark.parametrize("deferred", [False, True])
async def test_round1_rename_real_db_failure_reverts_directories_manifest_and_rows(
    skill_database, tmp_path, monkeypatch, overwrite, deferred
):
    from sqlalchemy.exc import SQLAlchemyError
    from qwenpaw.skills.lifecycle import SkillLifecycleService

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (_, owner, _, _), item, source, workspaces, sessions = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        await lifecycle.install(owner, "agentA", item["id"])
        ws = workspaces["agentA"]
        if overwrite:
            await save_via_route(
                monkeypatch,
                lifecycle,
                owner,
                ws,
                source_name="sample",
                name="renamed",
                content=(source / "SKILL.md").read_text(),
            )
            await lifecycle.install(owner, "agentA", item["id"])
            (ws / "skills/renamed/only-target.txt").write_text(
                "target", encoding="utf-8"
            )
        manifest = (ws / "skill.json").read_bytes()
        tree = private_tree(ws / "skills")
        rows = await governance.repository.installed("agentA")
        async with sessions() as session:
            await session.execute(
                text(
                    f"CREATE FUNCTION \"{skill_database.name}\".fail_rename() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN IF NEW.name = ''renamed'' THEN RAISE EXCEPTION ''fixture rename failure''; END IF; RETURN NEW; END'"
                )
            )
            kind = "CONSTRAINT " if deferred else ""
            timing = "DEFERRABLE INITIALLY DEFERRED " if deferred else ""
            await session.execute(
                text(
                    f"CREATE {kind}TRIGGER fail_rename AFTER UPDATE ON {governance.repository.table('agent_skills')} {timing}FOR EACH ROW EXECUTE FUNCTION \"{skill_database.name}\".fail_rename()"
                )
            )
        with pytest.raises(SQLAlchemyError, match="fixture rename failure"):
            await save_via_route(
                monkeypatch,
                lifecycle,
                owner,
                ws,
                source_name="sample",
                name="renamed",
                content=(source / "SKILL.md").read_text() + "\nEdited",
                overwrite=overwrite,
                expected_content_hash=directory_hash(ws / "skills/renamed", shared=False) if overwrite else None,
            )
        assert (ws / "skill.json").read_bytes() == manifest
        assert private_tree(ws / "skills") == tree
        assert await governance.repository.installed("agentA") == rows


@pytest.mark.asyncio
async def test_round1_rename_keeps_existing_local_name_support(
    skill_database, tmp_path, monkeypatch
):
    from qwenpaw.skills.lifecycle import SkillLifecycleService

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (_, owner, _, _), item, source, workspaces, _ = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        await lifecycle.install(owner, "agentA", item["id"])
        await save_via_route(
            monkeypatch,
            lifecycle,
            owner,
            workspaces["agentA"],
            source_name="sample",
            name="本地 skill",
            content=(source / "SKILL.md").read_text() + "\nLocal",
        )
        state = (await lifecycle.list_installed(owner, "agentA"))["items"][0]
        assert state["name"] == "本地 skill"
        assert state["detached"] is True
        assert (await lifecycle.auto_update(item["id"], ["agentA"]))["results"][0][
            "reason"
        ] == "detached"
        restored = await lifecycle.restore(
            owner, "agentA", state["name"], state["content_hash"]
        )
        assert restored["detached"] is False


@pytest.mark.asyncio
async def test_round1_rename_conflict_and_explicit_overwrite_keep_source_identity(
    skill_database, tmp_path, monkeypatch
):
    from fastapi import HTTPException
    from qwenpaw.skills.lifecycle import SkillLifecycleService

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (_, owner, _, _), item, source, workspaces, _ = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        ws = workspaces["agentA"]
        await lifecycle.install(owner, "agentA", item["id"])
        content = (source / "SKILL.md").read_text()
        await save_via_route(
            monkeypatch,
            lifecycle,
            owner,
            ws,
            source_name="sample",
            name="renamed",
            content=content,
        )
        await lifecycle.install(owner, "agentA", item["id"])
        (ws / "skills/renamed/only-target.txt").write_text(
            "replace me", encoding="utf-8"
        )
        before = private_tree(ws / "skills"), (ws / "skill.json").read_bytes()
        rows = await governance.repository.installed("agentA")
        with pytest.raises(HTTPException) as conflict:
            await save_via_route(
                monkeypatch,
                lifecycle,
                owner,
                ws,
                source_name="sample",
                name="renamed",
                content=content,
            )
        assert conflict.value.status_code == 409
        assert (private_tree(ws / "skills"), (ws / "skill.json").read_bytes()) == before
        assert await governance.repository.installed("agentA") == rows
        result = await save_via_route(
            monkeypatch,
            lifecycle,
            owner,
            ws,
            source_name="sample",
            name="renamed",
            content=content + "\nEdited",
            overwrite=True,
            expected_content_hash=conflict.value.detail["expected_content_hash"],
        )
        assert result["mode"] == "rename"
        after = await governance.repository.installed("agentA")
        assert set(after) == {"renamed"}
        assert after["renamed"]["id"] == rows["sample"]["id"]
        assert after["renamed"]["source_pool_version_id"] == item["version_id"]
        assert after["renamed"]["detached"] is True
        assert not (ws / "skills/sample").exists()
        assert not (ws / "skills/renamed/only-target.txt").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("damage", ["delete", "rename"])
@pytest.mark.parametrize("operation", ["restore", "update"])
async def test_round1_missing_document_lists_confirms_and_skips_only_detached_target(
    skill_database, tmp_path, damage, operation
):
    from qwenpaw.skills.lifecycle import SkillLifecycleService
    from qwenpaw.skills.snapshots import directory_hash
    from qwenpaw.agents.skill_system.registry import reconcile_workspace_manifest

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (admin, owner, _, user), item, source, workspaces, _ = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        await lifecycle.install(owner, "agentA", item["id"])
        await governance.set_agent_grant(admin, item["id"], "agentB", True)
        await lifecycle.install(user, "agentB", item["id"])
        ws = workspaces["agentA"]
        target = ws / "skills/sample"
        runtime = dict(
            enabled=False, channels=[], tags=["local"], config={"fixture": 1}
        )
        mutate_json(
            ws / "skill.json", {}, lambda p: p["skills"]["sample"].update(runtime)
        )
        if damage == "delete":
            (target / "SKILL.md").unlink()
        else:
            (target / "SKILL.md").rename(target / "RENAMED.md")
        local = (await lifecycle.list_installed(owner, "agentA"))["items"]
        assert len(local) == 1
        assert local[0]["detached"] is True
        assert len(local[0]["content_hash"]) == 64
        with pytest.raises(ValueError, match="missing_skill_document"):
            directory_hash(target)
        reconcile_workspace_manifest(ws)
        assert {
            k: read_skill_manifest(ws)["skills"]["sample"][k] for k in runtime
        } == runtime
        (source / "scripts/run.py").write_text("print('B')\n", encoding="utf-8")
        await governance.import_existing(
            admin, await governance.preview_existing(admin)
        )
        outcome = await lifecycle.auto_update(item["id"], ["agentA", "agentB"])
        assert [
            (r["agent_id"], r["status"], r["reason"]) for r in outcome["results"]
        ] == [("agentA", "skipped", "detached"), ("agentB", "updated", "")]
        assert (
            workspaces["agentB"] / "skills/sample/scripts/run.py"
        ).read_text() == "print('B')\n"
        (target / "scripts/run.py").write_text(
            "print('later edit')\n", encoding="utf-8"
        )
        tree, manifest = private_tree(target), (ws / "skill.json").read_bytes()
        with pytest.raises(ValueError, match="content_conflict"):
            await getattr(lifecycle, operation)(
                owner, "agentA", "sample", local[0]["content_hash"]
            )
        assert private_tree(target) == tree
        assert (ws / "skill.json").read_bytes() == manifest
        current = (await lifecycle.list_installed(owner, "agentA"))["items"][0]
        restored = await getattr(lifecycle, operation)(
            owner, "agentA", "sample", current["content_hash"]
        )
        assert restored["detached"] is False
        assert (target / "SKILL.md").is_file()
        assert not (target / "RENAMED.md").exists()
        assert (target / "scripts/run.py").read_text() == (
            "print('A')\n" if operation == "restore" else "print('B')\n"
        )
        assert {
            k: read_skill_manifest(ws)["skills"]["sample"][k] for k in runtime
        } == runtime


@asynccontextmanager
async def lifecycle_fixture(database, tmp_path):
    engine = create_async_engine(database.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine)

    @asynccontextmanager
    async def sessions():
        async with factory.begin() as session:
            yield session

    people = [actor(PlatformRole.ADMIN), actor(), actor(), actor()]
    admin, owner, collaborator, user = people
    repo = PostgresSkillRepository(schema=database.name, session_factory=sessions)
    try:
        async with sessions() as session:
            for index, person in enumerate(people):
                await session.execute(
                    text(
                        f"INSERT INTO {repo.table('users')} (id,username,password_hash,status,platform_role) VALUES (:id,:name,'fixture','active',:role)"
                    ),
                    {
                        "id": person.user_id,
                        "name": f"person{index}",
                        "role": person.platform_role.value,
                    },
                )
            for key, person in [("agentA", owner), ("agentB", user)]:
                await session.execute(
                    text(
                        f"INSERT INTO {repo.table('agents')} (id,owner_user_id,name,status,visibility,default_model_mode,draft_workspace_key) VALUES (:id,:owner,:name,'active','private','inherit','fixture')"
                    ),
                    {
                        "id": agent_database_id(key),
                        "owner": person.user_id,
                        "name": key,
                    },
                )
            for person, role in [(collaborator, "collaborator"), (user, "user")]:
                await session.execute(
                    text(
                        f"INSERT INTO {repo.table('agent_members')} (agent_id,user_id,role,granted_by) VALUES (:agent,:user,:role,:owner)"
                    ),
                    {
                        "agent": agent_database_id("agentA"),
                        "user": person.user_id,
                        "role": role,
                        "owner": owner.user_id,
                    },
                )
        source = tmp_path / "pool" / "sample"
        (source / "scripts").mkdir(parents=True)
        (source / "SKILL.md").write_text(
            "---\nname: sample\ndescription: Fixture\n---\nContent A", encoding="utf-8"
        )
        (source / "scripts" / "run.py").write_text("print('A')\n", encoding="utf-8")
        governance = SkillGovernanceService(
            repo, SnapshotStore(tmp_path / "snapshots"), source.parent
        )
        await governance.import_existing(
            admin, await governance.preview_existing(admin)
        )
        item = (await repo.list_items())[0]
        await governance.set_agent_grant(admin, item["id"], "agentA", True)
        workspaces = {key: tmp_path / key for key in ["agentA", "agentB"]}
        yield governance, people, item, source, workspaces, sessions
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_install_update_restore_and_runtime_fidelity(skill_database, tmp_path):
    from qwenpaw.skills.lifecycle import SkillLifecycleService

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        (
            governance,
            (admin, owner, collaborator, user),
            item,
            source,
            workspaces,
            sessions,
        ) = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        installed = await lifecycle.install(owner, "agentA", item["id"])
        assert installed["source_pool_version_id"] == str(item["version_id"])
        assert installed["detached"] is False
        ws = workspaces["agentA"]
        target = ws / "skills" / "sample"
        assert (target / "scripts" / "run.py").read_text() == "print('A')\n"
        assert read_skill_manifest(ws)["skills"]["sample"]["enabled"] is True

        def runtime_config(payload):
            payload["skills"]["sample"].update(
                enabled=False,
                channels=[],
                tags=["private"],
                config={"synthetic": "value"},
                future_runtime={"keep": True},
            )

        mutate_json(
            get_workspace_skill_manifest_path(ws),
            default_workspace_manifest(),
            runtime_config,
        )
        assert (await lifecycle.list_installed(owner, "agentA"))["items"][0][
            "detached"
        ] is False
        (target / "scripts" / "run.py").write_text("print('local')\n", encoding="utf-8")
        local = (await lifecycle.list_installed(owner, "agentA"))["items"][0]
        assert local["detached"] is True
        (source / "scripts" / "run.py").write_text("print('B')\n", encoding="utf-8")
        await governance.import_existing(
            admin, await governance.preview_existing(admin)
        )
        assert (await lifecycle.list_installed(owner, "agentA"))["items"][0][
            "update_available"
        ] is True
        with pytest.raises(ValueError, match="content_conflict"):
            await lifecycle.update(
                collaborator, "agentA", "sample", installed["content_hash"]
            )
        assert (target / "scripts" / "run.py").read_text() == "print('local')\n"
        restored = await lifecycle.restore(
            collaborator, "agentA", "sample", local["content_hash"]
        )
        assert restored["detached"] is False
        assert restored["update_available"] is True
        assert (target / "scripts" / "run.py").read_text() == "print('A')\n"
        updated = await lifecycle.update(
            owner, "agentA", "sample", restored["content_hash"]
        )
        assert updated["source_pool_version_id"] != installed["source_pool_version_id"]
        assert (target / "scripts" / "run.py").read_text() == "print('B')\n"
        entry = read_skill_manifest(ws)["skills"]["sample"]
        assert {
            key: entry[key]
            for key in ["enabled", "channels", "tags", "config", "future_runtime"]
        } == {
            "enabled": False,
            "channels": [],
            "tags": ["private"],
            "config": {"synthetic": "value"},
            "future_runtime": {"keep": True},
        }
        async with sessions() as session:
            row = (
                await session.execute(
                    text(
                        f"SELECT source_pool_version_id,detached FROM {governance.repository.table('agent_skills')}"
                    )
                )
            ).one()
            assert str(row.source_pool_version_id) == updated["source_pool_version_id"]
            assert row.detached is False


@pytest.mark.asyncio
async def test_authority_revocation_and_snapshot_tampering(skill_database, tmp_path):
    from qwenpaw.skills.lifecycle import SkillLifecycleService

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (admin, owner, collaborator, user), item, source, workspaces, _ = (
            fixture
        )
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        for person, key in [(user, "agentA"), (owner, "agentB")]:
            with pytest.raises(AuthorizationDeniedError):
                await lifecycle.install(person, key, item["id"])
        assert not any(path.exists() for path in workspaces.values())
        result = await lifecycle.install(collaborator, "agentA", item["id"])
        await governance.set_agent_grant(admin, item["id"], "agentA", False)
        for operation in [
            lambda: lifecycle.install(
                owner,
                "agentA",
                item["id"],
                overwrite=True,
                expected_content_hash=result["content_hash"],
            ),
            lambda: lifecycle.update(owner, "agentA", "sample", result["content_hash"]),
            lambda: lifecycle.restore(
                owner, "agentA", "sample", result["content_hash"]
            ),
        ]:
            with pytest.raises(AuthorizationDeniedError):
                await operation()
        assert (
            read_skill_manifest(workspaces["agentA"])["skills"]["sample"]["enabled"]
            is True
        )
        await governance.set_agent_grant(admin, item["id"], "agentA", True)
        version = await governance.repository.get_version(item["version_id"])
        (governance.snapshots.root / version["content_key"] / "SKILL.md").write_text(
            "tampered", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="snapshot_integrity_failed"):
            await lifecycle.restore(owner, "agentA", "sample", result["content_hash"])
        assert (
            (workspaces["agentA"] / "skills/sample/SKILL.md")
            .read_text()
            .endswith("Content A")
        )


@pytest.mark.asyncio
async def test_private_files_refresh_and_enabled_discovery(
    skill_database, tmp_path, monkeypatch
):
    from qwenpaw.skills.lifecycle import SkillLifecycleService
    from qwenpaw.agents.skill_system.registry import (
        reconcile_workspace_manifest,
        resolve_effective_skills,
    )
    from qwenpaw.agents.skill_system.workspace_service import SkillService

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (_, owner, _, _), item, _, workspaces, _ = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        await lifecycle.install(owner, "agentA", item["id"])
        ws = workspaces["agentA"]

        def empty_channel(payload):
            payload["skills"]["sample"]["channels"] = []

        mutate_json(
            get_workspace_skill_manifest_path(ws),
            default_workspace_manifest(),
            empty_channel,
        )
        reconcile_workspace_manifest(ws)
        entry = read_skill_manifest(ws)["skills"]["sample"]
        assert entry["channels"] == []
        assert entry["source_pool_version_id"] == str(item["version_id"])
        assert resolve_effective_skills(ws, "console") == []
        private = ws / "skills" / "private"
        private.mkdir()
        (private / "SKILL.md").write_text(
            "---\nname: private\ndescription: Private\n---\nFixture", encoding="utf-8"
        )
        (private / "config.json").write_text('{"fixture":true}', encoding="utf-8")
        reconcile_workspace_manifest(ws)
        rows = (await lifecycle.list_installed(owner, "agentA"))["items"]
        row = next(row for row in rows if row["name"] == "private")
        assert row["source_pool_version_id"] is None and row["detached"] is False
        assert len(row["content_hash"]) == 64
        SkillService(ws).disable_skill("sample")
        assert resolve_effective_skills(ws, "console") == []


@pytest.mark.asyncio
async def test_database_commit_failure_rolls_back_disk_and_manifest(
    skill_database, tmp_path
):
    from qwenpaw.skills.lifecycle import SkillLifecycleService
    from sqlalchemy.exc import SQLAlchemyError

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (admin, owner, _, _), item, source, workspaces, sessions = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        installed = await lifecycle.install(owner, "agentA", item["id"])
        ws = workspaces["agentA"]
        manifest = (ws / "skill.json").read_bytes()
        (source / "SKILL.md").write_text(
            "---\nname: sample\ndescription: Fixture\n---\nContent B", encoding="utf-8"
        )
        await governance.import_existing(
            admin, await governance.preview_existing(admin)
        )
        # A deferred trigger fails at the actual DB commit after files were installed.
        async with sessions() as session:
            await session.execute(
                text(
                    f"CREATE FUNCTION \"{skill_database.name}\".fail_binding() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN RAISE EXCEPTION ''fixture commit failure''; END'"
                )
            )
            await session.execute(
                text(
                    f"CREATE CONSTRAINT TRIGGER fail_binding AFTER INSERT OR UPDATE ON {governance.repository.table('agent_skills')} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION \"{skill_database.name}\".fail_binding()"
                )
            )
        with pytest.raises(SQLAlchemyError):
            await lifecycle.update(owner, "agentA", "sample", installed["content_hash"])
        assert (ws / "skill.json").read_bytes() == manifest
        assert (ws / "skills/sample/SKILL.md").read_text().endswith("Content A")
        assert (
            str(
                (await governance.repository.installed("agentA"))["sample"][
                    "source_pool_version_id"
                ]
            )
            == installed["source_pool_version_id"]
        )


@pytest.mark.asyncio
async def test_auto_update_skips_detached_and_missing_grants(skill_database, tmp_path):
    from qwenpaw.skills.lifecycle import SkillLifecycleService

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (admin, owner, _, user), item, source, workspaces, _ = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        await lifecycle.install(owner, "agentA", item["id"])
        await governance.set_agent_grant(admin, item["id"], "agentB", True)
        await lifecycle.install(user, "agentB", item["id"])
        target = workspaces["agentA"] / "skills/sample/scripts/run.py"
        target.write_text("print('local')\n", encoding="utf-8")
        await governance.set_agent_grant(admin, item["id"], "agentB", False)
        (source / "scripts/run.py").write_text("print('B')\n", encoding="utf-8")
        await governance.import_existing(
            admin, await governance.preview_existing(admin)
        )
        outcome = await lifecycle.auto_update(item["id"], ["agentA", "agentB"])
        assert {
            (row["agent_id"], row["status"], row["reason"])
            for row in outcome["results"]
        } == {
            ("agentA", "skipped", "detached"),
            ("agentB", "skipped", "not_authorized"),
        }
        assert target.read_text() == "print('local')\n"
        assert (
            workspaces["agentB"] / "skills/sample/scripts/run.py"
        ).read_text() == "print('A')\n"


@pytest.mark.asyncio
async def test_confirmation_rechecked_after_staging_scan(
    skill_database, tmp_path, monkeypatch
):
    from qwenpaw.skills.lifecycle import SkillLifecycleService
    from qwenpaw.agents.skill_system import workspace_service

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (admin, owner, _, _), item, source, workspaces, _ = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        installed = await lifecycle.install(owner, "agentA", item["id"])
        target = workspaces["agentA"] / "skills/sample/scripts/run.py"
        manifest = (workspaces["agentA"] / "skill.json").read_bytes()
        original_scan = workspace_service.scan_skill_dir_or_raise

        def edit_during_scan(stage, name):
            original_scan(stage, name)
            target.write_text("print('external edit')\n", encoding="utf-8")

        monkeypatch.setattr(
            workspace_service, "scan_skill_dir_or_raise", edit_during_scan
        )
        with pytest.raises(ValueError, match="content_conflict"):
            await lifecycle.restore(
                owner, "agentA", "sample", installed["content_hash"]
            )
        assert target.read_text() == "print('external edit')\n"
        assert (workspaces["agentA"] / "skill.json").read_bytes() == manifest


@pytest.mark.asyncio
async def test_two_target_commit_failure_reverts_all_copies(skill_database, tmp_path):
    from qwenpaw.skills.lifecycle import SkillLifecycleService
    from sqlalchemy.exc import SQLAlchemyError

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (admin, owner, _, user), item, source, workspaces, sessions = (
            fixture
        )
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        await lifecycle.install(owner, "agentA", item["id"])
        await governance.set_agent_grant(admin, item["id"], "agentB", True)
        await lifecycle.install(user, "agentB", item["id"])
        manifests = {
            key: (ws / "skill.json").read_bytes() for key, ws in workspaces.items()
        }
        (source / "scripts/run.py").write_text("print('B')\n", encoding="utf-8")
        await governance.import_existing(
            admin, await governance.preview_existing(admin)
        )
        async with sessions() as session:
            await session.execute(
                text(
                    f"CREATE FUNCTION \"{skill_database.name}\".fail_second() RETURNS trigger LANGUAGE plpgsql AS 'BEGIN IF NEW.agent_id = ''{agent_database_id('agentB')}''::uuid THEN RAISE EXCEPTION ''fixture second target''; END IF; RETURN NEW; END'"
                )
            )
            await session.execute(
                text(
                    f"CREATE CONSTRAINT TRIGGER fail_second AFTER INSERT OR UPDATE ON {governance.repository.table('agent_skills')} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION \"{skill_database.name}\".fail_second()"
                )
            )
        with pytest.raises(SQLAlchemyError):
            await lifecycle.auto_update(item["id"], ["agentA", "agentB"])
        for key, ws in workspaces.items():
            assert (ws / "skill.json").read_bytes() == manifests[key]
            assert (ws / "skills/sample/scripts/run.py").read_text() == "print('A')\n"
            assert str(
                (await governance.repository.installed(key))["sample"][
                    "source_pool_version_id"
                ]
            ) == str(item["version_id"])


@pytest.mark.asyncio
async def test_authorized_background_uses_published_version_and_reports_skips(
    skill_database, tmp_path, monkeypatch
):
    from qwenpaw.skills.lifecycle import SkillLifecycleService
    from qwenpaw.agents.skill_system import pool_service

    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (admin, owner, _, _), item, source, workspaces, _ = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        await lifecycle.install(owner, "agentA", item["id"])
        (source / "scripts/run.py").write_text("print('B')\n", encoding="utf-8")
        await governance.import_existing(
            admin, await governance.preview_existing(admin)
        )
        (source / "scripts/run.py").write_text(
            "print('unpublished')\n", encoding="utf-8"
        )
        monkeypatch.setattr(
            "qwenpaw.skills.runtime.get_skill_lifecycle_service", lambda: lifecycle
        )
        monkeypatch.setattr(
            pool_service,
            "read_skill_pool_manifest",
            lambda: {
                "skills": {
                    "sample": {"auto_update": True},
                    "unpublished": {"auto_update": True},
                }
            },
        )
        monkeypatch.setattr(
            pool_service,
            "list_workspaces",
            lambda: [
                {"agent_id": key, "workspace_dir": str(ws)}
                for key, ws in workspaces.items()
            ],
        )
        result = await pool_service.run_authorized_pool_auto_update_sync()
        assert (
            workspaces["agentA"] / "skills/sample/scripts/run.py"
        ).read_text() == "print('B')\n"
        assert not workspaces["agentB"].exists()
        assert result["synced"] == [{"skill": "sample", "agents": ["agentA"]}]
        reasons = {
            row["reason"] for batch in result["results"] for row in batch["results"]
        }
        assert {"not_authorized", "immutable_version_required"}.issubset(reasons)


@pytest.mark.asyncio
async def test_real_scan_rejection_preserves_installed_copy(
    skill_database, tmp_path, monkeypatch
):
    from qwenpaw.skills.lifecycle import SkillLifecycleService
    from qwenpaw.exceptions import SkillScanError

    monkeypatch.setattr("qwenpaw.constant.WORKING_DIR", tmp_path)
    async with lifecycle_fixture(skill_database, tmp_path) as fixture:
        governance, (admin, owner, _, _), item, source, workspaces, _ = fixture
        lifecycle = SkillLifecycleService(governance, workspaces.__getitem__)
        installed = await lifecycle.install(owner, "agentA", item["id"])
        manifest = (workspaces["agentA"] / "skill.json").read_bytes()
        # Publish under the existing optional off policy, then require the genuine scanner on install.
        monkeypatch.setenv("QWENPAW_SKILL_SCAN_MODE", "off")
        (source / "scripts/run.py").write_text(
            "import os\nos.system('rm -rf /')\n", encoding="utf-8"
        )
        await governance.import_existing(
            admin, await governance.preview_existing(admin)
        )
        monkeypatch.setenv("QWENPAW_SKILL_SCAN_MODE", "block")
        with pytest.raises(SkillScanError):
            await lifecycle.update(owner, "agentA", "sample", installed["content_hash"])
        assert (workspaces["agentA"] / "skill.json").read_bytes() == manifest
        assert (
            workspaces["agentA"] / "skills/sample/scripts/run.py"
        ).read_text() == "print('A')\n"
        assert str(
            (await governance.repository.installed("agentA"))["sample"][
                "source_pool_version_id"
            ]
        ) == str(item["version_id"])
