"""Public projections deliberately exclude paths and template configuration."""

from dataclasses import dataclass
from pydantic import BaseModel


@dataclass(frozen=True)
class SkillSnapshot:
    snapshot_key: str
    content_hash: str


class CatalogSkill(BaseModel):
    id: str
    name: str
    version_id: str
    version: str
    content_hash: str


def catalog_skill(row):
    return CatalogSkill(
        **{key: str(row[key]) for key in CatalogSkill.model_fields}
    ).model_dump()
