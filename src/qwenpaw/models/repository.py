"""Schema-qualified metadata, grants, and audited setting transactions."""

import json
import re
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from ..access.agent_repository import agent_database_id
from ..persistence.database import database_session


class PostgresModelRepository:
    def __init__(self, *, schema, session_factory=database_session):
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
            raise ValueError("Unsafe PostgreSQL schema name")
        self.schema = schema
        self.session_factory = session_factory

    def table(self, name):
        return f'"{self.schema}"."{name}"'

    async def get_status(self):
        async with self.session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"SELECT value,version FROM {self.table('system_settings')} WHERE key='model_governance'"
                        )
                    )
                )
                .mappings()
                .first()
            )
            return (
                {"enforced": bool(row["value"]["enforced"]), "version": row["version"]}
                if row
                else {"enforced": False, "version": 0}
            )

    async def import_metadata(self, rows, actor_id):
        async with self.session_factory() as session:
            for row in rows:
                pid = uuid5(
                    NAMESPACE_URL, "qwenpaw:model-provider:" + row["provider_id"]
                )
                await session.execute(
                    text(f"""
                        INSERT INTO {self.table('model_providers')} (id,name,type,status,base_url_metadata,created_by)
                        VALUES (:id,:name,'runtime','active',CAST(:metadata AS jsonb),:actor)
                        ON CONFLICT (name)
                        DO UPDATE SET base_url_metadata=EXCLUDED.base_url_metadata,updated_at=now()
                        """),
                    {
                        "id": pid,
                        "name": row["provider_id"],
                        "metadata": json.dumps({"display_name": row["provider_name"]}),
                        "actor": actor_id,
                    },
                )
                caps = {
                    key: row[key]
                    for key in ("supports_image", "supports_video", "max_input_length")
                }
                await session.execute(
                    text(f"""
                        INSERT INTO {self.table('models')} (id,provider_id,model_key,display_name,capabilities,status)
                        VALUES (:id,:provider,:model,:name,CAST(:caps AS jsonb),'active')
                        ON CONFLICT (provider_id,model_key)
                        DO UPDATE SET display_name=EXCLUDED.display_name,capabilities=EXCLUDED.capabilities,updated_at=now()
                        """),
                    {
                        "id": UUID(row["id"]),
                        "provider": pid,
                        "model": row["model"],
                        "name": row["name"],
                        "caps": json.dumps(caps),
                    },
                )

    async def list_models(self):
        async with self.session_factory() as session:
            rows = (await session.execute(text(f"""
                            SELECT m.id,m.model_key AS model,m.display_name AS name,m.status,p.status AS provider_status,p.name AS provider_id,p.base_url_metadata->>'display_name' AS provider_name,m.capabilities,
                            COALESCE((SELECT jsonb_agg(jsonb_build_object(
                                'user_id',g.subject_id,'username',u.username,'enabled',g.enabled
                            ) ORDER BY u.username)
                            FROM {self.table('model_grants')} g
                            JOIN {self.table('users')} u ON u.id=g.subject_id
                            WHERE g.model_id=m.id AND g.subject_type='user'), '[]'::jsonb) AS user_grants
                            FROM {self.table('models')} m
                            JOIN {self.table('model_providers')} p ON p.id=m.provider_id
                            ORDER BY p.name,m.model_key
                            """))).mappings().all()
            return [{**dict(row), "id": str(row["id"])} for row in rows]

    async def list_users(self):
        async with self.session_factory() as session:
            rows = (await session.execute(text(f"""
                            SELECT id,username
                            FROM {self.table('users')}
                            WHERE status='active'
                            AND platform_role='member'
                            ORDER BY username
                            """))).mappings().all()
            return [dict(row) for row in rows]

    async def allowed_models(self, user_id, agent_id):
        # Agent grants only apply while the caller can actually use that Agent.
        async with self.session_factory() as session:
            rows = await session.execute(
                text(f"""
                    SELECT DISTINCT g.model_id
                    FROM {self.table('model_grants')} g
                    WHERE g.enabled
                    AND ((g.subject_type='user'
                    AND g.subject_id=:user)
                    OR (g.subject_type='platform'
                    AND g.subject_id IS NULL)
                    OR (g.subject_type='agent'
                    AND g.subject_id=:agent
                    AND EXISTS (SELECT 1
                    FROM {self.table('agents')} a
                    WHERE a.id=:agent
                    AND a.status='active'
                    AND (a.owner_user_id=:user
                    OR a.visibility='public'
                    OR EXISTS (SELECT 1
                    FROM {self.table('agent_members')} am
                    WHERE am.agent_id=a.id
                    AND am.user_id=:user
                    AND am.revoked_at IS NULL)))))
                    """),
                {
                    "user": user_id,
                    "agent": agent_database_id(agent_id) if agent_id else None,
                },
            )
            return {str(value) for value in rows.scalars().all()}

    async def set_user_grant(self, model_id, user_id, enabled, actor_id):
        async with self.session_factory() as session:
            valid = (
                await session.execute(
                    text(
                        f"SELECT 1 FROM {self.table('users')} WHERE id=:id AND status='active'"
                    ),
                    {"id": user_id},
                )
            ).first()
            if not valid:
                raise ValueError("user_unavailable")
            model = (
                await session.execute(
                    text(f"SELECT 1 FROM {self.table('models')} WHERE id=:id"),
                    {"id": UUID(str(model_id))},
                )
            ).first()
            if not model:
                raise ValueError("model_not_found")
            await session.execute(
                text(f"""
                    INSERT INTO {self.table('model_grants')} (id,model_id,subject_type,subject_id,enabled,created_by)
                    VALUES (:id,:model,'user',:user,:enabled,:actor)
                    ON CONFLICT (model_id,subject_type,subject_id)
                    DO UPDATE SET enabled=EXCLUDED.enabled
                    """),
                {
                    "id": uuid4(),
                    "model": UUID(str(model_id)),
                    "user": user_id,
                    "enabled": enabled,
                    "actor": actor_id,
                },
            )
        return {"enabled": enabled}

    async def set_model_status(self, model_id, enabled):
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    text(
                        f"UPDATE {self.table('models')} SET status=:status,updated_at=now() WHERE id=:id RETURNING id"
                    ),
                    {
                        "id": UUID(str(model_id)),
                        "status": "active" if enabled else "disabled",
                    },
                )
            ).first()
            if not row:
                raise ValueError("model_not_found")
        return {"enabled": enabled}

    async def set_enforced(self, enabled, expected_version, reason, actor_id):
        async with self.session_factory() as session:
            # Serialize the initial absent-row case as well as ordinary updates.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
                {"key": self.schema + ":model_governance"},
            )
            row = (await session.execute(text(f"""
                            SELECT value,version
                            FROM {self.table('system_settings')}
                            WHERE key='model_governance' FOR UPDATE
                            """))).mappings().first()
            version = row["version"] if row else 0
            if expected_version != version:
                raise ValueError("version_conflict")
            value = json.dumps({"enforced": enabled})
            await session.execute(
                text(f"""
                    INSERT INTO {self.table('system_settings')} (key,value,version,updated_by)
                    VALUES ('model_governance',CAST(:value AS jsonb),:version,:actor)
                    ON CONFLICT (key)
                    DO UPDATE SET value=EXCLUDED.value,version=EXCLUDED.version,updated_by=EXCLUDED.updated_by,updated_at=now()
                    """),
                {"value": value, "version": version + 1, "actor": actor_id},
            )
            await session.execute(
                text(f"""
                    INSERT INTO {self.table('system_setting_revisions')} (id,key,old_value,new_value,changed_by,reason)
                    VALUES (:id,'model_governance',CAST(:old AS jsonb),CAST(:new AS jsonb),:actor,:reason)
                    """),
                {
                    "id": uuid4(),
                    "old": json.dumps(row["value"]) if row else None,
                    "new": value,
                    "actor": actor_id,
                    "reason": reason,
                },
            )
            return {"enforced": enabled, "version": version + 1}

    async def references(self, model_ids):
        try:
            return await self._visible_references(model_ids)
        except DBAPIError as exc:
            raise ValueError("model_reference_authority_unavailable") from exc

    async def _visible_references(self, model_ids):
        async with self.session_factory() as session:
            # This does not bypass RLS: PostgreSQL rejects queries whose rows
            # would be filtered. Never interpret partial visibility as unused.
            await session.execute(text("SET LOCAL row_security = off"))
            publications = (
                await session.execute(
                    text(
                        f"SELECT count(*) FROM {self.table('shared_app_publications')}"
                    )
                )
            ).scalar_one()
            if publications:
                raise ValueError("publication_reference_unavailable")
            rows = (
                (
                    await session.execute(
                        text(
                            f"SELECT id,agent_id FROM {self.table('conversations')} WHERE model_override_id=ANY(:ids)"
                        ),
                        {"ids": [UUID(str(mid)) for mid in model_ids]},
                    )
                )
                .mappings()
                .all()
            )
            return [
                {"conversation_id": str(row["id"]), "agent_id": str(row["agent_id"])}
                for row in rows
            ]
