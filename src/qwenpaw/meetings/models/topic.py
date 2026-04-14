# -*- coding: utf-8 -*-
"""Meeting module data models - Topic."""

from typing import Optional
from pydantic import BaseModel, Field


class MeetingTopic(BaseModel):
    """会议议题模型."""

    title: str = Field(..., description="议题标题")
    description: Optional[str] = Field(None, description="议题描述")
    context: Optional[str] = Field(None, description="议题背景")
