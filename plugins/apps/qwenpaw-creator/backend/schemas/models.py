# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

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


def validation_source_from_reuse_llm(reuse_llm: bool) -> str:
    """Map the legacy ``reuse_llm`` flag onto ``validation_source``."""

    return "llm" if reuse_llm else "custom"


def reuse_llm_from_validation_source(validation_source: str) -> bool:
    """Mirror ``validation_source`` back onto the legacy wire field."""

    return validation_source == "llm"


class GroundingConfig(ModelConfigItem):
    """Web-grounding retrieval and visual-verification configuration.

    The inherited model fields configure a custom visual verifier.
    ``reuse_llm`` remains in the wire format for older saved/plugin-host
    configurations and mirrors ``validation_source == "llm"``. Search has
    separate credentials so a generic verifier is never assumed to support
    provider-native web tools.
    """

    enabled: bool = True
    reuse_llm: bool = True
    validation_source: Literal["llm", "vlm", "custom"] = "llm"
    tavily_api_key: str = ""
    native_search_enabled: bool = True
    search_provider: Literal["dashscope_qwen"] = "dashscope_qwen"
    search_reuse_llm: bool = True
    search_model_name: str = ""
    search_api_key: str = ""
    search_base_url: str = ""
    search_protocol: str = "DashScope（百炼）"

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_grounding_config(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        migrated = dict(value)
        if "validation_source" not in migrated:
            migrated["validation_source"] = validation_source_from_reuse_llm(
                migrated.get("reuse_llm", True),
            )
        migrated["reuse_llm"] = reuse_llm_from_validation_source(
            migrated["validation_source"],
        )
        if "search_reuse_llm" not in migrated:
            migrated["search_reuse_llm"] = (
                value.get("reuse_llm", True)
                if "validation_source" not in value
                else True
            )
        if not migrated["search_reuse_llm"]:
            for search_field, legacy_field in {
                "search_model_name": "model_name",
                "search_api_key": "api_key",
                "search_base_url": "base_url",
                "search_protocol": "protocol",
            }.items():
                if search_field not in migrated and legacy_field in value:
                    migrated[search_field] = value[legacy_field]
        return migrated


class ExecutionAuthorizationConfig(StrictModel):
    mode: Literal["required", "allow_all"] = "required"


class CreationCheckpointConfig(StrictModel):
    """Pit-stop gates the user must clear before costly generation.

    ``required`` blocks visual generation until the plan (and later the
    character/scene designs) are confirmed; ``skip`` runs unattended.
    """

    mode: Literal["required", "skip"] = "required"


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
    grounding: GroundingConfig = Field(default_factory=GroundingConfig)
    asr: AsrConfig = Field(default_factory=AsrConfig)
    image: ModelConfigItem
    video: ModelConfigItem
    oss: OssConfig = Field(default_factory=OssConfig)
    execution_authorization: ExecutionAuthorizationConfig = Field(
        default_factory=ExecutionAuthorizationConfig,
        alias="executionAuthorization",
    )
    creation_checkpoints: CreationCheckpointConfig = Field(
        default_factory=CreationCheckpointConfig,
        alias="creationCheckpoints",
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
