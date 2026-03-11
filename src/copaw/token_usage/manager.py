# -*- coding: utf-8 -*-
"""Token usage manager"""

import json
import logging
import threading
from datetime import date, timedelta
from pathlib import Path

import aiofiles
from pydantic import BaseModel, Field

from ..constant import WORKING_DIR, TOKEN_USAGE_FILE

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


class TokenUsageSummary(BaseModel):
    """Aggregated token usage summary returned by get_summary()."""

    total_prompt_tokens: int = Field(0, ge=0)
    total_completion_tokens: int = Field(0, ge=0)
    total_calls: int = Field(0, ge=0)
    by_model: dict[str, TokenUsageByModel] = Field(
        default_factory=dict,
        description="Per composite key (provider:model)",
    )
    by_provider: dict[str, TokenUsageStats] = Field(
        default_factory=dict,
        description="Per provider_id",
    )
    by_date: dict[str, TokenUsageStats] = Field(
        default_factory=dict,
        description="Per date (YYYY-MM-DD)",
    )


class TokenUsageManager:
    """Manager for token usage records.
    Use get_instance() to obtain the singleton."""

    _instance: "TokenUsageManager | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._path: Path = (WORKING_DIR / TOKEN_USAGE_FILE).expanduser()
        self._file_lock = threading.Lock()

    async def _load_data(self) -> dict:
        """Load full token usage data from disk."""
        if not self._path.exists():
            return {}
        try:
            async with aiofiles.open(
                self._path,
                mode="r",
                encoding="utf-8",
            ) as f:
                raw = await f.read()
            return json.loads(raw) if raw.strip() else {}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                "Failed to read token usage file %s: %s",
                self._path,
                e,
            )
            return {}

    async def _save_data(self, data: dict) -> None:
        """Persist token usage data to disk."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(
                self._path,
                mode="w",
                encoding="utf-8",
            ) as f:
                await f.write(json.dumps(data, ensure_ascii=False, indent=2))
        except OSError as e:
            logger.warning(
                "Failed to write token usage to %s: %s",
                self._path,
                e,
            )

    async def record(
        self,
        provider_id: str,
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        at_date: date | None = None,
    ) -> None:
        """Record token usage for a given provider, model and date.

        Args:
            provider_id: ID of the provider (e.g. "dashscope", "openai").
            model_name: Name of the model (e.g. "qwen3-max", "gpt-4").
            prompt_tokens: Number of input/prompt tokens.
            completion_tokens: Number of output/completion tokens.
            at_date: Date to record under. Defaults to today (UTC).
        """
        if at_date is None:
            at_date = date.today()

        date_str = at_date.isoformat()
        composite_key = f"{provider_id}:{model_name}"

        with self._file_lock:
            data = await self._load_data()
            if date_str not in data:
                data[date_str] = {}

            by_key = data[date_str]
            if composite_key not in by_key:
                by_key[composite_key] = {
                    "provider_id": provider_id,
                    "model_name": model_name,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "call_count": 0,
                }

            entry = by_key[composite_key]
            entry.setdefault("provider_id", provider_id)
            entry.setdefault("model_name", model_name)
            entry["prompt_tokens"] += prompt_tokens
            entry["completion_tokens"] += completion_tokens
            entry["call_count"] += 1

            await self._save_data(data)

    async def _query(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        model_name: str | None = None,
        provider_id: str | None = None,
    ) -> list[TokenUsageRecord]:
        """Return raw token usage records (used by get_summary)."""
        data = await self._load_data()
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=30)

        results: list[TokenUsageRecord] = []
        current = start_date
        while current <= end_date:
            date_str = current.isoformat()
            by_key = data.get(date_str, {})
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
        start_date: date | None = None,
        end_date: date | None = None,
        model_name: str | None = None,
        provider_id: str | None = None,
    ) -> TokenUsageSummary:
        """Get aggregated token usage summary.

        Args:
            start_date: Start of date range (inclusive).
            end_date: End of date range (inclusive).
            model_name: Optional model name filter.
            provider_id: Optional provider ID filter.

        Returns:
            TokenUsageSummary with totals and by_model, by_provider, by_date.
        """
        records = await self._query(
            start_date=start_date,
            end_date=end_date,
            model_name=model_name,
            provider_id=provider_id,
        )

        total_prompt = 0
        total_completion = 0
        total_calls = 0
        by_model_raw: dict[str, dict] = {}
        by_provider_raw: dict[str, dict] = {}
        by_date_raw: dict[str, dict] = {}

        for r in records:
            pt = r.prompt_tokens
            ct = r.completion_tokens
            calls = r.call_count
            total_prompt += pt
            total_completion += ct
            total_calls += calls

            model = r.model
            prov = r.provider_id
            composite = f"{prov}:{model}" if prov else model
            if composite not in by_model_raw:
                by_model_raw[composite] = {
                    "provider_id": prov,
                    "model": model,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "call_count": 0,
                }
            by_model_raw[composite]["prompt_tokens"] += pt
            by_model_raw[composite]["completion_tokens"] += ct
            by_model_raw[composite]["call_count"] += calls

            if prov not in by_provider_raw:
                by_provider_raw[prov] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "call_count": 0,
                }
            by_provider_raw[prov]["prompt_tokens"] += pt
            by_provider_raw[prov]["completion_tokens"] += ct
            by_provider_raw[prov]["call_count"] += calls

            dt = r.date
            if dt not in by_date_raw:
                by_date_raw[dt] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "call_count": 0,
                }
            by_date_raw[dt]["prompt_tokens"] += pt
            by_date_raw[dt]["completion_tokens"] += ct
            by_date_raw[dt]["call_count"] += calls

        by_model = {
            k: TokenUsageByModel.model_validate(v)
            for k, v in by_model_raw.items()
        }
        by_provider = {
            k: TokenUsageStats.model_validate(v)
            for k, v in by_provider_raw.items()
        }
        by_date = {
            k: TokenUsageStats.model_validate(v)
            for k, v in sorted(by_date_raw.items())
        }

        return TokenUsageSummary(
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            total_calls=total_calls,
            by_model=by_model,
            by_provider=by_provider,
            by_date=by_date,
        )

    @classmethod
    def get_instance(cls) -> "TokenUsageManager":
        """Return the singleton TokenUsageManager instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance


def get_token_usage_manager() -> TokenUsageManager:
    """Return the singleton TokenUsageManager instance."""
    return TokenUsageManager.get_instance()
