# -*- coding: utf-8 -*-
"""Stop interrupt middleware.

Checks if a /stop signal has been set for the current agent.
If so, raises CancelledError to trigger the agent's handle_interrupt.
Uses a module-level dict keyed by agent name for cross-component signaling.
"""
import asyncio
import logging
import threading

logger = logging.getLogger(__name__)

# Global stop flags: agent_name -> Event
_stop_flags: dict[str, threading.Event] = {}
_lock = threading.Lock()


def request_agent_stop(agent_name: str) -> bool:
    """Signal an agent to stop. Called from channel/router layer."""
    with _lock:
        if agent_name not in _stop_flags:
            _stop_flags[agent_name] = threading.Event()
        _stop_flags[agent_name].set()
        logger.info("Stop requested for agent: %s", agent_name)
        return True


def is_agent_stop_requested(agent_name: str) -> bool:
    """Check if stop has been requested for an agent."""
    with _lock:
        flag = _stop_flags.get(agent_name)
        return flag is not None and flag.is_set()


def clear_agent_stop(agent_name: str) -> None:
    """Clear the stop flag after handling."""
    with _lock:
        _stop_flags.pop(agent_name, None)


class StopInterruptMiddleware:
    """Pre-reasoning middleware that checks for /stop signals.

    Each reasoning cycle, checks the global stop flag for this agent.
    If set, raises CancelledError to trigger handle_interrupt.
    """

    def __init__(self, agent_name: str = ""):
        self._agent_name = agent_name

    def set_agent_name(self, name: str):
        self._agent_name = name

    async def __call__(self, agent, memory, **kwargs):
        """Check stop flag before each reasoning step."""
        name = self._agent_name or getattr(agent, "name", "")
        if not name:
            return

        if is_agent_stop_requested(name):
            clear_agent_stop(name)
            logger.info(
                "Stop interrupt detected for agent=%s, raising CancelledError",
                name,
            )
            raise asyncio.CancelledError()
