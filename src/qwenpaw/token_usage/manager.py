# -*- coding: utf-8 -*-
"""Token usage manager — thin orchestrator.
"""

import logging
import threading
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..constant import WORKING_DIR, TOKEN_USAGE_FILE
from .buffer import TokenUsageBuffer, _UsageEvent

logger = logging.getLogger(__name__)


class TokenUsageStats(BaseModel):
    """Prompt/completion tokens and call count."""

    prompt_tokens: int = Field(0, ge=0)
    completion_tokens: int = Field(0, ge=0)
    call_count: int = Field(0, ge=0)


class TokenUsageRecord(TokenUsageStats):
    """Single row from token usage query (per date + provider + model)."""

    date: str = Field(..., description="Date (YYYY-MM-DD)")
    provider_id: str = Field("", description="Provider ID")
    model: str = Field(..., description="Model name")


class TokenUsageByModel(TokenUsageStats):
    """Per-model aggregate in summary (provider + model + counts)."""

    provider_id: str = Field("", description="Provider ID")
    model: str = Field(..., description="Model name")


class TokenUsageByDateModel(TokenUsageStats):
    """Per-date per-model aggregate in summary."""

    provider_id: str = Field("", description="Provider ID")
    model: str = Field(..., description="Model name")


class TokenUsageSummary(BaseModel):
    """Aggregated token usage summary returned by get_summary()."""

    total_prompt_tokens: int = Field(0, ge=0)
    total_completion_tokens: int = Field(0, ge=0)
    total_calls: int = Field(0, ge=0)
    by_model: dict[str, TokenUsageByModel] = Field(
        default_factory=dict,
        description="Per model (provider:model key) aggregation",
    )
    by_date: dict[str, TokenUsageStats] = Field(
        default_factory=dict,
        description="Per date (YYYY-MM-DD) - all models combined",
    )


