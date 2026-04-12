# -*- coding: utf-8 -*-
from pydantic import Field
from pydantic_settings import BaseSettings


class ModelSettings(BaseSettings):
    DASHSCOPE_BASE_URL: str = Field(
        description="Base URL for DashScope API",
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    COPAW_LLM_MAX_RETRIES: int = Field(
        description="Maximum number of retries for LLM API calls",
        default=3,
        ge=0,
    )

    COPAW_LLM_MAX_CONCURRENT: int = Field(
        description=(
            "Max concurrent in-flight LLM calls. Excess wait on semaphore"
        ),
        default=10,
        ge=1,
    )

    COPAW_LLM_MAX_QPM: int = Field(
        description=(
            "Max queries per minute. 0=unlimited. E.g. OpenAI Tier-1 ~500 QPM"
        ),
        default=600,
        ge=0,
    )

    COPAW_LLM_BACKOFF_BASE: float = Field(
        description="Base in seconds for exponential backoff on retries",
        default=1.0,
        ge=0.1,
    )

    COPAW_LLM_BACKOFF_CAP: float = Field(
        description="Max backoff time in seconds for LLM retries",
        default=10.0,
        ge=0.5,
    )

    COPAW_LLM_RATE_LIMIT_PAUSE: float = Field(
        description="Global pause seconds when 429 received.\n"
        "Override by Retry-After header",
        default=5.0,
        ge=1.0,
    )

    COPAW_LLM_RATE_LIMIT_JITTER: float = Field(
        description=(
            "Random jitter seconds to stagger concurrent waiters wake-up"
        ),
        default=1.0,
        ge=0.0,
    )

    COPAW_LLM_ACQUIRE_TIMEOUT: float = Field(
        description=(
            "Max seconds to wait for semaphore slot before RuntimeError"
        ),
        default=300.0,
        ge=10.0,
    )
