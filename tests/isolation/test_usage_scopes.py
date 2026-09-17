# -*- coding: utf-8 -*-
"""Task 10.4 用量事实和三层聚合隔离契约。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from fastapi import HTTPException
from starlette.requests import Request

from qwenpaw.access.actor import ActorContext, ActorType
from qwenpaw.access.agent_repository import agent_database_id
from qwenpaw.identity.models import PlatformRole
from qwenpaw.token_usage.usage_repository import (
    PostgresUsageRepository,
    UsageEvent,
)
from qwenpaw.token_usage.usage_service import UsageScopeDenied, UsageScopeService
from qwenpaw.app.routers import token_usage as token_usage_router
from qwenpaw.app.routers import agent_stats as agent_stats_router
from qwenpaw.token_usage.manager import TokenUsageSummary
from qwenpaw.agent_stats.postgres_repository import PostgresAgentStatsRepository
from types import SimpleNamespace


def _actor(user_id, role=PlatformRole.MEMBER) -> ActorContext:
    return ActorContext(
        user_id=user_id,
        actor_type=ActorType.USER,
        platform_role=role,
        admin_mode=False,
        request_id="task-10-4",
    )


def _request(user_id, role=PlatformRole.MEMBER) -> Request:
    request = Request({"type": "http", "headers": []})
    request.state.actor = _actor(user_id, role)
    return request


@pytest.mark.asyncio
async def test_token_usage_route_binds_actor_and_scope(monkeypatch) -> None:
    user_id = uuid4()
    captured = {}

    class Service:
        async def get_details(self, **kwargs):
            captured.update(kwargs)
            return []

    monkeypatch.setattr(token_usage_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(token_usage_router, "_usage_scope_service", lambda: Service())

    result = await token_usage_router.get_token_usage_details(
        _request(user_id),
        start_date=None,
        end_date=None,
        model=None,
        provider=None,
        scope="personal",
        agent_id=None,
    )

    assert result == []
    assert captured["actor"].user_id == user_id
    assert captured["scope"] == "personal"


@pytest.mark.asyncio
async def test_platform_scope_denial_returns_403(monkeypatch) -> None:
    class Service:
        async def get_details(self, **_kwargs):
            raise UsageScopeDenied()

    monkeypatch.setattr(token_usage_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(token_usage_router, "_usage_scope_service", lambda: Service())

    with pytest.raises(HTTPException) as exc_info:
        await token_usage_router.get_token_usage_details(
            _request(uuid4()),
            start_date=None,
            end_date=None,
            model=None,
            provider=None,
            scope="platform",
            agent_id=None,
        )
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_agent_stats_uses_authorized_agent_usage_not_global(monkeypatch) -> None:
    actor_id = uuid4()
    scoped_usage = TokenUsageSummary(total_prompt_tokens=17, total_calls=2)
    captured = {}

    async def get_agent(_request):
        return SimpleNamespace(agent_id="usage-agent", workspace_dir="unused")

    class UsageService:
        async def get_summary(self, **kwargs):
            captured["usage"] = kwargs
            return scoped_usage

    class StatsRepository:
        async def get_summary(self, **kwargs):
            captured["stats"] = kwargs
            return "agent-summary"

    monkeypatch.setattr(agent_stats_router, "is_multi_user_enabled", lambda: True)
    monkeypatch.setattr(agent_stats_router, "get_agent_for_request", get_agent)
    monkeypatch.setattr(
        agent_stats_router, "_usage_scope_service", lambda: UsageService()
    )
    monkeypatch.setattr(
        agent_stats_router,
        "PostgresAgentStatsRepository",
        lambda **_kwargs: StatsRepository(),
    )

    result = await agent_stats_router.get_agent_statistics(
        _request(actor_id), start_date=None, end_date=None
    )

    assert result == "agent-summary"
    assert captured["usage"]["scope"] == "agent"
    assert captured["usage"]["agent_key"] == "usage-agent"
    assert captured["stats"]["token_summary"] is scoped_usage


@pytest.fixture
def usage_database(postgres_test_schema):
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_test_schema.async_url())
    config.attributes["target_schema"] = postgres_test_schema.name
    command.upgrade(config, "head")
    engine = create_async_engine(postgres_test_schema.async_url(), poolclass=NullPool)
    factory = async_sessionmaker(engine)

    @asynccontextmanager
    async def sessions():
        async with factory.begin() as session:
            yield session

    yield postgres_test_schema.name, sessions


@pytest.mark.asyncio
async def test_personal_agent_and_platform_usage_scopes(usage_database) -> None:
    schema, sessions = usage_database
    owner_id, collaborator_id, user_id, admin_id = [uuid4() for _ in range(4)]
    provider_id = uuid5(NAMESPACE_URL, "qwenpaw:model-provider:test-provider")
    model_id = uuid4()
    agent_key = "usage-shared-agent"
    agent_id = agent_database_id(agent_key)
    async with sessions() as session:
        for current_id, username, role in (
            (owner_id, "usage-owner", "member"),
            (collaborator_id, "usage-collaborator", "member"),
            (user_id, "usage-user", "member"),
            (admin_id, "usage-admin", "admin"),
        ):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".users '
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (:id,:username,'hash','active',:role)"
                ),
                {"id": current_id, "username": username, "role": role},
            )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".model_providers '
                "(id,name,type,status,created_by) "
                "VALUES (:id,'test-provider','runtime','active',:owner)"
            ),
            {"id": provider_id, "owner": owner_id},
        )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".models '
                "(id,provider_id,model_key,display_name,status) "
                "VALUES (:id,:provider,'test-model','Test Model','active')"
            ),
            {"id": model_id, "provider": provider_id},
        )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".agents '
                "(id,owner_user_id,name,status,visibility,default_model_mode,"
                "draft_workspace_key) VALUES "
                "(:id,:owner,'Usage Agent','active','shared','inherited','usage')"
            ),
            {"id": agent_id, "owner": owner_id},
        )
        for member_id, role in (
            (collaborator_id, "collaborator"),
            (user_id, "user"),
        ):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".agent_members '
                    "(agent_id,user_id,role,granted_by) "
                    "VALUES (:agent,:user,:role,:owner)"
                ),
                {
                    "agent": agent_id,
                    "user": member_id,
                    "role": role,
                    "owner": owner_id,
                },
            )

    repository = PostgresUsageRepository(schema=schema, session_factory=sessions)
    occurred_at = datetime(2026, 9, 7, 8, tzinfo=UTC)
    for current_id, prompt, completion in (
        (owner_id, 10, 1),
        (collaborator_id, 20, 2),
        (user_id, 5, 3),
    ):
        assert await repository.append(
            UsageEvent(
                occurred_at=occurred_at,
                user_id=current_id,
                actor_type="user",
                agent_key=agent_key,
                provider_key="test-provider",
                model_key="test-model",
                prompt_tokens=prompt,
                completion_tokens=completion,
            )
        )

    service = UsageScopeService(repository=repository, schema=schema)
    owner_personal = await service.get_summary(
        actor=_actor(owner_id),
        scope="personal",
        start_date=date(2026, 9, 7),
        end_date=date(2026, 9, 7),
    )
    assert owner_personal.total_prompt_tokens == 10

    owner_agent = await service.get_summary(
        actor=_actor(owner_id),
        scope="agent",
        agent_key=agent_key,
        start_date=date(2026, 9, 7),
        end_date=date(2026, 9, 7),
    )
    collaborator_agent = await service.get_summary(
        actor=_actor(collaborator_id),
        scope="agent",
        agent_key=agent_key,
        start_date=date(2026, 9, 7),
        end_date=date(2026, 9, 7),
    )
    user_agent = await service.get_summary(
        actor=_actor(user_id),
        scope="agent",
        agent_key=agent_key,
        start_date=date(2026, 9, 7),
        end_date=date(2026, 9, 7),
    )
    assert owner_agent.total_prompt_tokens == 35
    assert collaborator_agent.total_prompt_tokens == 35
    assert user_agent.total_prompt_tokens == 5

    with pytest.raises(UsageScopeDenied):
        await service.get_summary(
            actor=_actor(owner_id),
            scope="platform",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 9, 7),
        )
    platform = await service.get_summary(
        actor=_actor(admin_id, PlatformRole.ADMIN),
        scope="platform",
        start_date=date(2026, 9, 7),
        end_date=date(2026, 9, 7),
    )
    assert platform.total_prompt_tokens == 35
    assert set(platform.by_model) == {"test-provider:test-model"}


@pytest.mark.asyncio
async def test_missing_model_mapping_fails_closed(usage_database) -> None:
    schema, sessions = usage_database
    repository = PostgresUsageRepository(schema=schema, session_factory=sessions)

    assert not await repository.append(
        UsageEvent(
            occurred_at=datetime.now(UTC),
            user_id=uuid4(),
            actor_type="user",
            agent_key="missing-agent",
            provider_key="missing-provider",
            model_key="missing-model",
            prompt_tokens=1,
            completion_tokens=1,
        )
    )


@pytest.mark.asyncio
async def test_postgres_agent_stats_limits_user_and_aggregates_owner(
    usage_database,
) -> None:
    schema, sessions = usage_database
    owner_id, user_id = uuid4(), uuid4()
    agent_key = "usage-stats-agent"
    agent_id = agent_database_id(agent_key)
    conversation_owner, conversation_user = uuid4(), uuid4()
    async with sessions() as session:
        for current_id, username in (
            (owner_id, "stats-owner"),
            (user_id, "stats-user"),
        ):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".users '
                    "(id,username,password_hash,status,platform_role) "
                    "VALUES (:id,:username,'hash','active','member')"
                ),
                {"id": current_id, "username": username},
            )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".agents '
                "(id,owner_user_id,name,status,visibility,default_model_mode,"
                "draft_workspace_key) VALUES "
                "(:id,:owner,'Stats Agent','active','shared','inherited','stats')"
            ),
            {"id": agent_id, "owner": owner_id},
        )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".agent_members '
                "(agent_id,user_id,role,granted_by) "
                "VALUES (:agent,:user,'user',:owner)"
            ),
            {"agent": agent_id, "user": user_id, "owner": owner_id},
        )
        for conversation_id, current_id in (
            (conversation_owner, owner_id),
            (conversation_user, user_id),
        ):
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".conversations '
                    "(id,agent_id,owner_user_id,title,status,created_at,updated_at) "
                    "VALUES (:id,:agent,:owner,'private title','active',"
                    "'2026-09-07T08:00:00Z','2026-09-07T08:00:00Z')"
                ),
                {"id": conversation_id, "agent": agent_id, "owner": current_id},
            )
            await session.execute(
                text(
                    f'INSERT INTO "{schema}".messages '
                    "(id,conversation_id,sequence,role,message_type,content,status,"
                    "created_by,created_at) VALUES "
                    "(:id,:conversation,1,'user','message','{}','completed',"
                    ":owner,'2026-09-07T08:00:00Z')"
                ),
                {"id": uuid4(), "conversation": conversation_id, "owner": current_id},
            )
        await session.execute(
            text(
                f'INSERT INTO "{schema}".messages '
                "(id,conversation_id,sequence,role,message_type,content,status,"
                "created_by,created_at) VALUES "
                "(:id,:conversation,2,'assistant','message','{}','completed',"
                ":owner,'2026-09-08T08:00:00Z')"
            ),
            {"id": uuid4(), "conversation": conversation_user, "owner": user_id},
        )

    repository = PostgresAgentStatsRepository(schema=schema, session_factory=sessions)
    token_summary = TokenUsageSummary(total_prompt_tokens=9, total_calls=1)
    owner_stats = await repository.get_summary(
        agent_key=agent_key,
        viewer_user_id=owner_id,
        aggregate_all=True,
        start_date=date(2026, 9, 7),
        end_date=date(2026, 9, 8),
        token_summary=token_summary,
    )
    user_stats = await repository.get_summary(
        agent_key=agent_key,
        viewer_user_id=user_id,
        aggregate_all=False,
        start_date=date(2026, 9, 7),
        end_date=date(2026, 9, 8),
        token_summary=token_summary,
    )
    assert owner_stats.total_active_sessions == 2
    assert owner_stats.total_messages == 3
    assert user_stats.total_active_sessions == 1
    assert user_stats.total_messages == 2
    assert owner_stats.total_prompt_tokens == 9
