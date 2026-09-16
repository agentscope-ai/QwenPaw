"""Credential-free catalog contracts."""

from pydantic import BaseModel, ConfigDict


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    provider_id: str
    provider_name: str
    model: str
    name: str
    supports_image: bool | None = None
    supports_video: bool | None = None
    max_input_length: int
    available: bool = True


class GovernanceStatus(BaseModel):
    enforced: bool = False
    version: int = 0
