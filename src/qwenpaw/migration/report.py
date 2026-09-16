"""迁移预览报告模型；所有字段都可安全返回管理端。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class MigrationRejectedItem(BaseModel):
    code: str
    source: str
    detail: str


class MigrationConflict(BaseModel):
    code: str
    source: str
    detail: str


class SecretReference(BaseModel):
    reference: str
    version: Literal["fernet-v1", "plaintext", "unknown"]
    value_exposed: bool = False


class MigrationDomainReport(BaseModel):
    key: str
    label: str
    status: Literal["ready", "empty", "rejected", "unavailable"]
    count: int = Field(ge=0)
    source_hash: str
    mapping: dict[str, str]
    conflicts: list[MigrationConflict] = Field(default_factory=list)
    rejected: list[MigrationRejectedItem] = Field(default_factory=list)


class MigrationIntegrity(BaseModel):
    before_hash: str
    after_hash: str
    unchanged: bool


class MigrationPreviewSummary(BaseModel):
    domain_count: int = Field(ge=0)
    item_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    secret_reference_count: int = Field(ge=0)


class LegacyPostgresSnapshot(BaseModel):
    """旧 PostgreSQL 的脱敏只读探测结果。"""

    configured: bool
    table_count: int = Field(default=0, ge=0)
    row_count: int = Field(default=0, ge=0)
    schema_hash: str = (
        "sha256:e3b0c44298fc1c149afbf4c8996fb924"
        "27ae41e4649b934ca495991b7852b855"
    )
    error_code: str | None = None


class MigrationPreviewReport(BaseModel):
    generated_at: datetime
    read_only: Literal[True] = True
    summary: MigrationPreviewSummary
    integrity: MigrationIntegrity
    domains: list[MigrationDomainReport]
    secret_references: list[SecretReference] = Field(default_factory=list)


class MigrationExecutionReport(BaseModel):
    """单一领域一次迁移的脱敏、可复核结果。"""

    domain: str
    status: Literal[
        "completed",
        "completed_with_rejections",
        "empty",
        "rejected",
        "failed",
    ]
    execution_order: int = Field(ge=1)
    source_count: int = Field(ge=0)
    target_count: int = Field(ge=0)
    inserted_count: int = Field(ge=0)
    updated_count: int = Field(default=0, ge=0)
    unchanged_count: int = Field(ge=0)
    source_hash: str
    target_hash: str
    transaction_committed: bool
    rejected: list[MigrationRejectedItem] = Field(default_factory=list)
