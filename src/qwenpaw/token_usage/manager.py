# -*- coding: utf-8 -*-
"""Token usage manager — thin orchestrator.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from ..constant import WORKING_DIR, TOKEN_USAGE_FILE
from .buffer import TokenUsageBuffer, _UsageEvent
from .storage import save_data_sync

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover
    msvcrt = None

logger = logging.getLogger(__name__)

# Avoid circular import with turn_usage -> model_wrapper -> manager.
_TURN_USAGE_META_KEY = "qwenpaw_turn_usage"


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
    agent_id: str = Field("", description="Agent ID")


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


def _usage_totals(data: dict) -> tuple[int, int, int]:
    """Return (prompt, completion, calls) across all entries."""
    prompt = 0
    completion = 0
    calls = 0
    for day_bucket in data.values():
        if not isinstance(day_bucket, dict):
            continue
        for entry in day_bucket.values():
            if not isinstance(entry, dict):
                continue
            prompt += int(entry.get("prompt_tokens", 0) or 0)
            completion += int(entry.get("completion_tokens", 0) or 0)
            calls += int(entry.get("call_count", 0) or 0)
    return prompt, completion, calls


def _load_usage_file_sync(path: Path) -> dict:
    """Synchronous load used by the historical migration path."""
    if not path.exists():
        return {}
    try:
        with open(path, mode="r", encoding="utf-8") as f:
            raw = f.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "token_usage: migration failed to read %s: %s",
            path,
            exc,
        )
        return {}


def _extract_session_messages(session_data: dict) -> list:
    """Return raw message dicts from a session state (1.x or 2.0)."""
    agent_raw = session_data.get("agent", {})
    state_raw = agent_raw.get("state")
    if isinstance(state_raw, dict):
        ctx = state_raw.get("context")
        if isinstance(ctx, list) and ctx:
            return ctx
    memory_raw = agent_raw.get("memory", {})
    if isinstance(memory_raw, dict):
        return memory_raw.get("memories") or memory_raw.get("content") or []
    return []


def _resolve_msg_dict(msg_item) -> dict | None:
    """Normalize a session message item to a plain dict, or None."""
    if isinstance(msg_item, list) and msg_item:
        msg_data = msg_item[0]
    elif isinstance(msg_item, dict):
        msg_data = msg_item
    else:
        return None
    return msg_data if isinstance(msg_data, dict) else None


def _local_date_from_iso(iso_str: str) -> str:
    """Extract local-date YYYY-MM-DD from an ISO timestamp.

    Matches ``date.today()`` semantics used by the token-usage write path.
    """
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return iso_str[:10]


def _should_skip_by_mtime(session_file: Path, start_date: date) -> bool:
    """Return True when the session file was last touched before start_date."""
    try:
        mtime_date = date.fromtimestamp(session_file.stat().st_mtime)
        return mtime_date < start_date
    except OSError:
        return False


@contextmanager
def _file_write_lock(path: Path) -> Iterator[None]:
    """Serialize migration writes across processes (fcntl / msvcrt)."""
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        if fcntl is not None:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def _iter_agent_profiles() -> list[tuple[str, Path]]:
    """Return (agent_id, workspace_dir) pairs from config profiles."""
    from ..config.utils import load_config

    config = load_config()
    result: list[tuple[str, Path]] = []
    profiles = getattr(getattr(config, "agents", None), "profiles", None)
    if not profiles:
        return result
    for agent_id, profile in profiles.items():
        workspace_dir = Path(profile.workspace_dir).expanduser()
        if workspace_dir.exists():
            result.append((str(agent_id), workspace_dir))
    return result


def _collect_session_attribution(
    session_data: dict,
) -> list[tuple[str, str, int, int]]:
    """Return list of (date, provider:model, prompt, completion) evidence."""
    evidence: list[tuple[str, str, int, int]] = []
    for msg_item in _extract_session_messages(session_data):
        msg_data = _resolve_msg_dict(msg_item)
        if msg_data is None:
            continue
        timestamp = msg_data.get("created_at") or msg_data.get("timestamp")
        if not timestamp:
            continue
        date_str = _local_date_from_iso(str(timestamp))
        meta = msg_data.get("metadata")
        if not isinstance(meta, dict):
            continue
        turn_meta = meta.get(_TURN_USAGE_META_KEY)
        if not isinstance(turn_meta, dict):
            continue
        usage = turn_meta.get("usage")
        if not isinstance(usage, dict) or usage.get("estimated"):
            continue
        provider_id = str(usage.get("provider_id") or "")
        model_name = str(usage.get("model_name") or "")
        if not provider_id or not model_name:
            continue
        try:
            prompt = int(usage.get("prompt_tokens", 0) or 0)
            completion = int(usage.get("completion_tokens", 0) or 0)
        except (TypeError, ValueError):
            continue
        if prompt <= 0 and completion <= 0:
            continue
        evidence.append(
            (date_str, f"{provider_id}:{model_name}", prompt, completion),
        )
    return evidence


def _scan_agent_attribution(
    min_date: date | None = None,
) -> dict[tuple[str, str, str], list[int]]:
    """Aggregate strict session evidence by (date, model_key, agent_id)."""
    # values: [prompt_tokens, completion_tokens, call_count]
    attributed: dict[tuple[str, str, str], list[int]] = defaultdict(
        lambda: [0, 0, 0],
    )
    for agent_id, workspace_dir in _iter_agent_profiles():
        sessions_dir = workspace_dir / "sessions"
        if not sessions_dir.exists():
            continue
        for session_file in sessions_dir.glob("**/*.json"):
            if min_date is not None and _should_skip_by_mtime(
                session_file,
                min_date,
            ):
                continue
            try:
                with open(session_file, mode="r", encoding="utf-8") as f:
                    session_data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(session_data, dict):
                continue
            for (
                date_str,
                model_key,
                prompt,
                completion,
            ) in _collect_session_attribution(session_data):
                bucket = attributed[(date_str, model_key, agent_id)]
                bucket[0] += prompt
                bucket[1] += completion
                bucket[2] += 1
    return attributed


def _legacy_entry_identity(key: str, entry: dict) -> tuple[str, str]:
    """Resolve provider_id/model_name for a legacy provider:model entry."""
    provider_id = str(entry.get("provider_id") or "")
    model_name = str(entry.get("model_name") or "")
    if not provider_id or not model_name:
        if ":" in key:
            provider_id, model_name = key.split(":", 1)
        else:
            model_name = model_name or key
    return provider_id, model_name


def _accumulate_entry(
    day_out: dict,
    key: str,
    *,
    agent_id: str,
    provider_id: str,
    model_name: str,
    prompt: int,
    completion: int,
    calls: int,
) -> None:
    """Add counts into an existing day_out row, or create one."""
    existing = day_out.get(key)
    if isinstance(existing, dict):
        existing["prompt_tokens"] = (
            int(existing.get("prompt_tokens", 0) or 0) + prompt
        )
        existing["completion_tokens"] = (
            int(existing.get("completion_tokens", 0) or 0) + completion
        )
        existing["call_count"] = (
            int(existing.get("call_count", 0) or 0) + calls
        )
        return
    day_out[key] = {
        "agent_id": agent_id,
        "provider_id": provider_id,
        "model_name": model_name,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "call_count": calls,
    }


def _migrate_legacy_bucket(
    date_str: str,
    model_key: str,
    entry: dict,
    attributed: dict[tuple[str, str, str], list[int]],
    day_out: dict,
) -> None:
    """Split one legacy bucket into agent rows + unknown residual."""
    provider_id, model_name = _legacy_entry_identity(model_key, entry)
    legacy_prompt = int(entry.get("prompt_tokens", 0) or 0)
    legacy_completion = int(entry.get("completion_tokens", 0) or 0)
    legacy_calls = int(entry.get("call_count", 0) or 0)

    agent_rows: list[tuple[str, list[int]]] = []
    attr_prompt = 0
    attr_completion = 0
    attr_calls = 0
    for (d, mk, agent_id), vals in attributed.items():
        if d != date_str or mk != model_key:
            continue
        agent_rows.append((agent_id, vals))
        attr_prompt += vals[0]
        attr_completion += vals[1]
        attr_calls += vals[2]

    unsafe = (
        attr_prompt > legacy_prompt
        or attr_completion > legacy_completion
        or attr_calls > legacy_calls
    )
    if unsafe or not agent_rows:
        _accumulate_entry(
            day_out,
            f"|{model_key}",
            agent_id="",
            provider_id=provider_id,
            model_name=model_name,
            prompt=legacy_prompt,
            completion=legacy_completion,
            calls=legacy_calls,
        )
        if unsafe:
            logger.warning(
                "token_usage: skipped unsafe attribution for %s/%s "
                "(attributed=%s/%s/%s, legacy=%s/%s/%s)",
                date_str,
                model_key,
                attr_prompt,
                attr_completion,
                attr_calls,
                legacy_prompt,
                legacy_completion,
                legacy_calls,
            )
        return

    for agent_id, vals in agent_rows:
        _accumulate_entry(
            day_out,
            f"{agent_id}|{model_key}",
            agent_id=agent_id,
            provider_id=provider_id,
            model_name=model_name,
            prompt=vals[0],
            completion=vals[1],
            calls=vals[2],
        )

    residual = [
        legacy_prompt - attr_prompt,
        legacy_completion - attr_completion,
        legacy_calls - attr_calls,
    ]
    if residual[0] or residual[1] or residual[2]:
        _accumulate_entry(
            day_out,
            f"|{model_key}",
            agent_id="",
            provider_id=provider_id,
            model_name=model_name,
            prompt=residual[0],
            completion=residual[1],
            calls=residual[2],
        )


def _count_tool_calls_in_message(msg_data: dict) -> int:
    """Count tool_use / tool_call blocks in one message."""
    count = 0
    content = msg_data.get("content", [])
    if isinstance(content, list):
        for block in content:
            btype = (
                block.get("type")
                if isinstance(block, dict)
                else getattr(block, "type", None)
            )
            if btype in ("tool_use", "tool_call"):
                count += 1
    # Top-level tool_calls list (OpenAI-style messages).
    tool_calls = msg_data.get("tool_calls")
    if isinstance(tool_calls, list):
        count += len(tool_calls)
    return count


def _accumulate_session_tool_calls(
    session_data: dict,
    start_s: str,
    end_s: str,
    by_date: dict[str, int],
) -> None:
    """Add in-range tool-call counts from one session into by_date."""
    for msg_item in _extract_session_messages(session_data):
        msg_data = _resolve_msg_dict(msg_item)
        if msg_data is None:
            continue
        timestamp = msg_data.get("created_at") or msg_data.get("timestamp")
        if not timestamp:
            continue
        date_str = _local_date_from_iso(str(timestamp))
        if date_str < start_s or date_str > end_s:
            continue
        by_date[date_str] += _count_tool_calls_in_message(msg_data)


def collect_daily_tool_calls_sync(
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    """Scan all agent sessions and return daily tool-call counts.

    Returns:
        Mapping of YYYY-MM-DD -> total tool-call intents across all agents.
    """
    start_s = start_date.isoformat()
    end_s = end_date.isoformat()
    by_date: dict[str, int] = defaultdict(int)

    for _agent_id, workspace_dir in _iter_agent_profiles():
        sessions_dir = workspace_dir / "sessions"
        if not sessions_dir.exists():
            continue
        for session_file in sessions_dir.glob("**/*.json"):
            if _should_skip_by_mtime(session_file, start_date):
                continue
            try:
                with open(session_file, mode="r", encoding="utf-8") as f:
                    session_data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(session_data, dict):
                continue
            _accumulate_session_tool_calls(
                session_data,
                start_s,
                end_s,
                by_date,
            )

    return dict(by_date)


def _migrate_day_bucket(
    date_str: str,
    day_bucket: dict,
    attributed: dict[tuple[str, str, str], list[int]],
) -> dict:
    """Migrate one day's legacy keys; preserve already-migrated rows."""
    day_out: dict = {}
    for key, entry in day_bucket.items():
        if isinstance(entry, dict) and "|" in key:
            day_out[key] = entry
    for key, entry in day_bucket.items():
        if not isinstance(entry, dict) or "|" in key:
            continue
        _migrate_legacy_bucket(
            date_str,
            key,
            entry,
            attributed,
            day_out,
        )
    return day_out


