"""Configuration owned by the ADBPG memory plugin."""

from pydantic import BaseModel, ConfigDict, Field


class AutoMemorySearchConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    max_results: int = Field(default=3, ge=1)


class ADBPGMemoryConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rest_base_url: str = ""
    rest_api_key: str = ""
    memory_isolation: bool = True
    search_timeout: float = Field(default=10.0, ge=1.0)
    auto_memory_search_config: AutoMemorySearchConfig = Field(
        default_factory=AutoMemorySearchConfig,
    )
