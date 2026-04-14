# -*- coding: utf-8 -*-
"""Meeting module data models - Config and Document."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, model_validator

from .types import MeetingType, RoleType
from .topic import MeetingTopic
from .participant import MeetingParticipant
from .flow import MeetingFlow


class MeetingConfig(BaseModel):
    """会议配置模型."""

    meeting_id: Optional[str] = Field(None, description="会议 ID")
    version: str = Field(None, description="数据版本 YYMMDD")
    meeting_name: str = Field(..., description="会议名称")
    meeting_type: MeetingType = Field(..., description="会议类型")
    topic: MeetingTopic = Field(..., description="会议议题")
    participants: list[MeetingParticipant] = Field(
        default_factory=list,
        description="参与者",
    )
    flow: MeetingFlow = Field(default_factory=MeetingFlow, description="会议流程")

    @property
    def folder_prefix(self) -> str:
        """获取文件夹前缀: r_ (regular) 或 t_ (temporary)."""
        return "r_" if self.meeting_type == MeetingType.REGULAR else "t_"

    def get_version(self) -> str:
        """获取数据版本，格式 YYMMDD."""
        if self.version:
            return self.version
        return datetime.now().strftime("%y%m%d")

    @model_validator(mode="after")
    def validate_participant_roles(self) -> "MeetingConfig":
        """验证参与者角色冲突."""
        if not self.participants:
            return self

        # 检查 HOST 数量：有且仅有一个 HOST
        host_count = sum(1 for p in self.participants if p.is_host())
        if host_count > 1:
            raise ValueError(
                f"参与者中有多于 1 个 HOST 角色: 找到 {host_count} 个 HOST",
            )

        if host_count == 0:
            raise ValueError("会议配置错误: 必须有至少 1 个 HOST 角色")

        # 检查 DECIDER 数量：不能多于 1 个
        decider_count = sum(
            1 for p in self.participants if p.has_role(RoleType.DECIDER)
        )
        if decider_count > 1:
            raise ValueError(
                f"参与者中有多于 1 个 DECIDER 角色: 找到 {decider_count} 个 DECIDER",
            )

        return self

    @classmethod
    def from_dict(cls, data: dict) -> "MeetingConfig":
        """从字典创建配置."""
        return cls(**data)


class MeetingDocument(BaseModel):
    """会议文档模型."""

    meeting_id: str = Field(..., description="会议 ID")
    doc_type: str = Field(..., description="文档类型: goals/records/summary")
    path: str = Field(..., description="文档路径")
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="创建时间",
    )


class PromptsConfig(BaseModel):
    """提示词配置."""

    host: Optional[str] = Field(None, description="主持人提示词模板")
    reporter: Optional[str] = Field(None, description="汇报人提示词模板")
    reporter_round2: Optional[str] = Field(None, description="汇报人第2轮提示词模板")
    decider: Optional[str] = Field(None, description="决策人提示词模板")
