# -*- coding: utf-8 -*-
"""PostgreSQL automation repository for multi-user mode."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text

from ....access.agent_repository import agent_database_id
from ....persistence.database import database_session
from ..models import (
    AutomationAuthorization,
    AutomationGrant,
    CronExecutionRecord,
    CronJobSpec,
    JobsFile,
)
from .base import BaseJobRepository

_SAFE_SCHEMA = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class PostgresJobRepository(BaseJobRepository):
    """Store one Agent's schedules and grants in PostgreSQL."""

    def __init__(
        self,
        *,
        agent_key: str,
        schema: str,
        session_factory=database_session,
    ) -> None:
        if not _SAFE_SCHEMA.fullmatch(schema):
            raise ValueError("invalid_database_schema")
        self.agent_key = agent_key
        self.agent_id = agent_database_id(agent_key)
        self.schema = schema
        self.session_factory = session_factory

    def table(self, name: str) -> str:
        return f'"{self.schema}"."{name}"'

    @staticmethod
    def _task_payload(spec: CronJobSpec) -> dict:
        return {
            "enabled": spec.enabled,
            "task_type": spec.task_type,
            "text": spec.text,
            "request": (
                spec.request.model_dump(mode="json") if spec.request else None
            ),
            "save_result_to_inbox": spec.save_result_to_inbox,
            "runtime": spec.runtime.model_dump(mode="json"),
            "meta": spec.meta,
        }

    @classmethod
    def _scope_payload(cls, spec: CronJobSpec) -> dict:
        return {
            "schedule": spec.schedule.model_dump(mode="json"),
            "task": cls._task_payload(spec),
            "dispatch": spec.dispatch.model_dump(mode="json"),
        }

    @staticmethod
    def _job(row) -> CronJobSpec:
        task = dict(row["task"])
        return CronJobSpec.model_validate(
            {
                "id": str(row["id"]),
                "name": row["name"],
                "enabled": task.get("enabled", row["status"] == "active"),
                "schedule": row["schedule"],
                "task_type": task.get("task_type", "agent"),
                "text": task.get("text"),
                "request": task.get("request"),
                "save_result_to_inbox": task.get("save_result_to_inbox"),
                "runtime": task.get("runtime", {}),
                "meta": task.get("meta", {}),
                "dispatch": row["dispatch"],
                "created_by_user_id": row["created_by_user_id"],
                "automation_owner_user_id": row["automation_owner_user_id"],
                "status": row["status"],
                "config_version": row["config_version"],
            }
        )

    def _select(self) -> str:
        return (
            "id,name,schedule,task,dispatch,status,config_version,"
            "created_by_user_id,automation_owner_user_id"
        )

    async def load(self) -> JobsFile:
        return JobsFile(jobs=await self.list_jobs())

    async def save(self, jobs_file: JobsFile) -> None:
        existing = {job.id for job in await self.list_jobs()}
        desired = {job.id for job in jobs_file.jobs}
        for job in jobs_file.jobs:
            await self.upsert_job(job)
        for job_id in existing - desired:
            if job_id is not None:
                await self.delete_job(job_id)

    async def list_jobs(self) -> list[CronJobSpec]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            f"SELECT {self._select()} FROM "
                            f"{self.table('automation_schedules')} "
                            "WHERE agent_id=:agent ORDER BY created_at,id"
                        ),
                        {"agent": self.agent_id},
                    )
                )
                .mappings()
                .all()
            )
        return [self._job(row) for row in rows]

    async def get_job(self, job_id: str) -> CronJobSpec | None:
        async with self.session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"SELECT {self._select()} FROM "
                            f"{self.table('automation_schedules')} "
                            "WHERE id=:id AND agent_id=:agent"
                        ),
                        {"id": job_id, "agent": self.agent_id},
                    )
                )
                .mappings()
                .first()
            )
        return self._job(row) if row else None

    async def upsert_job(self, spec: CronJobSpec) -> None:
        if spec.id is None or spec.created_by_user_id is None:
            raise ValueError("automation_identity_required")
        owner = spec.automation_owner_user_id or spec.created_by_user_id
        schedule = spec.schedule.model_dump(mode="json")
        task = self._task_payload(spec)
        dispatch = spec.dispatch.model_dump(mode="json")
        async with self.session_factory() as session:
            current = (
                (
                    await session.execute(
                        text(
                            f"SELECT schedule,task,dispatch,status,config_version "
                            f"FROM {self.table('automation_schedules')} "
                            "WHERE id=:id AND agent_id=:agent FOR UPDATE"
                        ),
                        {"id": spec.id, "agent": self.agent_id},
                    )
                )
                .mappings()
                .first()
            )
            if current is None:
                await session.execute(
                    text(
                        f"INSERT INTO {self.table('automation_schedules')} "
                        "(id,agent_id,created_by_user_id,automation_owner_user_id,"
                        "type,name,schedule,timezone,task,dispatch,status,config_version) "
                        "VALUES (:id,:agent,:creator,:owner,:type,:name,CAST(:schedule AS jsonb),"
                        ":timezone,CAST(:task AS jsonb),CAST(:dispatch AS jsonb),:status,:version)"
                    ),
                    {
                        "id": spec.id,
                        "agent": self.agent_id,
                        "creator": spec.created_by_user_id,
                        "owner": owner,
                        "type": spec.schedule.type,
                        "name": spec.name,
                        "schedule": json.dumps(schedule),
                        "timezone": spec.schedule.timezone,
                        "task": json.dumps(task),
                        "dispatch": json.dumps(dispatch),
                        "status": spec.status,
                        "version": spec.config_version,
                    },
                )
                return
            current_task_scope = dict(current["task"])
            current_task_scope.pop("enabled", None)
            task_scope = dict(task)
            task_scope.pop("enabled", None)
            scope_changed = (
                current["schedule"] != schedule
                or current_task_scope != task_scope
                or current["dispatch"] != dispatch
            )
            version = current["config_version"] + 1 if scope_changed else current["config_version"]
            status = "pending_authorization" if scope_changed else spec.status
            if scope_changed:
                task["enabled"] = False
            await session.execute(
                text(
                    f"UPDATE {self.table('automation_schedules')} SET "
                    "name=:name,type=:type,schedule=CAST(:schedule AS jsonb),timezone=:timezone,"
                    "task=CAST(:task AS jsonb),dispatch=CAST(:dispatch AS jsonb),"
                    "status=:status,config_version=:version,updated_at=now() "
                    "WHERE id=:id AND agent_id=:agent"
                ),
                {
                    "id": spec.id,
                    "agent": self.agent_id,
                    "name": spec.name,
                    "type": spec.schedule.type,
                    "schedule": json.dumps(schedule),
                    "timezone": spec.schedule.timezone,
                    "task": json.dumps(task),
                    "dispatch": json.dumps(dispatch),
                    "status": status,
                    "version": version,
                },
            )
            if scope_changed:
                await session.execute(
                    text(
                        f"UPDATE {self.table('automation_grants')} SET revoked_at=now() "
                        "WHERE schedule_id=:id AND revoked_at IS NULL"
                    ),
                    {"id": spec.id},
                )

    async def delete_job(self, job_id: str) -> bool:
        async with self.session_factory() as session:
            await session.execute(
                text(
                    f"DELETE FROM {self.table('automation_executions')} "
                    "WHERE schedule_id=:id"
                ),
                {"id": job_id},
            )
            await session.execute(
                text(
                    f"DELETE FROM {self.table('automation_grants')} "
                    "WHERE schedule_id=:id"
                ),
                {"id": job_id},
            )
            result = await session.execute(
                text(
                    f"DELETE FROM {self.table('automation_schedules')} "
                    "WHERE id=:id AND agent_id=:agent"
                ),
                {"id": job_id, "agent": self.agent_id},
            )
            return bool(result.rowcount)

    async def set_status(self, job_id: str, status: str) -> None:
        async with self.session_factory() as session:
            result = await session.execute(
                text(
                    f"UPDATE {self.table('automation_schedules')} SET "
                    "status=:status,task=jsonb_set(task,'{enabled}',"
                    "to_jsonb(CAST(:enabled AS boolean))),updated_at=now() "
                    "WHERE id=:id AND agent_id=:agent"
                ),
                {
                    "id": job_id,
                    "agent": self.agent_id,
                    "status": status,
                    "enabled": status == "active",
                },
            )
            if not result.rowcount:
                raise KeyError("automation_not_found")

    async def authorize(
        self,
        job_id: str,
        *,
        authorized_by_user_id: UUID,
        config_version: int,
        authorization_digest: str,
        grants: list[tuple[str, dict, dict]],
    ) -> None:
        async with self.session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"SELECT automation_owner_user_id,config_version FROM "
                            f"{self.table('automation_schedules')} "
                            "WHERE id=:id AND agent_id=:agent FOR UPDATE"
                        ),
                        {"id": job_id, "agent": self.agent_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                raise KeyError("automation_not_found")
            if row["automation_owner_user_id"] != authorized_by_user_id:
                raise PermissionError("automation_owner_required")
            if row["config_version"] != config_version:
                raise ValueError("automation_version_conflict")
            await session.execute(
                text(
                    f"UPDATE {self.table('automation_grants')} SET revoked_at=now() "
                    "WHERE schedule_id=:id AND revoked_at IS NULL"
                ),
                {"id": job_id},
            )
            for capability, resource_scope, target_scope in grants:
                resource = {
                    **resource_scope,
                    "_config_version": config_version,
                    "_authorization_digest": authorization_digest,
                }
                await session.execute(
                    text(
                        f"INSERT INTO {self.table('automation_grants')} "
                        "(id,schedule_id,authorized_by_user_id,capability,resource_scope,target_scope) "
                        "VALUES (:id,:schedule,:actor,:capability,CAST(:resource AS jsonb),"
                        "CAST(:target AS jsonb))"
                    ),
                    {
                        "id": uuid4(),
                        "schedule": job_id,
                        "actor": authorized_by_user_id,
                        "capability": capability,
                        "resource": json.dumps(resource),
                        "target": json.dumps(target_scope),
                    },
                )
            await session.execute(
                text(
                    f"UPDATE {self.table('automation_schedules')} SET "
                    "status='active',task=jsonb_set(task,'{enabled}','true'::jsonb),"
                    "updated_at=now() WHERE id=:id AND agent_id=:agent"
                ),
                {"id": job_id, "agent": self.agent_id},
            )

    async def revoke_authorization(self, job_id: str) -> None:
        async with self.session_factory() as session:
            result = await session.execute(
                text(
                    f"UPDATE {self.table('automation_schedules')} SET "
                    "status='authorization_revoked',"
                    "task=jsonb_set(task,'{enabled}','false'::jsonb),updated_at=now() "
                    "WHERE id=:id AND agent_id=:agent"
                ),
                {"id": job_id, "agent": self.agent_id},
            )
            if not result.rowcount:
                raise KeyError("automation_not_found")
            await session.execute(
                text(
                    f"UPDATE {self.table('automation_grants')} SET revoked_at=now() "
                    "WHERE schedule_id=:id AND revoked_at IS NULL"
                ),
                {"id": job_id},
            )

    async def get_authorization(self, job_id: str) -> AutomationAuthorization | None:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            f"SELECT schedule_id,authorized_by_user_id,capability,"
                            f"resource_scope,target_scope FROM {self.table('automation_grants')} "
                            "WHERE schedule_id=:id AND revoked_at IS NULL "
                            "AND (expires_at IS NULL OR expires_at>now()) ORDER BY capability,id"
                        ),
                        {"id": job_id},
                    )
                )
                .mappings()
                .all()
            )
        if not rows:
            return None
        resource = dict(rows[0]["resource_scope"])
        version = int(resource.pop("_config_version"))
        digest = str(resource.pop("_authorization_digest"))
        grants = []
        for row in rows:
            grant_resource = dict(row["resource_scope"])
            grant_resource.pop("_config_version", None)
            grant_resource.pop("_authorization_digest", None)
            grants.append(
                AutomationGrant(
                    capability=row["capability"],
                    resource_scope=grant_resource,
                    target_scope=row["target_scope"],
                )
            )
        return AutomationAuthorization(
            schedule_id=rows[0]["schedule_id"],
            authorized_by_user_id=rows[0]["authorized_by_user_id"],
            config_version=version,
            authorization_digest=digest,
            grants=grants,
        )

    async def get_history(self, job_id: str) -> list[CronExecutionRecord]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            f"SELECT started_at,status,error_summary,trigger FROM "
                            f"{self.table('automation_executions')} WHERE schedule_id=:id "
                            "ORDER BY started_at DESC,id DESC LIMIT 50"
                        ),
                        {"id": job_id},
                    )
                )
                .mappings()
                .all()
            )
        return [
            CronExecutionRecord(
                run_at=row["started_at"],
                status=row["status"],
                error=row["error_summary"],
                trigger=row["trigger"],
            )
            for row in rows
        ]

    async def append_history(
        self,
        job_id: str,
        record: CronExecutionRecord,
        *,
        limit: int = 50,
    ) -> list[CronExecutionRecord]:
        async with self.session_factory() as session:
            await session.execute(
                text(
                    f"INSERT INTO {self.table('automation_executions')} "
                    "(id,schedule_id,status,trigger,started_at,finished_at,error_summary) "
                    "VALUES (:id,:schedule,:status,:trigger,:started,:finished,:error)"
                ),
                {
                    "id": uuid4(),
                    "schedule": job_id,
                    "status": record.status,
                    "trigger": record.trigger,
                    "started": record.run_at,
                    "finished": datetime.now(UTC) if record.status != "running" else None,
                    "error": record.error,
                },
            )
            await session.execute(
                text(
                    f"DELETE FROM {self.table('automation_executions')} WHERE id IN ("
                    f"SELECT id FROM {self.table('automation_executions')} "
                    "WHERE schedule_id=:schedule ORDER BY started_at DESC,id DESC OFFSET :limit)"
                ),
                {"schedule": job_id, "limit": limit},
            )
        return await self.get_history(job_id)

    async def delete_history(self, job_id: str) -> None:
        async with self.session_factory() as session:
            await session.execute(
                text(
                    f"DELETE FROM {self.table('automation_executions')} "
                    "WHERE schedule_id=:id"
                ),
                {"id": job_id},
            )

    async def prune_orphan_history(self, valid_job_ids: set[str]) -> None:
        del valid_job_ids
        async with self.session_factory() as session:
            await session.execute(
                text(
                    f"DELETE FROM {self.table('automation_executions')} e "
                    f"WHERE NOT EXISTS (SELECT 1 FROM {self.table('automation_schedules')} s "
                    "WHERE s.id=e.schedule_id)"
                )
            )
