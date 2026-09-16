# -*- coding: utf-8 -*-
"""用户个人资料库的受控路径解析。"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from ..constant import WORKING_DIR
from ..services.workspace_files import InvalidWorkspacePath, resolve_workspace_path


class PersonalLibraryPathDenied(ValueError):
    """资料库路径不能安全地解析到当前用户私有根目录。"""


class PersonalLibraryPathResolver:
    """只为可信用户 ID 创建和解析个人资料库根目录。"""

    def __init__(self, *, working_dir: Path = WORKING_DIR) -> None:
        self._working_dir = Path(working_dir).expanduser().resolve()

    def ensure_root(self, user_id: UUID, agent_id: UUID) -> Path:
        """创建并返回 ``user_libraries/{user_id}/{agent_id}`` 私有根目录。"""
        root = self._working_dir / "user_libraries" / str(user_id) / str(agent_id)
        current = self._working_dir
        for part in root.relative_to(self._working_dir).parts:
            current /= part
            if current.is_symlink():
                raise PersonalLibraryPathDenied("library_symlink_denied")
            current.mkdir(exist_ok=True)
        return root

    def resolve(
        self,
        *,
        user_id: UUID,
        agent_id: UUID,
        relative_path: str,
        allow_root: bool = False,
    ) -> Path:
        """解析当前用户资料库内的一个 POSIX 相对路径。"""
        root = self.ensure_root(user_id, agent_id)
        try:
            return resolve_workspace_path(
                root,
                relative_path,
                allow_root=allow_root,
                portable=True,
            )
        except InvalidWorkspacePath as exc:
            raise PersonalLibraryPathDenied("invalid_library_path") from exc
