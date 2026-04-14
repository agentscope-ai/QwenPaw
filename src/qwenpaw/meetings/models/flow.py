# -*- coding: utf-8 -*-
"""Meeting module data models - Flow."""

from typing import Literal
from pydantic import BaseModel, Field


class MeetingFlow(BaseModel):
    """会议流程配置模型."""

    rounds: list[Literal["raw", "reverse", "random", "alphabet"]] = Field(
        default_factory=lambda: ["raw"],
        description="每轮发言顺序模式列表，支持 raw/reverse/random/alphabet，长度即轮数",
    )
    speakers: list[str] = Field(default_factory=list, description="发言者 ID 列表")
    timeout_per_round: int = Field(120, description="每轮超时时间(秒)")

    def num_rounds(self) -> int:
        """获取轮次数量."""
        return len(self.rounds)

    def get_round_order(self, round_idx: int) -> str:
        """获取指定轮次的发言顺序模式.

        Args:
            round_idx: 轮次索引 (0-based)

        Returns:
            发言顺序模式: raw/reverse/random/alphabet
        """
        if 0 <= round_idx < len(self.rounds):
            return self.rounds[round_idx]
        return "raw"
