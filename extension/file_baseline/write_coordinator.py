# -*- coding: utf-8

from __future__ import annotations



import asyncio

import hashlib

import logging

from pathlib import Path

from typing import TYPE_CHECKING



from .drift_gate import (
    path_status_from_adapter,
    sha256_file,
    should_skip_drift_emit,
)
from .os_readonly import set_os_readonly, temporary_os_writable
from .paths import workspace_relative_path

from .write_context import is_file_baseline_maintenance



if TYPE_CHECKING:

    from .service import FileBaselineService



logger = logging.getLogger(__name__)



# Provenance values that mean "approval passed and write succeeded" — sole suppress anchor.

APPROVED_WRITE_PROVENANCES = frozenset(

    {"approved_agent_write", "approved_operator_console"},

)





class FileBaselineWriteCoordinator:

    def __init__(self, service: "FileBaselineService") -> None:

        self._service = service



    async def on_file_saved(

        self,

        *,

        agent_id: str,

        absolute_path: str | Path,

        provenance: str,

        suppress_watch_sec: float = 2.0,

    ) -> None:

        if is_file_baseline_maintenance():

            logger.debug(

                "persona_on_file_saved skipped=maintenance provenance=%s path=%s",

                provenance,

                absolute_path,

            )

            return

        if not self._service.is_enabled():

            logger.debug(

                "persona_on_file_saved skipped=disabled provenance=%s path=%s",

                provenance,

                absolute_path,

            )

            return

        if provenance == "system_maintenance":

            logger.debug(

                "persona_on_file_saved skipped=system_maintenance path=%s",

                absolute_path,

            )

            return



        settings = self._service.settings_store.load()

        workspace = self._service.settings_store.resolve_workspace(agent_id)

        rel_path = workspace_relative_path(workspace, Path(absolute_path))

        if rel_path is None:

            logger.debug(

                "persona_on_file_saved skipped=outside_workspace agent_id=%s "

                "provenance=%s path=%s",

                agent_id,

                provenance,

                absolute_path,

            )

            return



        protected = set(self._service.settings_store.effective_paths(settings, agent_id))

        if rel_path not in protected:

            logger.debug(

                "persona_on_file_saved skipped=not_protected agent_id=%s "

                "provenance=%s rel_path=%s",

                agent_id,

                provenance,

                rel_path,

            )

            return



        logger.info(

            "persona_on_file_saved agent_id=%s provenance=%s rel_path=%s",

            agent_id,

            provenance,

            rel_path,

        )



        if provenance in APPROVED_WRITE_PROVENANCES:

            await self._on_approved_write_baseline(

                agent_id=agent_id,

                absolute_path=absolute_path,

                rel_path=rel_path,

                provenance=provenance,

                suppress_watch_sec=suppress_watch_sec,

            )

            return



        if provenance in {"agent_tool", "external_untrusted", "external_watch", "operator_console"}:

            state_dir = self._service.settings_store.agent_state(agent_id)
            approved_sha, current_sha = path_status_from_adapter(
                self._service.adapter,
                workspace_root=workspace,
                state_dir=state_dir,
                rel_path=rel_path,
            )
            if not current_sha:
                current_sha = sha256_file(Path(absolute_path))
            if should_skip_drift_emit(
                approved_sha256=approved_sha,
                current_sha256=current_sha,
                agent_id=agent_id,
                rel_path=rel_path,
                provenance=provenance,
            ):
                return

            provenance_key = (

                "external_watch"

                if provenance in {"external_untrusted", "external_watch"}

                else "agent_tool"

            )

            logger.info(

                "persona_emit_drift_scheduled agent_id=%s rel_path=%s "

                "provenance_in=%s provenance_key=%s",

                agent_id,

                rel_path,

                provenance,

                provenance_key,

            )

            await self._service._emit_drift_for_path(

                settings,

                agent_id,

                rel_path,

                provenance=provenance_key,

            )



    async def commit_approved_write(

        self,

        *,

        agent_id: str,

        absolute_path: str | Path,

        content: str,

        encoding: str = "utf-8",

        expected_old_sha256: str,

        provenance: str = "approved_agent_write",

        suppress_watch_sec: float = 2.0,

    ) -> None:

        """Atomic disk write + baseline accept for an approved write proposal."""

        if provenance not in APPROVED_WRITE_PROVENANCES:

            raise ValueError(f"invalid approved write provenance: {provenance}")



        path = Path(absolute_path)

        current_sha = self._file_sha(path) if path.is_file() else hashlib.sha256(b"").hexdigest()

        if current_sha != expected_old_sha256:

            raise ValueError(

                "old_sha256 mismatch for approved write: "

                f"expected {expected_old_sha256[:12]}, got {current_sha[:12]}",

            )



        path.parent.mkdir(parents=True, exist_ok=True)

        temp_path = path.with_suffix(path.suffix + ".persona-tmp")

        writable_targets = [path] if path.is_file() else []
        with temporary_os_writable(writable_targets):
            temp_path.write_text(content, encoding=encoding)
            temp_path.replace(path)

        if self._service.is_enabled():
            rel_after = workspace_relative_path(
                self._service.settings_store.resolve_workspace(agent_id),
                path,
            )
            if rel_after is not None:
                settings = self._service.settings_store.load()
                protected = set(
                    self._service.settings_store.effective_paths(settings, agent_id),
                )
                if rel_after in protected:
                    set_os_readonly(path)



        await self.on_file_saved(

            agent_id=agent_id,

            absolute_path=path,

            provenance=provenance,

            suppress_watch_sec=suppress_watch_sec,

        )



    async def notify_approved_paths(

        self,

        *,

        agent_id: str,

        absolute_paths: list[str | Path],

        provenance: str = "approved_agent_write",

        suppress_watch_sec: float = 2.0,

    ) -> None:

        """After an approved shell/python execution, bump baseline for affected paths."""

        for absolute_path in absolute_paths:

            await self.on_file_saved(

                agent_id=agent_id,

                absolute_path=absolute_path,

                provenance=provenance,

                suppress_watch_sec=suppress_watch_sec,

            )



    async def _on_approved_write_baseline(

        self,

        *,

        agent_id: str,

        absolute_path: str | Path,

        rel_path: str,

        provenance: str,

        suppress_watch_sec: float,

    ) -> None:

        workspace = self._service.settings_store.resolve_workspace(agent_id)

        state_dir = self._service.settings_store.agent_state(agent_id)



        await asyncio.to_thread(

            self._service.adapter.approve_file,

            workspace_root=workspace,

            state_dir=state_dir,

            relative_path=rel_path,

        )

        self._service.drift_store.resolve_for_path(

            agent_id=agent_id,

            path=rel_path,

            status="accepted",

        )

        current_sha = self._file_sha(Path(absolute_path))

        self._service.watch_service.suppress.register(

            agent_id=agent_id,

            path=rel_path,

            sha256=current_sha,

            ttl_seconds=suppress_watch_sec,

        )

        await self._service.emitter.emit_baseline_updated(

            agent_id=agent_id,

            path=rel_path,

            new_sha256=current_sha,

        )

        logger.info(

            "persona_approved_write_baseline agent_id=%s rel_path=%s provenance=%s sha256=%s",

            agent_id,

            rel_path,

            provenance,

            current_sha[:12],

        )



    @staticmethod

    def _file_sha(path: Path) -> str:

        return hashlib.sha256(path.read_bytes()).hexdigest()


