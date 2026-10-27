# -*- coding: utf-8 -*-
"""Deliver ReMe's proactive agenda through QwenPaw's surfaces.

QwenPaw no longer produces proactive topics itself.  ReMe's proactive
chain (extract -> topics -> plan -> agenda) already ranks the day's
agenda and pins due reminders first, so delivery here is read-only
presentation:

* ``/proactive`` answers in the user's current chat with the top few
  openers (:func:`present_agenda_receipt`).  Reading the agenda is cheap;
  rebuilding it is not, so an empty read queues
  :func:`start_agenda_rebuild` and answers at once instead of holding the
  chat open for minutes;
* the idle trigger and the daily cron push the same items to the inbox
  (:func:`deliver_proactive_round`).

No LLM call and no tool execution happens on this path, which is what
keeps an agenda item from ever being mistaken for an instruction the
agent should carry out by itself.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ....config.config import load_agent_config
from ....utils.io_utils import run_sync_io
from ..action_provider import MemoryActionProvider
from ..reme_inbox import emit_proactive_agenda
from .proactive_agenda import (
    AgendaBundle,
    AgendaItem,
    ensure_agenda,
    refresh_in_progress,
    select_presentation_items,
)
from .proactive_delivery import (
    get_delivery_ledger,
    ledger_path,
    mark_delivered,
)
from .proactive_prompts import (
    render_agenda_receipt,
    text_for,
)

logger = logging.getLogger(__name__)

CHANNEL_CONVERSATION = "in_conversation"
CHANNEL_INBOX = "inbox"


@dataclass(frozen=True)
class ProactiveSettings:
    """The proactive slice of one agent's long-term memory config."""

    language: str = "en"
    enabled: bool = False
    inbox_enabled: bool = False
    max_items: int = 3
    cron_max_items: int = 0
    cooldown_days: int = 3
    refresh_min_interval_minutes: int = 120
    metadata_dir: str = "mem_metadata"


@dataclass
class AgendaRound:
    """What one proactive delivery attempt actually did."""

    language: str = "en"
    available: bool = False
    date: str = ""
    items: list[AgendaItem] = field(default_factory=list)
    shown: list[AgendaItem] = field(default_factory=list)
    refreshed: bool = False
    forced_refresh: bool = False
    throttled: bool = False
    hidden_total: int = 0
    cooldown_days: int = 0
    refresh_min_interval_minutes: int = 0
    pushed: bool = False
    event_id: str = ""
    skip_reason: str = ""

    def empty_state(self) -> str:
        """Localized explanation for a round with nothing to show.

        Withheld items outrank the refresh throttle: "everything was
        already surfaced" is the fact the user can act on, while the
        throttle only explains a round that had nothing to withhold.
        """
        if not self.available:
            key = "empty_unavailable"
        elif self.hidden_total:
            return text_for(
                "empty_all_delivered",
                self.language,
                count=self.hidden_total,
                days=self.cooldown_days,
            )
        elif self.throttled:
            return text_for(
                "empty_throttled",
                self.language,
                minutes=self.refresh_min_interval_minutes,
            )
        elif self.refreshed and self.forced_refresh:
            key = "empty_after_refresh_forced"
        else:
            key = "empty_after_refresh"
        return text_for(key, self.language)


async def load_proactive_settings(agent_id: str) -> ProactiveSettings:
    """Read the proactive switches without blocking the event loop."""
    agent_config = await run_sync_io(load_agent_config, agent_id)
    cfg = getattr(agent_config.running, "reme_light_memory_config", None)
    if cfg is None:
        return ProactiveSettings(language=agent_config.language)
    return ProactiveSettings(
        language=str(getattr(agent_config, "language", "en") or "en"),
        enabled=bool(getattr(cfg, "proactive_enabled", False)),
        inbox_enabled=bool(
            getattr(cfg, "proactive_inbox_push_enabled", False),
        ),
        max_items=int(getattr(cfg, "proactive_max_items", 3)),
        cron_max_items=int(getattr(cfg, "proactive_cron_max_items", 0)),
        cooldown_days=int(
            getattr(cfg, "proactive_delivery_cooldown_days", 3),
        ),
        refresh_min_interval_minutes=int(
            getattr(cfg, "proactive_refresh_min_interval_minutes", 120),
        ),
        metadata_dir=str(getattr(cfg, "metadata_dir", "mem_metadata")),
    )


def resolve_memory_provider(candidate: Any) -> MemoryActionProvider | None:
    """Return ``candidate`` when it can actually serve memory actions."""
    if isinstance(candidate, MemoryActionProvider):
        return candidate
    return None


def _ledger_for(workspace_dir: str, settings: ProactiveSettings):
    return get_delivery_ledger(
        ledger_path(workspace_dir, settings.metadata_dir),
    )


