# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import StrictModel


class ModelConfigItem(StrictModel):
    enabled: bool = False
    model_name: str = ""
    api_key: str = ""
    base_url: str = ""
    protocol: str = "OpenAI 兼容"
    custom_protocol: str = ""


class LlmConfig(ModelConfigItem):
    enabled: bool = True
    multimodal: bool = True


class VlmConfig(ModelConfigItem):
    use_llm: bool = True
    multimodal: bool = True


class AsrConfig(ModelConfigItem):
    provider: Literal["whisper", "fun-asr"] = "fun-asr"
    language: str = ""
    reuse_llm_key: bool = True


class ExecutionAuthorizationConfig(StrictModel):
    mode: Literal["required", "allow_all"] = "required"


class OssConfig(StrictModel):
    """QwenPaw Creator media OSS configuration stored in model_config.json."""

    enabled: bool = False
    access_key_id: str = ""
    access_key_secret: str = ""
    endpoint: str = ""
    bucket: str = ""
    public_base_url: str = ""
    policy_api_key: str = ""


class ModelConfigData(StrictModel):
    llm: LlmConfig
    vlm: VlmConfig
    asr: AsrConfig = Field(default_factory=AsrConfig)
    image: ModelConfigItem
    video: ModelConfigItem
    oss: OssConfig = Field(default_factory=OssConfig)
    execution_authorization: ExecutionAuthorizationConfig = Field(
        default_factory=ExecutionAuthorizationConfig,
        alias="executionAuthorization",
    )


class ModelConnectionTestRequest(StrictModel):
    type: Literal["llm", "vlm", "asr", "image", "video"]
    base_url: str = ""
    api_key: str = ""
    model_name: str = ""
    protocol: str = ""
    provider: Literal["whisper", "fun-asr"] | None = None


class ConnectionTestResponse(StrictModel):
    ok: bool
    ms: int = Field(ge=0, default=0)
    error: str | None = None
    detail: str | None = None
    suggestion: str | None = None
