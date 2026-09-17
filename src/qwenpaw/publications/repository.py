# -*- coding: utf-8 -*-
"""共享应用发布的 PostgreSQL Repository。"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncContextManager
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ..persistence.database import database_session
from .models import (
    ReviewStatus,
    SharedAppDraftRecord,
    SharedAppPublicationRecord,
    SharedAppRecord,
    SharedAppUserWorkspaceRecord,
)

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class PublicationStateConflict(RuntimeError):
    """发布状态或并发前置条件不成立。"""


class PublicationImmutableError(RuntimeError):
    """数据库拒绝修改不可变发布字段。"""


class PostgresSharedAppRepository:
    def __init__(
        self,
        *,
        schema: str,
        session_factory: Callable[[], AsyncContextManager[Any]] = database_session,
    ) -> None:
        normalized = schema.strip().lower()
        if not _SAFE_SCHEMA.fullmatch(normalized):
            raise ValueError("unsafe_postgres_schema")
        self.schema = normalized
        self._session_factory = session_factory

    def _table(self, name: str) -> str:
        return f'"{self.schema}"."{name}"'

    @asynccontextmanager
    async def _session(self):
        async with self._session_factory() as session:
            yield session

    @staticmethod
    def _row(row: Any, model: type[Any]) -> Any:
        mapping = row._mapping if hasattr(row, "_mapping") else row
        return model.model_validate(dict(mapping))

    @staticmethod
    def _json(value: dict[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    async def create_app(
        self, record: SharedAppRecord, *, request_id: str = "system"
    ) -> SharedAppRecord:
        async with self._session() as session:
            row = (
                await session.execute(
                    text(
                        f"INSERT INTO {self._table('shared_apps')} "
                        "(id,agent_id,owner_user_id,status,current_publication_id,created_at,updated_at) "
                        "VALUES (:id,:agent_id,:owner_user_id,:status,:current_publication_id,:created_at,:updated_at) "
                        "ON CONFLICT (agent_id) DO NOTHING RETURNING *"
                    ),
                    record.model_dump(),
                )
            ).mappings().first()
            if row is None:
                existing = (
                    await session.execute(
                        text(
                            f"SELECT * FROM {self._table('shared_apps')} WHERE agent_id=:agent_id"
                        ),
                        {"agent_id": record.agent_id},
                    )
                ).mappings().one()
                candidate = self._row(existing, SharedAppRecord)
                if candidate != record:
                    raise PublicationStateConflict("shared_app_conflict")
                return candidate
            created = self._row(row, SharedAppRecord)
            await self._write_audit(
                session,
                actor_id=record.owner_user_id,
                action="shared_app.create",
                resource_type="shared_app",
                resource_id=record.id,
                request_id=request_id,
            )
            return created

    async def create_draft(
        self, record: SharedAppDraftRecord, *, request_id: str = "system"
    ) -> SharedAppDraftRecord:
        values = record.model_dump(exclude={"manifest"})
        values["manifest"] = self._json(record.manifest)
        async with self._session() as session:
            row = (
                await session.execute(
                    text(
                        f"INSERT INTO {self._table('shared_app_drafts')} "
                        "(id,shared_app_id,revision,manifest,workspace_key,created_by,updated_at) "
                        "VALUES (:id,:shared_app_id,:revision,CAST(:manifest AS json),:workspace_key,:created_by,:updated_at) "
                        "RETURNING *"
                    ),
                    values,
                )
            ).mappings().one()
            await self._write_audit(
                session,
                actor_id=record.created_by,
                action="shared_app.draft.save",
                resource_type="shared_app",
                resource_id=record.shared_app_id,
                request_id=request_id,
            )
        return self._row(row, SharedAppDraftRecord)

    async def create_submission(
        self, record: SharedAppPublicationRecord, *, request_id: str = "system"
    ) -> SharedAppPublicationRecord:
        values = record.model_dump(exclude={"immutable_manifest"})
        values["immutable_manifest"] = self._json(record.immutable_manifest)
        async with self._session() as session:
            row = (
                await session.execute(
                    text(
                        f"INSERT INTO {self._table('shared_app_publications')} "
                        "(id,shared_app_id,version,immutable_manifest,baseline_workspace_key,"
                        "submitted_by,reviewed_by,review_status,review_note,reviewed_at,published_at,retired_at) "
                        "VALUES (:id,:shared_app_id,:version,CAST(:immutable_manifest AS json),"
                        ":baseline_workspace_key,:submitted_by,:reviewed_by,:review_status,:review_note,"
                        ":reviewed_at,:published_at,:retired_at) RETURNING *"
                    ),
                    values,
                )
            ).mappings().one()
            await self._write_audit(
                session,
                actor_id=record.submitted_by,
                action="shared_app.publication.submit",
                resource_type="shared_app_publication",
                resource_id=record.id,
                request_id=request_id,
            )
        return self._row(row, SharedAppPublicationRecord)

    async def get_app(self, app_id: UUID, *, for_update: bool = False):
        lock = " FOR UPDATE" if for_update else ""
        async with self._session() as session:
            row = (
                await session.execute(
                    text(
                        f"SELECT * FROM {self._table('shared_apps')} WHERE id=:id{lock}"
                    ),
                    {"id": app_id},
                )
            ).mappings().first()
        return self._row(row, SharedAppRecord) if row else None

    async def get_app_by_agent(self, agent_id: UUID):
        async with self._session() as session:
            row = (
                await session.execute(
                    text(
                        f"SELECT * FROM {self._table('shared_apps')} WHERE agent_id=:agent"
                    ),
                    {"agent": agent_id},
                )
            ).mappings().first()
        return self._row(row, SharedAppRecord) if row else None

    async def get_agent_owner(self, agent_id: UUID) -> UUID | None:
        async with self._session() as session:
            return (
                await session.execute(
                    text(
                        f"SELECT owner_user_id FROM {self._table('agents')} "
                        "WHERE id=:agent AND status<>'deleted'"
                    ),
                    {"agent": agent_id},
                )
            ).scalar_one_or_none()

    async def build_dependency_manifest(self, agent_id: UUID) -> dict[str, Any]:
        """从治理事实生成可发布依赖引用，不读取客户端声明。"""
        async with self._session() as session:
            skills = (
                await session.execute(
                    text(
                        f"SELECT v.id,v.content_hash FROM {self._table('agent_skills')} s "
                        f"JOIN {self._table('skill_pool_versions')} v "
                        "ON v.id=s.source_pool_version_id "
                        "WHERE s.agent_id=:agent AND s.enabled"
                    ),
                    {"agent": agent_id},
                )
            ).mappings().all()
            drivers = (
                await session.execute(
                    text(
                        f"SELECT d.id,d.credential_binding_id,r.revision,r.tool_allowlist "
                        f"FROM {self._table('agent_drivers')} d "
                        f"JOIN {self._table('driver_revisions')} r "
                        "ON r.id=d.current_revision_id "
                        "WHERE d.agent_id=:agent AND d.status='active'"
                    ),
                    {"agent": agent_id},
                )
            ).mappings().all()
            plugins = (
                await session.execute(
                    text(
                        f"SELECT p.id,p.version FROM {self._table('agent_plugin_settings')} s "
                        f"JOIN {self._table('plugin_installations')} p "
                        "ON p.id=s.plugin_installation_id "
                        "WHERE s.agent_id=:agent AND s.enabled AND p.status='active'"
                    ),
                    {"agent": agent_id},
                )
            ).mappings().all()
        return {
            "skills": [
                {"id": str(row["id"]), "content_hash": row["content_hash"]}
                for row in skills
            ],
            "mcp": [
                {
                    "id": str(row["id"]),
                    "revision": row["revision"],
                    "tool_allowlist": row["tool_allowlist"],
                }
                for row in drivers
            ],
            "plugins": [
                {"id": str(row["id"]), "version": row["version"]}
                for row in plugins
            ],
            "credentials": [
                {"id": str(row["credential_binding_id"]), "purpose": "mcp"}
                for row in drivers
                if row["credential_binding_id"] is not None
            ],
        }

    async def get_source_workspace_key(self, app_id: UUID) -> str | None:
        async with self._session() as session:
            return (
                await session.execute(
                    text(
                        f"SELECT a.draft_workspace_key FROM {self._table('shared_apps')} s "
                        f"JOIN {self._table('agents')} a ON a.id=s.agent_id WHERE s.id=:id"
                    ),
                    {"id": app_id},
                )
            ).scalar_one_or_none()

    async def get_draft(self, app_id: UUID, revision: int):
        async with self._session() as session:
            row = (
                await session.execute(
                    text(
                        f"SELECT * FROM {self._table('shared_app_drafts')} "
                        "WHERE shared_app_id=:app AND revision=:revision"
                    ),
                    {"app": app_id, "revision": revision},
                )
            ).mappings().first()
        return self._row(row, SharedAppDraftRecord) if row else None

    async def latest_draft(self, app_id: UUID):
        async with self._session() as session:
            row = (
                await session.execute(
                    text(
                        f"SELECT * FROM {self._table('shared_app_drafts')} "
                        "WHERE shared_app_id=:app ORDER BY revision DESC LIMIT 1"
                    ),
                    {"app": app_id},
                )
            ).mappings().first()
        return self._row(row, SharedAppDraftRecord) if row else None

    async def list_drafts(self, app_id: UUID):
        async with self._session() as session:
            rows = (
                await session.execute(
                    text(
                        f"SELECT * FROM {self._table('shared_app_drafts')} "
                        "WHERE shared_app_id=:app ORDER BY revision DESC"
                    ),
                    {"app": app_id},
                )
            ).mappings().all()
        return [self._row(row, SharedAppDraftRecord) for row in rows]

    async def list_publications(self, app_id: UUID):
        async with self._session() as session:
            rows = (
                await session.execute(
                    text(
                        f"SELECT * FROM {self._table('shared_app_publications')} "
                        "WHERE shared_app_id=:app ORDER BY id DESC"
                    ),
                    {"app": app_id},
                )
            ).mappings().all()
        return [self._row(row, SharedAppPublicationRecord) for row in rows]

    async def list_mine(self, owner_user_id: UUID):
        async with self._session() as session:
            rows = (
                await session.execute(
                    text(
                        f"SELECT * FROM {self._table('shared_apps')} "
                        "WHERE owner_user_id=:owner ORDER BY updated_at DESC"
                    ),
                    {"owner": owner_user_id},
                )
            ).mappings().all()
        return [self._row(row, SharedAppRecord) for row in rows]

    async def list_catalog(self):
        async with self._session() as session:
            rows = (
                await session.execute(
                    text(
                        f"SELECT p.* FROM {self._table('shared_apps')} s "
                        f"JOIN {self._table('shared_app_publications')} p "
                        "ON p.id=s.current_publication_id "
                        "WHERE s.status='active' AND p.review_status='approved' "
                        "ORDER BY s.updated_at DESC"
                    )
                )
            ).mappings().all()
        return [self._row(row, SharedAppPublicationRecord) for row in rows]

    async def list_pending(self):
        async with self._session() as session:
            rows = (
                await session.execute(
                    text(
                        f"SELECT * FROM {self._table('shared_app_publications')} "
                        "WHERE review_status='pending' ORDER BY id"
                    )
                )
            ).mappings().all()
        return [self._row(row, SharedAppPublicationRecord) for row in rows]

    async def list_admin_publications(self):
        async with self._session() as session:
            rows = (
                await session.execute(
                    text(
                        f"SELECT p.*,s.status AS app_status,s.current_publication_id "
                        f"FROM {self._table('shared_app_publications')} p "
                        f"JOIN {self._table('shared_apps')} s ON s.id=p.shared_app_id "
                        "ORDER BY p.reviewed_at NULLS FIRST,p.id"
                    )
                )
            ).mappings().all()
        return [
            {
                "publication": self._row(row, SharedAppPublicationRecord),
                "app_status": row["app_status"],
                "current_publication_id": row["current_publication_id"],
            }
            for row in rows
        ]

    async def get_publication(self, publication_id: UUID):
        async with self._session() as session:
            row = (
                await session.execute(
                    text(
                        f"SELECT * FROM {self._table('shared_app_publications')} WHERE id=:id"
                    ),
                    {"id": publication_id},
                )
            ).mappings().first()
        return self._row(row, SharedAppPublicationRecord) if row else None

    async def review(
        self,
        publication_id: UUID,
        *,
        reviewer_id: UUID,
        decision: ReviewStatus,
        note: str,
        reviewed_at: datetime,
        request_id: str = "system",
    ) -> SharedAppPublicationRecord:
        if decision not in {"approved", "rejected"}:
            raise ValueError("invalid_review_decision")
        async with self._session() as session:
            row = (
                await session.execute(
                    text(
                        f"UPDATE {self._table('shared_app_publications')} SET "
                        "reviewed_by=:reviewer,review_status=:decision,review_note=:note,reviewed_at=:reviewed_at "
                        "WHERE id=:id AND review_status='pending' RETURNING *"
                    ),
                    {
                        "id": publication_id,
                        "reviewer": reviewer_id,
                        "decision": decision,
                        "note": note,
                        "reviewed_at": reviewed_at,
                    },
                )
            ).mappings().first()
            if row is None:
                raise PublicationStateConflict("publication_not_pending")
            await self._write_audit(
                session,
                actor_id=reviewer_id,
                action=f"shared_app.publication.{decision}",
                resource_type="shared_app_publication",
                resource_id=publication_id,
                request_id=request_id,
            )
        return self._row(row, SharedAppPublicationRecord)

    async def switch_current(
        self,
        app_id: UUID,
        *,
        publication_id: UUID,
        expected_current_id: UUID | None,
        actor_id: UUID,
        changed_at: datetime,
        request_id: str = "system",
        audit_action: str = "shared_app.publication.publish",
    ) -> SharedAppRecord:
        try:
            async with self._session() as session:
                app_row = (
                    await session.execute(
                        text(
                            f"SELECT * FROM {self._table('shared_apps')} WHERE id=:id FOR UPDATE"
                        ),
                        {"id": app_id},
                    )
                ).mappings().first()
                if app_row is None:
                    raise PublicationStateConflict("shared_app_not_found")
                app = self._row(app_row, SharedAppRecord)
                if app.current_publication_id != expected_current_id:
                    raise PublicationStateConflict("publication_state_changed")
                publication = (
                    await session.execute(
                        text(
                            f"SELECT * FROM {self._table('shared_app_publications')} "
                            "WHERE id=:publication AND shared_app_id=:app FOR UPDATE"
                        ),
                        {"publication": publication_id, "app": app_id},
                    )
                ).mappings().first()
                if publication is None or publication["review_status"] != "approved":
                    raise PublicationStateConflict("publication_not_approved")
                if app.current_publication_id is not None:
                    await session.execute(
                        text(
                            f"UPDATE {self._table('shared_app_publications')} "
                            "SET retired_at=:changed WHERE id=:current"
                        ),
                        {"changed": changed_at, "current": app.current_publication_id},
                    )
                await session.execute(
                    text(
                        f"UPDATE {self._table('shared_app_publications')} SET "
                        "published_at=COALESCE(published_at,:changed),retired_at=NULL WHERE id=:target"
                    ),
                    {"changed": changed_at, "target": publication_id},
                )
                updated = (
                    await session.execute(
                        text(
                            f"UPDATE {self._table('shared_apps')} SET "
                            "current_publication_id=:publication,status='active',updated_at=:changed "
                            "WHERE id=:app RETURNING *"
                        ),
                        {
                            "publication": publication_id,
                            "changed": changed_at,
                            "app": app_id,
                        },
                    )
                ).mappings().one()
                await self._write_audit(
                    session,
                    actor_id=actor_id,
                    action=audit_action,
                    resource_type="shared_app_publication",
                    resource_id=publication_id,
                    request_id=request_id,
                )
                return self._row(updated, SharedAppRecord)
        except DBAPIError as exc:
            if "shared_app_publication_immutable" in str(exc):
                raise PublicationImmutableError(
                    "shared_app_publication_immutable"
                ) from exc
            raise

    async def get_user_workspace(
        self, app_id: UUID, publication_id: UUID, user_id: UUID
    ) -> SharedAppUserWorkspaceRecord | None:
        async with self._session() as session:
            row = (
                await session.execute(
                    text(
                        f"SELECT * FROM {self._table('shared_app_user_workspaces')} "
                        "WHERE shared_app_id=:app AND publication_id=:publication AND user_id=:user"
                    ),
                    {"app": app_id, "publication": publication_id, "user": user_id},
                )
            ).mappings().first()
        return self._row(row, SharedAppUserWorkspaceRecord) if row else None

    async def retire(
        self,
        app_id: UUID,
        *,
        expected_current_id: UUID,
        actor_id: UUID,
        changed_at: datetime,
        request_id: str = "system",
    ) -> SharedAppRecord:
        async with self._session() as session:
            app_row = (
                await session.execute(
                    text(
                        f"SELECT * FROM {self._table('shared_apps')} WHERE id=:id FOR UPDATE"
                    ),
                    {"id": app_id},
                )
            ).mappings().first()
            if app_row is None:
                raise PublicationStateConflict("shared_app_not_found")
            app = self._row(app_row, SharedAppRecord)
            if app.current_publication_id != expected_current_id:
                raise PublicationStateConflict("publication_state_changed")
            await session.execute(
                text(
                    f"UPDATE {self._table('shared_app_publications')} "
                    "SET retired_at=:changed WHERE id=:publication"
                ),
                {"changed": changed_at, "publication": expected_current_id},
            )
            row = (
                await session.execute(
                    text(
                        f"UPDATE {self._table('shared_apps')} SET "
                        "current_publication_id=NULL,status='retired',updated_at=:changed "
                        "WHERE id=:app RETURNING *"
                    ),
                    {"changed": changed_at, "app": app_id},
                )
            ).mappings().one()
            await self._write_audit(
                session,
                actor_id=actor_id,
                action="shared_app.retire",
                resource_type="shared_app",
                resource_id=app_id,
                request_id=request_id,
            )
        return self._row(row, SharedAppRecord)

    async def _write_audit(
        self,
        session,
        *,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID,
        request_id: str,
    ) -> None:
        await session.execute(
            text(
                f"INSERT INTO {self._table('audit_logs')} "
                "(id,actor_user_id,actor_identity_type,action,resource_type,"
                "resource_id,result,request_id,source,redacted_detail) VALUES "
                "(:id,:actor,'user',:action,:resource_type,:resource,"
                "'success',:request,'web',CAST('{}' AS jsonb))"
            ),
            {
                "id": uuid4(),
                "actor": actor_id,
                "action": action,
                "resource_type": resource_type,
                "resource": resource_id,
                "request": request_id,
            },
        )

    async def create_user_workspace(
        self,
        record: SharedAppUserWorkspaceRecord,
        *,
        request_id: str = "system",
    ) -> SharedAppUserWorkspaceRecord:
        async with self._session() as session:
            row = (
                await session.execute(
                    text(
                        f"INSERT INTO {self._table('shared_app_user_workspaces')} "
                        "(shared_app_id,publication_id,user_id,workspace_key,quota,status,created_at,updated_at) "
                        "VALUES (:shared_app_id,:publication_id,:user_id,:workspace_key,:quota,:status,:created_at,:updated_at) "
                        "ON CONFLICT (shared_app_id,publication_id,user_id) DO UPDATE "
                        "SET workspace_key=EXCLUDED.workspace_key RETURNING *"
                    ),
                    record.model_dump(),
                )
            ).mappings().one()
            await self._write_audit(
                session,
                actor_id=record.user_id,
                action="shared_app.workspace.create",
                resource_type="shared_app_publication",
                resource_id=record.publication_id,
                request_id=request_id,
            )
        return self._row(row, SharedAppUserWorkspaceRecord)
