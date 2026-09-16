# -*- coding: utf-8 -*-
"""从可信身份解析记忆作用域和受控目录。"""

from __future__ import annotations

import re
from pathlib import Path

from ..access.actor import ActorContext
from ..constant import WORKING_DIR
from .models import MemoryScope, MemoryScopeContext, MemoryScopeDenied

_SAFE_AGENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class MemoryScopeResolver:
    """唯一负责构造公共/私有记忆路径的解析器。"""

    def __init__(self, *, working_dir: Path = WORKING_DIR) -> None:
        self._working_dir = working_dir.resolve()

    def resolve_private(
        self,
        *,
        actor: ActorContext,
        agent_id: str,
        session_id: str | None = None,
        run_id: str | None = None,
    ) -> MemoryScopeContext:
        """解析当前登录用户在 Agent 下的私有作用域。"""
        self._validate_agent_id(agent_id)
        if actor.user_id is None:
            raise MemoryScopeDenied("authenticated_user_required")
        return MemoryScopeContext(
            actor_user_id=actor.user_id,
            agent_id=agent_id,
            scope=MemoryScope.PRIVATE,
            session_id=session_id,
            run_id=run_id,
        )

    def resolve_public(
        self,
        *,
        actor: ActorContext,
        agent_id: str,
        session_id: str | None = None,
        run_id: str | None = None,
        governance: bool = False,
    ) -> MemoryScopeContext:
        """解析 Agent 公共作用域。"""
        self._validate_agent_id(agent_id)
        return MemoryScopeContext(
            actor_user_id=actor.user_id,
            agent_id=agent_id,
            scope=MemoryScope.PUBLIC,
            session_id=session_id,
            run_id=run_id,
            governance=governance,
        )

    def workspace_path(self, context: MemoryScopeContext) -> Path:
        """仅从可信上下文生成受控绝对路径。"""
        self._validate_agent_id(context.agent_id)
        if context.scope is MemoryScope.PUBLIC:
            root = (self._working_dir / "workspaces").resolve()
            candidate = (root / context.agent_id).resolve()
        else:
            if context.actor_user_id is None:
                raise MemoryScopeDenied("authenticated_user_required")
            root = (
                self._working_dir / "user_workspaces" / str(context.actor_user_id)
            ).resolve()
            candidate = (root / context.agent_id).resolve()
        if not candidate.is_relative_to(root):
            raise MemoryScopeDenied("workspace_path_escape")
        return candidate

    def ensure_workspace(self, context: MemoryScopeContext) -> Path:
        """创建解析器控制的目录，并拒绝已有符号链接路径。"""
        candidate = self.workspace_path(context)
        root = (
            self._working_dir / "workspaces"
            if context.scope is MemoryScope.PUBLIC
            else self._working_dir / "user_workspaces" / str(context.actor_user_id)
        )
        current = self._working_dir
        for part in candidate.relative_to(self._working_dir).parts:
            current /= part
            if current.is_symlink():
                raise MemoryScopeDenied("workspace_symlink_denied")
            current.mkdir(exist_ok=True)
        if not candidate.is_relative_to(root.resolve()):
            raise MemoryScopeDenied("workspace_path_escape")
        return candidate

    def workspace_key(self, context: MemoryScopeContext) -> str:
        """返回可安全持久化的 POSIX 风格相对目录引用。"""
        return self.workspace_path(context).relative_to(self._working_dir).as_posix()

    @staticmethod
    def _validate_agent_id(agent_id: str) -> None:
        if agent_id in {".", ".."} or not _SAFE_AGENT_ID.fullmatch(agent_id):
            raise MemoryScopeDenied("invalid_agent_id")
