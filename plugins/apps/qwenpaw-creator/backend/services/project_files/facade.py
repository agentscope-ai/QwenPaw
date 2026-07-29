# -*- coding: utf-8 -*-
"""Async application facade for the synchronous filesystem primitives."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any, Mapping

from services.runtime_files.field_blocks import FieldBlockStore
from services.runtime_files.session_store import ProjectRuntimeSessionStore

from .commit import ProjectCommitBoundary, ProjectCommitResult
from .jq_transform import JqProjectTransformer
from .poller import ProjectPoller, ProjectSnapshotCacheEntry
from .recovery import (
    CreatorRecoveryReport,
    ProjectCommitRecoveryCoordinator,
    ProjectRecoveryReport,
)
from .review import (
    CreatorReviewRecoveryReport,
    ProjectReviewService,
    ReviewDecisionItem,
)
from .store import ProjectSnapshot, ProjectStore


@dataclass(slots=True)
class CreatorFileServices:
    root: Path
    projects: ProjectStore
    commits: ProjectCommitBoundary
    poller: ProjectPoller
    reviews: ProjectReviewService
    sessions: ProjectRuntimeSessionStore
    jq: JqProjectTransformer
    recovery: ProjectCommitRecoveryCoordinator
    startup_recovery: CreatorRecoveryReport
    startup_review_recovery: CreatorReviewRecoveryReport

    @classmethod
    def create(cls, root: Path) -> CreatorFileServices:
        projects = ProjectStore(root)
        recovery = ProjectCommitRecoveryCoordinator(projects)
        startup_recovery = recovery.recover_all()
        reviews = ProjectReviewService(projects)
        # Review decisions may depend on a compensating Project transaction.
        # Project journals therefore converge first, followed by Review facts.
        startup_review_recovery = reviews.recover_all()
        return cls(
            root=root,
            projects=projects,
            commits=ProjectCommitBoundary(projects),
            poller=ProjectPoller(projects),
            reviews=reviews,
            sessions=ProjectRuntimeSessionStore(root),
            jq=JqProjectTransformer(),
            recovery=recovery,
            startup_recovery=startup_recovery,
            startup_review_recovery=startup_review_recovery,
        )

    def recover_project(
        self,
        project_id: str,
        *,
        _lifecycle_lock_held: bool = False,
    ) -> ProjectRecoveryReport:
        return self.recovery.recover_project(
            project_id,
            _lifecycle_lock_held=_lifecycle_lock_held,
        )

    def recover_all(self) -> CreatorRecoveryReport:
        return self.recovery.recover_all()

    def blocks(self, project_id: str) -> FieldBlockStore:
        return FieldBlockStore(
            self.projects.project_root(project_id)
            / "runtime"
            / "locks"
            / "fields",
        )

    async def snapshot(
        self,
        project_id: str,
        *,
        force: bool = False,
    ) -> ProjectSnapshotCacheEntry:
        return await asyncio.to_thread(
            self.poller.poll_once,
            project_id,
            force=force,
        )

    async def commit_candidate(
        self,
        *,
        base: ProjectSnapshot,
        candidate: Mapping[str, Any],
        **metadata: Any,
    ) -> ProjectCommitResult:
        result = await asyncio.to_thread(
            self.commits.commit,
            base=base,
            candidate=candidate,
            **metadata,
        )
        await asyncio.to_thread(self.poller.note_commit, result.snapshot)
        return result

    async def apply_jq(
        self,
        *,
        project_id: str,
        program: str,
        string_args: Mapping[str, str] | None = None,
        json_args: Mapping[str, Any] | None = None,
        **metadata: Any,
    ) -> ProjectCommitResult:
        # No Project lock is held during jq/model execution.  The later commit
        # merges touched values against the then-current authority.
        base = await asyncio.to_thread(self.projects.read, project_id)
        candidate = await asyncio.to_thread(
            self.jq.transform,
            base.project.model_dump(mode="json"),
            program,
            string_args=string_args,
            json_args=json_args,
        )
        return await self.commit_candidate(
            base=base,
            candidate=candidate,
            **metadata,
        )

    async def active_review(self, project_id: str):
        return await asyncio.to_thread(self.reviews.active, project_id)

    async def active_reviews(self, project_id: str) -> list:
        return await asyncio.to_thread(self.reviews.all_pending, project_id)

    async def decide_review(
        self,
        *,
        project_id: str,
        review_id: str,
        decision_token: str,
        decisions: list[ReviewDecisionItem],
        decision_id: str | None = None,
        _lifecycle_lock_held: bool = False,
    ):
        result = await asyncio.to_thread(
            self.reviews.decide,
            project_id=project_id,
            review_id=review_id,
            decision_token=decision_token,
            decisions=decisions,
            decision_id=decision_id,
            _lifecycle_lock_held=_lifecycle_lock_held,
        )
        current = await asyncio.to_thread(self.projects.read, project_id)
        await asyncio.to_thread(self.poller.note_commit, current)
        return result


_registry_lock = threading.RLock()
_registry: dict[Path, CreatorFileServices] = {}


def creator_file_services(root: Path) -> CreatorFileServices:
    resolved = root.expanduser().resolve()
    with _registry_lock:
        services = _registry.get(resolved)
        if services is None:
            services = CreatorFileServices.create(resolved)
            _registry[resolved] = services
        return services


def clear_creator_file_service_registry() -> None:
    """Test/process-shutdown hook; durable state remains on disk."""

    with _registry_lock:
        for services in _registry.values():
            services.poller.stop()
        _registry.clear()


__all__ = [
    "CreatorFileServices",
    "clear_creator_file_service_registry",
    "creator_file_services",
]
