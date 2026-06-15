# -*- coding: utf-8
"""Console operator saves to persona-protected paths (proposal → approval → commit)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .agent_write import (
    GuardedWriteOutcome,
    _build_guard_result,
    _read_current_content,
    _truncate_for_api,
    current_file_sha256,
    resolve_protected_relative_path,
    sha256_text,
)
from .write_proposal import WriteProposalStore

if TYPE_CHECKING:
    from .service import PersonaBaselineService

logger = logging.getLogger(__name__)

OPERATOR_CONSOLE_TOOL = "operator_console_save"
OPERATOR_CONSOLE_SESSION_PREFIX = "persona-console:"


def operator_console_session_id(agent_id: str) -> str:
    return f"{OPERATOR_CONSOLE_SESSION_PREFIX}{agent_id}"


async def try_guarded_operator_file_write(
    service: "PersonaBaselineService",
    *,
    absolute_path: str,
    content: str,
    agent_id: str,
    encoding: str = "utf-8",
    timeout_seconds: float | None = None,
) -> GuardedWriteOutcome:
    """Proposal → approval → atomic commit for Console Save on protected files."""
    from qwenpaw.app.approvals import get_approval_service
    from qwenpaw.constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    rel_path = resolve_protected_relative_path(
        service,
        agent_id=agent_id,
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

    session_id = operator_console_session_id(agent_id)
    wait_timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else float(TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS)
    )

    store = WriteProposalStore(service.working_dir)
    proposal = store.create(
        agent_id=agent_id,
        relative_path=rel_path,
        absolute_path=str(path.resolve()),
        operation="console_save",
        tool_name=OPERATOR_CONSOLE_TOOL,
        old_sha256=old_sha256,
        new_sha256=new_sha256,
        encoding=encoding,
        content=content,
        session_id=session_id,
        user_id="operator",
        channel="console",
    )

    guard_result = _build_guard_result(OPERATOR_CONSOLE_TOOL, rel_path, content)
    current_content, current_truncated = _read_current_content(path, encoding=encoding)
    proposed_content, proposed_truncated = _truncate_for_api(content)
    approval_extra: dict[str, Any] = {
        "persona_write": {
            "proposal_id": proposal.proposal_id,
            "relative_path": rel_path,
            "absolute_path": proposal.absolute_path,
            "operation": "console_save",
            "old_sha256": old_sha256,
            "new_sha256": new_sha256,
            "current_content": current_content,
            "proposed_content": proposed_content,
            "current_truncated": current_truncated,
            "proposed_truncated": proposed_truncated,
            "content_preview": proposed_content[:500],
            "source": "operator_console",
        },
        "tool_call": {
            "id": f"persona-write-{proposal.proposal_id}",
            "name": OPERATOR_CONSOLE_TOOL,
            "input": {
                "file_path": rel_path,
                "operation": "console_save",
                "content": proposed_content,
                "current_content": current_content,
            },
        },
        "request_prompt": (
            f"Approve Console save to {rel_path} "
            f"({len(content.encode(encoding))} bytes)"
        ),
    }

    svc = get_approval_service()
    pending = await svc.create_pending(
        session_id=session_id,
        root_session_id=session_id,
        owner_agent_id=agent_id,
        user_id="operator",
        channel="console",
        agent_id=agent_id,
        tool_name=OPERATOR_CONSOLE_TOOL,
        result=guard_result,
        timeout_seconds=wait_timeout,
        extra=approval_extra,
    )

    logger.info(
        "persona_operator_write_pending proposal_id=%s path=%s request_id=%s",
        proposal.proposal_id,
        rel_path,
        pending.request_id,
    )

    decision = await svc.wait_for_approval(pending.request_id, wait_timeout)
    if decision != ApprovalDecision.APPROVED:
        store.delete(proposal.proposal_id)
        if decision == ApprovalDecision.DENIED:
            return GuardedWriteOutcome(
                status="denied",
                message=f"Operator denied Console save to `{rel_path}`.",
            )
        return GuardedWriteOutcome(
            status="timeout",
            message=f"Approval timed out for Console save to `{rel_path}`.",
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
                "Console save rejected."
            ),
        )

    try:
        await service.coordinator.commit_approved_write(
            agent_id=agent_id,
            absolute_path=path,
            content=reloaded.content,
            encoding=reloaded.encoding,
            expected_old_sha256=reloaded.old_sha256,
            provenance="approved_operator_console",
        )
    except Exception as exc:
        logger.exception(
            "persona_operator_write_commit_failed proposal_id=%s path=%s",
            proposal.proposal_id,
            rel_path,
        )
        store.delete(proposal.proposal_id)
        return GuardedWriteOutcome(
            status="error",
            message=f"Failed to commit approved Console save: {exc}",
        )

    store.delete(proposal.proposal_id)
    byte_count = len(reloaded.content.encode(reloaded.encoding))
    return GuardedWriteOutcome(
        status="committed",
        message=f"Approved and saved {byte_count} bytes to {path}.",
        bytes_written=byte_count,
    )