async def collect_agenda(
    memory_manager: Any,
    *,
    agent_id: str,
    workspace_dir: str,
    force_refresh: bool = False,
    limit: int | None = None,
    settings: ProactiveSettings | None = None,
    allow_refresh: bool = True,
) -> AgendaRound:
    """Read (and refresh when empty) the agenda for one delivery round.

    ``allow_refresh=False`` keeps the round read-only: ReMe's rebuild costs
    minutes of model work, so a caller answering a live chat asks for the
    ranked agenda only and schedules the rebuild itself.
    """
    resolved = settings or await load_proactive_settings(agent_id)
    provider = resolve_memory_provider(memory_manager)
    cap = resolved.max_items if limit is None else limit
    base = AgendaRound(
        language=resolved.language,
        forced_refresh=force_refresh,
        cooldown_days=resolved.cooldown_days,
        refresh_min_interval_minutes=resolved.refresh_min_interval_minutes,
    )
    if provider is None:
        base.skip_reason = "unavailable"
        return base

    ledger = _ledger_for(workspace_dir, resolved)
    bundle: AgendaBundle = await ensure_agenda(
        provider,
        ledger,
        cooldown_days=resolved.cooldown_days,
        min_interval_minutes=resolved.refresh_min_interval_minutes,
        force_refresh=force_refresh,
        scope=workspace_dir,
        refresh=allow_refresh,
    )
    base.available = bundle.available
    base.date = bundle.date
    base.items = list(bundle.items)
    base.refreshed = bundle.refreshed
    base.throttled = bundle.throttled
    base.hidden_total = bundle.hidden_total
    base.shown = select_presentation_items(bundle.items, limit=cap)
    if not base.available:
        base.skip_reason = "unavailable"
    elif not base.shown:
        # Name the most specific cause: everything withheld beats the
        # refresh throttle, which only matters when nothing was withheld.
        if base.hidden_total:
            base.skip_reason = "all_delivered"
        else:
            base.skip_reason = "throttled" if bundle.throttled else "empty"
    return base


async def present_agenda_receipt(
    *,
    agent_id: str,
    workspace_dir: str,
    memory_manager: Any,
    limit: int | None = None,
    session_id: str = "",
    settings: ProactiveSettings | None = None,
) -> str:
    """Answer ``/proactive`` in chat without ever blocking on a rebuild.

    Reading ReMe's ranked agenda is cheap, so a non-empty agenda is presented
    right away -- a few openers as one message, never an instruction to the
    agent -- and reported back as delivered.

    When nothing is left to show, the rebuild (ReMe's extract -> topics ->
    plan -> agenda chain, minutes of model work) is queued in the background
    and the caller gets an immediate notice instead of a spinner.  The
    receipt then follows on its own: a console push to the session that
    asked, plus an inbox card whenever that switch is on.
    """
    resolved = settings or await load_proactive_settings(agent_id)
    if not resolved.enabled:
        return text_for("disabled", resolved.language)

    outcome = await collect_agenda(
        memory_manager,
        agent_id=agent_id,
        workspace_dir=workspace_dir,
        limit=limit,
        settings=resolved,
        allow_refresh=False,
    )
    if outcome.shown:
        await mark_delivered(
            resolve_memory_provider(memory_manager),
            _ledger_for(workspace_dir, resolved),
            items=outcome.shown,
            channel=CHANNEL_CONVERSATION,
            external_ref=session_id,
            date=outcome.date,
        )
        return render_agenda_receipt(
            outcome.shown,
            resolved.language,
            date=outcome.date,
        )

    # Nothing to present.  Name the most specific reason; only a genuinely
    # empty agenda earns a rebuild, and only one at a time.
    if not outcome.available:
        return text_for("empty_unavailable", resolved.language)
    if outcome.hidden_total:
        return text_for(
            "empty_all_delivered",
            resolved.language,
            count=outcome.hidden_total,
            days=resolved.cooldown_days,
        )
    if outcome.throttled:
        return text_for(
            "empty_throttled",
            resolved.language,
            minutes=resolved.refresh_min_interval_minutes,
        )
    queued = start_agenda_rebuild(
        agent_id=agent_id,
        workspace_dir=workspace_dir,
        memory_manager=memory_manager,
        session_id=session_id,
        limit=limit,
        settings=resolved,
    )
    return rebuild_notice(
        resolved.language,
        queued=queued,
        inbox_enabled=resolved.inbox_enabled,
    )


def rebuild_notice(
    agent_language: Any,
    *,
    queued: bool,
    inbox_enabled: bool = False,
) -> str:
    """What an interactive surface says after handing a rebuild off.

    Shared by ``/proactive`` and ``/proactive now`` so both answer at once
    with the same promise: the receipt arrives separately, and the inbox
    keeps a durable copy when that switch is on.
    """
    if not queued:
        return text_for("rebuild_in_progress", agent_language)
    notice = text_for("rebuild_started", agent_language)
    if inbox_enabled:
        inbox_note = text_for("rebuild_started_inbox", agent_language)
        notice = f"{notice}\n\n{inbox_note}"
    return notice


