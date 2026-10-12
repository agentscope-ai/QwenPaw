# -*- coding: utf-8 -*-
"""Deliver ReMe's proactive agenda through QwenPaw's surfaces.

QwenPaw no longer produces proactive topics itself.  ReMe's proactive
chain (extract -> topics -> plan -> agenda) already ranks the day's
agenda and pins due reminders first, so delivery here is read-only
presentation:

* ``/proactive`` answers in the user's current chat with the top few
  openers (:func:`build_agenda_receipt`);
* the idle trigger and the daily cron push the same items to the inbox
  (:func:`deliver_proactive_round`).

No LLM call and no tool execution happens on this path, which is what
keeps an agenda item from ever being mistaken for an instruction the
agent should carry out by itself.
"""

import logging
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
) -> AgendaRound:
    """Read (and refresh when empty) the agenda for one delivery round."""
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


async def build_agenda_receipt(
    *,
    agent_id: str,
    workspace_dir: str,
    memory_manager: Any,
    limit: int | None = None,
    external_ref: str = "",
    settings: ProactiveSettings | None = None,
) -> str:
    """Build the ``/proactive`` in-chat receipt and mark it delivered.

    The receipt is the whole delivery: a few ranked openers rendered as one
    assistant message.  The agent is never asked to act on them, so an
    agenda item cannot turn into an unrequested tool call.
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
    )
    if not outcome.shown:
        return outcome.empty_state()

    await mark_delivered(
        resolve_memory_provider(memory_manager),
        _ledger_for(workspace_dir, resolved),
        items=outcome.shown,
        channel=CHANNEL_CONVERSATION,
        external_ref=external_ref,
        date=outcome.date,
    )
    return render_agenda_receipt(
        outcome.shown,
        resolved.language,
        date=outcome.date,
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
        language=resolved.language,
    )
    if event is None:
        outcome.skip_reason = "inbox_rejected"
        return outcome

    outcome.pushed = True
    outcome.event_id = str(event.get("id") or "")
    await mark_delivered(
        resolve_memory_provider(memory_manager),
        _ledger_for(workspace_dir, resolved),
        items=outcome.shown,
        channel=CHANNEL_INBOX,
        external_ref=outcome.event_id,
        date=outcome.date,
    )
    return outcome


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
