# -*- coding: utf-8 -*-
"""Async application facade for the synchronous filesystem primitives."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import logging
from pathlib import Path
import threading
from typing import Any, Mapping

from services.runtime_files.field_blocks import FieldBlockStore
from services.runtime_files import (
    MessageChannel,
    MessageClassification,
    RuntimeGoalNotFound,
    RuntimeSessionNotFound,
)
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
    ReviewDecisionJournalState,
    ReviewRejectionAction,
    ReviewRejectionFeedback,
    render_rejection_feedback_message,
)
from .store import ProjectSnapshot, ProjectStore


logger = logging.getLogger(__name__)


def _log_safe(value: object) -> str:
    """Neutralise CR/LF so user-provided values cannot forge log lines."""
    return str(value).replace("\r", "\\r").replace("\n", "\\n")


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
        services = cls(
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
        services.recover_review_rejection_feedback_messages()
        return services

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
        rejection_feedback: ReviewRejectionFeedback | None = None,
        decision_id: str | None = None,
        _lifecycle_lock_held: bool = False,
    ):
        result = await asyncio.to_thread(
            self.reviews.decide,
            project_id=project_id,
            review_id=review_id,
            decision_token=decision_token,
            decisions=decisions,
            rejection_feedback=rejection_feedback,
            decision_id=decision_id,
            _lifecycle_lock_held=_lifecycle_lock_held,
        )
        current = await asyncio.to_thread(self.projects.read, project_id)
        await asyncio.to_thread(self.poller.note_commit, current)
        return result

    async def publish_review_followup(
        self,
        *,
        project_id: str,
        review_id: str,
        decision_id: str,
    ) -> ReviewRejectionAction | None:
        """Append one idempotent Runtime continuation for a Review decision."""

        auto_continued = await self._auto_continue_storyboard_videos(
            project_id=project_id,
            review_id=review_id,
            decision_id=decision_id,
        )
        return await asyncio.to_thread(
            self._publish_review_followup,
            project_id=project_id,
            review_id=review_id,
            decision_id=decision_id,
            auto_continued=auto_continued,
        )

    async def _auto_continue_storyboard_videos(
        self,
        *,
        project_id: str,
        review_id: str,
        decision_id: str,
    ) -> list[str]:
        """Start video generation for approved storyboards, when safe.

        The Runtime never auto-resumed a paused specialist: after approval
        the mainline had to re-delegate, and models routinely skipped that
        step while claiming the video was already running. Only fires when
        execution authorization is allow_all — otherwise dispatching here
        would bypass the cost-approval gate — and only for approved
        storyboard artifacts whose element has no main output yet. Failures
        never block the follow-up message; the mainline instruction remains
        the fallback.
        """

        from models.config import (
            EXECUTION_AUTHORIZATION_ALLOW_ALL,
            get_execution_authorization_mode,
        )

        if (
            get_execution_authorization_mode()
            != EXECUTION_AUTHORIZATION_ALLOW_ALL
        ):
            return []
        try:
            journal = await asyncio.to_thread(
                self.reviews.get_decision_journal,
                project_id,
                review_id,
                decision_id,
            )
        except Exception:
            return []
        if (
            journal.state is not ReviewDecisionJournalState.FINALIZED
            or journal.rejection_feedback is not None
            or not all(item.decision == "ACCEPT" for item in journal.decisions)
        ):
            return []
        targets = self._accepted_artifact_targets(journal)
        if not targets:
            return []
        snapshot = await asyncio.to_thread(self.projects.read, project_id)
        project = snapshot.project
        continued: list[str] = []
        for item in targets:
            target_ref = str(item.get("target_ref") or "")
            version_id = str(item.get("artifact_version_id") or "")
            if not target_ref.startswith("element:"):
                continue
            artifact = project.assets.artifact_versions_by_id.get(version_id)
            if artifact is None or artifact.kind != "r2v_storyboard_image":
                continue
            element_id = target_ref.removeprefix("element:")
            element = None
            for timeline in project.timelines.items.values():
                element = timeline.elements_by_id.get(element_id)
                if element is not None:
                    break
            if element is None or "main" in element.outputs:
                continue
            digest = sha256(
                f"{project_id}\0{review_id}\0{decision_id}\0"
                f"{target_ref}".encode("utf-8"),
            ).hexdigest()
            try:
                from services.media_files.r2v_execution import (
                    execute_file_r2v_command,
                )

                await execute_file_r2v_command(
                    self,
                    project_id=project_id,
                    target_ref=target_ref,
                    arguments={},
                    idempotency_key=f"review-auto-continue-{digest}",
                )
            except Exception:
                logger.exception(
                    "auto-continue video failed for %s in Project %s",
                    _log_safe(target_ref),
                    _log_safe(project_id),
                )
                continue
            continued.append(target_ref)
        return continued

    async def publish_review_rejection_feedback(
        self,
        *,
        project_id: str,
        review_id: str,
        decision_id: str,
    ) -> ReviewRejectionAction | None:
        """Backward-compatible alias for Review follow-up publication."""

        return await self.publish_review_followup(
            project_id=project_id,
            review_id=review_id,
            decision_id=decision_id,
        )

    def recover_review_rejection_feedback_messages(self) -> None:
        """Replay the rejection-feedback outbox after a process crash.

        A crash can happen after the Review journal is finalized but before
        its Session message is appended. The deterministic client message ID
        makes replay safe even when the first append actually succeeded.
        """

        for project_id in self.projects.discover_project_ids():
            try:
                journals = self.reviews.finalized_rejection_feedback_journals(
                    project_id,
                )
            except Exception:
                logger.exception(
                    "failed to discover rejection feedback for Project %s",
                    project_id,
                )
                continue
            for journal in journals:
                try:
                    self._publish_review_followup(
                        project_id=project_id,
                        review_id=journal.review_id,
                        decision_id=journal.decision_id,
                    )
                except Exception:
                    logger.exception(
                        "failed to recover rejection feedback %s "
                        "for Project %s",
                        journal.decision_id,
                        project_id,
                    )

    def _followup_conversation_id(
        self,
        project_id: str,
        session: Any,
        journal: Any,
    ) -> str | None:
        """Locate the Conversation a review follow-up message belongs to.

        Prefers the Conversation of the originating request, then the
        active Goal's Conversation, then the default Conversation.
        """

        messages = self.sessions.list_messages(
            project_id,
            session.session_id,
            after_seq=0,
            limit=None,
        )
        originating = next(
            (
                item
                for item in messages
                if item.message_seq
                == journal.review_before.request_message_seq
            ),
            None,
        )
        if originating is not None:
            return originating.conversation_id
        if session.active_goal_id is not None:
            try:
                goal = self.sessions.get_goal(
                    project_id,
                    session.active_goal_id,
                )
                return goal.conversation_id
            except RuntimeGoalNotFound:
                pass
        conversations = self.sessions.list_conversations(
            project_id,
            session.session_id,
        )
        default = next(
            (item for item in conversations if item.is_default),
            conversations[0] if conversations else None,
        )
        return default.conversation_id if default is not None else None

    def _followup_message_text(
        self,
        project_id: str,
        journal: Any,
        *,
        auto_continued: list[str] | None = None,
    ) -> str | None:
        """Render the follow-up text, or ``None`` when none is warranted."""

        if journal.state is not ReviewDecisionJournalState.FINALIZED:
            return None
        if journal.rejection_feedback is not None:
            return render_rejection_feedback_message(journal)
        accepted_targets = self._accepted_artifact_targets(journal)
        if not accepted_targets or not all(
            item.decision == "ACCEPT" for item in journal.decisions
        ):
            return None
        # A batch can expose several media Reviews at once. Queue exactly
        # one continuation, after the last pending Review resolves, so a
        # multi-image approval does not fan out into duplicate Agent runs.
        if self.reviews.active(project_id) is not None:
            return None
        return self._render_review_approval_message(
            accepted_targets,
            auto_continued=auto_continued or [],
        )

    def _publish_review_followup(
        self,
        *,
        project_id: str,
        review_id: str,
        decision_id: str,
        auto_continued: list[str] | None = None,
    ) -> ReviewRejectionAction | None:
        """Synchronous implementation shared by HTTP and startup recovery."""

        journal = self.reviews.get_decision_journal(
            project_id,
            review_id,
            decision_id,
        )
        feedback = journal.rejection_feedback
        text = self._followup_message_text(
            project_id,
            journal,
            auto_continued=auto_continued,
        )
        if text is None:
            return None
        try:
            session = self.sessions.get_project_session_snapshot(project_id)
        except RuntimeSessionNotFound:
            # Unit-created/legacy Projects may have Reviews but no Runtime
            # Session. The feedback remains durable in the decision journal.
            return feedback.action if feedback is not None else None

        conversation_id = self._followup_conversation_id(
            project_id,
            session,
            journal,
        )
        if conversation_id is None:
            return feedback.action if feedback is not None else None

        digest = sha256(
            f"{project_id}\0{review_id}\0{decision_id}".encode("utf-8"),
        ).hexdigest()
        client_message_id = (
            f"review-feedback-{digest}"
            if feedback is not None
            else f"review-approval-resume-{digest}"
        )
        metadata = {
            "reviewId": review_id,
            "decisionId": decision_id,
            "targets": (
                [
                    item.model_dump(mode="json")
                    for item in journal.rejection_targets
                ]
                if feedback is not None
                else self._accepted_artifact_targets(journal)
            ),
        }
        if feedback is not None:
            serialized_feedback = feedback.model_dump(
                mode="json",
                by_alias=True,
            )
            # Adding the unified field must not change the retry payload of
            # legacy decisions. Session admission compares the entire payload
            # for a stable client_message_id during crash recovery.
            if serialized_feedback.get("feedbackNote") is None:
                serialized_feedback.pop("feedbackNote", None)
            metadata["rejectionFeedback"] = serialized_feedback
        else:
            metadata["reviewResolution"] = "ACCEPTED"
        if feedback is None or (
            feedback.action is ReviewRejectionAction.UNDO_AND_REGENERATE
        ):
            # A regenerate decision is a new, target-scoped user mutation.
            # Admit it through the same durable boundary as AgentDock input so
            # an older in-memory run cannot keep working from the pre-reject
            # snapshot or regenerate without seeing the user's feedback.
            self.sessions.admit_user_request(
                project_id,
                session.session_id,
                conversation_id,
                request_id=client_message_id,
                client_message_id=client_message_id,
                content_parts=[{"type": "text", "text": text}],
                source=(
                    "review_rejection_feedback"
                    if feedback is not None
                    else "review_approval_resume"
                ),
                channel=MessageChannel.AGENTDOCK,
                classification=MessageClassification.REVIEW_REVISE,
                metadata=metadata,
            )
        else:
            # UNDO_ONLY is durable context, not executable work.
            self.sessions.append_message(
                project_id,
                session.session_id,
                conversation_id,
                role="system",
                content_parts=[{"type": "text", "text": text}],
                message_id=f"message-review-feedback-{digest}",
                client_message_id=client_message_id,
                source="review_rejection_feedback",
                channel=MessageChannel.RUNTIME,
                classification=MessageClassification.REVIEW_COMMENT,
                metadata=metadata,
            )
        return feedback.action if feedback is not None else None

    @staticmethod
    def _accepted_artifact_targets(journal) -> list[dict[str, str]]:
        accepted = {
            item.operation_id
            for item in journal.decisions
            if item.decision == "ACCEPT"
        }
        targets: dict[str, dict[str, str]] = {}
        for operation in journal.review_before.operations:
            if operation.operation_id not in accepted:
                continue
            if not (operation.json_pointer or "").startswith(
                "/assets/artifact_versions_by_id/",
            ):
                continue
            after = operation.after
            if not isinstance(after, Mapping):
                continue
            metadata = after.get("metadata")
            metadata = metadata if isinstance(metadata, Mapping) else {}
            version_id = str(after.get("version_id") or "").strip()
            target_ref = str(
                metadata.get("targetRef")
                or after.get("owner_ref")
                or operation.target_ref
                or "",
            ).strip()
            if not version_id or not target_ref:
                continue
            targets.setdefault(
                target_ref,
                {
                    "target_ref": target_ref,
                    "artifact_version_id": version_id,
                    "label": str(after.get("name") or target_ref).strip(),
                },
            )
        return list(targets.values())

    @staticmethod
    def _render_review_approval_message(
        targets: list[dict[str, str]],
        *,
        auto_continued: list[str] | None = None,
    ) -> str:
        lines = [
            "【系统自动消息 · 审阅已通过】",
            (
                "用户已通过以下产物。请从原任务的下一个未完成步骤自动继续；"
                "不要重新生成已通过产物，也不要要求用户输入 continue。"
            ),
            (
                "若通过的产物是某 R2V Element 的分镜图，其视频不会自动开始："
                "请立即对该 Element 重新委派 R2V 生成 Director 以继续生成视频；"
                "这不算重新生成已通过产物。其他被暂停的 Specialist 同理，"
                "需重新委派同一目标才会继续后续步骤。"
            ),
            "已通过产物：",
        ]
        lines.extend(
            f"- {item['label']}（{item['target_ref']} · "
            f"{item['artifact_version_id']}）"
            for item in targets
        )
        if auto_continued:
            lines.append(
                "以下 Element 的视频已由 Runtime 自动开始生成，"
                "请勿重新委派这些 Element，继续其他未完成步骤即可：",
            )
            lines.extend(f"- {target}" for target in auto_continued)
        return "\n".join(lines)


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
