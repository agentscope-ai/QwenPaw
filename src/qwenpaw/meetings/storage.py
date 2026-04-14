# -*- coding: utf-8 -*-
"""Meeting storage management."""

import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from qwenpaw.constant import WORKING_DIR

if TYPE_CHECKING:
    from .models.config import MeetingDocument

logger = logging.getLogger(__name__)


class MeetingStorage:
    """会议存储管理类."""

    def __init__(self, _workspace_dir: str = None):
        """初始化存储管理.

        Args:
            workspace_dir: 废弃参数，保留向后兼容，现在统一使用 WORKING_DIR
        """
        self.workspace_dir = WORKING_DIR
        self.meetings_dir = self.workspace_dir / "meetings"
        self.meetings_dir.mkdir(parents=True, exist_ok=True)
        # meta 子文件夹存放会议配置 JSON
        self.meta_dir = self.meetings_dir / "meta"
        self.meta_dir.mkdir(parents=True, exist_ok=True)

    def get_meeting_dir(self, _meeting_id: str) -> Path:
        """获取会议目录.

        Args:
            _meeting_id: 会议 ID

        Returns:
            会议目录路径
        """
        return self.meetings_dir

    def get_meta_path(self, meeting_id: str) -> Path:
        """获取会议配置 JSON 文件路径.

        Args:
            meeting_id: 会议 ID

        Returns:
            JSON 文件完整路径
        """
        return self.meta_dir / f"{meeting_id}.json"

    def generate_doc_path(
        self,
        meeting_id: str,
        doc_type: str,
        dt: Optional[datetime] = None,
        folder_name: Optional[str] = None,
    ) -> str:
        """生成文档路径.

        Args:
            meeting_id: 会议 ID
            doc_type: 文档类型 (goals/records/summary)
            dt: 日期时间
            folder_name: 会议文件夹名称 (如 r_A1B2C3D4_技术评审)

        Returns:
            相对路径
        """
        dt = dt or datetime.now()
        if folder_name:
            filename = f"{dt.strftime('%y%m%d_%H%M')}_{doc_type}.md"
            return f"meetings/{folder_name}/{filename}"
        # 兼容旧格式
        date_dir = dt.strftime("%Y-%m")
        filename = (
            f"{dt.strftime('%d_%H%M')}_{meeting_id}_meeting_{doc_type}.md"
        )
        return f"meetings/{date_dir}/{filename}"

    def get_path(self, doc: "MeetingDocument|None") -> Path:
        """获取会议文档的完整路径.

        Args:
            doc: MeetingDocument 对象

        Returns:
            完整路径
        """
        return self.get_doc_full_path(doc.path)

    def get_doc_full_path(self, relative_path: str) -> Path:
        """获取文档完整路径.

        Args:
            relative_path: 相对路径

        Returns:
            完整路径

        Raises:
            ValueError: 如果路径试图穿越工作目录
        """
        if Path(relative_path).is_absolute() or ".." in relative_path:
            logger.warning(
                f"[meeting-storage] path rejected => {relative_path}",
            )
            raise ValueError(
                f"Invalid path traversal attempt: {relative_path}",
            )
        full_path = (self.workspace_dir / relative_path).resolve()
        if not full_path.is_relative_to(self.workspace_dir.resolve()):
            logger.warning(
                f"[meeting-storage] path rejected => {relative_path}",
            )
            raise ValueError(f"Path outside workspace: {relative_path}")
        return full_path

    def write_doc(self, relative_path: str, content: str) -> Path:
        """写入文档.

        Args:
            relative_path: 相对路径
            content: 文档内容

        Returns:
            完整路径
        """
        full_path = self.get_doc_full_path(relative_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            full_path.write_text(content, encoding="utf-8")
            logger.info(
                f"[meeting-storage] written to {relative_path}",
            )
        except Exception as e:
            logger.error(
                f"[meeting-storage] written failed {relative_path}, err: {e}",
            )
        return full_path

    def read_doc(self, relative_path: str) -> str:
        """读取文档.

        Args:
            relative_path: 相对路径

        Returns:
            文档内容
        """
        full_path = self.get_doc_full_path(relative_path)
        if full_path.exists():
            return full_path.read_text(encoding="utf-8")
        logger.debug(
            f"[meeting-storage] read doc not found: {relative_path}",
        )
        return ""

    def update_index(
        self,
        meeting_id: str,
        meeting_info: dict,
        folder_name: Optional[str] = None,
    ) -> None:
        """更新全局索引.

        Args:
            meeting_id: 会议 ID
            meeting_info: 会议信息
            folder_name: 会议文件夹名称
        """
        index_path = self.meetings_dir / "index.md"
        now = datetime.now()

        # 读取现有索引
        content = ""
        if index_path.exists():
            content = index_path.read_text(encoding="utf-8")

        # 生成新条目
        new_entry = self._format_index_entry(meeting_info, folder_name, now)

        # 如果已存在该会议，更新条目；否则追加
        if f"<!-- {meeting_id} -->" in content:
            # 替换现有条目
            pattern = rf"<!-- {meeting_id} -->.*?<!-- /{meeting_id} -->\n"
            content = re.sub(
                pattern,
                new_entry + "\n",
                content,
                flags=re.DOTALL,
            )
        else:
            # 追加新条目
            content = content.rstrip() + "\n" + new_entry + "\n"

        try:
            index_path.write_text(content, encoding="utf-8")
            logger.info(f"[meeting-storage] updated index: {meeting_id}")
        except Exception as e:
            logger.error(
                f"[meeting-storage] write failed {index_path}, err: {e}",
            )

    def _format_index_entry(
        self,
        meeting_info: dict,
        folder_name: Optional[str],
        dt: datetime,
    ) -> str:
        """格式化索引条目.

        格式: 名称 | Topic | 类型 | 文件夹 | 时间
        """
        folder = folder_name or meeting_info.get("folder_name", "")
        # 提取 topic title
        topic = meeting_info.get("topic", {})
        topic_title = (
            topic.get("title", "-") if isinstance(topic, dict) else "-"
        )
        return f"""<!-- {meeting_info.get("meeting_id", "unknown")} -->
| {meeting_info.get("meeting_name", "")} | {topic_title} |
| {meeting_info.get("meeting_type", "")} | [{folder}]({folder}/) |
| {dt.strftime("%Y-%m-%d %H:%M")} |
<!-- /{meeting_info.get("meeting_id", "unknown")} -->"""

    def cleanup_old_meetings(self, max_age_days: int = 7) -> int:
        """清理过期会议文档.

        Args:
            max_age_days: 最大保留天数

        Returns:
            清理的文档数量
        """
        count = 0
        now = datetime.now()
        max_age = timedelta(days=max_age_days)

        for root, dirs, files in os.walk(self.meetings_dir):
            dirs[:] = [d for d in dirs if re.match(r"^\d{4}-\d{2}$", d)]

            for f in files:
                if not f.endswith(".md"):
                    continue

                filepath = Path(root) / f
                try:
                    mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
                    if (now - mtime) > max_age:
                        filepath.unlink()
                        count += 1
                        logger.info(
                            f"[meeting-storage] cleaned up: {filepath}",
                        )
                except Exception as e:
                    logger.error(
                        f"[meeting-storage] clean failed {filepath}, err: {e}",
                    )

        return count
