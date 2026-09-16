# -*- coding: utf-8 -*-
"""个人、Agent 匿名聚合和平台全局用量策略。"""

from __future__ import annotations

from datetime import date

from ..access.actor import ActorContext
from ..access.agent_repository import AgentResourceRole
from ..identity.models import PlatformRole
from .manager import TokenUsageByModel, TokenUsageStats, TokenUsageSummary
from .usage_repository import PostgresUsageRepository


class UsageScopeDenied(RuntimeError):
    def __init__(self) -> None:
        super().__init__("forbidden")


class UsageScopeService:
    """把可信主体转换为 Repository 查询范围。"""

    def __init__(self, *, repository: PostgresUsageRepository, schema: str) -> None:
        self.repository = repository
        self.schema = schema

    async def get_details(
        self,
        *,
        actor: ActorContext,
        scope: str,
        start_date: date,
        end_date: date,
        agent_key: str | None = None,
        model_name: str | None = None,
        provider_key: str | None = None,
    ):
        if actor.user_id is None:
            raise UsageScopeDenied()
        user_id = actor.user_id
        scoped_agent: str | None = None
        if scope == "personal":
            pass
        elif scope == "platform":
            if actor.platform_role is not PlatformRole.ADMIN:
                raise UsageScopeDenied()
            user_id = None
        elif scope == "agent" and agent_key:
            role = await self.repository.get_agent_role(
                user_id=actor.user_id,
                agent_key=agent_key,
            )
            if role is None:
                raise UsageScopeDenied()
            scoped_agent = agent_key
            if role in {AgentResourceRole.OWNER, AgentResourceRole.COLLABORATOR}:
                user_id = None
        else:
            raise UsageScopeDenied()
        return await self.repository.get_details(
            start_date=start_date,
            end_date=end_date,
            user_id=user_id,
            agent_key=scoped_agent,
            model_name=model_name,
            provider_key=provider_key,
        )

    async def get_summary(self, **kwargs) -> TokenUsageSummary:
        records = await self.get_details(**kwargs)
        by_model: dict[str, dict[str, object]] = {}
        by_date: dict[str, dict[str, int]] = {}
        for record in records:
            key = f"{record.provider_id}:{record.model}"
            model = by_model.setdefault(
                key,
                {
                    "provider_id": record.provider_id,
                    "model": record.model,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "call_count": 0,
                },
            )
            day = by_date.setdefault(
                record.date,
                {"prompt_tokens": 0, "completion_tokens": 0, "call_count": 0},
            )
            for target in (model, day):
                target["prompt_tokens"] += record.prompt_tokens  # type: ignore[operator]
                target["completion_tokens"] += record.completion_tokens  # type: ignore[operator]
                target["call_count"] += record.call_count  # type: ignore[operator]
        return TokenUsageSummary(
            total_prompt_tokens=sum(r.prompt_tokens for r in records),
            total_completion_tokens=sum(r.completion_tokens for r in records),
            total_calls=sum(r.call_count for r in records),
            by_model={
                key: TokenUsageByModel.model_validate(value)
                for key, value in by_model.items()
            },
            by_date={
                key: TokenUsageStats.model_validate(value)
                for key, value in by_date.items()
            },
        )


__all__ = ["UsageScopeDenied", "UsageScopeService"]
