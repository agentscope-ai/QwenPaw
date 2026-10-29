"""模型提供方标识。密钥不进仓库。"""

from __future__ import annotations

from dataclasses import dataclass


class ModelConfigError(Exception):
    """配置缺失。"""


@dataclass(frozen=True)
class ProviderIds:
    """六类模型 id。"""

    router: str = "qwen2.5-1.5b"
    worker: str = "qwen3.8-27b"
    judge: str = "qwen3-235b"
    embed: str = "qwen3-embed"
    ocr: str = "paddleocr"
    asr: str = "qwen3-asr"
    api_key: str = "test-key"


__all__ = ["ModelConfigError", "ProviderIds"]
