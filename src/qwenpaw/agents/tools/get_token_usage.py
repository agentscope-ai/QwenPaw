# -*- coding: utf-8 -*-
"""Tool to query token usage statistics."""

from datetime import date, timedelta

from agentscope.message import TextBlock
from agentscope.tool import ToolChunk
from agentscope.message import ToolResultState

from ...runtime.tool_registry import tool_descriptor
from ...token_usage import get_token_usage_manager
from ...access.actor import ActorContext, ActorType
from ...app.agent_context import get_current_user_id
from ...identity.models import PlatformRole
from ...identity.runtime import get_identity_schema, is_multi_user_enabled
from ...token_usage.usage_repository import PostgresUsageRepository
from ...token_usage.usage_service import UsageScopeService


def _usage_scope_service() -> UsageScopeService:
    schema = get_identity_schema()
    return UsageScopeService(
        repository=PostgresUsageRepository(schema=schema),
        schema=schema,
    )


@tool_descriptor(
    async_execution=True,
    tool_type="internal",
    policy_name="GetTokenUsage",
    ui_description="Get llm token usage",
    ui_icon="📊",
)
async def get_token_usage(
    days: int = 30,
    model_name: str | None = None,
    provider_id: str | None = None,
) -> ToolChunk:
    """Query LLM token usage over the past N days.

    Use this when the user asks about token consumption, API usage,
    or how many tokens have been used.

    Args:
        days: Number of days to look back (default: 30).
        model_name: Optional model name to filter by.
        provider_id: Optional provider ID to filter by.

    Returns:
        ToolChunk with a formatted summary of token usage.
    """
    end = date.today()
    start = end - timedelta(days=max(1, min(days, 365)))
    if is_multi_user_enabled():
        user_id = get_current_user_id()
        if not user_id:
            raise RuntimeError("usage_actor_unavailable")
        from uuid import UUID

        summary = await _usage_scope_service().get_summary(
            actor=ActorContext(
                user_id=UUID(user_id),
                actor_type=ActorType.USER,
                platform_role=PlatformRole.MEMBER,
                admin_mode=False,
                request_id="tool:get_token_usage",
            ),
            scope="personal",
            start_date=start,
            end_date=end,
            model_name=model_name,
            provider_key=provider_id,
        )
    else:
        summary = await get_token_usage_manager().get_summary(
            start_date=start,
            end_date=end,
            model_name=model_name,
            provider_id=provider_id,
        )

    lines: list[str] = []
    filter_desc = []
    if model_name:
        filter_desc.append(f"model={model_name}")
    if provider_id:
        filter_desc.append(f"provider={provider_id}")
    if not filter_desc:
        filter_desc.append("all models")
    lines.append(f"Token usage ({start} ~ {end}, {', '.join(filter_desc)}):")
    lines.append("")
    total_tokens = summary.total_prompt_tokens + summary.total_completion_tokens
    lines.append(f"- Total tokens: {total_tokens:,}")
    lines.append(f"- Prompt tokens: {summary.total_prompt_tokens:,}")
    lines.append(
        f"- Completion tokens: {summary.total_completion_tokens:,}",
    )
    lines.append(f"- Total calls: {summary.total_calls:,}")
    lines.append("")

    if summary.by_model:
        lines.append("By model:")
        for model, stats in summary.by_model.items():
            tokens = stats.prompt_tokens + stats.completion_tokens
            lines.append(
                f"  - {model}: {tokens:,} tokens ({stats.call_count} calls)",
            )
        lines.append("")

    if summary.by_date and len(summary.by_date) <= 14:
        lines.append("By date:")
        for dt, stats in list(summary.by_date.items())[-7:]:
            tokens = stats.prompt_tokens + stats.completion_tokens
            lines.append(
                f"  - {dt}: {tokens:,} tokens ({stats.call_count} calls)",
            )
    elif summary.by_date:
        lines.append(
            f"By date: {len(summary.by_date)} days with usage "
            "(see console for details)",
        )

    text = "\n".join(lines) if lines else "No token usage data in this period."
    return ToolChunk(
        is_last=True,
        state=ToolResultState.SUCCESS,
        content=[TextBlock(type="text", text=text)],
    )
