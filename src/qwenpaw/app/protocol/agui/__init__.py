# -*- coding: utf-8 -*-
"""AG-UI protocol adapter for QwenPaw.

This module implements the AG-UI protocol endpoint at /protocol/agui/chat,
which converts AgentScope events to AG-UI protocol format.
"""
from .router import router  # noqa: F401

__all__ = ["router"]
