"""以 PostgreSQL 事实约束插件治理与用户应用访问。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID, uuid4

from sqlalchemy import text

from ..access.actor import ActorContext
from ..access.agent_repository import AgentResourceRole, agent_database_id
from ..access.capabilities import Capability
from ..access.service import AuthorizationService
from ..persistence.database import database_session


class PluginAccessError(RuntimeError):
    """插件不存在、停用或主体无权访问。"""


@dataclass(frozen=True, slots=True)
class PluginInstallation:
    """插件安装治理所需的最小稳定投影。"""

    id: UUID
    plugin_id: str
    version: str
    plugin_type: str
    status: str
    audience_mode: Literal["all_members", "selected_users"] = "selected_users"
    selected_user_ids: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class AppAudience:
    """管理 API 使用的应用授权模式。"""

    mode: Literal["all_members", "selected_users"]
    selected_user_ids: tuple[UUID, ...] = ()


class PluginGovernanceRepository(Protocol):
    async def register_installation(
        self,
        candidate: PluginInstallation,
        source_type: str,
        source_ref: str,
        content_hash: str,
        actor_id: UUID,
        audience: AppAudience,
    ) -> PluginInstallation: ...

    async def list_installations(self) -> list[PluginInstallation]: ...

    async def get_installation(self, plugin_id: str) -> PluginInstallation | None: ...

    async def is_user_granted(self, installation_id: UUID, user_id: UUID) -> bool: ...

    async def replace_audience(
        self,
        installation_id: UUID,
        audience: AppAudience,
        actor_id: UUID,
    ) -> None: ...

    async def save_agent_setting(
        self,
        agent_id: UUID,
        installation_id: UUID,
        enabled: bool,
        config: dict,
        actor_id: UUID,
    ): ...

    async def get_agent_setting(
        self,
        agent_id: UUID,
        installation_id: UUID,
    ): ...

    async def set_status(
        self, installation_id: UUID, status: str, actor_id: UUID
    ) -> PluginInstallation: ...

    async def delete_installation(
        self, installation_id: UUID, actor_id: UUID
    ) -> None: ...


class PluginGovernanceService:
    """集中执行插件角色、状态与授权判断。"""

    def __init__(self, repository: PluginGovernanceRepository) -> None:
        self.repository = repository

    @staticmethod
    def require_manage(actor: ActorContext) -> None:
        AuthorizationService().require(actor, Capability.PLUGINS_MANAGE)

    async def list_manageable(self, actor: ActorContext) -> list[PluginInstallation]:
        self.require_manage(actor)
        return await self.repository.list_installations()

    async def _is_granted(
        self, actor: ActorContext, installation: PluginInstallation
    ) -> bool:
        if actor.user_id is None:
            return True
        return await self.repository.is_user_granted(installation.id, actor.user_id)

    async def list_authorized(self, actor: ActorContext) -> list[PluginInstallation]:
        AuthorizationService().require(actor, Capability.PLATFORM_USE)
        result = []
        for installation in await self.repository.list_installations():
            if installation.status != "active":
                continue
            if await self._is_granted(actor, installation):
                result.append(installation)
        return result

    async def require_app_access(
        self, actor: ActorContext, plugin_id: str
    ) -> PluginInstallation:
        AuthorizationService().require(actor, Capability.PLATFORM_USE)
        installation = await self.repository.get_installation(plugin_id)
        if (
            installation is None
            or installation.status != "active"
            or not await self._is_granted(actor, installation)
        ):
            raise PluginAccessError("plugin_unavailable_or_forbidden")
        return installation

    async def replace_audience(
        self,
        actor: ActorContext,
        plugin_id: str,
        audience: AppAudience,
    ) -> None:
        self.require_manage(actor)
        installation = await self.repository.get_installation(plugin_id)
        if installation is None:
            raise PluginAccessError("plugin_not_found")
        normalized = AppAudience(
            mode=audience.mode,
            selected_user_ids=(
                ()
                if audience.mode == "all_members"
                else tuple(sorted(set(audience.selected_user_ids), key=str))
            ),
        )
        if actor.user_id is None:
            raise PluginAccessError("plugin_actor_missing")
        await self.repository.replace_audience(
            installation.id, normalized, actor.user_id
        )

    async def register_installation(
        self,
        actor: ActorContext,
        candidate: PluginInstallation,
        *,
        source_type: str,
        source_ref: str,
        content_hash: str,
        audience: AppAudience,
    ) -> PluginInstallation:
        self.require_manage(actor)
        if actor.user_id is None:
            raise PluginAccessError("plugin_actor_missing")
        normalized = AppAudience(
            mode=audience.mode,
            selected_user_ids=(
                ()
                if audience.mode == "all_members"
                else tuple(sorted(set(audience.selected_user_ids), key=str))
            ),
        )
        return await self.repository.register_installation(
            candidate,
            source_type,
            source_ref,
            content_hash,
            actor.user_id,
            normalized,
        )

    async def set_status(
        self, actor: ActorContext, plugin_id: str, *, enabled: bool
    ) -> PluginInstallation:
        self.require_manage(actor)
        installation = await self.repository.get_installation(plugin_id)
        if installation is None:
            raise PluginAccessError("plugin_not_found")
        if actor.user_id is None:
            raise PluginAccessError("plugin_actor_missing")
        return await self.repository.set_status(
            installation.id,
            "active" if enabled else "disabled",
            actor.user_id,
        )

    async def begin_uninstall(
        self, actor: ActorContext, plugin_id: str
    ) -> PluginInstallation:
        self.require_manage(actor)
        installation = await self.repository.get_installation(plugin_id)
        if installation is None:
            raise PluginAccessError("plugin_not_found")
        if actor.user_id is None:
            raise PluginAccessError("plugin_actor_missing")
        return await self.repository.set_status(
            installation.id, "uninstalling", actor.user_id
        )

    async def complete_uninstall(self, actor: ActorContext, plugin_id: str) -> None:
        self.require_manage(actor)
        installation = await self.repository.get_installation(plugin_id)
        if installation is None:
            raise PluginAccessError("plugin_not_found")
        if installation.status != "uninstalling":
            raise PluginAccessError("plugin_uninstall_not_started")
        if actor.user_id is None:
            raise PluginAccessError("plugin_actor_missing")
        await self.repository.delete_installation(installation.id, actor.user_id)

    async def fail_uninstall(
        self, actor: ActorContext, plugin_id: str
    ) -> PluginInstallation:
        self.require_manage(actor)
        installation = await self.repository.get_installation(plugin_id)
        if installation is None:
            raise PluginAccessError("plugin_not_found")
        if actor.user_id is None:
            raise PluginAccessError("plugin_actor_missing")
        return await self.repository.set_status(
            installation.id, "failed", actor.user_id
        )

    async def save_agent_setting(
        self,
        actor: ActorContext,
        agent_access,
        plugin_id: str,
        *,
        enabled: bool,
        config: dict,
    ):
        if agent_access.historical_read_only or agent_access.role not in (
            AgentResourceRole.OWNER,
            AgentResourceRole.COLLABORATOR,
        ):
            raise PluginAccessError("agent_plugin_edit_forbidden")
        installation = await self.require_app_access(actor, plugin_id)
        if actor.user_id is None:
            raise PluginAccessError("plugin_actor_missing")
        agent_id = getattr(agent_access, "agent_id", None)
        if agent_id is None:
            agent_id = agent_database_id(agent_access.agent_key)
        return await self.repository.save_agent_setting(
            agent_id,
            installation.id,
            enabled,
            dict(config),
            actor.user_id,
        )

    async def get_agent_setting(
        self,
        actor: ActorContext,
        agent_access,
        plugin_id: str,
    ):
        if agent_access.role not in (
            AgentResourceRole.OWNER,
            AgentResourceRole.COLLABORATOR,
            AgentResourceRole.USER,
        ):
            raise PluginAccessError("agent_plugin_read_forbidden")
        installation = await self.require_app_access(actor, plugin_id)
        agent_id = getattr(agent_access, "agent_id", None)
        if agent_id is None:
            agent_id = agent_database_id(agent_access.agent_key)
        return await self.repository.get_agent_setting(agent_id, installation.id)


class PostgresPluginGovernanceRepository:
    """Schema 限定的插件安装、授权与 Agent 设置仓储。"""

    def __init__(self, *, schema: str, session_factory=database_session) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", schema):
            raise ValueError("invalid_database_schema")
        self.schema = schema
        self.session_factory = session_factory

    def table(self, name: str) -> str:
        return f'"{self.schema}"."{name}"'

    @staticmethod
    def _installation(row) -> PluginInstallation:
        return PluginInstallation(
            id=row["id"],
            plugin_id=row["plugin_id"],
            version=row["version"],
            plugin_type=row["plugin_type"],
            status=row["status"],
            audience_mode=row.get("audience_mode", "selected_users"),
            selected_user_ids=tuple(row.get("selected_user_ids") or ()),
        )

    def _projection_sql(self) -> str:
        return (
            "p.id,p.plugin_id,p.version,p.plugin_type,p.status,"
            "CASE WHEN EXISTS (SELECT 1 FROM "
            f"{self.table('app_grants')} ga WHERE ga.plugin_installation_id=p.id "
            "AND ga.enabled AND ga.subject_type='all_members') "
            "THEN 'all_members' ELSE 'selected_users' END AS audience_mode,"
            "ARRAY(SELECT gu.subject_id FROM "
            f"{self.table('app_grants')} gu WHERE gu.plugin_installation_id=p.id "
            "AND gu.enabled AND gu.subject_type='user' ORDER BY gu.subject_id) "
            "AS selected_user_ids"
        )

    async def list_installations(self) -> list[PluginInstallation]:
        async with self.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        text(
                            f"SELECT {self._projection_sql()} "
                            f"FROM {self.table('plugin_installations')} p "
                            "ORDER BY plugin_id"
                        )
                    )
                )
                .mappings()
                .all()
            )
        return [self._installation(row) for row in rows]

    async def reconcile_discovered_installations(
        self,
        discovered: list[tuple[PluginInstallation, str, str]],
    ) -> int:
        """首次启用治理时登记存量磁盘插件，并保持已有授权不变。"""
        if not discovered:
            return 0
        created = 0
        async with self.session_factory() as session:
            admin_id = await session.scalar(
                text(
                    f"SELECT id FROM {self.table('users')} "
                    "WHERE platform_role='admin' AND status='active' "
                    "ORDER BY created_at,id LIMIT 1"
                )
            )
            if admin_id is None:
                raise PluginAccessError("plugin_reconcile_admin_missing")
            for candidate, source_ref, content_hash in discovered:
                inserted = await session.scalar(
                    text(
                        f"INSERT INTO {self.table('plugin_installations')} "
                        "(id,plugin_id,version,plugin_type,source_type,source_ref,"
                        "content_hash,status,installed_by) VALUES "
                        "(:id,:plugin_id,:version,:plugin_type,'path',:source_ref,"
                        ":content_hash,'active',:actor) ON CONFLICT (plugin_id) "
                        "DO NOTHING RETURNING id"
                    ),
                    {
                        "id": candidate.id,
                        "plugin_id": candidate.plugin_id,
                        "version": candidate.version,
                        "plugin_type": candidate.plugin_type,
                        "source_ref": source_ref,
                        "content_hash": content_hash,
                        "actor": admin_id,
                    },
                )
                if inserted is None:
                    continue
                await self._replace_audience_in_session(
                    session,
                    inserted,
                    AppAudience(mode="all_members"),
                    admin_id,
                )
                created += 1
        return created

    async def register_installation(
        self,
        candidate: PluginInstallation,
        source_type: str,
        source_ref: str,
        content_hash: str,
        actor_id: UUID,
        audience: AppAudience,
    ) -> PluginInstallation:
        async with self.session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"INSERT INTO {self.table('plugin_installations')} "
                            "(id,plugin_id,version,plugin_type,source_type,source_ref,"
                            "content_hash,status,installed_by) VALUES "
                            "(:id,:plugin_id,:version,:plugin_type,:source_type,"
                            ":source_ref,:content_hash,:status,:actor) "
                            "ON CONFLICT (plugin_id) DO UPDATE SET "
                            "version=EXCLUDED.version,plugin_type=EXCLUDED.plugin_type,"
                            "source_type=EXCLUDED.source_type,source_ref=EXCLUDED.source_ref,"
                            "content_hash=EXCLUDED.content_hash,status=EXCLUDED.status,"
                            "installed_by=EXCLUDED.installed_by,installed_at=now(),"
                            "disabled_at=NULL RETURNING id,plugin_id,version,plugin_type,status"
                        ),
                        {
                            "id": candidate.id,
                            "plugin_id": candidate.plugin_id,
                            "version": candidate.version,
                            "plugin_type": candidate.plugin_type,
                            "source_type": source_type,
                            "source_ref": source_ref,
                            "content_hash": content_hash,
                            "status": candidate.status,
                            "actor": actor_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            await self._replace_audience_in_session(
                session, row["id"], audience, actor_id
            )
        return self._installation(row)

    async def get_installation(self, plugin_id: str) -> PluginInstallation | None:
        async with self.session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"SELECT {self._projection_sql()} "
                            f"FROM {self.table('plugin_installations')} p "
                            "WHERE p.plugin_id=:plugin_id"
                        ),
                        {"plugin_id": plugin_id},
                    )
                )
                .mappings()
                .first()
            )
        return self._installation(row) if row is not None else None

    async def is_user_granted(self, installation_id: UUID, user_id: UUID) -> bool:
        async with self.session_factory() as session:
            allowed = await session.execute(
                text(
                    f"SELECT EXISTS(SELECT 1 FROM {self.table('app_grants')} g "
                    f"JOIN {self.table('users')} u ON u.id=:user_id "
                    "AND u.status='active' WHERE g.plugin_installation_id=:plugin "
                    "AND g.enabled AND ((g.subject_type='all_members' "
                    "AND g.subject_id IS NULL) OR (g.subject_type='user' "
                    "AND g.subject_id=:user_id)))"
                ),
                {"plugin": installation_id, "user_id": user_id},
            )
            return bool(allowed.scalar_one())

    async def replace_audience(
        self,
        installation_id: UUID,
        audience: AppAudience,
        actor_id: UUID,
    ) -> None:
        async with self.session_factory() as session:
            await self._replace_audience_in_session(
                session, installation_id, audience, actor_id
            )

    async def _replace_audience_in_session(
        self,
        session,
        installation_id: UUID,
        audience: AppAudience,
        actor_id: UUID,
    ) -> None:
        exists = await session.execute(
            text(
                f"SELECT 1 FROM {self.table('plugin_installations')} "
                "WHERE id=:id FOR UPDATE"
            ),
            {"id": installation_id},
        )
        if exists.scalar_one_or_none() is None:
            raise PluginAccessError("plugin_not_found")
        users = list(audience.selected_user_ids)
        if users:
            valid = await session.execute(
                text(
                    f"SELECT id FROM {self.table('users')} "
                    "WHERE id=ANY(CAST(:ids AS uuid[])) AND status='active'"
                ),
                {"ids": users},
            )
            if set(valid.scalars().all()) != set(users):
                raise PluginAccessError("plugin_audience_user_invalid")
        await session.execute(
            text(
                f"DELETE FROM {self.table('app_grants')} "
                "WHERE plugin_installation_id=:id"
            ),
            {"id": installation_id},
        )
        subjects = (
            [("all_members", None)]
            if audience.mode == "all_members"
            else [("user", user_id) for user_id in users]
        )
        for subject_type, subject_id in subjects:
            await session.execute(
                text(
                    f"INSERT INTO {self.table('app_grants')} "
                    "(id,plugin_installation_id,subject_type,subject_id,enabled,granted_by) "
                    "VALUES (:id,:plugin,:subject_type,:subject_id,true,:actor)"
                ),
                {
                    "id": uuid4(),
                    "plugin": installation_id,
                    "subject_type": subject_type,
                    "subject_id": subject_id,
                    "actor": actor_id,
                },
            )

    async def save_agent_setting(
        self,
        agent_id: UUID,
        installation_id: UUID,
        enabled: bool,
        config: dict,
        actor_id: UUID,
    ):
        async with self.session_factory() as session:
            await session.execute(
                text(
                    f"INSERT INTO {self.table('agent_plugin_settings')} "
                    "(agent_id,plugin_installation_id,enabled,config,updated_by) "
                    "VALUES (:agent,:plugin,:enabled,CAST(:config AS jsonb),:actor) "
                    "ON CONFLICT (agent_id,plugin_installation_id) DO UPDATE SET "
                    "enabled=EXCLUDED.enabled,config=EXCLUDED.config,"
                    "updated_by=EXCLUDED.updated_by,updated_at=now()"
                ),
                {
                    "agent": agent_id,
                    "plugin": installation_id,
                    "enabled": enabled,
                    "config": json.dumps(config),
                    "actor": actor_id,
                },
            )
        return {"enabled": enabled, "config": config, "updated_by": actor_id}

    async def get_agent_setting(
        self,
        agent_id: UUID,
        installation_id: UUID,
    ):
        async with self.session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"SELECT enabled,config,updated_by,updated_at FROM "
                            f"{self.table('agent_plugin_settings')} "
                            "WHERE agent_id=:agent AND plugin_installation_id=:plugin"
                        ),
                        {"agent": agent_id, "plugin": installation_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return {"enabled": False, "config": {}}
        return dict(row)

    async def set_status(
        self, installation_id: UUID, status: str, actor_id: UUID
    ) -> PluginInstallation:
        async with self.session_factory() as session:
            row = (
                (
                    await session.execute(
                        text(
                            f"UPDATE {self.table('plugin_installations')} SET "
                            "status=CAST(:status AS varchar),disabled_at=CASE "
                            "WHEN CAST(:status AS varchar)='disabled' "
                            "THEN now() ELSE NULL END WHERE id=:id "
                            "RETURNING id,plugin_id,version,plugin_type,status"
                        ),
                        {"id": installation_id, "status": status},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise PluginAccessError("plugin_not_found")
            await session.execute(
                text(
                    f"INSERT INTO {self.table('audit_logs')} "
                    "(id,actor_user_id,actor_identity_type,action,resource_type,"
                    "resource_id,result,request_id,source) VALUES "
                    "(:id,:actor,'user',:action,'plugin',:resource,'success',"
                    ":request,'plugin_governance')"
                ),
                {
                    "id": uuid4(),
                    "actor": actor_id,
                    "action": f"plugin.{status}",
                    "resource": str(installation_id),
                    "request": str(uuid4()),
                },
            )
        return self._installation(row)

    async def delete_installation(self, installation_id: UUID, actor_id: UUID) -> None:
        async with self.session_factory() as session:
            await session.execute(
                text(
                    f"DELETE FROM {self.table('app_user_data')} "
                    "WHERE plugin_installation_id=:id"
                ),
                {"id": installation_id},
            )
            await session.execute(
                text(
                    f"DELETE FROM {self.table('agent_plugin_settings')} "
                    "WHERE plugin_installation_id=:id"
                ),
                {"id": installation_id},
            )
            await session.execute(
                text(
                    f"DELETE FROM {self.table('app_grants')} "
                    "WHERE plugin_installation_id=:id"
                ),
                {"id": installation_id},
            )
            await session.execute(
                text(
                    f"DELETE FROM {self.table('plugin_capabilities')} "
                    "WHERE plugin_installation_id=:id"
                ),
                {"id": installation_id},
            )
            removed = await session.execute(
                text(
                    f"DELETE FROM {self.table('plugin_installations')} "
                    "WHERE id=:id AND status='uninstalling' RETURNING plugin_id"
                ),
                {"id": installation_id},
            )
            if removed.scalar_one_or_none() is None:
                raise PluginAccessError("plugin_uninstall_not_started")
