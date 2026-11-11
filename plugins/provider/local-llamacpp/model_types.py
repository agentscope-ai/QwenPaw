# -*- coding: utf-8 -*-
"""Values used by the llama.cpp manager and its management API."""

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class DownloadSource(str, Enum):
    HUGGINGFACE = "huggingface"
    MODELSCOPE = "modelscope"
    AUTO = "auto"


@dataclass(frozen=True)
class LocalModelConfig:
    max_context_length: int = 65536
    port: int | None = None


@dataclass(frozen=True)
class LocalModelInfo:
    """Local files, download source and server capability probes."""

    id: str
    name: str
    size_bytes: int = 0
    downloaded: bool = False
    source: DownloadSource = DownloadSource.AUTO
    supports_multimodal: bool | None = None
    supports_image: bool | None = None
    supports_video: bool | None = None
    probe_source: str | None = None
    model_type: Literal["chat", "decision"] = "chat"


@dataclass(frozen=True)
class LocalServerInfo:
    port: int
    model_info: LocalModelInfo


PICCOLO_REPO_IDS = {
    f"{owner}/Piccolo-{size}B{suffix}"
    for owner in ("agentscope-ai", "AgentScope")
    for size in (4, 9, 27)
    for suffix in ("", "-BF16", "-Q8_0", "-Q4_K_M")
}
PICCOLO_DOWNLOAD_PATTERNS = [
    "*.gguf",
    "LICENSE",
    "README.md",
    "decision-inference.json",
]
