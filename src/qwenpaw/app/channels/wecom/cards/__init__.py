# -*- coding: utf-8 -*-
"""WeCom interactive template-card subsystem.

* :mod:`.dispatcher` — routing-only ``WecomCardHandler``: matches
  outbound ``message_type`` and inbound ``task_id`` prefixes against
  registered card kinds.
* :mod:`.context`    — shared helpers (meta/body extraction, session
  context builder, stream lifecycle) used by individual card modules.
* :mod:`.tool_guard` — tool-guard approval card (build / parse /
  render / handle), wired into the dispatcher.

Adding a new card kind:

1. Drop a new module here that exposes ``NAME``, ``MESSAGE_TYPE``,
   ``TASK_ID_PREFIX`` plus ``async render(channel, ...)`` and
   ``async handle(channel, frame)``.
2. Register it in :meth:`.dispatcher.WecomCardHandler._register_kinds`.
"""
from .dispatcher import CardKind, WecomCardHandler

__all__ = ["WecomCardHandler", "CardKind"]
