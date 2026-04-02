# -*- coding: utf-8 -*-
from pydantic import Field
from pydantic_settings import BaseSettings


class MemorySettings(BaseSettings):
    COPAW_MEMORY_COMPACT_KEEP_RECENT: int = Field(
        description="Number of recent memory items to keep during compaction",
        default=3,
        ge=0,
    )

    COPAW_MEMORY_COMPACT_RATIO: float = Field(
        description="Ratio of memory items to keep during compaction",
        default=0.7,
        ge=0,
    )

    MEMORY_STORE_BACKEND: str = Field(
        description="Backend storage for memory ('auto', 'sqlite', 'redis')",
        default="auto",
    )

    FTS_ENABLED: bool = Field(
        description="Whether to enable full-text search",
        default=True,
    )

    EMBEDDING_API_KEY: str = Field(
        description="API key for embedding service",
        default="",
    )

    EMBEDDING_BASE_URL: str = Field(
        description="Base URL for embedding service",
        default="",
    )

    EMBEDDING_MODEL_NAME: str = Field(
        description="Model name for embeddings",
        default="",
    )
