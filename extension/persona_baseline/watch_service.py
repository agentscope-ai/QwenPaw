# -*- coding: utf-8
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from watchfiles import Change, awatch

from .suppress_registry import SuppressRegistry

if TYPE_CHECKING:
    from .service import PersonaBaselineService

logger = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = 0.5


class PersonaWatchService:
    def __init__(self, service: "PersonaBaselineService") -> None:
        self._service = service
        self.suppress = SuppressRegistry()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._debounce_until: dict[tuple[str, str], float] = {}
        self._stop_event = asyncio.Event()

    @property
    def running(self) -> bool:
        return bool(self._tasks)

    async def start_all(self) -> None:
        if not self._service.is_enabled():
            return
        self._stop_event.clear()
        for agent_id in self._service.settings_store.list_agent_ids():
            await self.start_agent(agent_id)

    async def stop_all(self) -> None:
        self._stop_event.set()
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def start_agent(self, agent_id: str) -> None:
        if agent_id in self._tasks:
            return
        self._tasks[agent_id] = asyncio.create_task(
            self._watch_agent(agent_id),
            name=f"persona-watch-{agent_id}",
        )

    def clear_debounce(self, agent_id: str, path: str) -> None:
        self._debounce_until.pop((agent_id, path), None)
        self.suppress.clear_path(agent_id, path)

    async def _watch_agent(self, agent_id: str) -> None:
        workspace = self._service.settings_store.resolve_workspace(agent_id)
        try:
            async for changes in awatch(
                workspace,
                debounce=100,
                recursive=True,
            ):
                if self._stop_event.is_set() or not self._service.is_enabled():
                    break
                settings = self._service.settings_store.load()
                protected = set(
                    self._service.settings_store.effective_paths(settings, agent_id),
                )
                for _change, abs_path in changes:
                    if _change not in {Change.modified, Change.added}:
                        continue
                    rel_path = self._relative_path(workspace, Path(abs_path))
                    if rel_path is None or rel_path not in protected:
                        continue
                    target = Path(abs_path)
                    if not target.is_file():
                        continue
                    try:
                        content = target.read_bytes()
                    except OSError:
                        continue
                    content_sha = hashlib.sha256(content).hexdigest()
                    if self.suppress.should_ignore(
                        agent_id=agent_id,
                        path=rel_path,
                        content=content,
                    ):
                        logger.info(
                            "persona_watch_suppressed agent_id=%s path=%s "
                            "sha256=%s change=%s",
                            agent_id,
                            rel_path,
                            content_sha[:12],
                            _change.name,
                        )
                        continue
                    debounce_key = (agent_id, rel_path)
                    now = time.time()
                    if self._debounce_until.get(debounce_key, 0) > now:
                        logger.debug(
                            "persona_watch_debounced agent_id=%s path=%s",
                            agent_id,
                            rel_path,
                        )
                        continue
                    self._debounce_until[debounce_key] = now + _DEBOUNCE_SECONDS
                    logger.info(
                        "persona_watch_emit agent_id=%s path=%s sha256=%s change=%s",
                        agent_id,
                        rel_path,
                        content_sha[:12],
                        _change.name,
                    )
                    await self._service._emit_drift_for_path(
                        settings,
                        agent_id,
                        rel_path,
                        provenance="external_watch",
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Persona watch failed for agent %s", agent_id)
        finally:
            self._tasks.pop(agent_id, None)

    @staticmethod
    def _relative_path(workspace: Path, absolute_path: Path) -> str | None:
        try:
            return absolute_path.resolve().relative_to(workspace.resolve()).as_posix()
        except ValueError:
            return None
