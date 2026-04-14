# -*- coding: utf-8 -*-
"""Meeting Manager - Core meeting orchestration logic."""

import asyncio
import json
import logging
import random
import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from qwenpaw.app.ai_calc import summarize_speech
from qwenpaw.constant import WORKING_DIR
from .models import (
    MeetingConfig,
    MeetingDocument,
    MeetingParticipant,
    MeetingStatus,
    PhaseType,
    RoleType,
)
from .prompts import (
    build_host_prompt,
    build_reporter_prompt,
    build_decider_prompt,
)
from .storage import MeetingStorage
from .rpc import SACPClient

logger = logging.getLogger(__name__)

# 8位随机ID字符集 (26字母 + 10数字，不含易混淆的0/O/1/l/I)
_ID_CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class MeetingManager:
    """会议管理器 - 核心编排逻辑."""

    def __init__(
        self,
        config: MeetingConfig,
    ):
        """初始化会议管理器.

        Args:
            config: 会议配置
        """
        self.c = config
        self.workspace_dir = str(WORKING_DIR)
        self.storage = MeetingStorage()
        self.rpc = SACPClient()

        # 会议状态（CREATED: 对象已实例化，INITIALIZED: 文档路径已生成）
        self.status = MeetingStatus.CREATED
        self.current_phase: Optional[PhaseType] = None
        self.current_round: int = 0
        self.current_participant_idx: int = 0

        # 文档路径
        self.goals_doc: Optional[MeetingDocument] = None
        self.records_doc: Optional[MeetingDocument] = None
        self.summary_doc: Optional[MeetingDocument] = None

        # 生成会议 ID 和文件夹名
        if not self.c.meeting_id:
            self.c.meeting_id = self._generate_meeting_id()
        self._folder_name = self._generate_folder_name()

    def _generate_meeting_id(self) -> str:
        """生成8位随机会议 ID (字母+数字)."""
        return "".join(random.choices(_ID_CHARS, k=8))

    def _sanitize_name(self, name: str, max_chars: int = 20) -> str:
        """清理名称，替换特殊字符，截断长度.

        Args:
            name: 原始名称
            max_chars: 最大字符数（中文算1个字符）

        Returns:
            清理后的名称
        """
        # 替换特殊字符为空格，然后压缩空格，最后替换为下划线
        sanitized = re.sub(r"[^\w\u4e00-\u9fff]+", "_", name)
        sanitized = re.sub(r"_+", "_", sanitized)
        sanitized = sanitized.strip("_")

        # 按字节长度截断（中文占2-3字节，20个汉字约60字节）
        result = []
        byte_count = 0
        for char in sanitized:
            char_bytes = len(char.encode("utf-8"))
            if byte_count + char_bytes <= max_chars * 3:  # 宽松截断
                result.append(char)
                byte_count += char_bytes
            else:
                break
        return "".join(result)

    def _generate_folder_name(self) -> str:
        """生成会议文件夹名称.

        格式: r_{meeting_id}_{sanitized_title} (例会)
              t_{meeting_id}_{sanitized_title} (临时会议)
        """
        prefix = self.c.folder_prefix
        title = self._sanitize_name(
            self.c.topic.title or self.c.meeting_name,
            max_chars=20,
        )
        return f"{prefix}{self.c.meeting_id}_{title}"

    def run(self) -> dict:
        """运行会议（同步入口）.

        Returns:
            会议结果
        """
        return asyncio.run(self.run_async())

    async def run_async(self) -> dict:
        """运行会议（异步入口）.

        Returns:
            会议结果
        """
        logger.info(f"[meeting:{self.c.meeting_id}]starting")
        self.status = MeetingStatus.RUNNING

        try:
            await self._opening()
            main_points = {}
            for _ in range(self.c.flow.num_rounds()):
                await self._round_speaking(main_points)
                self.current_round += 1

            decision, reasons = await self._decision()

            await self._generate_summary(decision, reasons, main_points)

            self.status = MeetingStatus.COMPLETED
            logger.info(
                f"[meeting:{self.c.meeting_id}]completed",
            )

        except Exception as e:
            logger.error(
                f"[meeting:{self.c.meeting_id}]failed, err: {e}",
            )
            self.status = MeetingStatus.FAILED
            raise

        finally:
            await self.rpc.close()

        return self._build_result()

    def get_result(self) -> dict:
        """获取会议结果.

        Returns:
            会议结果字典
        """
        return self._build_result()

    def create(self) -> None:
        """创建会议 - 初始化文档并写入 goals."""
        if self.c.meeting_id is None:
            raise ValueError("meeting_id cannot be None")
        logger.info(f"[meeting:{self.c.meeting_id}]creating")

        # 生成文档路径（使用新结构）
        now = datetime.now()
        folder_name = self._folder_name

        goals_path = self.storage.generate_doc_path(
            self.c.meeting_id,
            "goals",
            now,
            folder_name,
        )
        records_path = self.storage.generate_doc_path(
            self.c.meeting_id,
            "records",
            now,
            folder_name,
        )
        summary_path = self.storage.generate_doc_path(
            self.c.meeting_id,
            "summary",
            now,
            folder_name,
        )

        # 创建文档对象
        self.goals_doc = MeetingDocument(
            meeting_id=self.c.meeting_id,
            doc_type="goals",
            path=goals_path,
        )
        self.records_doc = MeetingDocument(
            meeting_id=self.c.meeting_id,
            doc_type="records",
            path=records_path,
        )
        self.summary_doc = MeetingDocument(
            meeting_id=self.c.meeting_id,
            doc_type="summary",
            path=summary_path,
        )

        # 写入 goals 内容（从 topic 直接生成）
        goals_content = self._build_goals_from_topic()
        self.storage.write_doc(self.goals_doc.path, goals_content)

        # 初始化发言记录文档
        self._init_records_doc()

        # 保存配置到 meta/
        self._save_config()

        # 更新索引
        self._update_index()

        self.status = MeetingStatus.INITIALIZED
        logger.info(f"[meeting:{self.c.meeting_id}]created")

    def _build_goals_from_topic(self) -> str:
        """从 topic 构建 goals 内容."""
        return f"""# 会议目标

## 会议信息

| 字段 | 内容 |
|------|------|
| 会议ID | {self.c.meeting_id} |
| 会议名称 | {self.c.meeting_name} |
| 会议类型 | {self.c.meeting_type.value} |
| 创建时间 | {_ts()} |

---

## 议题：{self.c.topic.title}

## 目的：
{self.c.topic.description or ""}

## 内容、背景、目标：
{self.c.topic.context or ""}

---


*本目标于 {_ts()} 生成*
"""

    def _save_config(self) -> None:
        """保存会议配置到 meta/ 目录."""
        if self.c.meeting_id is None:
            raise ValueError("meeting_id cannot be None")
        config_data = {
            "version": self.c.get_version(),
            "meeting_id": self.c.meeting_id,
            "meeting_name": self.c.meeting_name,
            "meeting_type": self.c.meeting_type.value,
            "folder_name": self._folder_name,
            "topic": self.c.topic.model_dump() if self.c.topic else None,
            "participants": [p.model_dump() for p in self.c.participants],
            "flow": self.c.flow.model_dump() if self.c.flow else None,
        }

        meta_path = self.storage.get_meta_path(self.c.meeting_id)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(
            json.dumps(config_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(
            "[meetings] manager<%s> saved config: %s",
            self.c.meeting_id,
            meta_path,
        )

    def reset(self) -> None:
        """重置会议 - 重新初始化文档，清除运行状态.

        用于重新开始一个已完成的会议。
        """
        if self.c.meeting_id is None:
            raise ValueError("meeting_id cannot be None")
        logger.info(f"[meeting:{self.c.meeting_id}]resetting")

        # 重置运行状态
        self.current_phase = None
        self.current_round = 0
        self.current_participant_idx = 0

        # 重新生成文档路径（使用新时间戳）
        now = datetime.now()
        goals_path = self.storage.generate_doc_path(
            self.c.meeting_id,
            "goals",
            now,
            self._folder_name,
        )
        records_path = self.storage.generate_doc_path(
            self.c.meeting_id,
            "records",
            now,
            self._folder_name,
        )
        summary_path = self.storage.generate_doc_path(
            self.c.meeting_id,
            "summary",
            now,
            self._folder_name,
        )

        # 删除旧文档
        for doc in [self.goals_doc, self.records_doc, self.summary_doc]:
            if doc:
                full_path = Path(self.storage.workspace_dir) / doc.path
                if full_path.exists():
                    full_path.unlink()
                    logger.debug(f"Deleted old doc: {doc.path}")

        # 创建新文档对象
        self.goals_doc = MeetingDocument(
            meeting_id=self.c.meeting_id,
            doc_type="goals",
            path=goals_path,
        )
        self.records_doc = MeetingDocument(
            meeting_id=self.c.meeting_id,
            doc_type="records",
            path=records_path,
        )
        self.summary_doc = MeetingDocument(
            meeting_id=self.c.meeting_id,
            doc_type="summary",
            path=summary_path,
        )

        # 重新写入 goals 内容
        goals_content = self._build_goals_from_topic()
        self.storage.write_doc(self.goals_doc.path, goals_content)

        # 重新初始化发言记录文档
        self._init_records_doc()

        # 更新状态
        self.status = MeetingStatus.INITIALIZED
        logger.info(
            f"[meeting:{self.c.meeting_id}]reset complete",
        )

    def _init_records_doc(self) -> None:
        """初始化发言记录文档."""
        if not self.records_doc:
            return

        logger.info(
            f"[meeting:{self.c.meeting_id}] init {self.records_doc.path}",
        )

        participants_str = ", ".join(
            f"{p.name}({'/'.join(r.value for r in p.roles)})"
            for p in self.c.participants
        )
        content = f"""# 发言记录

## 会议信息

| 字段 | 内容 |
|------|------|
| 会议ID | {self.c.meeting_id} |
| 会议名称 | {self.c.meeting_name} |
| 会议类型 | {self.c.meeting_type.value} |
| 开始时间 | {_ts()} |
| 参会人员 | {participants_str} |

---

"""
        self.storage.write_doc(self.records_doc.path, content)

    def _update_index(self) -> None:
        """更新全局索引."""
        if self.c.meeting_id is None:
            raise ValueError("meeting_id cannot be None")
        logger.debug(f"Updating index for meeting: {self.c.meeting_id}")
        meeting_info = {
            "meeting_id": self.c.meeting_id,
            "meeting_name": self.c.meeting_name,
            "meeting_type": self.c.meeting_type.value,
            "topic_title": self.c.topic.title,
            "folder_name": self._folder_name,
        }
        self.storage.update_index(
            self.c.meeting_id,
            meeting_info,
            self._folder_name,
        )

    async def _generate_goals(self) -> None:
        """生成会议目标文档."""
        self.current_phase = PhaseType.BACKGROUND
        self.current_round = 0
        logger.info(
            f"[meeting:{self.c.meeting_id}] generating goals",
        )

        # 获取主持人
        host = self._get_participant_by_role(RoleType.HOST)
        if not host:
            logger.warning(
                f"[meeting:{self.c.meeting_id}] using default goals",
            )
            content = self._build_default_goals()
        else:
            # 构建提示词
            logger.info(
                f"[meeting:{self.c.meeting_id}] calling host: {host.name}",
            )
            prompt = build_host_prompt(
                participant=host,
                topic=self.c.topic,
            )
            content, _reasons = await self._call_agent(host, prompt)

        logger.info(
            f"[meeting:{self.c.meeting_id}] written to: {self.goals_doc.path}",
        )
        self.storage.write_doc(self.goals_doc.path, content)

    def _build_default_goals(self) -> str:
        """构建默认目标内容."""
        return f"""# 会议目标

## 会议信息

| 字段 | 内容 |
|------|------|
| 会议ID | {self.c.meeting_id} |
| 会议名称 | {self.c.meeting_name} |
| 会议类型 | {self.c.meeting_type.value} |
| 准备时间 | {_ts()} |

---

## 议题：{self.c.topic.title}

{self.c.topic.description or ""}

{self.c.topic.context or ""}

---

*本目标由系统自动生成于 {_ts()}*
"""

    async def _opening(self) -> None:
        """开场阶段."""
        self.current_phase = PhaseType.OPENING
        self.current_round = 1
        meet_info = f"meet<{self.c.meeting_id}, open>"
        logger.info(f"[meetings] {meet_info} start")

        host = self._get_participant_by_role(RoleType.HOST)
        if not host:
            logger.warning(f"[meetings] {meet_info} skipped: no host")
            return

        # 构建主持人开场提示词
        prompt = build_host_prompt(
            host,
            self.c.topic,
            str(self.storage.get_path(self.goals_doc)),
            str(self.storage.get_path(self.records_doc)),
        )

        content, reasons = await self._call_agent(host, prompt)
        tags = [
            f"[{_ts()}]",
            host.name,
            f"({host.id[:8]})",
            f"{self.current_phase}#{self.current_round}",
        ]
        record = self._append_to_records(tags, content, reasons)
        logger.info(f"[meetings] {meet_info} save {record}")

    async def _round_speaking(self, main_points: dict[str, list[str]]) -> None:
        """轮次发言."""
        self.current_phase = PhaseType.ROUND
        meet_info = f"meet<{self.c.meeting_id}, #{self.current_round}>"
        logger.info(f"[meetings] {meet_info} start")

        speakers = self._get_all_speaking_participants()
        if not speakers:
            logger.warning(f"[meetings] {meet_info} skipped: no speakers")
            return

        speaker_ids = [p.id for p in speakers]

        def gen_order():
            # current_round 是 1-based，但 get_round_order 是 0-based
            round_idx = self.current_round - 1
            round_order = self.c.flow.get_round_order(round_idx)
            speak_order = list(speaker_ids)  # 创建副本，避免修改原列表
            if round_order == "reverse":
                speak_order.reverse()
            elif round_order == "random":
                random.shuffle(speak_order)
            elif round_order == "alphabet":
                speak_order.sort()
            return speak_order, round_order

        ordered, order_typ = gen_order()
        logger.info(
            f"[meetings] {meet_info} get order<{order_typ}>: {ordered}",
        )
        for speaker_id in ordered:
            self.current_participant_idx = speaker_ids.index(speaker_id)
            speaker = speakers[self.current_participant_idx]
            prompt = build_reporter_prompt(
                speaker,
                self.c.topic,
                self.current_round,
                ordered,
                str(self.storage.get_path(self.goals_doc)),
                str(self.storage.get_path(self.records_doc)),
            )

            content, reasons = await self._call_agent(speaker, prompt)
            tags = [
                f"[{_ts()}]",
                speaker.name,
                f"({speaker.id[:8]})",
                f"{self.current_phase}#{self.current_round}",
            ]
            record = self._append_to_records(tags, content, reasons)
            logger.debug(
                f"[meetings] {meet_info} {speaker.name} saved {record}",
            )
            speaker_key = f"{speaker.name}({speaker_id})"
            if speaker_key not in main_points:
                main_points[speaker_key] = []
            main_points[speaker_key].append(content)

        logger.info(f"[meetings] {meet_info} got main points of {ordered}")

    async def _decision(self) -> tuple[str, list[str]]:
        """决策阶段."""
        self.current_phase = PhaseType.DECISION
        self.current_round += 1
        meet_info = f"meet<{self.c.meeting_id}, decision>"
        logger.info(f"[meetings] {meet_info} start")

        decider = self._get_participant_by_role(RoleType.DECIDER)
        if not decider:
            logger.warning(f"[meetings] {meet_info} skipped: no decider")
            return "没有任何决策", ["无决策人或不在线"]

        # 构建提示词
        prompt = build_decider_prompt(
            decider,
            self.c.topic,
            str(self.storage.get_path(self.goals_doc)),
            str(self.storage.get_path(self.records_doc)),
            str(self.storage.get_path(self.summary_doc)),
        )

        content, reasons = await self._call_agent(decider, prompt)
        tags = [
            f"[{_ts()}]",
            decider.name,
            f"({decider.id[:8]})",
            f"{self.current_phase}#{self.current_round}",
        ]
        record = self._append_to_records(tags, content, reasons)
        logger.info(f"[meetings] {meet_info} save {record}")
        return content, reasons

    async def _generate_summary(
        self,
        decision: str,
        reasons: list[str],
        main_points: dict[str, list[str]],
    ) -> None:
        """生成会议纪要."""
        self.current_phase = PhaseType.SUMMARY
        self.current_round += 1
        meet_info = f"meet<{self.c.meeting_id}, summary>"
        logger.info(f"[meetings] {meet_info} start")
        # Write decision content to summary doc
        if not self.summary_doc:
            logger.warning(f"[meetings] {meet_info} skipped: no summary_doc")
            return
        # 精简发言要点（使用 LLM 摘要）
        summarized_points = {}
        for speaker, points in main_points.items():
            summarized = []
            for point in points:
                summarized_point = await summarize_speech(point, max_length=80)
                summarized.append(summarized_point)
            summarized_points[speaker] = summarized
        # 生成纪要内容
        summary_content = self._build_summary(
            decision,
            reasons,
            summarized_points,
        )
        self.storage.write_doc(self.summary_doc.path, summary_content)
        logger.info(f"[meetings] {meet_info} done: {self.summary_doc}")

    def _build_summary(
        self,
        decision: str,
        reasons: list[str],
        main_points: dict[str, list[str]],
    ) -> str:
        main_block = "\n".join(
            f"- {speaker}\n\t- {'\n\t- '.join(points)}"
            for speaker, points in main_points.items()
        )
        participants_str = ", ".join(
            f"{p.name}({'/'.join(r.value for r in p.roles)})"
            for p in self.c.participants
        )
        return f"""# 会议纪要

## 会议信息

| 字段 | 内容 |
|------|------|
| 会议ID | {self.c.meeting_id} |
| 会议名称 | {self.c.meeting_name} |
| 会议类型 | {self.c.meeting_type.value} |
| 结束时间 | {_ts()} |
| 参会人员 | {participants_str} |

---

## 最终决策
{decision}

## 决策依据
- {"\n- ".join(reasons)}

## 发言要点
{main_block}

## 发言记录
`{self.records_doc.path if self.records_doc else ""}`

"""

    def _get_reasons_json_path(self) -> Path:
        """获取 reasons JSON 文件路径（与 records.md 同级目录）."""
        if not self.records_doc:
            return (
                WORKING_DIR / "meetings" / f"{self.c.meeting_id}_reasons.json"
            )
        # 从 records_doc.path 推导同级路径：
        # meetings/{folder}/{yyMMdd_HHMM}_records.md ->
        # meetings/{folder}/{yyMMdd_HHMM}_reasons.json
        records_path = self.records_doc.path
        reasons_path = records_path.replace("_records.md", "_reasons.json")
        return WORKING_DIR / reasons_path

    def _append_to_records(
        self,
        content_tags: list[str],
        content: str,
        reasons: list[str] = None,
    ) -> str:
        """追加发言到记录.

        Args:
            content_tags: 发言标签
            content: 发言内容
            reasons: 思维链 or 错误堆栈 （可选）
        """
        if not self.records_doc:
            return "records_doc not found"

        existing = self.storage.read_doc(self.records_doc.path)
        reasons = reasons or []
        # 构造发言记录条目（不含 reasons，避免信息污染）
        new_entry = f"""
--------
{" ".join(content_tags)}
{content}
"""
        updated = existing + new_entry
        self.storage.write_doc(self.records_doc.path, updated)

        # 将 reasons 单独存储到 WORKING_DIR/reasons/ 下的 JSON 文件
        if reasons:
            json_path = self._get_reasons_json_path()
            json_path.parent.mkdir(parents=True, exist_ok=True)
            existing_json = []
            if json_path.exists():
                try:
                    existing_json = json.loads(
                        json_path.read_text(encoding="utf-8"),
                    )
                except json.JSONDecodeError:
                    existing_json = []
            # 解析 content_tags: [时间, 发言人, (id), 阶段#轮次]
            time_str = _ts()
            speaker = ""
            phase = ""
            for tag in content_tags:
                if tag.startswith("["):
                    time_str = tag.strip("[]")
                elif tag.startswith("("):
                    pass  # id 部分
                elif "#" in tag:
                    phase = tag
                else:
                    speaker = tag
            new_reason_entry = {
                "时间": time_str,
                "阶段": phase,
                "发言人": speaker,
                "发言内容": content,
                "reasons": reasons,
            }
            existing_json.append(new_reason_entry)
            json_path.write_text(
                json.dumps(existing_json, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        return new_entry

    async def _call_agent(
        self,
        agent: MeetingParticipant,
        prompt: str,
    ) -> tuple[str, list[str]]:
        """调用 Agent.

        Args:
            agent: 参与者
            prompt: 提示词

        Returns:
            Tuple of (Agent 响应文本, 思维链 mermaid)
        """
        call_info = f"meet<{self.c.meeting_id}> agent[{agent.name},{agent.id}]"
        logger.info(f"[meetings] {call_info} start")
        content, reasons = "未发言", []
        try:
            reply_agent_id = agent.id
            host = self._get_participant_by_role(RoleType.HOST)
            ask_agent_id = host.id if host else "__system__"
            session_id = f"{self.c.meeting_id}"
            result = await self.rpc.chat(
                agent.endpoint.url,
                agent.endpoint.auth_key,
                prompt,
                session_id,
                ask_agent_id,
                reply_agent_id,
                False,
            )
            content, reasons = (
                result.get("content", ""),
                result.get(
                    "reasons",
                    [],
                ),
            )
        except Exception as e:
            content, reasons = f"遇到问题: {str(e)}", traceback.format_exception(e)

        logger.info(
            f"[meetings] {call_info} got {content} \n\t reason {reasons}",
        )
        return content, reasons

    def _get_participant_by_role(
        self,
        role: RoleType,
    ) -> Optional[MeetingParticipant]:
        """根据角色获取参与者."""
        for p in self.c.participants:
            if p.has_role(role):
                return p
        return None

    def _get_participants_by_role(
        self,
        role: RoleType,
    ) -> list[MeetingParticipant]:
        """根据角色获取所有参与者."""
        return [p for p in self.c.participants if p.has_role(role)]

    def _get_all_speaking_participants(self) -> list[MeetingParticipant]:
        """获取所有可以发言的参与者（包括 HOST+REPORTER）."""
        return [p for p in self.c.participants if p.can_speak()]

    def _build_result(self) -> dict:
        """构建结果."""
        return {
            "status": self.status.value,
            "meeting_id": self.c.meeting_id,
            "meeting_name": self.c.meeting_name,
            "meeting_type": self.c.meeting_type.value,
            "documents": {
                "goals_path": self.goals_doc.path if self.goals_doc else None,
                "records_path": self.records_doc.path
                if self.records_doc
                else None,
                "summary_path": self.summary_doc.path
                if self.summary_doc
                else None,
            },
        }

    def get_status(self) -> dict:
        """获取会议状态."""
        return {
            "meeting_id": self.c.meeting_id,
            "status": self.status.value,
            "current_phase": self.current_phase.value
            if self.current_phase
            else None,
            "current_round": self.current_round,
            "current_participant_idx": self.current_participant_idx,
        }

    def stop(self) -> None:
        """停止会议."""
        self.status = MeetingStatus.STOPPED
        logger.info(f"[meeting:{self.c.meeting_id}]stopped")
