"""Schema-qualified skill metadata and serialized publication transactions."""

import re
from contextlib import asynccontextmanager
from uuid import UUID, uuid4
from sqlalchemy import text
from ..access.agent_repository import agent_database_id
from ..persistence.database import database_session


class PostgresSkillRepository:
    def __init__(self, *, schema, session_factory=database_session):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
            raise ValueError("invalid_database_schema")
        self.schema = schema
        self.session_factory = session_factory

    def table(self, name):
        return f'"{self.schema}"."{name}"'

    async def installed(self, agent_id, *, session=None):
        if session is None:
            async with self.session_factory() as current:
                return await self.installed(agent_id, session=current)
        rows = (
            (
                await session.execute(
                    text(f"""
            SELECT a.*,v.skill_id,v.version AS source_pool_version,v.content_hash AS source_content_hash
            FROM {self.table('agent_skills')} a
            LEFT JOIN {self.table('skill_pool_versions')} v ON v.id=a.source_pool_version_id
            WHERE a.agent_id=:agent
        """),
                    {"agent": agent_database_id(agent_id)},
                )
            )
            .mappings()
            .all()
        )
        return {row["name"]: dict(row) for row in rows}

    @asynccontextmanager
    async def lifecycle_transaction(self):
        async with self.session_factory() as session:
            yield session

    async def lock_agent_editor(self, session, agent_id, *, actor=None, internal=False):
        """Keep local edit authority stable without requiring a pool grant."""
        from ..access.service import AuthorizationDeniedError, AuthorizationService
        from ..access.capabilities import Capability

        agent = agent_database_id(agent_id)
        row = (
            (
                await session.execute(
                    text(
                        f"SELECT owner_user_id,status FROM {self.table('agents')} WHERE id=:agent FOR UPDATE"
                    ),
                    {"agent": agent},
                )
            )
            .mappings()
            .first()
        )
        if row is None or row["status"] != "active":
            raise AuthorizationDeniedError()
        if not internal:
            AuthorizationService().require(actor, Capability.AGENT_USE)
            active = (
                await session.execute(
                    text(
                        f"SELECT status FROM {self.table('users')} WHERE id=:user FOR SHARE"
                    ),
                    {"user": actor.user_id},
                )
            ).scalar_one_or_none()
            member = (
                (
                    await session.execute(
                        text(
                            f"SELECT role,revoked_at FROM {self.table('agent_members')} WHERE agent_id=:agent AND user_id=:user FOR SHARE"
                        ),
                        {"agent": agent, "user": actor.user_id},
                    )
                )
                .mappings()
                .first()
            )
            if active != "active" or (
                row["owner_user_id"] != actor.user_id
                and (
                    member is None
                    or member["role"] != "collaborator"
                    or member["revoked_at"] is not None
                )
            ):
                raise AuthorizationDeniedError()

    async def lock_lifecycle_authority(
        self, session, agent_id, skill_id, *, actor=None, internal=False
    ):
        """Lock actual authority rows through the file write and commit, including revocation."""
        from ..access.service import AuthorizationDeniedError

        await self.lock_agent_editor(session, agent_id, actor=actor, internal=internal)
        agent = agent_database_id(agent_id)
        item = (
            (
                await session.execute(
                    text(
                        f"SELECT name,status,current_version_id FROM {self.table('skill_pool_items')} WHERE id=:skill FOR SHARE"
                    ),
                    {"skill": UUID(str(skill_id))},
                )
            )
            .mappings()
            .first()
        )
        grant = (
            await session.execute(
                text(
                    f"SELECT enabled FROM {self.table('skill_pool_agent_grants')} WHERE skill_id=:skill AND agent_id=:agent FOR SHARE"
                ),
                {"skill": UUID(str(skill_id)), "agent": agent},
            )
        ).scalar_one_or_none()
        if item is None or item["status"] != "active" or grant is not True:
            raise AuthorizationDeniedError()
        return dict(item)

    async def bind_installed(self, session, agent_id, name, version, enabled):
        await session.execute(
            text(f"""
            INSERT INTO {self.table('agent_skills')}
                (id,agent_id,name,content_key,enabled,source_pool_version_id,detached)
            VALUES (:id,:agent,:name,:key,:enabled,:version,false)
            ON CONFLICT (agent_id,name) DO UPDATE SET
                content_key=EXCLUDED.content_key,enabled=EXCLUDED.enabled,
                source_pool_version_id=EXCLUDED.source_pool_version_id,detached=false,updated_at=now()
        """),
            {
                "id": uuid4(),
                "agent": agent_database_id(agent_id),
                "name": name,
                "key": "skills/" + name,
                "enabled": enabled,
                "version": version["id"],
            },
        )

    async def mark_detached(self, session, agent_id, name, detached):
        await session.execute(
            text(
                f"UPDATE {self.table('agent_skills')} SET detached=:detached WHERE agent_id=:agent AND name=:name AND source_pool_version_id IS NOT NULL"
            ),
            {"detached": detached, "agent": agent_database_id(agent_id), "name": name},
        )

    async def unbind_installed(self, session, agent_id, name):
        """End the current source relationship without deleting historical request FKs."""
        await session.execute(
            text(
                f"UPDATE {self.table('agent_skills')} SET source_pool_version_id=NULL,detached=false,enabled=false,updated_at=now() WHERE agent_id=:agent AND name=:name"
            ),
            {"agent": agent_database_id(agent_id), "name": name},
        )

    async def rename_installed(self, session, agent_id, old_name, new_name):
        """Move the source row, retaining its identity and version binding."""
        values = {
            "agent": agent_database_id(agent_id),
            "old": old_name,
            "new": new_name,
        }
        await session.execute(
            text(
                f"DELETE FROM {self.table('agent_skills')} WHERE agent_id=:agent AND name=:new"
            ),
            values,
        )
        await session.execute(
            text(
                f"UPDATE {self.table('agent_skills')} SET name=:new,content_key=:key,updated_at=now() WHERE agent_id=:agent AND name=:old"
            ),
            {**values, "key": "skills/" + new_name},
        )

    async def agent_role(self, user_id, agent_id):
        async with self.session_factory() as session:
            return (
                await session.execute(
                    text(f"""
                SELECT CASE WHEN a.owner_user_id=:user THEN 'owner' ELSE m.role END
                FROM {self.table('agents')} a
                JOIN {self.table('users')} u ON u.id=:user AND u.status='active'
                LEFT JOIN {self.table('agent_members')} m ON m.agent_id=a.id AND m.user_id=:user AND m.revoked_at IS NULL
                WHERE a.id=:agent AND a.status='active'
            """),
                    {"user": user_id, "agent": agent_database_id(agent_id)},
                )
            ).scalar_one_or_none()

    async def list_items(self, agent_id=None):
        async with self.session_factory() as session:
            condition = (
                ""
                if agent_id is None
                else f"AND i.status='active' AND EXISTS (SELECT 1 FROM {self.table('skill_pool_agent_grants')} g WHERE g.skill_id=i.id AND g.agent_id=:agent AND g.enabled)"
            )
            rows = (
                (
                    await session.execute(
                        text(f"""
                SELECT i.id,i.name,i.status,v.id AS version_id,v.version,v.content_hash
                FROM {self.table('skill_pool_items')} i
                JOIN {self.table('skill_pool_versions')} v ON v.id=i.current_version_id
                WHERE true {condition} ORDER BY i.name
            """),
                        (
                            {"agent": agent_database_id(agent_id)}
                            if agent_id is not None
                            else {}
                        ),
                    )
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]

    async def get_version(self, version_id):
        async with self.session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"SELECT * FROM {self.table('skill_pool_versions')} WHERE id=:id"
                        ),
                        {"id": UUID(str(version_id))},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ValueError("skill_version_not_found")
            return dict(row)

    async def _audit(self, session, actor_id, action, resource_id):
        await session.execute(
            text(
                f"""INSERT INTO {self.table('audit_logs')}
            (id,actor_user_id,actor_identity_type,action,resource_type,resource_id,result,request_id,source)
            VALUES (:id,:actor,'user',:action,'skill',:resource,'success',:request,'skill_governance')"""
            ),
            {
                "id": uuid4(),
                "actor": actor_id,
                "action": action,
                "resource": resource_id,
                "request": str(uuid4()),
            },
        )

    async def _publish(self, session, name, snapshot, actor_id, snapshots):
        snapshots.verify(snapshot.snapshot_key, snapshot.content_hash)
        await session.execute(
            text(
                f"INSERT INTO {self.table('skill_pool_items')} (id,name,status,created_by) VALUES (:id,:name,'active',:actor) ON CONFLICT (name) DO NOTHING"
            ),
            {"id": uuid4(), "name": name, "actor": actor_id},
        )
        item = (
            (
                await session.execute(
                    text(
                        f"SELECT id FROM {self.table('skill_pool_items')} WHERE name=:name FOR UPDATE"
                    ),
                    {"name": name},
                )
            )
            .mappings()
            .one()
        )
        existing = (
            (
                await session.execute(
                    text(
                        f"SELECT id,content_key,content_hash FROM {self.table('skill_pool_versions')} WHERE skill_id=:id AND content_hash=:hash ORDER BY created_at LIMIT 1"
                    ),
                    {"id": item["id"], "hash": snapshot.content_hash},
                )
            )
            .mappings()
            .first()
        )
        if existing is not None:
            snapshots.verify(existing["content_key"], existing["content_hash"])
        version_id = existing["id"] if existing is not None else uuid4()
        if existing is None:
            await session.execute(
                text(
                    f"INSERT INTO {self.table('skill_pool_versions')} (id,skill_id,version,content_key,content_hash,published_by) VALUES (:id,:skill,:version,:key,:hash,:actor)"
                ),
                {
                    "id": version_id,
                    "skill": item["id"],
                    "version": snapshot.content_hash[:32],
                    "key": snapshot.snapshot_key,
                    "hash": snapshot.content_hash,
                    "actor": actor_id,
                },
            )
        await session.execute(
            text(
                f"UPDATE {self.table('skill_pool_items')} SET current_version_id=:version,updated_at=now() WHERE id=:id"
            ),
            {"version": version_id, "id": item["id"]},
        )
        return version_id

    async def import_snapshots(self, rows, actor_id, snapshots):
        async with self.session_factory() as session:
            for name, snapshot in rows:
                version = await self._publish(
                    session, name, snapshot, actor_id, snapshots
                )
                await self._audit(session, actor_id, "skill.import", version)

    async def set_agent_grant(self, skill_id, agent_id, enabled, actor_id):
        async with self.session_factory() as session:
            active = (
                await session.execute(
                    text(
                        f"SELECT id FROM {self.table('agents')} WHERE id=:agent AND status='active'"
                    ),
                    {"agent": agent_database_id(agent_id)},
                )
            ).scalar_one_or_none()
            item = (
                await session.execute(
                    text(
                        f"SELECT id FROM {self.table('skill_pool_items')} WHERE id=:skill"
                    ),
                    {"skill": UUID(str(skill_id))},
                )
            ).scalar_one_or_none()
            if active is None or item is None:
                raise ValueError("skill_or_agent_not_found")
            await session.execute(
                text(
                    f"INSERT INTO {self.table('skill_pool_agent_grants')} (skill_id,agent_id,enabled,changed_by) VALUES (:skill,:agent,:enabled,:actor) ON CONFLICT (skill_id,agent_id) DO UPDATE SET enabled=EXCLUDED.enabled,changed_by=EXCLUDED.changed_by,updated_at=now()"
                ),
                {"skill": item, "agent": active, "enabled": enabled, "actor": actor_id},
            )
            await self._audit(session, actor_id, "skill.grant", item)
        return {"skill_id": str(item), "agent_id": agent_id, "enabled": enabled}

    async def list_grants(self, skill_id):
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            f"SELECT agent_id,enabled,changed_by,updated_at FROM {self.table('skill_pool_agent_grants')} WHERE skill_id=:skill ORDER BY agent_id"
                        ),
                        {"skill": UUID(str(skill_id))},
                    )
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]

    async def set_item_status(self, skill_id, enabled, actor_id):
        async with self.session_factory() as session:
            status = "active" if enabled else "disabled"
            row = (
                await session.execute(
                    text(
                        f"UPDATE {self.table('skill_pool_items')} SET status=:status,updated_at=now() WHERE id=:id RETURNING id"
                    ),
                    {"id": UUID(str(skill_id)), "status": status},
                )
            ).scalar_one_or_none()
            if row is None:
                raise ValueError("skill_not_found")
            await self._audit(session, actor_id, "skill.status", row)
        return {"id": str(row), "status": status}

    async def create_request(self, agent_id, name, snapshot, actor_id):
        async with self.session_factory() as session:
            # Register only the FK identity of an existing local skill; never persist private config.
            await session.execute(
                text(
                    f"INSERT INTO {self.table('agent_skills')} (id,agent_id,name,content_key) VALUES (:id,:agent,:name,:key) ON CONFLICT (agent_id,name) DO NOTHING"
                ),
                {
                    "id": uuid4(),
                    "agent": agent_database_id(agent_id),
                    "name": name,
                    "key": "skills/" + name,
                },
            )
            skill = (
                await session.execute(
                    text(
                        f"SELECT id FROM {self.table('agent_skills')} WHERE agent_id=:agent AND name=:name"
                    ),
                    {"agent": agent_database_id(agent_id), "name": name},
                )
            ).scalar_one()
            request_id = uuid4()
            await session.execute(
                text(
                    f"INSERT INTO {self.table('skill_publish_requests')} (id,agent_skill_id,submitted_by,status,snapshot_key,content_hash,skill_name) VALUES (:id,:skill,:actor,'pending',:key,:hash,:name)"
                ),
                {
                    "id": request_id,
                    "skill": skill,
                    "actor": actor_id,
                    "key": snapshot.snapshot_key,
                    "hash": snapshot.content_hash,
                    "name": name,
                },
            )
            await self._audit(session, actor_id, "skill.request.submit", request_id)
        return {
            "id": str(request_id),
            "status": "pending",
            "review_version": 0,
            "content_hash": snapshot.content_hash,
        }

    async def get_request(self, request_id):
        async with self.session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"SELECT * FROM {self.table('skill_publish_requests')} WHERE id=:id"
                        ),
                        {"id": UUID(str(request_id))},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ValueError("request_not_found")
            return dict(row)

    async def list_requests(self):
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            f"""SELECT r.id,r.skill_name,r.submitted_by,
                            COALESCE(NULLIF(u.display_name,''),u.username) AS applicant_name,
                            a.id AS agent_id,a.name AS agent_name,
                            r.status,r.content_hash,r.review_version,
                            r.published_version_id,r.reviewed_by,r.review_note,
                            r.created_at,r.reviewed_at
                            FROM {self.table('skill_publish_requests')} r
                            LEFT JOIN {self.table('agent_skills')} s ON s.id=r.agent_skill_id
                            LEFT JOIN {self.table('agents')} a ON a.id=s.agent_id
                            LEFT JOIN {self.table('users')} u ON u.id=r.submitted_by
                            ORDER BY CASE WHEN r.status='pending' THEN 0 ELSE 1 END,
                            r.created_at DESC"""
                        )
                    )
                )
                .mappings()
                .all()
            )
            return [dict(row) for row in rows]

    async def review_request(
        self, request_id, decision, expected_version, note, actor_id, snapshots
    ):
        from .records import SkillSnapshot

        async with self.session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"SELECT * FROM {self.table('skill_publish_requests')} WHERE id=:id FOR UPDATE"
                        ),
                        {"id": UUID(str(request_id))},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise ValueError("request_not_found")
            target_status = "approved" if decision == "approve" else "rejected"
            if row["status"] != "pending":
                if row["status"] == target_status:
                    return self._review_result(row)
                raise ValueError("request_already_reviewed")
            if row["review_version"] != expected_version:
                raise ValueError("version_conflict")
            published = None
            if decision == "approve":
                if (
                    not row["snapshot_key"]
                    or not row["content_hash"]
                    or not row["skill_name"]
                ):
                    raise ValueError("request_snapshot_required")
                snapshots.verify(row["snapshot_key"], row["content_hash"])
                published = await self._publish(
                    session,
                    row["skill_name"],
                    SkillSnapshot(row["snapshot_key"], row["content_hash"]),
                    actor_id,
                    snapshots,
                )
            updated = (
                (
                    await session.execute(
                        text(
                            f"UPDATE {self.table('skill_publish_requests')} SET status=:status,review_version=review_version+1,reviewed_by=:actor,review_note=:note,reviewed_at=now(),published_version_id=:version WHERE id=:id RETURNING *"
                        ),
                        {
                            "id": row["id"],
                            "status": target_status,
                            "actor": actor_id,
                            "note": note,
                            "version": published,
                        },
                    )
                )
                .mappings()
                .one()
            )
            await self._audit(session, actor_id, "skill.request." + decision, row["id"])
            return self._review_result(updated)

    @staticmethod
    def _review_result(row):
        return {
            "id": str(row["id"]),
            "status": row["status"],
            "review_version": row["review_version"],
            "published_version_id": (
                str(row["published_version_id"])
                if row["published_version_id"]
                else None
            ),
        }
