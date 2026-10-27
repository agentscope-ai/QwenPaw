# -*- coding: utf-8 -*-
"""Proactive agenda delivery for QwenPaw agents.

Topics are produced by ReMe's proactive chain; this package only reads the
ranked agenda and presents it (in-chat receipt, idle/cron inbox push) and
reports back what was already delivered.
"""

from .proactive_agenda import (
    AgendaBundle,
    AgendaItem,
    AgendaRead,
    ensure_agenda,
    fetch_agenda,
    refresh_agenda,
    select_presentation_items,
)
from .proactive_delivery import (
    DeliveryLedger,
    get_delivery_ledger,
    ledger_path,
    mark_delivered,
)
from .proactive_responder import (
    AgendaRound,
    ProactiveSettings,
    collect_agenda,
    deliver_proactive_round,
    load_proactive_settings,
    present_agenda_receipt,
    rebuild_notice,
    start_agenda_rebuild,
)
from .proactive_trigger import (
    disable_proactive_for_session,
    enable_proactive_for_session,
    proactive_configs,
    proactive_tasks,
    proactive_trigger_loop,
)
from .proactive_types import ProactiveConfig

__all__ = [
    "AgendaBundle",
    "AgendaItem",
    "AgendaRead",
    "AgendaRound",
    "DeliveryLedger",
    "ProactiveConfig",
    "ProactiveSettings",
    "collect_agenda",
    "deliver_proactive_round",
    "disable_proactive_for_session",
    "enable_proactive_for_session",
    "ensure_agenda",
    "fetch_agenda",
    "get_delivery_ledger",
    "ledger_path",
    "load_proactive_settings",
    "mark_delivered",
    "present_agenda_receipt",
    "proactive_configs",
    "proactive_tasks",
    "proactive_trigger_loop",
    "rebuild_notice",
    "refresh_agenda",
    "select_presentation_items",
    "start_agenda_rebuild",
]
