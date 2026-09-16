# -*- coding: utf-8 -*-
"""共享应用发布状态机。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from pathlib import Path
from uuid import UUID
from uuid import uuid4

from ..access.actor import ActorContext, ActorType
from ..identity.models import PlatformRole
from ..access.agent_repository import agent_database_id
from .models import (
    SharedAppDraftRecord,
    SharedAppPublicationRecord,
    SharedAppRecord,
    SharedAppUserWorkspaceRecord,
)


class PublicationAccessError(RuntimeError):
    """调用主体无权执行发布治理动作。"""


class PublicationStateError(RuntimeError):
    """发布资源或状态不满足动作前置条件。"""


class PublicationDependencyError(RuntimeError):
    """固定依赖不可用。"""

    def __init__(self, report) -> None:
        super().__init__("publication_dependency_unavailable")
        self.report = report


class SharedAppService:
    """只编排共享应用状态，不处理 HTTP 或前端展示。"""

    def __init__(
        self,
        repository,
        validator,
        *,
        snapshot_builder=None,
        source_workspace_resolver: Callable[[str], object] | None = None,
        manifest_builder=None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repository = repository
        self.validator = validator
        self.snapshot_builder = snapshot_builder
        self.source_workspace_resolver = source_workspace_resolver
        self.manifest_builder = manifest_builder
        self.clock = clock

    def _require_valid_baseline(self, publication) -> None:
        if self.snapshot_builder is None:
            return
        integrity = publication.immutable_manifest.get("integrity", {})
        if not self.snapshot_builder.verify(
            publication.baseline_workspace_key,
            str(integrity.get("workspace_hash") or ""),
        ):
            raise PublicationStateError("PUBLICATION_BASELINE_INVALID")

    @staticmethod
    def _require_admin(actor: ActorContext) -> UUID:
        if (
            actor.actor_type is not ActorType.USER
            or actor.user_id is None
            or actor.platform_role is not PlatformRole.ADMIN
        ):
            raise PublicationAccessError("publications_review_required")
        return actor.user_id

    @staticmethod
    def _require_user(actor: ActorContext) -> UUID:
        if actor.actor_type is not ActorType.USER or actor.user_id is None:
            raise PublicationAccessError("authenticated_user_required")
        return actor.user_id

    async def create_app(self, actor: ActorContext, agent_key: str):
        owner_id = self._require_user(actor)
        agent_id = agent_database_id(agent_key)
        if await self.repository.get_agent_owner(agent_id) != owner_id:
            raise PublicationAccessError("shared_app_owner_required")
        existing = await self.repository.get_app_by_agent(agent_id)
        if existing is not None:
            if existing.owner_user_id != owner_id:
                raise PublicationAccessError("shared_app_owner_required")
            return existing
        now = self.clock()
        return await self.repository.create_app(
            SharedAppRecord(
                id=uuid4(),
                agent_id=agent_id,
                owner_user_id=owner_id,
                status="draft",
                created_at=now,
                updated_at=now,
            ),
            request_id=actor.request_id,
        )

    async def save_draft(
        self,
        actor: ActorContext,
        app_id: UUID,
        manifest: dict,
    ):
        owner_id = self._require_user(actor)
        app = await self.repository.get_app(app_id)
        if app is None or app.owner_user_id != owner_id:
            raise PublicationAccessError("shared_app_owner_required")
        workspace_key = await self.repository.get_source_workspace_key(app_id)
        if workspace_key is None:
            raise PublicationStateError("shared_app_source_unavailable")
        latest = await self.repository.latest_draft(app_id)
        revision = 1 if latest is None else latest.revision + 1
        return await self.repository.create_draft(
            SharedAppDraftRecord(
                id=uuid4(),
                shared_app_id=app_id,
                revision=revision,
                manifest=manifest,
                workspace_key=workspace_key,
                created_by=owner_id,
                updated_at=self.clock(),
            ),
            request_id=actor.request_id,
        )

    async def submit(
        self,
        actor: ActorContext,
        app_id: UUID,
        revision: int,
    ):
        owner_id = self._require_user(actor)
        app = await self.repository.get_app(app_id)
        if app is None or app.owner_user_id != owner_id:
            raise PublicationAccessError("shared_app_owner_required")
        draft = await self.repository.get_draft(app_id, revision)
        if draft is None:
            raise PublicationStateError("shared_app_draft_not_found")
        existing = await self.repository.list_publications(app_id)
        if any(item.version == f"r{revision}" for item in existing):
            raise PublicationStateError("shared_app_revision_already_submitted")
        manifest = (
            await self.manifest_builder(app, draft)
            if self.manifest_builder is not None
            else dict(draft.manifest)
        )
        report = await self.validator.validate(manifest, mode="strong")
        if not report.ok:
            raise PublicationDependencyError(report)
        if self.snapshot_builder is None or self.source_workspace_resolver is None:
            raise PublicationStateError("publication_snapshot_unavailable")
        publication_id = uuid4()
        source = self.source_workspace_resolver(draft.workspace_key)
        snapshot = self.snapshot_builder.build(source, publication_id)
        canonical = json.dumps(
            manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        manifest["integrity"] = {
            "format_version": 1,
            "manifest_hash": hashlib.sha256(canonical).hexdigest(),
            "workspace_hash": snapshot.workspace_hash,
            "source_draft_id": str(draft.id),
            "source_revision": draft.revision,
        }
        return await self.repository.create_submission(
            SharedAppPublicationRecord(
                id=publication_id,
                shared_app_id=app_id,
                version=f"r{revision}",
                immutable_manifest=manifest,
                baseline_workspace_key=snapshot.workspace_key,
                submitted_by=owner_id,
                review_status="pending",
            ),
            request_id=actor.request_id,
        )

    async def list_mine(self, actor: ActorContext):
        return await self.repository.list_mine(self._require_user(actor))

    async def list_catalog(self, actor: ActorContext):
        self._require_user(actor)
        return await self.repository.list_catalog()

    async def start_conversation(
        self,
        actor: ActorContext,
        app_id: UUID,
        *,
        agent_key: str,
        chat_manager,
        workspace_resolver,
        working_dir: Path,
    ) -> dict:
        """创建固定到当前发布版本的私人 ChatSpec 与数据库会话。"""
        from ..app.chats.models import ChatSpec

        user_id = self._require_user(actor)
        app = await self.repository.get_app(app_id)
        if app is None or app.status != "active" or app.current_publication_id is None:
            raise PublicationStateError("shared_app_not_active")
        publication = await self.repository.get_publication(app.current_publication_id)
        if publication is None or publication.review_status != "approved":
            raise PublicationStateError("publication_not_approved")
        self._require_valid_baseline(publication)
        report = await self.validator.validate(publication.immutable_manifest, mode="read")
        if not report.ok:
            raise PublicationDependencyError(report)
        runtime = workspace_resolver.resolve_shared_app_runtime(
            user_id=user_id,
            shared_app_id=app.id,
            publication_id=publication.id,
        )
        workspace_record = await self.repository.get_user_workspace(
            app.id, publication.id, user_id
        )
        if workspace_record is None:
            baseline = Path(working_dir).joinpath(
                *publication.baseline_workspace_key.split("/")
            )
            if not baseline.is_dir():
                raise PublicationStateError("publication_baseline_unavailable")
            runtime.path.parent.mkdir(parents=True, exist_ok=True)
            if not runtime.path.exists():
                staging = runtime.path.parent / f".init-{uuid4().hex[:8]}"
                try:
                    shutil.copytree(baseline, staging)
                    try:
                        os.replace(staging, runtime.path)
                    except OSError:
                        if not runtime.path.is_dir():
                            raise
                finally:
                    if staging.exists():
                        shutil.rmtree(staging)
            now = self.clock()
            workspace_record = await self.repository.create_user_workspace(
                SharedAppUserWorkspaceRecord(
                    shared_app_id=app.id,
                    publication_id=publication.id,
                    user_id=user_id,
                    workspace_key=runtime.workspace_key,
                    status="active",
                    created_at=now,
                    updated_at=now,
                ),
                request_id=actor.request_id,
            )
        elif workspace_record.workspace_key != runtime.workspace_key:
            raise PublicationStateError("publication_workspace_mismatch")
        display = publication.immutable_manifest.get("display", {})
        chat = ChatSpec(
            name=str(display.get("name") or "共享应用"),
            session_id=f"shared-app:{app.id}:{uuid4()}",
            user_id=str(user_id),
            channel="console",
            meta={
                "shared_app_id": str(app.id),
                "publication_id": str(publication.id),
                "publication_version": publication.version,
                "locked_model": {
                    "provider_id": publication.immutable_manifest["model"]["provider_id"],
                    "model": publication.immutable_manifest["model"]["model"],
                },
            },
        )
        chat = await chat_manager.create_chat(chat)
        conversation_repository = chat_manager.conversation_repository
        if conversation_repository is None:
            await chat_manager.delete_chats([chat.id])
            raise PublicationStateError("conversation_authority_unavailable")
        try:
            conversation = await conversation_repository.with_user(
                user_id
            ).bind_publication(
                UUID(chat.id),
                expected_agent_id=app.agent_id,
                shared_app_id=app.id,
                publication_id=publication.id,
                updated_at=chat.updated_at,
            )
        except Exception:
            await chat_manager.delete_chats([chat.id])
            raise
        if conversation is None:
            await chat_manager.delete_chats([chat.id])
            raise PublicationStateError("conversation_authority_unavailable")
        model = publication.immutable_manifest["model"]
        return {
            "agent_id": agent_key,
            "conversation_id": str(conversation.id),
            "publication_id": str(publication.id),
            "version": publication.version,
            "locked_model": {
                "provider_id": model["provider_id"],
                "model": model["model"],
            },
            "workspace_key": runtime.workspace_key,
        }

    async def review(
        self,
        actor: ActorContext,
        publication_id: UUID,
        decision: Literal["approved", "rejected"],
        note: str,
    ):
        reviewer_id = self._require_admin(actor)
        publication = await self.repository.get_publication(publication_id)
        if publication is None:
            raise PublicationStateError("publication_not_found")
        if publication.review_status != "pending":
            raise PublicationStateError("publication_not_pending")
        normalized_note = note.strip()
        if decision == "rejected" and not normalized_note:
            raise PublicationStateError("publication_rejection_note_required")
        return await self.repository.review(
            publication_id,
            reviewer_id=reviewer_id,
            decision=decision,
            note=normalized_note,
            reviewed_at=self.clock(),
            request_id=actor.request_id,
        )

    async def publish(
        self,
        actor: ActorContext,
        app_id: UUID,
        publication_id: UUID,
        *,
        expected_current_id: UUID | None,
    ):
        actor_id = self._require_admin(actor)
        publication = await self.repository.get_publication(publication_id)
        if publication is None or publication.shared_app_id != app_id:
            raise PublicationStateError("publication_not_found")
        if publication.review_status != "approved":
            raise PublicationStateError("publication_not_approved")
        self._require_valid_baseline(publication)
        report = await self.validator.validate(
            publication.immutable_manifest,
            mode="strong",
        )
        if not report.ok:
            raise PublicationDependencyError(report)
        return await self.repository.switch_current(
            app_id,
            publication_id=publication_id,
            expected_current_id=expected_current_id,
            actor_id=actor_id,
            changed_at=self.clock(),
            request_id=actor.request_id,
        )

    async def rollback(
        self,
        actor: ActorContext,
        app_id: UUID,
        publication_id: UUID,
        *,
        expected_current_id: UUID | None,
    ):
        actor_id = self._require_admin(actor)
        publication = await self.repository.get_publication(publication_id)
        if publication is None or publication.shared_app_id != app_id:
            raise PublicationStateError("publication_not_found")
        if publication.review_status != "approved":
            raise PublicationStateError("publication_not_approved")
        self._require_valid_baseline(publication)
        report = await self.validator.validate(
            publication.immutable_manifest, mode="strong"
        )
        if not report.ok:
            raise PublicationDependencyError(report)
        return await self.repository.switch_current(
            app_id,
            publication_id=publication_id,
            expected_current_id=expected_current_id,
            actor_id=actor_id,
            changed_at=self.clock(),
            request_id=actor.request_id,
            audit_action="shared_app.publication.rollback",
        )

    async def retire(
        self,
        actor: ActorContext,
        app_id: UUID,
        *,
        expected_current_id: UUID,
    ):
        actor_id = self._require_admin(actor)
        return await self.repository.retire(
            app_id,
            expected_current_id=expected_current_id,
            actor_id=actor_id,
            changed_at=self.clock(),
            request_id=actor.request_id,
        )
