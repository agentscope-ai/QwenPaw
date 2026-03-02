# -*- coding: utf-8 -*-
"""Persona package for CoPaw.

This package provides persona (role) management capabilities for CoPaw,
allowing different agent behaviors per channel and user.

Example:
    >>> from copaw.agents.persona import PersonaManager, PersonaScope
    >>> manager = PersonaManager()
    >>> await manager.load()
    >>> persona = await manager.get_active_persona(
    ...     channel="dingtalk",
    ...     user_id="user123",
    ... )
"""

from .models import PersonaScope, PersonaSpec
from .persona_manager import PersonaManager

__all__ = [
    "PersonaScope",
    "PersonaSpec",
    "PersonaManager",
]