_rebuild_tasks: dict[str, "asyncio.Task[None]"] = {}


def _rebuild_key(workspace_dir: str, agent_id: str) -> str:
    return (workspace_dir or agent_id or "").strip() or "default"


def rebuild_in_progress(workspace_dir: str, agent_id: str = "") -> bool:
    """Whether this workspace already has a rebuild queued or running."""
    task = _rebuild_tasks.get(_rebuild_key(workspace_dir, agent_id))
    if task is not None and not task.done():
        return True
    # The idle trigger and the daily cron refresh through ``ensure_agenda``
    # without queueing a task here, so ask the refresh registry too.
    return refresh_in_progress(workspace_dir)


def start_agenda_rebuild(
    *,
    agent_id: str,
    workspace_dir: str,
    memory_manager: Any,
    session_id: str = "",
    limit: int | None = None,
    settings: ProactiveSettings | None = None,
) -> bool:
    """Queue one background rebuild; ``False`` when one is already running.

    No interactive surface should wait minutes for ReMe's chain, and one
    rebuild per workspace is enough: a second ``/proactive`` -- or a cron or
    idle round landing at the same moment -- reports the running one instead
    of stacking another chain on the same ``interests.yaml``.
    """
    if rebuild_in_progress(workspace_dir, agent_id):
        logger.info(
            "proactive agenda rebuild already running: workspace=%s",
            workspace_dir or agent_id,
        )
        return False
    key = _rebuild_key(workspace_dir, agent_id)
    task = asyncio.create_task(
        _rebuild_and_deliver(
            agent_id=agent_id,
            workspace_dir=workspace_dir,
            memory_manager=memory_manager,
            session_id=session_id,
            limit=limit,
            settings=settings,
        ),
        name=f"proactive-rebuild-{key}",
    )
    _rebuild_tasks[key] = task

    def _forget(_done: "asyncio.Task[None]", _key: str = key) -> None:
        _rebuild_tasks.pop(_key, None)

    task.add_done_callback(_forget)
    return True


