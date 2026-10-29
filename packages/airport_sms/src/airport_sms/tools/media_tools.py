"""媒体工具：OCR / ASR 适配器接口。不关闭案件。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MediaAttachment:
    """附加到案件证据的文本结果。"""

    kind: str
    text: str
    asset_id: str


class OcrAdapter(Protocol):
    """OCR 适配。"""

    def recognize(self, asset_id: str, payload: bytes) -> str:
        """识别图片文字。"""
        ...


class AsrAdapter(Protocol):
    """ASR 适配。"""

    def transcribe(self, asset_id: str, payload: bytes) -> str:
        """转写音频。"""
        ...


class FakeOcr:
    """测试用 OCR。"""

    def recognize(self, asset_id: str, payload: bytes) -> str:
        """返回固定样本文本。"""
        return f"ocr:{asset_id}:{len(payload)}"


class FakeAsr:
    """测试用 ASR。"""

    def transcribe(self, asset_id: str, payload: bytes) -> str:
        """返回固定转写。"""
        return f"asr:{asset_id}:{len(payload)}"


def attach_ocr_text(
    ocr: OcrAdapter, *, asset_id: str, payload: bytes
) -> MediaAttachment:
    """运行 OCR 并返回附件，不改案件状态。"""
    text = ocr.recognize(asset_id, payload)
    return MediaAttachment(kind="ocr", text=text, asset_id=asset_id)


def attach_asr_text(
    asr: AsrAdapter, *, asset_id: str, payload: bytes
) -> MediaAttachment:
    """运行 ASR 并返回附件，不改案件状态。"""
    text = asr.transcribe(asset_id, payload)
    return MediaAttachment(kind="asr", text=text, asset_id=asset_id)


__all__ = [
    "AsrAdapter",
    "FakeAsr",
    "FakeOcr",
    "MediaAttachment",
    "OcrAdapter",
    "attach_asr_text",
    "attach_ocr_text",
]
