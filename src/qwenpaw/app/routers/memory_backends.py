# -*- coding: utf-8 -*-
"""API routes for memory backend discovery."""

from __future__ import annotations

from fastapi import APIRouter

from ...agents.memory import ReMeLightMemoryManager
from ...plugins.registry import PluginRegistry

router = APIRouter(prefix="/memory-backends", tags=["memory-backends"])


@router.get("")
def list_memory_backends() -> list[dict]:
    """Return all available memory backends.

    Returns built-in backends plus any plugin-registered backends.
    """
    backends = [
        {
            "id": ReMeLightMemoryManager.backend_name(),
            "label": ReMeLightMemoryManager.backend_label(),
            "description": "Local file-based memory with vector search",
        },
    ]

    registry = PluginRegistry()
    for _bid, reg in registry.get_all_memory_backends().items():
        backends.append(
            {
                "id": reg.backend_id,
                "label": reg.label,
                "description": reg.description,
            },
        )

    return backends