async def _rebuild_and_deliver(
    *,
    agent_id: str,
    workspace_dir: str,
    memory_manager: Any,
    session_id: str,
    limit: int | None,
    settings: ProactiveSettings | None,
) -> None:
    """Rebuild the agenda in the background, then deliver its receipt."""
    # This task outlives the request that queued it, so re-seed the context
    # everything downstream (inbox store, config cache) resolves.
    from ....app.agent_context import (  # noqa: PLC0415
        set_current_agent_id,
    )
    from ....config.context import (  # noqa: PLC0415
        set_current_workspace_dir,
    )

    set_current_agent_id(agent_id)
    set_current_workspace_dir(Path(workspace_dir) if workspace_dir else None)

    resolved = settings or await load_proactive_settings(agent_id)
    started = time.monotonic()
    try:
        outcome = await collect_agenda(
            memory_manager,
            agent_id=agent_id,
            workspace_dir=workspace_dir,
            force_refresh=True,
            limit=limit,
            settings=resolved,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("proactive agenda rebuild failed")
        await notify_rebuild_result(
            session_id,
            text_for("rebuild_failed", resolved.language, error=exc),
        )
        return

    elapsed = int(time.monotonic() - started)
    logger.info(
        "proactive agenda rebuild done in %ds: shown=%d reason=%s",
        elapsed,
        len(outcome.shown),
        outcome.skip_reason or "-",
    )
    if not outcome.shown:
        # ``refreshed`` tells a rebuild that found nothing apart from one
        # that never succeeded (ReMe down, job missing, refresh error).
        if outcome.refreshed:
            notice = text_for(
                "rebuild_empty",
                resolved.language,
                seconds=elapsed,
            )
        else:
            notice = text_for(
                "rebuild_failed",
                resolved.language,
                error=outcome.skip_reason or "unavailable",
            )
        await notify_rebuild_result(session_id, notice)
        return

    pushed = False
    if resolved.inbox_enabled:
        pushed = await _push_to_inbox(
            agent_id=agent_id,
            workspace_dir=workspace_dir,
            memory_manager=memory_manager,
            settings=resolved,
            outcome=outcome,
            channel="idle",
        )
    if pushed:
        notice = text_for(
            "rebuild_done_inbox",
            resolved.language,
            count=len(outcome.shown),
            seconds=elapsed,
        )
    else:
        # Without a durable inbox copy the chat notice carries the receipt.
        await mark_delivered(
            resolve_memory_provider(memory_manager),
            _ledger_for(workspace_dir, resolved),
            items=outcome.shown,
            channel=CHANNEL_CONVERSATION,
            external_ref=session_id,
            date=outcome.date,
        )
        notice = render_agenda_receipt(
            outcome.shown,
            resolved.language,
            date=outcome.date,
        )
    await notify_rebuild_result(session_id, notice)


async def notify_rebuild_result(session_id: str, text: str) -> None:
    """Push one out-of-band notice into the console session that asked.

    This is the surface cron already uses for out-of-band text: the console
    polls it and shows a bubble.  Bubbles are transient, which is why a
    rebuild with items also lands in the inbox whenever that switch is on.
    """
    if not session_id or not text.strip():
        return
    try:
        from ....app.console_push_store import (  # noqa: PLC0415
            append as push_store_append,
        )

        await push_store_append(session_id, text.strip())
    except Exception:  # noqa: BLE001
        logger.warning(
            "proactive rebuild notice could not be pushed",
            exc_info=True,
        )


async def deliver_proactive_round(
    *,
    agent_id: str,
    workspace_dir: str,
    memory_manager: Any,
    channel: str = "idle",
    force_refresh: bool = False,
    limit: int | None = None,
    settings: ProactiveSettings | None = None,
) -> AgendaRound:
    """Push one agenda round to the inbox; stay silent when empty.

    Used by the idle trigger (``channel="idle"``) and by the daily cron job
    (``channel="cron"``, ``force_refresh=True``).  Both are automatic
    surfaces, so an empty agenda produces no event and no notification --
    only a log line.
    """
    # The idle trigger calls this from an ``asyncio.create_task`` that never
    # passes through ``ContextVarsSetupHook``, so anything downstream that
    # resolves the current agent (inbox store, config cache) would otherwise
    # silently fall back to the default agent.
    from ....app.agent_context import (  # noqa: PLC0415
        set_current_agent_id,
    )
    from ....config.context import (  # noqa: PLC0415
        set_current_workspace_dir,
    )

    set_current_agent_id(agent_id)
    set_current_workspace_dir(Path(workspace_dir) if workspace_dir else None)

    resolved = settings or await load_proactive_settings(agent_id)
    if not resolved.enabled:
        logger.info("proactive round skipped; feature disabled")
        return AgendaRound(
            language=resolved.language,
            skip_reason="disabled",
        )
    if not resolved.inbox_enabled:
        logger.info("proactive round skipped; inbox push disabled")
        return AgendaRound(
            language=resolved.language,
            available=True,
            skip_reason="inbox_disabled",
        )

    cap = resolved.cron_max_items if channel == "cron" else resolved.max_items
    if limit is not None:
        cap = limit
    outcome = await collect_agenda(
        memory_manager,
        agent_id=agent_id,
        workspace_dir=workspace_dir,
        force_refresh=force_refresh,
        limit=cap,
        settings=resolved,
    )
    if not outcome.shown:
        logger.info(
            "proactive round produced nothing: channel=%s reason=%s",
            channel,
            outcome.skip_reason or "empty",
        )
        return outcome

    await _push_to_inbox(
        agent_id=agent_id,
        workspace_dir=workspace_dir,
        memory_manager=memory_manager,
        settings=resolved,
        outcome=outcome,
        channel=channel,
    )
    return outcome


async def _push_to_inbox(
    *,
    agent_id: str,
    workspace_dir: str,
    memory_manager: Any,
    settings: ProactiveSettings,
    outcome: AgendaRound,
    channel: str,
) -> bool:
    """Emit one round's inbox card and report it as delivered."""
    from ....app.inbox_store import (  # noqa: PLC0415
        append_event as append_inbox_event,
    )

    memory_config = await run_sync_io(
        _memory_config_for,
        agent_id,
    )
    event = await emit_proactive_agenda(
        agent_id=agent_id,
        memory_config=memory_config,
        date=outcome.date,
        items=outcome.shown,
        append_event=append_inbox_event,
        channel=channel,
        language=settings.language,
    )
    if event is None:
        outcome.skip_reason = "inbox_rejected"
        return False

    outcome.pushed = True
    outcome.event_id = str(event.get("id") or "")
    await mark_delivered(
        resolve_memory_provider(memory_manager),
        _ledger_for(workspace_dir, settings),
        items=outcome.shown,
        channel=CHANNEL_INBOX,
        external_ref=outcome.event_id,
        date=outcome.date,
    )
    return True


def _memory_config_for(agent_id: str) -> Any:
    agent_config = load_agent_config(agent_id)
    return agent_config.running.reme_light_memory_config


async def last_inbox_push_at(
    workspace_dir: str,
    settings: ProactiveSettings,
) -> datetime | None:
    """When the ledger last recorded an inbox push, for idle spacing."""
    ledger = _ledger_for(workspace_dir, settings)
    await ledger.load()
    return ledger.last_delivered_at(channel=CHANNEL_INBOX)
