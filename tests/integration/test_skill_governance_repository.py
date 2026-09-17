"""Governance transactions on the isolated migration PostgreSQL fixture."""

from contextlib import asynccontextmanager
from uuid import uuid4
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool


@pytest.fixture
def skill_database(postgres_test_schema):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_test_schema.async_url())
    config.attributes["target_schema"] = postgres_test_schema.name
    command.upgrade(config, "head")
    return postgres_test_schema


@pytest.mark.asyncio
async def test_catalog_and_fixed_publication_transactions(skill_database, tmp_path):
    from qwenpaw.skills.repository import PostgresSkillRepository
    from qwenpaw.skills.service import SkillGovernanceService
    from qwenpaw.skills.snapshots import SnapshotStore
    from qwenpaw.access.agent_repository import agent_database_id
    from qwenpaw.access.service import AuthorizationDeniedError
    from qwenpaw.identity.models import PlatformRole
    from tests.isolation.test_skill_pool_governance import actor

    schema = skill_database.name
    engine = create_async_engine(skill_database.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine)

    @asynccontextmanager
    async def sessions():
        async with factory.begin() as session:
            yield session

    admin, owner, collaborator, user = (
        actor(PlatformRole.ADMIN),
        actor(),
        actor(),
        actor(),
    )
    repo = PostgresSkillRepository(schema=schema, session_factory=sessions)
    pool = tmp_path / "pool"
    source = pool / "sample"
    source.mkdir(parents=True)
    content_a = "---\nname: sample\ndescription: Example\n---\nContent A"
    (source / "SKILL.md").write_text(content_a, encoding="utf-8")
    service = SkillGovernanceService(repo, SnapshotStore(tmp_path / "snapshots"), pool)
    try:
        async with sessions() as session:
            for i, person in enumerate([admin, owner, collaborator, user]):
                await session.execute(
                    text(
                        f"INSERT INTO \"{schema}\".users (id,username,password_hash,status,platform_role) VALUES (:id,:name,'x','active',:role)"
                    ),
                    {
                        "id": person.user_id,
                        "name": f"person{i}",
                        "role": person.platform_role.value,
                    },
                )
            for key, person in [("agentA", owner), ("agentB", user)]:
                await session.execute(
                    text(
                        f"INSERT INTO \"{schema}\".agents (id,owner_user_id,name,status,visibility,default_model_mode,draft_workspace_key) VALUES (:id,:owner,:name,'active','private','inherit','fixture')"
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
                        f'INSERT INTO "{schema}".agent_members (agent_id,user_id,role,granted_by) VALUES (:agent,:user,:role,:owner)'
                    ),
                    {
                        "agent": agent_database_id("agentA"),
                        "user": person.user_id,
                        "role": role,
                        "owner": owner.user_id,
                    },
                )
        preview = await service.preview_existing(admin)
        await service.import_existing(admin, preview)
        assert (await service.list_catalog(owner, "agentA"))["items"] == []
        item = (await repo.list_items())[0]
        await service.set_agent_grant(admin, item["id"], "agentA", True)
        resolved = await service.require_agent_version(
            owner, "agentA", item["version_id"]
        )
        assert resolved["content_hash"] == item["content_hash"]
        await service.set_agent_grant(admin, item["id"], "agentA", False)
        with pytest.raises(AuthorizationDeniedError):
            await service.require_agent_version(owner, "agentA", item["version_id"])
        await service.set_agent_grant(admin, item["id"], "agentA", True)
        for person in [owner, collaborator]:
            catalog = await service.list_catalog(person, "agentA")
            assert [row["name"] for row in catalog["items"]] == ["sample"]
            assert set(catalog["items"][0]) == {
                "id",
                "name",
                "version_id",
                "version",
                "content_hash",
            }
        for person, key in [(owner, "agentB"), (user, "agentA")]:
            with pytest.raises(AuthorizationDeniedError):
                await service.list_catalog(person, key)
        with pytest.raises(AuthorizationDeniedError):
            await service.submit_request(collaborator, "agentA", "sample", source)
        request = await service.submit_request(owner, "agentA", "sample", source)
        (source / "SKILL.md").write_text("Content B", encoding="utf-8")
        submitted = await service.request_detail(admin, request["id"])
        assert submitted["files"] == ["SKILL.md"]
        assert await service.request_file(admin, request["id"], "SKILL.md") == {
            "content": content_a
        }
        with pytest.raises(AuthorizationDeniedError):
            await service.request_detail(owner, request["id"])
        with pytest.raises(ValueError, match="invalid_skill_file"):
            await service.request_file(admin, request["id"], "../config.json")
        approved = await service.review_request(
            admin, request["id"], "approve", 0, "ok"
        )
        repeated = await service.review_request(
            admin, request["id"], "approve", 0, "ok"
        )
        assert approved == repeated
        import asyncio

        concurrent = await service.submit_request(owner, "agentA", "sample", source)
        results = await asyncio.gather(
            *(
                service.review_request(admin, concurrent["id"], "approve", 0, "race")
                for _ in range(2)
            )
        )
        assert results[0] == results[1]
        fixed = await repo.get_version(approved["published_version_id"])
        assert (
            service.snapshots.verify(fixed["content_key"], fixed["content_hash"])
            / "SKILL.md"
        ).read_text(encoding="utf-8") == content_a
        await service.set_item_status(admin, item["id"], False)
        (source / "SKILL.md").write_text(content_a, encoding="utf-8")
        await service.import_existing(admin, await service.preview_existing(admin))
        assert (await repo.list_items())[0]["status"] == "disabled"
        assert (await service.list_catalog(owner, "agentA"))["items"] == []
        async with sessions() as session:
            assert (
                await session.execute(
                    text(f'SELECT count(*) FROM "{schema}".skill_pool_agent_grants')
                )
            ).scalar_one() == 1
            assert (
                await session.execute(
                    text(f'SELECT count(*) FROM "{schema}".skill_pool_versions')
                )
            ).scalar_one() == 2
            assert (
                await session.execute(
                    text(
                        f"SELECT count(*) FROM \"{schema}\".audit_logs WHERE action='skill.request.approve'"
                    )
                )
            ).scalar_one() == 2
        # A transaction-level audit failure must roll back versions and approval together.
        (source / "SKILL.md").write_text(content_a + " C", encoding="utf-8")
        failed = await service.submit_request(owner, "agentA", "sample", source)

        @asynccontextmanager
        async def failed_sessions():
            async with factory.begin() as session:
                await session.execute(text("SET LOCAL ROLE qwenpaw_runtime"))
                yield session

        async with sessions() as session:
            await session.execute(
                text(f'GRANT USAGE ON SCHEMA "{schema}" TO qwenpaw_runtime')
            )
            await session.execute(
                text(
                    f'GRANT SELECT,INSERT,UPDATE ON ALL TABLES IN SCHEMA "{schema}" TO qwenpaw_runtime'
                )
            )
            await session.execute(
                text(f'REVOKE INSERT ON "{schema}".audit_logs FROM qwenpaw_runtime')
            )
        restricted = SkillGovernanceService(
            PostgresSkillRepository(schema=schema, session_factory=failed_sessions),
            service.snapshots,
            pool,
        )
        from sqlalchemy.exc import SQLAlchemyError

        with pytest.raises(SQLAlchemyError):
            await restricted.review_request(admin, failed["id"], "approve", 0, "fail")
        assert (
            next(
                row
                for row in await repo.list_requests()
                if str(row["id"]) == failed["id"]
            )["status"]
            == "pending"
        )
        async with sessions() as session:
            assert (
                await session.execute(
                    text(f'SELECT count(*) FROM "{schema}".skill_pool_versions')
                )
            ).scalar_one() == 2
        tampered = await service.submit_request(owner, "agentA", "sample", source)
        async with sessions() as session:
            key = (
                await session.execute(
                    text(
                        f'SELECT snapshot_key FROM "{schema}".skill_publish_requests WHERE id=:id'
                    ),
                    {"id": __import__("uuid").UUID(tampered["id"])},
                )
            ).scalar_one()
        (service.snapshots.root / key / "SKILL.md").write_text(
            "tampered", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="snapshot_integrity_failed"):
            await service.review_request(admin, tampered["id"], "approve", 0, "")
        async with sessions() as session:
            await session.execute(
                text(
                    f'UPDATE "{schema}".skill_publish_requests SET snapshot_key=NULL WHERE id=:id'
                ),
                {"id": __import__("uuid").UUID(tampered["id"])},
            )
        with pytest.raises(ValueError, match="request_snapshot_required"):
            await service.review_request(admin, tampered["id"], "approve", 0, "")
        rejected = await service.review_request(
            admin, tampered["id"], "reject", 0, "legacy"
        )
        assert rejected["status"] == "rejected"
        assert rejected["published_version_id"] is None
        # No item becomes visible if one member of an import batch fails DB validation.
        fresh = service.snapshots.capture(source, "fresh")
        with pytest.raises(SQLAlchemyError):
            await repo.import_snapshots(
                [("fresh", fresh), ("x" * 300, fresh)], admin.user_id, service.snapshots
            )
        assert "fresh" not in {row["name"] for row in await repo.list_items()}
        (source / "SKILL.md").write_text(content_a, encoding="utf-8")
        same = await service.submit_request(owner, "agentA", "sample", source)
        (service.snapshots.root / fixed["content_key"] / "SKILL.md").write_text(
            "corrupt published snapshot", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="snapshot_integrity_failed"):
            await service.review_request(admin, same["id"], "approve", 0, "")
        count_before = len(await repo.list_requests())
        (source / "SKILL.md").write_text("ghp_" + "F" * 36, encoding="utf-8")
        with pytest.raises(ValueError, match="shared_skill_credentials_detected"):
            await service.submit_request(owner, "agentA", "sample", source)
        assert len(await repo.list_requests()) == count_before
    finally:
        await engine.dispose()
