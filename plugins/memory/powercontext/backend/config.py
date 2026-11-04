# -*- coding: utf-8 -*-
"""Configuration owned by the PowerContext memory plugin."""

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class PowerContextAutoMemorySearchConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    mode: Literal["prepare", "memory"] = "prepare"
    max_results: int = Field(default=3, ge=1)
    max_context_bytes: int = Field(default=12000, ge=1024, le=32768)


class PowerContextAssemblySection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: Literal["profile", "topic-memory", "memory", "experience"]
    limit: int = Field(ge=1, le=8, strict=True)

    @model_validator(mode="after")
    def validate_experience_limit(self):
        if self.family == "experience" and self.limit > 2:
            raise ValueError("PowerContext experience limit must be <= 2")
        return self


class PowerContextAssemblyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: Literal["markdown"] = "markdown"
    sections: list[PowerContextAssemblySection] = Field(
        default_factory=lambda: [
            PowerContextAssemblySection(family="profile", limit=1),
            PowerContextAssemblySection(family="topic-memory", limit=2),
            PowerContextAssemblySection(family="memory", limit=3),
            PowerContextAssemblySection(family="experience", limit=2),
        ],
    )
    show: list[Literal["recall_rank", "confidence"]] = Field(
        default_factory=list,
    )

    @model_validator(mode="after")
    def validate_unique_values(self):
        families = [section.family for section in self.sections]
        if len(families) != len(set(families)):
            raise ValueError("PowerContext context families must be unique")
        if len(self.show) != len(set(self.show)):
            raise ValueError("PowerContext context show fields must be unique")
        return self


class PowerContextMemoryConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_url: str = ""
    token: str = ""
    scope_id: str = Field(default="", max_length=256)
    timeout: float = Field(default=10.0, ge=1.0, le=60.0, allow_inf_nan=False)
    auto_memory_search_config: PowerContextAutoMemorySearchConfig = Field(
        default_factory=PowerContextAutoMemorySearchConfig,
    )
    context_assembly: PowerContextAssemblyConfig = Field(
        default_factory=PowerContextAssemblyConfig,
    )

    @model_validator(mode="after")
    def validate_search_limit(self):
        if self.auto_memory_search_config.max_results > 50:
            raise ValueError("PowerContext max_results must be <= 50")
        return self

    @field_validator("scope_id")
    @classmethod
    def validate_scope_id(cls, value: str) -> str:
        normalized = value.strip()
        if value and not normalized:
            raise ValueError("PowerContext scope_id must not be blank")
        return normalized
