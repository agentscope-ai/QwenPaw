# -*- coding: utf-8 -*-
"""DataPaw plugin routers.

Only ``tasks_router`` survives in the plugin form — ``mode_router``
was dropped together with plan/agent dual mode (see
``datapaw-as-plugin-via-monkeypatch.md`` §6.1).
"""
from .tasks import router as tasks_router

__all__ = ["tasks_router"]