class TokenUsageManager:
    """Orchestrator for token usage recording and querying."""

    _instance: "TokenUsageManager | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        path: Path = (WORKING_DIR / TOKEN_USAGE_FILE).expanduser()
        self._buffer = TokenUsageBuffer(path)
        self._flush_interval = 10  # default

    def start(self, flush_interval: int = 10) -> None:
        """Start background flush task.

        Must be called from an async context (e.g. app lifespan startup).
        ``flush_interval`` is the number of seconds between flushes.
        """
        self._flush_interval = flush_interval
        # Recreate buffer with desired flush_interval if different from default
        if flush_interval != 10:
            path: Path = (WORKING_DIR / TOKEN_USAGE_FILE).expanduser()
            self._buffer = TokenUsageBuffer(
                path,
                flush_interval=flush_interval,
            )
        self._buffer.start()

    async def stop(self) -> None:
        """Stop the flush task and perform a final flush before exit."""
        await self._buffer.stop()

    def enqueue(self, event: _UsageEvent) -> None:
        """Synchronous fire-and-forget — enqueue a pre-built usage event.

        Called directly from ``TokenRecordingModelWrapper._record_usage()``
        on the hot path. No ``await`` required.
        """
        self._buffer.enqueue(event)

    async def record(
        self,
        provider_id: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        at_date: Optional[date] = None,
    ) -> None:
        """Record token usage for a given provider, model and date.

        Convenience async wrapper around ``enqueue()`` for callers that
        prefer the original async interface (e.g. tests, skill tools).

        Args:
            provider_id: ID of the provider (e.g. "dashscope", "openai").
            model_name: Name of the model (e.g. "qwen3-max", "gpt-4").
            prompt_tokens: Number of input/prompt tokens.
            completion_tokens: Number of output/completion tokens.
            at_date: Date to record under. Defaults to today (local).
        """
        from datetime import datetime, timezone

        if at_date is None:
            at_date = date.today()
        self._buffer.enqueue(
            _UsageEvent(
                provider_id=provider_id,
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                date_str=at_date.isoformat(),
                now_iso=datetime.now(tz=timezone.utc).isoformat(
                    timespec="seconds",
                ),
            ),
        )

    async def _query(
        self,
        merged: dict,
        start_date: date,
        end_date: date,
        model_name: Optional[str],
        provider_id: Optional[str],
    ) -> list[TokenUsageRecord]:
        """Return per-day records from the merged data dict."""
        results: list[TokenUsageRecord] = []

        current = start_date
        while current <= end_date:
            date_str = current.isoformat()
            by_key = merged.get(date_str, {})
            for _key, entry in by_key.items():
                rec_provider = entry.get("provider_id", "")
                rec_model = entry.get("model_name") or _key
                if model_name is not None and rec_model != model_name:
                    continue
                if provider_id is not None and rec_provider != provider_id:
                    continue
                results.append(
                    TokenUsageRecord(
                        date=date_str,
                        provider_id=rec_provider,
                        model=rec_model,
                        prompt_tokens=entry.get("prompt_tokens", 0),
                        completion_tokens=entry.get("completion_tokens", 0),
                        call_count=entry.get("call_count", 0),
                    ),
                )
            current += timedelta(days=1)

        return results

    async def get_summary(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        model_name: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> TokenUsageSummary:
        """Get aggregated token usage summary.

        Args:
            start_date: Start of date range (inclusive). Default: 30 days ago.
            end_date: End of date range (inclusive). Default: today.
            model_name: Optional model name filter.
            provider_id: Optional provider ID filter.

        Returns:
            TokenUsageSummary with totals, by_model, by_provider, by_date.
        """
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        merged = await self._buffer.get_merged_data()

        records = await self._query(
            merged,
            start_date,
            end_date,
            model_name,
            provider_id,
        )

        total_prompt = 0
        total_completion = 0
        total_calls = 0
        by_model_raw: dict[str, dict] = {}
        by_date_raw: dict[str, dict] = {}

        for r in records:
            pt = r.prompt_tokens
            ct = r.completion_tokens
            calls = r.call_count
            total_prompt += pt
            total_completion += ct
            total_calls += calls

            # Aggregate by model
            model_key = (
                f"{r.provider_id}:{r.model}" if r.provider_id else r.model
            )
            bm = by_model_raw.setdefault(
                model_key,
                {
                    "provider_id": r.provider_id,
                    "model": r.model,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "call_count": 0,
                },
            )
            bm["prompt_tokens"] += pt
            bm["completion_tokens"] += ct
            bm["call_count"] += calls

            # Aggregate by date
            bd = by_date_raw.setdefault(
                r.date,
                {"prompt_tokens": 0, "completion_tokens": 0, "call_count": 0},
            )
            bd["prompt_tokens"] += pt
            bd["completion_tokens"] += ct
            bd["call_count"] += calls

        return TokenUsageSummary(
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            total_calls=total_calls,
            by_model={
                k: TokenUsageByModel.model_validate(v)
                for k, v in sorted(by_model_raw.items())
            },
            by_date={
                k: TokenUsageStats.model_validate(v)
                for k, v in sorted(by_date_raw.items())
            },
        )

    async def get_details(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        model_name: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> list[TokenUsageRecord]:
        """Get raw token usage records for frontend aggregation.

        Args:
            start_date: Start of date range (inclusive). Default: 30 days ago.
            end_date: End of date range (inclusive). Default: today.
            model_name: Optional model name filter.
            provider_id: Optional provider ID filter.

        Returns:
            List of TokenUsageRecord with per-date per-model data.
        """
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        merged = await self._buffer.get_merged_data()

        records = await self._query(
            merged,
            start_date,
            end_date,
            model_name,
            provider_id,
        )

        return records

    @classmethod
    def get_instance(cls) -> "TokenUsageManager":
        """Return the process-wide singleton ``TokenUsageManager``."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance


def get_token_usage_manager() -> TokenUsageManager:
    """Return the process-wide singleton ``TokenUsageManager``."""
    return TokenUsageManager.get_instance()


# Marker placed on a usage-note ``Msg.metadata`` so the agent memory keeps it
# for display/reload but excludes it from the prompt sent to the model.
USAGE_NOTE_META_KEY = "qwenpaw_usage_note"


def fmt_tokens(n: int) -> str:
    return f"{n / 1000:.1f}K" if n >= 1000 else str(n)


# (title, turn-template, turn-template-estimated, context-template).
# Templates use {tt}/{pt}/{ct} for turn tokens, {est}/{mx}/{ratio} for context.
_USAGE_NOTE_I18N: dict[str, tuple[str, str, str, str]] = {
    "zh": (
        "用量统计",
        "本轮 **{tt}** tok （in {pt} · out {ct}）",
        "本轮约 **{tt}** tok （in {pt} · out {ct}）",
        "上下文 **{est}** / **{mx}** （{ratio:.1f}%）",
    ),
    "ja": (
        "使用量統計",
        "このターン **{tt}** tok （入力 {pt} · 出力 {ct}）",
        "このターン約 **{tt}** tok （入力 {pt} · 出力 {ct}）",
        "コンテキスト **{est}** / **{mx}** （{ratio:.1f}%）",
    ),
    "ru": (
        "Статистика использования",
        "Ход **{tt}** tok (in {pt} · out {ct})",
        "Ход примерно **{tt}** tok (in {pt} · out {ct})",
        "Контекст **{est}** / **{mx}** ({ratio:.1f}%)",
    ),
    "pt": (
        "Estatísticas de uso",
        "Turno **{tt}** tok (in {pt} · out {ct})",
        "Turno aprox. **{tt}** tok (in {pt} · out {ct})",
        "Contexto **{est}** / **{mx}** ({ratio:.1f}%)",
    ),
    "en": (
        "Usage statistics",
        "This turn **{tt}** tok (in {pt} · out {ct})",
        "~This turn **{tt}** tok (in {pt} · out {ct})",
        "Context **{est}** / **{mx}** ({ratio:.1f}%)",
    ),
}


def _lang(language: str | None) -> str:
    prefix = (language or "").lower()[:2]
    return prefix if prefix in _USAGE_NOTE_I18N else "en"


def format_usage_chat_note(
    turn: dict[str, Any] | None,
    ctx: dict[str, Any] | None,
    language: str | None = "zh",
) -> str:
    title, turn_tpl, turn_tpl_est, ctx_tpl = _USAGE_NOTE_I18N[_lang(language)]
    lines: list[str] = []
    if turn:
        tpl = turn_tpl_est if turn.get("estimated") else turn_tpl
        lines.append(
            tpl.format(
                tt=fmt_tokens(int(turn.get("total_tokens", 0) or 0)),
                pt=fmt_tokens(int(turn.get("prompt_tokens", 0) or 0)),
                ct=fmt_tokens(int(turn.get("completion_tokens", 0) or 0)),
            ),
        )
    if ctx:
        lines.append(
            ctx_tpl.format(
                est=fmt_tokens(int(ctx.get("estimated_tokens", 0) or 0)),
                mx=fmt_tokens(int(ctx.get("max_input_length", 0) or 0)),
                ratio=float(ctx.get("context_usage_ratio", 0) or 0),
            ),
        )
    if not lines:
        return ""
    return f"📊 **{title}**\n" + "\n".join(lines)
