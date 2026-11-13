# -*- coding: utf-8 -*-
"""Wire-only browser execution kernel backed by owner-scoped subprocesses."""

from __future__ import annotations

from ...utils.io_utils import run_sync_io
from .subprocess_plane import SubprocessPlane
from .wire import ExecRequest, ExecResult, sweep_spill


def _worker_key(workspace_id: str, session_id: str) -> str:
    """Compose the per-session worker isolation key."""
    return f"{workspace_id}/{session_id}"


class KernelRuntime:
    """Route execution and lifecycle calls to the subprocess plane."""

    def __init__(
        self,
        plane: SubprocessPlane | None = None,
        idle_ttl: float = 600.0,
        session_idle_ttl: float = 900.0,
        exec_timeout_seconds: float = 120.0,
    ) -> None:
        self._plane = plane or SubprocessPlane(
            idle_ttl=idle_ttl,
            session_idle_ttl=session_idle_ttl,
            exec_timeout_seconds=exec_timeout_seconds,
        )

    async def run(self, request: ExecRequest) -> ExecResult:
        key = _worker_key(
            request.owner_workspace_id,
            request.owner_session_id,
        )
        return await self._plane.run(key, request)

    async def reset(self, workspace_id: str, session_id: str) -> None:
        await self._plane.discard_worker(_worker_key(workspace_id, session_id))

    async def discard_idle_workers(self) -> None:
        """Drop idle workers only; provider sessions remain available."""
        await self._plane.discard_idle_workers()

    async def sweep_idle_sessions(self) -> None:
        """Reclaim idle sessions while retaining busy or pinned work."""
        await self._plane.sweep_idle_sessions()

    async def sweep_wire_spill(self) -> None:
        """Remove stale wire spill files without blocking the event loop."""
        await run_sync_io(sweep_spill)

    async def discard_all_workers(self) -> None:
        """Drop every worker only; provider sessions remain available."""
        await self._plane.discard_all_workers()

    async def on_response_cycle_end(
        self,
        workspace_id: str,
        session_id: str,
    ) -> None:
        """Release response-cycle tabs owned by one chat session."""
        await self._plane.on_response_cycle_end(workspace_id, session_id)

    async def close_session(
        self,
        workspace_id: str,
        session_id: str,
    ) -> None:
        """Close all browser state owned by one chat session."""
        await self._plane.close_session(workspace_id, session_id)

    async def close_workspace(self, workspace_id: str) -> None:
        """Reclaim every provider session owned by one workspace."""
        await self._plane.close_workspace(workspace_id)

    def pin(self, workspace_id: str, session_id: str) -> None:
        """Keep one session worker alive while a human owns its browser."""
        self._plane.pin(_worker_key(workspace_id, session_id))

    def discard_all_workers_sync(self) -> None:
        """Drop workers synchronously only; provider sessions remain live."""
        self._plane.discard_all_workers_sync()


class BrowserKernelManager:
    """Own the singleton execution runtime used by browser tool callers."""

    def __init__(self) -> None:
        from ...config.utils import load_config

        browser = load_config().browser
        self._runtime = KernelRuntime(
            idle_ttl=browser.idle_ttl_seconds,
            session_idle_ttl=browser.session_idle_ttl_seconds,
            exec_timeout_seconds=browser.exec_timeout_seconds,
        )

    async def execute(self, request: ExecRequest) -> ExecResult:
        await self._runtime.discard_idle_workers()
        await self._runtime.sweep_idle_sessions()
        return await self._runtime.run(request)

    async def reset_session(self, workspace_id: str, session_id: str) -> None:
        await self._runtime.reset(workspace_id, session_id)

    async def discard_idle_workers(self) -> None:
        """Drop idle workers only; provider sessions remain available."""
        await self._runtime.discard_idle_workers()

    async def sweep_idle_sessions(self) -> None:
        """Reclaim idle sessions while retaining busy or pinned work."""
        await self._runtime.sweep_idle_sessions()

    async def sweep_wire_spill(self) -> None:
        """Remove stale wire spill files through the execution kernel."""
        await self._runtime.sweep_wire_spill()

    async def discard_all_workers(self) -> None:
        """Drop all workers only; provider sessions remain available."""
        await self._runtime.discard_all_workers()

    async def on_response_cycle_end(
        self,
        workspace_id: str,
        session_id: str,
    ) -> None:
        """Run browser response-cycle cleanup for one console chat."""
        await self._runtime.on_response_cycle_end(workspace_id, session_id)

    async def close_session(
        self,
        workspace_id: str,
        session_id: str,
    ) -> None:
        """Close browser tabs after a chat is archived or deleted."""
        await self._runtime.close_session(workspace_id, session_id)

    async def close_workspace(self, workspace_id: str) -> None:
        """Reclaim every provider session owned by one restored workspace."""
        await self._runtime.close_workspace(workspace_id)

    def mark_handoff_pending(self, workspace_id: str, session_id: str) -> None:
        """Protect a browser worker until the user resumes after handoff."""
        self._runtime.pin(workspace_id, session_id)

    def discard_all_workers_sync(self) -> None:
        """Drop workers synchronously only; provider sessions remain live."""
        self._runtime.discard_all_workers_sync()


_MANAGER: BrowserKernelManager | None = None


def get_default_kernel_manager() -> BrowserKernelManager:
    """Return the process-local control-plane manager singleton."""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = BrowserKernelManager()
    return _MANAGER
