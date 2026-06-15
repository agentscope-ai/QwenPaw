# -*- coding: utf-8 -*-
"""Agent-controlled writes to file-baseline-protected paths (proposal → approval → commit)."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .paths import workspace_relative_path
from .trust_root import agent_integrity_write_blocked
from .write_proposal import WriteProposal, WriteProposalStore

if TYPE_CHECKING:
    from .service import FileBaselineService

logger = logging.getLogger(__name__)

FILE_BASELINE_WRITE_API_CONTENT_LIMIT = 12_000


def _truncate_for_api(text: str, *, limit: int = FILE_BASELINE_WRITE_API_CONTENT_LIMIT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _read_current_content(path: Path, *, encoding: str) -> tuple[str, bool]:
    if not path.is_file():
        return "", False
    try:
        text = path.read_text(encoding=encoding)
    except OSError:
        return "", False
    return _truncate_for_api(text)

FILE_BASELINE_WRITE_KIND = "file_baseline_write"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str, *, encoding: str) -> str:
    return sha256_bytes(text.encode(encoding))


def current_file_sha256(path: Path) -> str:
    if not path.is_file():
        return sha256_bytes(b"")
    return sha256_bytes(path.read_bytes())


def resolve_protected_relative_path(
    service: "FileBaselineService",
    *,
    agent_id: str,
    absolute_path: str | Path,
) -> str | None:
    if not service.is_enabled():
        return None
    settings = service.settings_store.load()
    workspace = service.settings_store.resolve_workspace(agent_id)
    rel_path = workspace_relative_path(workspace, Path(absolute_path))
    if rel_path is None:
        return None
    protected = set(service.settings_store.effective_paths(settings, agent_id))
    if rel_path not in protected:
        return None
    return rel_path


@dataclass(frozen=True)
class GuardedWriteOutcome:
    """Result of a guarded agent file write attempt."""

    status: str
    message: str = ""
    bytes_written: int = 0

    @property
    def handled(self) -> bool:
        """True when file_io must not perform its own disk write."""
        return self.status in {
            "committed",
            "denied",
            "timeout",
            "no_session",
            "unchanged",
            "conflict",
            "error",
        }

    @property
    def ok(self) -> bool:
        return self.status in {"committed", "unchanged", "direct"}


def _build_guard_result(tool_name: str, rel_path: str, preview: str) -> Any:
    from qwenpaw.security.tool_guard.models import (
        GuardFinding,
        GuardSeverity,
        GuardThreatCategory,
        ToolGuardResult,
    )

    snippet = preview[:240] + ("…" if len(preview) > 240 else "")
    finding = GuardFinding(
        id="persona-write-approval",
        rule_id="persona_protected_write",
        category=GuardThreatCategory.PRIVILEGE_ESCALATION,
        severity=GuardSeverity.HIGH,
        title="Persona protected file change",
        description=(
            f"Agent tool `{tool_name}` proposes changing protected path "
            f"`{rel_path}`. Operator approval is required before writing."
        ),
        tool_name=tool_name,
        param_name="file_path",
        snippet=snippet,
        remediation="Approve in Console Inbox to apply the change and update baseline.",
        guardian="file_baseline",
    )
    return ToolGuardResult(
        tool_name=tool_name,
        params={"file_path": rel_path},
        findings=[finding],
        guardians_used=["file_baseline"],
    )


async def try_guarded_agent_file_write(
    service: "FileBaselineService",
    *,
    absolute_path: str,
    content: str,
    tool_name: str,
    operation: str = "write",
    encoding: str = "utf-8",
    agent_id: str | None = None,
    session_id: str | None = None,
    root_session_id: str | None = None,
    user_id: str | None = None,
    channel: str | None = None,
    owner_agent_id: str | None = None,
    timeout_seconds: float | None = None,
) -> GuardedWriteOutcome:
    """Proposal → approval → atomic commit for persona-protected agent writes."""
    from qwenpaw.app.agent_context import (
        get_current_agent_id,
        get_current_channel,
        get_current_root_session_id,
        get_current_session_id,
        get_current_user_id,
    )
    from qwenpaw.app.approvals import get_approval_service
    from qwenpaw.constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    resolved_agent_id = agent_id or get_current_agent_id() or "default"

    blocked = agent_integrity_write_blocked(
        service.working_dir,
        absolute_path,
    )
    if blocked:
        return GuardedWriteOutcome(status="denied", message=blocked)

    rel_path = resolve_protected_relative_path(
        service,
        agent_id=resolved_agent_id,
        absolute_path=absolute_path,
    )
    if rel_path is None:
        return GuardedWriteOutcome(status="direct")

    path = Path(absolute_path)
    old_sha256 = current_file_sha256(path)
    new_sha256 = sha256_text(content, encoding=encoding)
    if old_sha256 == new_sha256:
        return GuardedWriteOutcome(
            status="unchanged",
            message="Content unchanged; no write performed.",
        )

    resolved_session_id = session_id or get_current_session_id() or ""
    if not resolved_session_id:
        return GuardedWriteOutcome(
            status="no_session",
            message=(
                "Persona-protected file writes require an active session so an "
                "operator can approve the change in Console."
            ),
        )

    resolved_user_id = user_id or get_current_user_id() or ""
    resolved_channel = channel or get_current_channel() or "console"
    resolved_root_session = (
        root_session_id or get_current_root_session_id() or resolved_session_id
    )
    resolved_owner = owner_agent_id or resolved_agent_id
    wait_timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else float(TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS)
    )

    store = WriteProposalStore(service.working_dir)
    proposal = store.create(
        agent_id=resolved_agent_id,
        relative_path=rel_path,
        absolute_path=str(path.resolve()),
        operation=operation,
        tool_name=tool_name,
        old_sha256=old_sha256,
        new_sha256=new_sha256,
        encoding=encoding,
        content=content,
        session_id=resolved_session_id,
        user_id=resolved_user_id,
        channel=resolved_channel,
    )

    guard_result = _build_guard_result(tool_name, rel_path, content)
    current_content, current_truncated = _read_current_content(path, encoding=encoding)
    proposed_content, proposed_truncated = _truncate_for_api(content)
    approval_extra: dict[str, Any] = {
        "file_baseline_write": {
            "proposal_id": proposal.proposal_id,
            "relative_path": rel_path,
            "absolute_path": proposal.absolute_path,
            "operation": operation,
            "old_sha256": old_sha256,
            "new_sha256": new_sha256,
            "current_content": current_content,
            "proposed_content": proposed_content,
            "current_truncated": current_truncated,
            "proposed_truncated": proposed_truncated,
            "content_preview": proposed_content[:500],
        },
        "tool_call": {
            "id": f"persona-write-{proposal.proposal_id}",
            "name": tool_name,
            "input": {
                "file_path": rel_path,
                "operation": operation,
                "content": proposed_content,
                "current_content": current_content,
            },
        },
        "request_prompt": (
            f"Approve persona write to {rel_path} "
            f"({operation}, {len(content.encode(encoding))} bytes)"
        ),
    }

    svc = get_approval_service()
    pending = await svc.create_pending(
        session_id=resolved_session_id,
        root_session_id=resolved_root_session,
        owner_agent_id=resolved_owner,
        user_id=resolved_user_id,
        channel=resolved_channel,
        agent_id=resolved_agent_id,
        tool_name=tool_name,
        result=guard_result,
        timeout_seconds=wait_timeout,
        extra=approval_extra,
    )

    logger.info(
        "file_baseline_write_approval_pending proposal_id=%s path=%s request_id=%s",
        proposal.proposal_id,
        rel_path,
        pending.request_id,
    )

    try:
        decision = await svc.wait_for_approval(pending.request_id, wait_timeout)
    finally:
        pass

    if decision != ApprovalDecision.APPROVED:
        store.delete(proposal.proposal_id)
        if decision == ApprovalDecision.DENIED:
            return GuardedWriteOutcome(
                status="denied",
                message=(
                    f"Operator denied the proposed change to `{rel_path}`."
                ),
            )
        return GuardedWriteOutcome(
            status="timeout",
            message=(
                f"Approval timed out for proposed change to `{rel_path}`."
            ),
        )

    reloaded = store.load(proposal.proposal_id)
    if reloaded is None:
        return GuardedWriteOutcome(
            status="error",
            message="Write proposal expired before commit.",
        )

    current_sha = current_file_sha256(path)
    if current_sha != reloaded.old_sha256:
        store.delete(proposal.proposal_id)
        return GuardedWriteOutcome(
            status="conflict",
            message=(
                "Protected file changed while awaiting approval; "
                "proposal rejected."
            ),
        )

    try:
        await service.coordinator.commit_approved_write(
            agent_id=resolved_agent_id,
            absolute_path=path,
            content=reloaded.content,
            encoding=reloaded.encoding,
            expected_old_sha256=reloaded.old_sha256,
        )
    except Exception as exc:
        logger.exception(
            "file_baseline_write_commit_failed proposal_id=%s path=%s",
            proposal.proposal_id,
            rel_path,
        )
        store.delete(proposal.proposal_id)
        return GuardedWriteOutcome(
            status="error",
            message=f"Failed to commit approved write: {exc}",
        )

    store.delete(proposal.proposal_id)
    byte_count = len(reloaded.content.encode(reloaded.encoding))
    logger.info(
        "file_baseline_write_committed proposal_id=%s path=%s bytes=%d",
        proposal.proposal_id,
        rel_path,
        byte_count,
    )
    return GuardedWriteOutcome(
        status="committed",
        message=f"Approved and wrote {byte_count} bytes to {path}.",
        bytes_written=byte_count,
    )
