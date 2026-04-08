# -*- coding: utf-8 -*-
"""Meeting prompts utilities."""

from typing import Optional
from .models import (
    MeetingParticipant,
    MeetingTopic,
    PromptsConfig,
)


# 默认提示词模板
DEFAULT_PROMPTS = PromptsConfig(
    host=(
        "你是{participant_name}，负责主持{topic_title}的讨论。"
        "请开场，100-300字。\n\n"
        "议题背景：{topic_description}\n"
        "相关上下文：{topic_context}\n\n"
        "目标文档：{goals_path}\n"
        "发言记录：{records_path}\n\n"
        "重要：请只返回发言内容，不要写入任何文件。"
        "会议记录由系统统一追加。"
    ),
    reporter=(
        "你是{participant_name}，请就{topic_title}发表见解（{intent}）。"
        "请发言200-500字。\n\n"
        "目标文档：{goals_path}\n"
        "发言顺序：{speaking_order}\n\n"
        "重要：请只返回发言内容，不要写入任何文件。"
        "会议记录由系统统一追加。"
    ),
    reporter_round2=(
        "你是{participant_name}，这是第{round}轮，请基于其他人的观点进行"
        "回应和补充。请回应200-500字。\n\n"
        "目标文档：{goals_path}\n"
        "发言记录：{records_path}\n"
        "发言顺序：{speaking_order}\n\n"
        "重要：请只返回发言内容，不要写入任何文件。"
        "会议记录由系统统一追加。"
    ),
    decider=(
        "你是{participant_name}，请就{topic_title}综合所有发言给出最终决策。"
        "请言简意赅，100-300字。每次发言的会议纪要（摘要）控制在50-150字，"
        "不超过250字。\n\n"
        "目标文档：{goals_path}\n"
        "发言记录：{records_path}\n"
        "会议纪要：{summary_path}\n\n"
        "重要：请只返回发言内容，不要写入任何文件。"
        "会议记录由系统统一追加。"
    ),
)


def build_host_prompt(
    participant: MeetingParticipant,
    topic: MeetingTopic,
    goals_path: str = "",
    records_path: str = "",
    prompts: Optional[PromptsConfig] = None,
) -> str:
    """构建主持人提示词."""
    prompts = prompts or DEFAULT_PROMPTS
    template = prompts.host or DEFAULT_PROMPTS.host

    return template.format(
        participant_name=participant.name,
        topic_title=topic.title,
        topic_description=topic.description or "",
        topic_context=topic.context or "",
        goals_path=goals_path or "",
        records_path=records_path or "",
    )


def build_reporter_prompt(
    participant: MeetingParticipant,
    topic: MeetingTopic,
    round_num: int = 1,
    speaking_order: Optional[list[str]] = None,
    goals_path: str = "",
    records_path: str = "",
    prompts: Optional[PromptsConfig] = None,
) -> str:
    prompts = prompts or DEFAULT_PROMPTS

    if round_num == 1:
        template = prompts.reporter or DEFAULT_PROMPTS.reporter
    else:
        template = prompts.reporter_round2 or DEFAULT_PROMPTS.reporter_round2

    order_str = ", ".join(speaking_order) if speaking_order else ""

    return template.format(
        participant_name=participant.name,
        topic_title=topic.title,
        intent=participant.intent or "",
        round=round_num,
        goals_path=goals_path or "",
        records_path=records_path or "",
        speaking_order=order_str,
    )


def build_decider_prompt(
    participant: MeetingParticipant,
    topic: MeetingTopic,
    goals_path: str = "",
    records_path: str = "",
    summary_path: str = "",
    prompts: Optional[PromptsConfig] = None,
) -> str:
    """构建决策人提示词."""
    prompts = prompts or DEFAULT_PROMPTS
    template = prompts.decider or DEFAULT_PROMPTS.decider

    return template.format(
        participant_name=participant.name,
        topic_title=topic.title,
        goals_path=goals_path or "",
        records_path=records_path or "",
        summary_path=summary_path or "",
    )
