# -*- coding: utf-8 -*-
"""DataPaw plugin routers."""
from .data_sources import router as data_sources_router
from .tasks import router as tasks_router

__all__ = ["data_sources_router", "tasks_router"]