def migrate_historical_agent_ids_sync(path: Path) -> bool:
    """Idempotently backfill agent_id into legacy token usage rows.

    Only keys without ``|`` are migrated. Returns True when a write occurred.
    """
    with _file_write_lock(path):
        # Re-read under lock for a consistent multi-worker snapshot.
        data = _load_usage_file_sync(path)
        has_legacy = any(
            isinstance(day_bucket, dict)
            and any("|" not in key for key in day_bucket)
            for day_bucket in data.values()
        )
        if not data or not has_legacy:
            return False

        before = _usage_totals(data)
        min_date: date | None = None
        for date_str in data:
            try:
                parsed = date.fromisoformat(str(date_str)[:10])
            except ValueError:
                continue
            if min_date is None or parsed < min_date:
                min_date = parsed
        attributed = _scan_agent_attribution(min_date=min_date)
        migrated: dict = {}
        for date_str, day_bucket in data.items():
            if not isinstance(day_bucket, dict):
                continue
            migrated[date_str] = _migrate_day_bucket(
                date_str,
                day_bucket,
                attributed,
            )

        after = _usage_totals(migrated)
        if after != before:
            logger.warning(
                "token_usage: migration aborted to preserve totals "
                "(before=%s, after=%s)",
                before,
                after,
            )
            return False

        if not save_data_sync(path, migrated):
            logger.warning("token_usage: migration failed to persist %s", path)
            return False

        logger.info(
            "token_usage: historical agent attribution migration complete",
        )
        return True


