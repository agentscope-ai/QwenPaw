# -*- coding: utf-8 -*-
"""Storage accounting, and the one action that takes settled history back."""

from __future__ import annotations

from pydantic import Field

from .common import StrictModel


class ProjectStorageProfileData(StrictModel):
    """One Project's footprint, split at its release baseline."""

    project_id: str = Field(alias="projectId")
    baseline_at: str | None = Field(default=None, alias="baselineAt")
    history_kept_at: str | None = Field(
        default=None,
        alias="historyKeptAt",
    )
    reclaim_confirmed_at: str | None = Field(
        default=None,
        alias="reclaimConfirmedAt",
    )
    pending_reclaim_bytes: int = Field(default=0, alias="pendingReclaimBytes")
    task_work_bytes: int = Field(default=0, alias="taskWorkBytes")
    task_work_legacy_bytes: int = Field(default=0, alias="taskWorkLegacyBytes")
    task_work_reclaimable_bytes: int = Field(
        default=0,
        alias="taskWorkReclaimableBytes",
    )
    event_stream_bytes: int = Field(default=0, alias="eventStreamBytes")
    transactions_bytes: int = Field(default=0, alias="transactionsBytes")
    transactions_legacy_bytes: int = Field(
        default=0,
        alias="transactionsLegacyBytes",
    )
    orphan_bytes: int = Field(default=0, alias="orphanBytes")


class HistoryReclaimRequest(StrictModel):
    """An explicit, deliberate press: the action refuses a missing confirm."""

    confirm: bool = Field(default=False, strict=True)


class HistoryReclaimResultData(StrictModel):
    """What one on-demand history sweep actually took off the disk."""

    project_id: str = Field(alias="projectId")
    history_kept: bool = Field(alias="historyKept")
    confirmed_at: str | None = Field(default=None, alias="confirmedAt")
    removed_transactions: int = Field(default=0, alias="removedTransactions")
    transaction_bytes: int = Field(default=0, alias="transactionBytes")
    released_files: int = Field(default=0, alias="releasedFiles")
    released_bytes: int = Field(default=0, alias="releasedBytes")


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
    event_stream_bytes: int = Field(default=0, alias="eventStreamBytes")


class StorageProfileData(StrictModel):
    """What the runtime keeps on disk and what it has already released."""

    data_root: str = Field(alias="dataRoot")
    generated_at: str = Field(alias="generatedAt")
    scratch_release_enabled: bool = Field(alias="scratchReleaseEnabled")
    released_files: int = Field(default=0, alias="releasedFiles")
    released_bytes: int = Field(default=0, alias="releasedBytes")
    elision_backup_bytes: int = Field(default=0, alias="elisionBackupBytes")
    auto_reclaim_max_bytes: int = Field(
        default=0,
        alias="autoReclaimMaxBytes",
    )
    event_stream_report_max_bytes: int = Field(
        default=0,
        alias="eventStreamReportMaxBytes",
    )
    totals: StorageTotalsData = Field(default_factory=StorageTotalsData)
    projects: list[ProjectStorageProfileData] = Field(default_factory=list)
