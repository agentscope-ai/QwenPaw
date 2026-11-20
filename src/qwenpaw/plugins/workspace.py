# -*- coding: utf-8 -*-
"""Paths in the calling workspace and its bound conversation's projects."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .errors import SDKAccessError, SDKError, StaleContextError

if TYPE_CHECKING:
    from .tools import ToolContext


class WorkspaceService:
    """Use call.workspace_ops. Resolved paths do not grant I/O permission.

    Relative paths use the primary project, or the workspace when no project
    is configured. Results are filesystem snapshots: callers must still use
    the host's normal permission checks when opening files or executing work.
    """

    def __init__(self, context: ToolContext):
        self._context = context

    def _guard(self) -> None:
        call = self._context
        if call._plugin is None or not call.workspace_id:
            raise SDKError("Workspace operations require a host-bound context")
        call._plugin._guard()
        if call.resources.closed or call.resources._closing or call.cancelled:
            raise StaleContextError("The workspace caller's scope has ended")

    @property
    def directory(self) -> Path:
        """The configured workspace root; never the process working directory."""
        from ..config.utils import load_config

        self._guard()
        profile = load_config().agents.profiles.get(self._context.workspace_id)
        if profile is None or not profile.enabled:
            raise SDKAccessError("Workspace is not configured and enabled")
        return Path(profile.workspace_dir).expanduser().resolve()

    async def project_directories(self) -> tuple[Path, ...]:
        """Effective project roots, primary first; unconfigured means ().

        During a native turn this preserves its pinned directory selection.
        Otherwise only the bound, identity-matching saved conversation is
        considered. There is no arbitrary session selector.
        """
        from ..config.context import (
            get_current_project_dirs,
            get_current_session_id,
            get_current_workspace_dir,
        )
        from ..config.utils import load_agent_config
        from ..app.agent_context import (
            get_current_user_id,
            get_current_channel,
        )
        from ..services.project_directory import (
            agent_project_dirs_from_config,
            resolve_effective_project_dirs,
            session_project_dirs_raw_from_meta,
        )

        call = self._context
        root = self.directory
        pinned = get_current_project_dirs()
        ambient = get_current_workspace_dir()
        if (
            call.session_id
            and get_current_session_id() == call.session_id
            and call.identity.user_id
            and get_current_user_id() == call.identity.user_id
            and call.identity.channel
            and get_current_channel() == call.identity.channel
            and ambient is not None
            and ambient.resolve() == root
            and pinned is not None
        ):
            return tuple(item.path for item in pinned)
        meta = None
        from .apps import AppContext

        if isinstance(call, AppContext) and call._services.selected_chat:
            _, chat = await call._services.selected_conversation()
            meta = chat.meta
        elif call.session_id:
            identity = call.identity
            if not identity.user_id or not identity.channel:
                raise SDKAccessError(
                    "Conversation project paths require an identified caller",
                )
            manager = call._plugin._loader.registry.get_workspace_manager()
            workspace = (
                await manager.get_agent(call.workspace_id) if manager else None
            )
            if workspace is None:
                raise SDKError("Workspace is unavailable")
            chat_id = await workspace.chat_manager.get_chat_id_by_session(
                call.session_id,
                identity.channel,
                identity.user_id,
            )
            chat = (
                await workspace.chat_manager.get_chat(chat_id)
                if chat_id
                else None
            )
            if chat is not None:
                meta = chat.meta

        def resolve() -> tuple[Path, ...]:
            self._guard()
            resolved = resolve_effective_project_dirs(
                root,
                agent_project_dirs=agent_project_dirs_from_config(
                    load_agent_config(call.workspace_id),
                ),
                session_project_dirs=session_project_dirs_raw_from_meta(meta),
            )
            return tuple(item.path for item in resolved.dirs)

        result = await call.resources.run_sync(resolve)
        self._guard()
        return result

    async def resolve_path(self, path: str | Path) -> Path:
        """Normalize a path and reject escapes from the workspace/project roots.

        Missing targets are allowed, for creation. Symlinks are resolved before
        containment checks. This does not open the path or prevent a later
        filesystem change; it is not a replacement for operation-time checks.
        """
        root = self.directory
        projects = await self.project_directories()

        def resolve() -> Path:
            candidate = Path(path).expanduser()
            target = (
                (projects[0] if projects else root) / candidate
            ).resolve()
            if not any(
                target.is_relative_to(base.resolve())
                for base in (root, *projects)
            ):
                raise SDKAccessError(
                    "Path is outside the bound workspace and projects",
                )
            return target

        result = await self._context.resources.run_sync(resolve)
        self._guard()
        return result
