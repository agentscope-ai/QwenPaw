# -*- coding: utf-8 -*-
"""Require real, current-turn file delivery for explicit artifact requests."""
from __future__ import annotations

import re
from agentscope.message import Msg, TextBlock, ToolCallBlock, ToolResultBlock

from .image_generation_guard import ImageGenerationGuard, output_media_types
from ..loop.gates import StopAction, StopHandlerResult

_FILE_TYPES = {
    r"pdf": "application/pdf",
    r"pptx?|powerpoint|幻灯片|演示文稿": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    r"docx|word": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    r"xlsx|excel|电子表格": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    r"html": "text/html",
    r"csv": "text/csv",
    r"海报|图片|图像|插画|png|jpe?g|webp": "image/",
}


def creation_action(text: str):
    if re.search(
        r"(?:只要|只需|仅需|只写|只生成).{0,12}(?:文案|提示词)|不要.{0,8}(?:生成|制作|绘制)|^(?:/[\w-]+\s+)?(?:请)?(?:如何|怎么|解释|介绍|how\b|explain\b)",
        text,
    ):
        return None
    return re.search(
        r"生成|制作|设计|绘制|修改|编辑|画一|画只|画个|画张|(?:给我|帮我|请|我想|^|\s)画|编写|导出(?:为)?|转换(?:为|成)?|转(?:为|成)|做一|create|generate|edit|export(?: to)?|convert.+?to|draw",
        text,
        re.I,
    )


def requested_file_types(text: str) -> set[str]:
    action = creation_action(text)
    if action is None:
        return set()
    target = text[action.end() :]
    requested = {
        mime
        for pattern, mime in _FILE_TYPES.items()
        if re.search(pattern, target, re.I)
    }
    return requested or {
        mime for pattern, mime in _FILE_TYPES.items() if re.search(pattern, text, re.I)
    }


class FileDeliveryGuard(ImageGenerationGuard):
    """Reuse bounded completion retries with format-specific delivery evidence."""

    reason = "requested_file_not_delivered"
    force_initial_tool = False
    continuation_message = (
        "The requested file formats have not all been delivered in this turn. "
        "Follow the enabled skill, actually create and validate the files, then "
        "call send_file_to_user for each requested format. Reading instructions "
        "or describing a file is not completion. Never invent a download URL. "
        "If blocked, inspect the actual tool error and explain the missing prerequisite."
    )
    failure_message = "本次文件生成或交付未完成，尚未成功发送所需格式的文件，不能标记为已完成。请查看本轮工具错误或缺少的必要信息后重试。"

    def __init__(self, required_types: set[str]):
        super().__init__()
        self.required_types = frozenset(required_types)
        self._sent_types: set[str] = set()
        self._dispatch_denied = False

    @property
    def delivered(self) -> bool:
        return all(
            any(sent.startswith(required) for sent in self._sent_types)
            for required in self.required_types
        )

    def observe(self, context: list) -> None:
        for message in context:
            for block in message.get_content_blocks():
                if (
                    not isinstance(block, (ToolCallBlock, ToolResultBlock))
                    or block.id in self._old_ids
                ):
                    continue
                if isinstance(block, ToolCallBlock):
                    self.has_tool_calls = True
                if isinstance(block, ToolResultBlock) and block.name == "spawn_subagent":
                    if block.state == "success":
                        self._dispatch_denied = False
                    elif any("子任务未获授权" in getattr(item, "text", "") for item in block.output):
                        self._dispatch_denied = True
                if (
                    isinstance(block, ToolResultBlock)
                    and block.state == "success"
                    and block.name == "send_file_to_user"
                ):
                    self._sent_types.update(output_media_types(block.output))

    def check(self, final_msg, *, allow_retry=True):
        if final_msg is not None and self._dispatch_denied and not self.delivered:
            return StopHandlerResult(
                action=StopAction.TERMINATE, reason="subtask_authorization_failed",
                final_message=Msg(name=final_msg.name, role="assistant", content=[TextBlock(
                    text="后台未能取得子任务的执行权限，文件尚未交付。已完成的步骤已保留，无需重复确认同一份样稿。",
                )]),
            )
        if final_msg is not None:
            text = final_msg.get_text_content() or ""
            asks_input = re.search(
                r"请.{0,8}(?:确认|提供|上传|选择|批准)|等待.{0,8}(?:确认|批准)|缺少.{0,12}(?:信息|材料|文件)|please.{0,12}(?:provide|confirm|approve|upload)",
                text,
                re.I,
            )
            claims_done = re.search(
                r"已.{0,6}(?:生成|完成|制作|创建|发送|导出)|生成.{0,4}(?:好了|完毕)|下载|download|generated|created|completed|attached|ready|/artifacts/",
                re.sub(
                    r"(?:大纲|计划|提纲|材料清单)已(?:生成|完成|整理)|已(?:生成|完成|整理)(?:了)?(?:大纲|计划|提纲|材料清单)",
                    "",
                    text,
                ),
                re.I,
            )
            if asks_input and not claims_done:
                return StopHandlerResult(action=StopAction.BYPASS)
        return super().check(final_msg, allow_retry=allow_retry)
