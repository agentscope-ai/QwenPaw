# -*- coding: utf-8 -*-
"""Creator-owned authorization for unattended automation runs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from ..access.actor import ActorContext, ActorType
from ..access.agent_repository import AgentAccessRecord, AgentResourceRole
from ..app.crons.models import AutomationAuthorization, CronJobSpec
from ..identity.models import PlatformRole


class AutomationAuthorizationError(RuntimeError):
    """Stable automation authorization failure."""


@dataclass(frozen=True, slots=True)
class AutomationAuthorizationPreview:
    schedule_id: UUID
    config_version: int
    authorization_digest: str
    agent_key: str
    target_user_id: UUID
    target_channel: str
    target_session_id: str
    tool_names: tuple[str, ...]


AccessResolver = Callable[
    [ActorContext, str], Awaitable[AgentAccessRecord | None]
]
AccountActiveResolver = Callable[[UUID], Awaitable[bool]]


class AutomationAuthorizationService:
    """Keep automation authority bounded by its creator's live access."""

    def __init__(
        self,
        *,
        repository: Any,
        agent_key: str,
        access_resolver: AccessResolver,
        tool_names_provider: Callable[[], Iterable[str]],
        account_active_resolver: AccountActiveResolver | None = None,
    ) -> None:
        self.repository = repository
        self.agent_key = agent_key
        self.access_resolver = access_resolver
        self.tool_names_provider = tool_names_provider
        self.account_active_resolver = account_active_resolver

    async def create(
        self,
        actor: ActorContext,
        spec: CronJobSpec,
    ) -> CronJobSpec:
        user_id = self._require_user(actor)
        await self._require_agent_access(actor)
        target = spec.dispatch.target.model_copy(update={"user_id": str(user_id)})
        dispatch = spec.dispatch.model_copy(update={"target": target})
        request = (
            spec.request.model_copy(update={"user_id": str(user_id)})
            if spec.request is not None
            else None
        )
        runtime = spec.runtime.model_copy(update={"tool_safety": True})
        created = spec.model_copy(
            update={
                "id": spec.id or str(uuid4()),
                "created_by_user_id": user_id,
                "automation_owner_user_id": user_id,
                "dispatch": dispatch,
                "request": request,
                "runtime": runtime,
                "status": "pending_authorization",
                "config_version": 1,
                "enabled": False,
            }
        )
        await self.repository.upsert_job(created)
        return created

    async def require_modify(
        self,
        actor: ActorContext,
        job_id: str,
    ) -> CronJobSpec:
        job = await self._require_visible(job_id)
        if actor.user_id is None or actor.user_id != job.automation_owner_user_id:
            raise AutomationAuthorizationError("automation_owner_required")
        await self._require_agent_access(actor)
        return job

    async def require_view(
        self,
        actor: ActorContext,
        job_id: str,
    ) -> CronJobSpec:
        job = await self._require_visible(job_id)
        if actor.user_id == job.automation_owner_user_id:
            return job
        access = await self._require_agent_access(actor)
        if (
            access.role is AgentResourceRole.OWNER
            or actor.platform_role is PlatformRole.ADMIN
        ):
            return job
        raise AutomationAuthorizationError("automation_not_found")

    async def list_visible(
        self,
        actor: ActorContext,
        *,
        scope: str = "mine",
    ) -> list[CronJobSpec]:
        user_id = self._require_user(actor)
        jobs = await self.repository.list_jobs()
        if scope == "mine":
            return [job for job in jobs if job.automation_owner_user_id == user_id]
        if scope != "agent":
            raise AutomationAuthorizationError("automation_scope_invalid")
        access = await self._require_agent_access(actor)
        if (
            access.role is not AgentResourceRole.OWNER
            and actor.platform_role is not PlatformRole.ADMIN
        ):
            raise AutomationAuthorizationError("automation_agent_view_forbidden")
        return jobs

    async def replace(
        self,
        actor: ActorContext,
        job_id: str,
        spec: CronJobSpec,
    ) -> CronJobSpec:
        current = await self.require_modify(actor, job_id)
        owner = current.automation_owner_user_id
        assert owner is not None
        target = spec.dispatch.target.model_copy(update={"user_id": str(owner)})
        request = (
            spec.request.model_copy(update={"user_id": str(owner)})
            if spec.request is not None
            else None
        )
        replacement = spec.model_copy(
            update={
                "id": job_id,
                "created_by_user_id": current.created_by_user_id,
                "automation_owner_user_id": owner,
                "dispatch": spec.dispatch.model_copy(update={"target": target}),
                "request": request,
                "runtime": spec.runtime.model_copy(update={"tool_safety": True}),
                "status": current.status,
                "config_version": current.config_version,
            }
        )
        await self.repository.upsert_job(replacement)
        updated = await self.repository.get_job(job_id)
        if updated is None:
            raise AutomationAuthorizationError("automation_not_found")
        return updated

    async def preview(
        self,
        actor: ActorContext,
        job_id: str,
    ) -> AutomationAuthorizationPreview:
        job = await self.require_modify(actor, job_id)
        return self._preview(job)

    async def authorize(
        self,
        actor: ActorContext,
        job_id: str,
        *,
        config_version: int,
        authorization_digest: str,
    ) -> CronJobSpec:
        job = await self.require_modify(actor, job_id)
        expected = self._preview(job)
        if expected.config_version != config_version:
            raise AutomationAuthorizationError("automation_version_conflict")
        if expected.authorization_digest != authorization_digest:
            raise AutomationAuthorizationError("automation_digest_conflict")
        grants: list[tuple[str, dict, dict]] = [
            (
                "automation.execute",
                {"agent_key": self.agent_key},
                {"owner_user_id": str(expected.target_user_id)},
            ),
            (
                f"dispatch:{expected.target_channel}",
                {},
                {
                    "user_id": str(expected.target_user_id),
                    "session_id": expected.target_session_id,
                },
            ),
        ]
        grants.extend(
            (
                f"tool:{tool_name}",
                {"agent_key": self.agent_key},
                {"owner_user_id": str(expected.target_user_id)},
            )
            for tool_name in expected.tool_names
        )
        await self.repository.authorize(
            job_id,
            authorized_by_user_id=expected.target_user_id,
            config_version=config_version,
            authorization_digest=authorization_digest,
            grants=grants,
        )
        setter = getattr(self.repository, "set_status", None)
        if setter is not None:
            await setter(job_id, "active")
        return job.model_copy(update={"status": "active", "enabled": True})

    async def pause(self, actor: ActorContext, job_id: str) -> CronJobSpec:
        job = await self._require_visible(job_id)
        may_pause = actor.user_id == job.automation_owner_user_id
        if not may_pause:
            access = await self._require_agent_access(actor)
            may_pause = (
                access.role is AgentResourceRole.OWNER
                or actor.platform_role is PlatformRole.ADMIN
            )
        if not may_pause:
            raise AutomationAuthorizationError("automation_pause_forbidden")
        await self.repository.set_status(job_id, "paused")
        return job.model_copy(update={"status": "paused", "enabled": False})

    async def resume(self, actor: ActorContext, job_id: str) -> CronJobSpec:
        job = await self.require_modify(actor, job_id)
        if job.status != "paused" or await self.repository.get_authorization(job_id) is None:
            raise AutomationAuthorizationError("automation_authorization_required")
        await self.repository.set_status(job_id, "active")
        return job.model_copy(update={"status": "active", "enabled": True})

    async def delete(self, actor: ActorContext, job_id: str) -> bool:
        await self.require_modify(actor, job_id)
        return bool(await self.repository.delete_job(job_id))

    async def revoke(self, actor: ActorContext, job_id: str) -> CronJobSpec:
        job = await self.require_modify(actor, job_id)
        await self.repository.revoke_authorization(job_id)
        return job.model_copy(
            update={"status": "authorization_revoked", "enabled": False}
        )

    async def validate_execution(
        self,
        job_id: str,
    ) -> tuple[CronJobSpec, AutomationAuthorization]:
        job = await self._require_visible(job_id)
        if job.status != "active" or not job.enabled:
            raise AutomationAuthorizationError("automation_not_active")
        owner = job.automation_owner_user_id
        if owner is None:
            await self._revoke_status(job_id)
            raise AutomationAuthorizationError("automation_owner_missing")
        if self.account_active_resolver is not None and not await self.account_active_resolver(owner):
            await self._revoke_status(job_id)
            raise AutomationAuthorizationError("automation_owner_inactive")
        owner_actor = ActorContext(
            user_id=owner,
            actor_type=ActorType.AUTOMATION,
            platform_role=PlatformRole.MEMBER,
            admin_mode=False,
            request_id=f"automation:{job_id}",
        )
        access = await self.access_resolver(owner_actor, self.agent_key)
        if access is None or access.status != "active":
            await self._revoke_status(job_id)
            raise AutomationAuthorizationError("automation_agent_access_revoked")
        authorization = await self.repository.get_authorization(job_id)
        expected = self._preview(job)
        if (
            authorization is None
            or authorization.authorized_by_user_id != owner
            or authorization.config_version != job.config_version
            or authorization.authorization_digest != expected.authorization_digest
        ):
            await self._revoke_status(job_id)
            raise AutomationAuthorizationError("automation_authorization_invalid")
        return job, authorization

    async def _revoke_status(self, job_id: str) -> None:
        revoke = getattr(self.repository, "revoke_authorization", None)
        if revoke is not None:
            await revoke(job_id)
        else:
            await self.repository.set_status(job_id, "authorization_revoked")

    async def _require_visible(self, job_id: str) -> CronJobSpec:
        job = await self.repository.get_job(job_id)
        if job is None:
            raise AutomationAuthorizationError("automation_not_found")
        return job

    async def _require_agent_access(self, actor: ActorContext) -> AgentAccessRecord:
        access = await self.access_resolver(actor, self.agent_key)
        if access is None or access.status != "active":
            raise AutomationAuthorizationError("automation_agent_access_required")
        return access

    def _preview(self, job: CronJobSpec) -> AutomationAuthorizationPreview:
        owner = job.automation_owner_user_id
        if owner is None:
            raise AutomationAuthorizationError("automation_owner_missing")
        tool_names = (
            tuple(sorted(set(self.tool_names_provider())))
            if job.task_type == "agent"
            else ()
        )
        payload = {
            "agent_key": self.agent_key,
            "config_version": job.config_version,
            "schedule": job.schedule.model_dump(mode="json"),
            "task_type": job.task_type,
            "text": job.text,
            "request": job.request.model_dump(mode="json") if job.request else None,
            "runtime": job.runtime.model_dump(mode="json"),
            "dispatch": job.dispatch.model_dump(mode="json"),
            "tool_names": tool_names,
        }
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return AutomationAuthorizationPreview(
            schedule_id=UUID(str(job.id)),
            config_version=job.config_version,
            authorization_digest=digest,
            agent_key=self.agent_key,
            target_user_id=owner,
            target_channel=job.dispatch.channel,
            target_session_id=job.dispatch.target.session_id,
            tool_names=tool_names,
        )

    @staticmethod
    def _require_user(actor: ActorContext) -> UUID:
        if actor.user_id is None:
            raise AutomationAuthorizationError("automation_authenticated_user_required")
        return actor.user_id


