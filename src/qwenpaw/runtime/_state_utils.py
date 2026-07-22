# -*- coding: utf-8 -*-
"""Shared session-state utilities."""
from __future__ import annotations


class StateProxy:
    """Minimal proxy satisfying SafeJSONSession's state_module protocol.

    Used by session hooks and builtin commands to load/save AgentState
    without instantiating a full agent.
    """

    def __init__(self) -> None:
        self.data: dict = {}

    def state_dict(self) -> dict:
        return self.data

    def load_state_dict(self, d: dict) -> None:
        self.data = d


__all__ = ["StateProxy"]
