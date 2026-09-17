# -*- coding: utf-8 -*-
# flake8: noqa: E501
"""Process-level lifecycle hooks for the file-native Creator Agent driver."""

from __future__ import annotations

import threading

from services.project_files.facade import CreatorFileServices

from .driver import FileCreatorAgentRuntime
from .model_client import AgentChatClient


_registry_lock = threading.RLock()
_runtime: FileCreatorAgentRuntime | None = None


async def start_creator_agent_runtime(
    services: CreatorFileServices,
    *,
    model_client: AgentChatClient | None = None,
    poll_interval_seconds: float = 1.0,
) -> FileCreatorAgentRuntime:
    global _runtime
    with _registry_lock:
        current = _runtime
        if current is None:
            current = FileCreatorAgentRuntime(
                services,
                model_client=model_client,
                poll_interval_seconds=poll_interval_seconds,
            )
            _runtime = current
        elif current.services.root != services.root:
            raise RuntimeError(
                "Creator Agent Runtime is already bound to another data root",
            )
        elif (
            model_client is not None
            and current.model_client is not model_client
        ):
            raise RuntimeError(
                "Creator Agent Runtime is already bound to another model client",
            )
    await current.start()
    return current


async def stop_creator_agent_runtime() -> None:
    global _runtime
    with _registry_lock:
        current = _runtime
        _runtime = None
    if current is not None:
        await current.stop()


def get_creator_agent_runtime() -> FileCreatorAgentRuntime | None:
    with _registry_lock:
        return _runtime


def notify_creator_agent_runtime(project_id: str) -> bool:
    current = get_creator_agent_runtime()
    if current is None:
        return False
    current.notify(project_id)
    return True


async def interrupt_creator_agent_runtime(
    project_id: str,
    *,
    superseded: bool = False,
    reason: str = "user_interrupt",
    expected_run_id: str | None = None,
) -> bool:
    current = get_creator_agent_runtime()
    if current is None:
        return False
    return await current.interrupt(
        project_id,
        superseded=superseded,
        reason=reason,
        expected_run_id=expected_run_id,
    )


def reset_creator_agent_runtime_registry_for_tests() -> None:
    """Synchronous guard for tests that already stopped the async driver."""

    global _runtime
    with _registry_lock:
        current = _runtime
        if current is not None and current.started:
            raise RuntimeError(
                "stop Creator Agent Runtime before resetting it",
            )
        _runtime = None


__all__ = [
    "get_creator_agent_runtime",
    "interrupt_creator_agent_runtime",
    "notify_creator_agent_runtime",
    "reset_creator_agent_runtime_registry_for_tests",
    "start_creator_agent_runtime",
    "stop_creator_agent_runtime",
]
