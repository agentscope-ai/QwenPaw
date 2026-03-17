# -*- coding: utf-8 -*-
"""Data models for local model management."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class BackendType(str, Enum):
    LLAMACPP = "llamacpp"
    MLX = "mlx"


class DownloadSource(str, Enum):
    HUGGINGFACE = "huggingface"
    MODELSCOPE = "modelscope"


class LocalModelInfo(BaseModel):
    """Metadata for a single downloaded local model."""

    id: str = Field(..., description="Unique ID: <repo_id>/<filename>")
    repo_id: str = Field(
        ...,
        description="Source repo, e.g. 'Qwen/Qwen3-8B-GGUF'",
    )
    filename: str = Field(
        ...,
        description="Model file, e.g. 'mistral-7b-instruct-v0.2.Q4_K_M.gguf'",
    )
    backend: BackendType
    source: DownloadSource = DownloadSource.HUGGINGFACE
    file_size: int = Field(default=0, description="File size in bytes")
    local_path: str = Field(
        default="",
        description="Absolute path to model file on disk",
    )
    display_name: str = Field(default="", description="Human-friendly name")


class DownloadProgress(BaseModel):
    """Progress event emitted during model download."""

    repo_id: str
    filename: str
    total_bytes: int = 0
    downloaded_bytes: int = 0
    status: str = "downloading"  # "downloading" | "complete" | "error"
    error: Optional[str] = None


class LocalModelsManifest(BaseModel):
    """Persisted to ~/.boostclaw/models/manifest.json."""

    models: dict[str, LocalModelInfo] = Field(default_factory=dict)