def build_automation_authorization_service(repository: Any, agent_key: str):
    """Build the production service without coupling Workspace to SQL."""
    from sqlalchemy import text

    from ..access.agent_repository import PostgresAgentRepository
    from ..governance.tool_registry import DEFAULT_REGISTRY
    from ..identity.runtime import get_identity_schema
    from ..persistence.database import database_session

    schema = get_identity_schema()
    access_repository = PostgresAgentRepository(schema=schema)

    async def resolve_access(
        actor: ActorContext,
        requested_agent_key: str,
    ) -> AgentAccessRecord | None:
        if actor.user_id is None:
            return None
        return await access_repository.get_accessible(
            agent_key=requested_agent_key,
            user_id=actor.user_id,
        )

    async def account_active(user_id: UUID) -> bool:
        async with database_session() as session:
            return bool(
                await session.scalar(
                    text(
                        f'SELECT EXISTS(SELECT 1 FROM "{schema}".users '
                        "WHERE id=:id AND status='active')"
                    ),
                    {"id": user_id},
                )
            )

    return AutomationAuthorizationService(
        repository=repository,
        agent_key=agent_key,
        access_resolver=resolve_access,
        tool_names_provider=DEFAULT_REGISTRY.get_all_tool_names,
        account_active_resolver=account_active,
    )
