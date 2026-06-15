# -*- coding: utf-8
"""Approval gate before agent shell/python execution touches protected files."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, TypeVar

from .agent_write import (
    _build_guard_result,
    _read_current_content,
    _truncate_for_api,
)
from .post_command_verify import verify_protected_baselines_after_command
from .shell_preflight import (
    absolute_paths_for_relative,
    detect_python_protected_write_targets,
    detect_shell_protected_write_targets,
)
from .os_readonly import temporary_os_writable
from .state_integrity_verify import (
    capture_state_hashes_for_agent,
    verify_integrity_state_after_command,
)
from .trust_root import detect_integrity_state_write_in_text

if TYPE_CHECKING:
    from agentscope.tool import ToolResponse

    from .service import FileBaselineService

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class GuardedCommandOutcome:
    """Result of a guarded shell/python execution attempt."""

    status: str
    message: str = ""
    response: "ToolResponse | None" = None

    @property
    def handled(self) -> bool:
        return self.status != "direct"


def _restored_command_response(
    *,
    tool_name: str,
    restored_paths: list[str],
    result: "ToolResponse | None" = None,
) -> "GuardedCommandOutcome":
    from agentscope.message import TextBlock
    from agentscope.tool import ToolResponse

    paths_text = ", ".join(restored_paths)
    message = (
        f"Blocked: {tool_name} altered protected file(s) ({paths_text}); "
        "content restored from baseline."
    )
    logger.warning(
        "file_baseline_command_guard tool=%s outcome=restored paths=%s",
        tool_name,
        restored_paths,
    )
    return GuardedCommandOutcome(
        status="restored",
        message=message,
        response=ToolResponse(content=[TextBlock(type="text", text=f"Error: {message}")]),
    )


def _blocked_state_response(
    *,
    tool_name: str,
    blocked_paths: list[str],
) -> "GuardedCommandOutcome":
    from agentscope.message import TextBlock
    from agentscope.tool import ToolResponse

    paths_text = ", ".join(blocked_paths)
    message = (
        f"Blocked: {tool_name} cannot modify integrity-protection state "
        f"({paths_text}). Baseline metadata is operator-maintained only."
    )
    logger.warning(
        "file_baseline_command_guard tool=%s outcome=state_blocked paths=%s",
        tool_name,
        blocked_paths,
    )
    return GuardedCommandOutcome(
        status="state_blocked",
        message=message,
        response=ToolResponse(content=[TextBlock(type="text", text=f"Error: {message}")]),
    )


async def _finalize_command_execution(
    service: "FileBaselineService",
    *,
    agent_id: str,
    tool_name: str,
    result: "ToolResponse",
    state_hashes_before: dict[str, str] | None = None,
) -> GuardedCommandOutcome:
    state_drift = await verify_integrity_state_after_command(
        service,
        agent_id,
        before_hashes=state_hashes_before,
    )
    if state_drift:
        return _blocked_state_response(
            tool_name=tool_name,
            blocked_paths=state_drift,
        )

    restored = await verify_protected_baselines_after_command(
        service,
        agent_id=agent_id,
    )
    if restored:
        return _restored_command_response(
            tool_name=tool_name,
            restored_paths=restored,
            result=result,
        )
    return GuardedCommandOutcome(status="executed", response=result)


async def _await_command_approval(
    service: "FileBaselineService",
    *,
    agent_id: str,
    session_id: str,
    root_session_id: str,
    user_id: str,
    channel: str,
    tool_name: str,
    rel_paths: list[str],
    preview_text: str,
    tool_input: dict[str, Any],
    timeout_seconds: float,
) -> tuple[str, str]:
    """Create approval, wait, return (status, message). status in approved|denied|timeout|no_session."""
    from qwenpaw.app.agent_context import get_current_session_id
    from qwenpaw.app.approvals import get_approval_service
    from qwenpaw.constant import TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS
    from qwenpaw.security.tool_guard.approval import ApprovalDecision

    resolved_session = session_id or get_current_session_id() or ""
    if not resolved_session:
        return (
            "no_session",
            "Persona-protected writes require an active session for operator approval.",
        )

    wait_timeout = timeout_seconds or float(TOOL_GUARD_APPROVAL_TIMEOUT_SECONDS)
    primary_rel = rel_paths[0]
    workspace = service.settings_store.resolve_workspace(agent_id)
    primary_abs = workspace / primary_rel
    current_content, current_truncated = _read_current_content(
        primary_abs,
        encoding="utf-8",
    )
    proposed_preview, proposed_truncated = _truncate_for_api(preview_text)

    guard_result = _build_guard_result(tool_name, primary_rel, preview_text)
    approval_extra: dict[str, Any] = {
        "file_baseline_write": {
            "relative_path": primary_rel,
            "protected_paths": rel_paths,
            "absolute_path": str(primary_abs.resolve()),
            "operation": "command_execute",
            "current_content": current_content,
            "proposed_content": proposed_preview,
            "current_truncated": current_truncated,
            "proposed_truncated": proposed_truncated,
            "content_preview": proposed_preview[:500],
            "source": "agent_command",
        },
        "tool_call": {
            "id": f"persona-command-{tool_name}",
            "name": tool_name,
            "input": {
                **tool_input,
                "file_path": primary_rel,
                "protected_paths": rel_paths,
                "current_content": current_content,
            },
        },
        "request_prompt": (
            f"Approve {tool_name} that may modify protected file(s): "
            + ", ".join(rel_paths)
        ),
    }

    svc = get_approval_service()
    pending = await svc.create_pending(
        session_id=resolved_session,
        root_session_id=root_session_id or resolved_session,
        owner_agent_id=agent_id,
        user_id=user_id,
        channel=channel,
        agent_id=agent_id,
        tool_name=tool_name,
        result=guard_result,
        timeout_seconds=wait_timeout,
        extra=approval_extra,
    )

    decision = await svc.wait_for_approval(pending.request_id, wait_timeout)
    if decision == ApprovalDecision.APPROVED:
        return "approved", ""
    if decision == ApprovalDecision.DENIED:
        return "denied", f"Operator denied {tool_name} affecting protected path(s)."
    return "timeout", f"Approval timed out for {tool_name}."


async def _run_with_command_guard(
    service: "FileBaselineService",
    *,
    agent_id: str,
    session_id: str,
    root_session_id: str,
    user_id: str,
    channel: str,
    tool_name: str,
    rel_paths: list[str],
    preview_text: str,
    tool_input: dict[str, Any],
    execute_fn: Callable[[], Awaitable[T]],
    to_response: Callable[[T], "ToolResponse"],
    timeout_seconds: float = 0.0,
    cwd: Path | None = None,
) -> GuardedCommandOutcome:
    state_before = capture_state_hashes_for_agent(service, agent_id)

    state_blocked = detect_integrity_state_write_in_text(
        service.working_dir,
        preview_text,
        cwd=cwd,
    )
    if state_blocked:
        return _blocked_state_response(tool_name=tool_name, blocked_paths=state_blocked)

    if not rel_paths:
        logger.info(
            "file_baseline_command_guard tool=%s agent_id=%s outcome=direct "
            "reason=no_protected_targets session_id=%s",
            tool_name,
            agent_id,
            session_id or "(empty)",
        )
        result = await execute_fn()
        return await _finalize_command_execution(
            service,
            agent_id=agent_id,
            tool_name=tool_name,
            result=to_response(result),
            state_hashes_before=state_before,
        )

    logger.info(
        "file_baseline_command_guard tool=%s agent_id=%s rel_paths=%s "
        "session_id=%s awaiting_approval=true",
        tool_name,
        agent_id,
        rel_paths,
        session_id or "(empty)",
    )

    status, message = await _await_command_approval(
        service,
        agent_id=agent_id,
        session_id=session_id,
        root_session_id=root_session_id,
        user_id=user_id,
        channel=channel,
        tool_name=tool_name,
        rel_paths=rel_paths,
        preview_text=preview_text,
        tool_input=tool_input,
        timeout_seconds=timeout_seconds,
    )
    logger.info(
        "file_baseline_command_guard tool=%s agent_id=%s rel_paths=%s "
        "approval_status=%s message=%s",
        tool_name,
        agent_id,
        rel_paths,
        status,
        message,
    )
    if status == "no_session":
        from agentscope.message import TextBlock
        from agentscope.tool import ToolResponse

        return GuardedCommandOutcome(
            status="no_session",
            message=message,
            response=ToolResponse(content=[TextBlock(type="text", text=f"Error: {message}")]),
        )
    if status in {"denied", "timeout"}:
        from agentscope.message import TextBlock
        from agentscope.tool import ToolResponse

        return GuardedCommandOutcome(
            status=status,
            message=message,
            response=ToolResponse(content=[TextBlock(type="text", text=f"Error: {message}")]),
        )

    abs_paths = absolute_paths_for_relative(
        service,
        agent_id=agent_id,
        relative_paths=rel_paths,
    )
    with temporary_os_writable(abs_paths):
        result = await execute_fn()
    response = to_response(result)
    await service.coordinator.notify_approved_paths(
        agent_id=agent_id,
        absolute_paths=abs_paths,
        provenance="approved_agent_write",
    )
    logger.info(
        "file_baseline_command_guard tool=%s agent_id=%s rel_paths=%s "
        "outcome=executed_after_approval",
        tool_name,
        agent_id,
        rel_paths,
    )
    return await _finalize_command_execution(
        service,
        agent_id=agent_id,
        tool_name=tool_name,
        result=response,
        state_hashes_before=state_before,
    )


async def try_guarded_shell_command(
    service: "FileBaselineService",
    *,
    command: str,
    cwd: Path | None,
    execute_fn: Callable[[], Awaitable["ToolResponse"]],
) -> GuardedCommandOutcome:
    from qwenpaw.app.agent_context import (
        get_current_agent_id,
        get_current_channel,
        get_current_root_session_id,
        get_current_session_id,
        get_current_user_id,
    )

    agent_id = get_current_agent_id() or "default"
    rel_paths = detect_shell_protected_write_targets(
        service,
        agent_id=agent_id,
        command=command,
        cwd=cwd,
    )
    if rel_paths:
        logger.info(
            "persona_shell_guard_triggered agent_id=%s paths=%s command=%s",
            agent_id,
            rel_paths,
            command[:240],
        )
    return await _run_with_command_guard(
        service,
        agent_id=agent_id,
        session_id=get_current_session_id() or "",
        root_session_id=get_current_root_session_id() or "",
        user_id=get_current_user_id() or "",
        channel=get_current_channel() or "console",
        tool_name="execute_shell_command",
        rel_paths=rel_paths,
        preview_text=command,
        tool_input={"command": command, "cwd": str(cwd) if cwd else None},
        execute_fn=execute_fn,
        to_response=lambda r: r,
        cwd=cwd,
    )


async def try_guarded_python_code(
    service: "FileBaselineService",
    *,
    code: str,
    execute_fn: Callable[[], Awaitable["ToolResponse"]],
) -> GuardedCommandOutcome:
    from qwenpaw.app.agent_context import (
        get_current_agent_id,
        get_current_channel,
        get_current_root_session_id,
        get_current_session_id,
        get_current_user_id,
    )

    agent_id = get_current_agent_id() or "default"
    rel_paths = detect_python_protected_write_targets(
        service,
        agent_id=agent_id,
        code=code,
    )
    workspace = service.settings_store.resolve_workspace(agent_id)
    return await _run_with_command_guard(
        service,
        agent_id=agent_id,
        session_id=get_current_session_id() or "",
        root_session_id=get_current_root_session_id() or "",
        user_id=get_current_user_id() or "",
        channel=get_current_channel() or "console",
        tool_name="execute_python_code",
        rel_paths=rel_paths,
        preview_text=code,
        tool_input={"code": code},
        execute_fn=execute_fn,
        to_response=lambda r: r,
        cwd=workspace,
    )
