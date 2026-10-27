# -*- coding: utf-8 -*-
"""Steer mode — guidance the agent picks up on its next turn.

``/steer <guidance>`` records the text per session; the hook consumes it
at ``PRE_AGENT_BUILD`` of the following turn and injects it as context.
"""

from .handler import make_steer_command_spec
from .hook import SteerInjectionHook
from .store import clear, pop_guidance, put_guidance

__all__ = [
    "SteerInjectionHook",
    "clear",
    "make_steer_command_spec",
    "pop_guidance",
    "put_guidance",
]
