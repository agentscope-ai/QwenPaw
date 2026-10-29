"""能力与工具描述。"""

from airport_sms.tools.case_tools import ToolResult, draft_case, invoke_case_tool
from airport_sms.tools.media_tools import (
    FakeAsr,
    FakeOcr,
    MediaAttachment,
    attach_asr_text,
    attach_ocr_text,
)
from airport_sms.tools.registry import (
    DuplicateToolError,
    ToolDescriptor,
    ToolRegistry,
    UnknownToolError,
    build_default_registry,
)

__all__ = [
    "DuplicateToolError",
    "FakeAsr",
    "FakeOcr",
    "MediaAttachment",
    "ToolDescriptor",
    "ToolRegistry",
    "ToolResult",
    "UnknownToolError",
    "attach_asr_text",
    "attach_ocr_text",
    "build_default_registry",
    "draft_case",
    "invoke_case_tool",
]
