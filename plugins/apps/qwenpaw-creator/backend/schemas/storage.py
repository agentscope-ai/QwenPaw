# -*- coding: utf-8 -*-
"""Read-only storage accounting for the Creator runtime."""

from __future__ import annotations

from pydantic import Field

from .common import StrictModel


class ProjectStorageProfileData(StrictModel):
    """One Project's footprint, split at its release baseline."""

    project_id: str = Field(alias="projectId")
    baseline_at: str | None = Field(default=None, alias="baselineAt")
    task_work_bytes: int = Field(default=0, alias="taskWorkBytes")
    task_work_legacy_bytes: int = Field(default=0, alias="taskWorkLegacyBytes")
    task_work_reclaimable_bytes: int = Field(
        default=0,
        alias="taskWorkReclaimableBytes",
    )
    transactions_bytes: int = Field(default=0, alias="transactionsBytes")
    transactions_legacy_bytes: int = Field(
        default=0,
        alias="transactionsLegacyBytes",
    )
    orphan_bytes: int = Field(default=0, alias="orphanBytes")


class StorageTotalsData(StrictModel):
    task_work_bytes: int = Field(default=0, alias="taskWorkBytes")
    task_work_legacy_bytes: int = Field(default=0, alias="taskWorkLegacyBytes")
    task_work_reclaimable_bytes: int = Field(
        default=0,
        alias="taskWorkReclaimableBytes",
    )
    transactions_bytes: int = Field(default=0, alias="transactionsBytes")
    transactions_legacy_bytes: int = Field(
        default=0,
        alias="transactionsLegacyBytes",
    )
    orphan_bytes: int = Field(default=0, alias="orphanBytes")


class StorageProfileData(StrictModel):
    """What the runtime keeps on disk and what it has already released."""

    data_root: str = Field(alias="dataRoot")
    generated_at: str = Field(alias="generatedAt")
    scratch_release_enabled: bool = Field(alias="scratchReleaseEnabled")
    released_files: int = Field(default=0, alias="releasedFiles")
    released_bytes: int = Field(default=0, alias="releasedBytes")
    totals: StorageTotalsData = Field(default_factory=StorageTotalsData)
    projects: list[ProjectStorageProfileData] = Field(default_factory=list)
