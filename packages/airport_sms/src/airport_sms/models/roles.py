"""模型角色枚举。"""

from __future__ import annotations

from enum import Enum


class ModelRole(str, Enum):
    """网关角色。"""

    ROUTER = "router"
    WORKER = "worker"
    JUDGE = "judge"
    EMBED = "embed"
    OCR = "ocr"
    ASR = "asr"


__all__ = ["ModelRole"]