class TokenUsageManager:
    """Orchestrator for token usage recording and querying."""

    _instance: "TokenUsageManager | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        path: Path = (WORKING_DIR / TOKEN_USAGE_FILE).expanduser()
        self._buffer = TokenUsageBuffer(path)
        self._flush_interval = 10  # default

    async def migrate_historical_agent_ids(self) -> bool:
        """Run historical agent attribution migration off the event loop."""
        # pylint: disable=protected-access
        path = self._buffer._path
        return await asyncio.to_thread(
            migrate_historical_agent_ids_sync,
            path,
        )

    async def get_daily_tool_calls(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> dict[str, int]:
        """Return daily tool-call totals across all configured agents."""
        if end_date is None:
            end_date = date.today()
        if start_date is None:
            start_date = end_date - timedelta(days=30)
        return await asyncio.to_thread(
            collect_daily_tool_calls_sync,
            start_date,
            end_date,
        )

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
        agent_id: str = "",
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
            agent_id: Optional agent ID that produced this usage.
        """
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
                agent_id=agent_id,
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
                rec_agent = entry.get("agent_id", "")
                # Backward compat: old keys have no "|"; new keys are
                # "agent_id|provider:model".
                if not rec_agent and "|" in _key:
                    rec_agent = _key.split("|", 1)[0]
                rec_provider = entry.get("provider_id", "")
                rec_model = entry.get("model_name") or _key.rsplit(":", 1)[-1]
                if model_name is not None and rec_model != model_name:
                    continue
                if provider_id is not None and rec_provider != provider_id:
                    continue
                results.append(
                    TokenUsageRecord(
                        date=date_str,
                        provider_id=rec_provider,
                        model=rec_model,
                        agent_id=rec_agent,
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
