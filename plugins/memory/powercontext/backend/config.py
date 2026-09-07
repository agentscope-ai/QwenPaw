"""Configuration owned by the PowerContext memory plugin."""

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
    max_results: int = Field(default=3, ge=1)
    max_context_bytes: int = Field(default=12000, ge=1024, le=32768)


class PowerContextMemoryConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    base_url: str = ""
    token: str = ""
    scope_id: str = Field(default="", max_length=256)
    timeout: float = Field(default=10.0, ge=1.0, le=60.0, allow_inf_nan=False)
    auto_memory_search_config: PowerContextAutoMemorySearchConfig = Field(
        default_factory=PowerContextAutoMemorySearchConfig,
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
