# -*- coding: utf-8 -*-
"""Feishu interactive card subsystem.

* :mod:`.dispatcher` — routing-only ``FeishuCardHandler``: matches
  outbound ``message_type`` and inbound ``action_type`` against
  registered card kinds.
* :mod:`.context`    — shared helpers (meta/body extraction, session
  context builder) used by individual card modules.
* :mod:`.tool_guard` — tool-guard approval card (build / parse /
  render / handle), wired into the dispatcher.

Adding a new card kind:

1. Drop a new module here that exposes ``NAME``, ``MESSAGE_TYPE``,
   ``ACTION_TYPE`` plus ``render`` coroutine and ``handle`` callable.
2. Register it in :meth:`.dispatcher.FeishuCardHandler._register_kinds`.
"""
from .dispatcher import CardKind, FeishuCardHandler

__all__ = ["FeishuCardHandler", "CardKind"]
