# -*- coding: utf-8 -*-
"""Built-in tool for delegating tasks to external agent runners.

Uses the ACP protocol.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from agentscope.message import TextBlock
from agentscope.tool import ToolResponse

from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from ..acp.tool_adapter import (
    format_close_response,
    format_final_assistant_response,
    format_permission_suspended_response,
    format_stream_snapshot_response,
    render_event_text,
    response_text,
)

logger = logging.getLogger(__name__)


@dataclass
class _RunnerState:
    agent_id: str
    chat_id: str
    runner: str
    action: str
    status: str
    created_at: float
    updated_at: float
    content: list[TextBlock] = field(default_factory=list)
    error: Optional[str] = None
    pending_permission: Any = None


_runner_state_lock = asyncio.Lock()
_runner_states: dict[tuple[str, str, str], _RunnerState] = {}


def _current_workspace_dir() -> Path:
    return (get_current_workspace_dir() or Path(WORKING_DIR)).expanduser()


def _current_agent_id() -> str:
    from ...app.agent_context import get_current_agent_id

    return get_current_agent_id()


def _resolve_execution_cwd(cwd: str, workspace_dir: Path) -> Path:
    cwd_text = cwd.strip()
    if not cwd_text:
        return workspace_dir.resolve()
    candidate = Path(cwd_text).expanduser()
    if not candidate.is_absolute():
        candidate = workspace_dir / candidate
    return candidate.resolve()


def _get_acp_service() -> Any:
    from ...app.agent_context import get_current_agent_id
    from ...config.config import ACPConfig
    from ...config.config import load_agent_config
    from ..acp import get_acp_service, init_acp_service

    agent_id = get_current_agent_id()
    agent_config = load_agent_config(agent_id)
    acp_config = agent_config.acp or ACPConfig()
    service = get_acp_service(agent_id)
    if service is None or getattr(service, "config", None) != acp_config:
        service = init_acp_service(agent_id, acp_config)
    return service


def _get_available_acp_runners() -> list[str]:
    from ...app.agent_context import get_current_agent_id
    from ...config.config import ACPConfig, load_agent_config

    agent_id = get_current_agent_id()
    agent_config = load_agent_config(agent_id)
    acp_config = agent_config.acp or ACPConfig()
    return sorted(
        name
        for name, runner_cfg in acp_config.agents.items()
        if getattr(runner_cfg, "enabled", False)
    )


def _format_available_runners_text() -> str:
    runners = _get_available_acp_runners()
    if not runners:
        return "No enabled ACP runners are currently configured."
    return "Available ACP runners: " + ", ".join(runners) + "."


def _request_context_chat_id() -> str:
    from ...app.agent_context import get_current_session_id

    session_id = str(get_current_session_id() or "")
    if not session_id:
        raise ValueError(
            "delegate agent requires request context with a session_id; "
            "this tool can only run inside a bound chat session",
        )
    return session_id


def _validate_action_inputs(
    *,
    action_name: str,
    runner_name: str,
    message_text: str,
) -> Optional[str]:
    allowed_actions = {
        "list",
        "status",
        "start",
        "message",
        "respond",
        "close",
    }
    if action_name not in allowed_actions:
        return (
            "Error: action must be one of: list, status, start, message, "
            "respond, close."
        )
    if action_name not in {"list", "status"} and not runner_name:
        return "Error: runner is empty."
    if action_name in {"message", "respond"} and not message_text:
        if action_name == "message":
            return (
                "Error: message is empty. Use action='start' "
                "to begin a new conversation."
            )
        return (
            "Error: message is empty. For action='respond', pass the "
            "exact selected permission option id in message."
        )
    return None


def _task_key(
    agent_id: str,
    chat_id: str,
    runner_name: str,
) -> tuple[str, str, str]:
    return agent_id, chat_id, runner_name


def _format_timestamp(value: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


async def _get_runner_state(
    *,
    agent_id: str,
    chat_id: str,
    runner_name: str,
) -> Optional[_RunnerState]:
    async with _runner_state_lock:
        return _runner_states.get(_task_key(agent_id, chat_id, runner_name))


async def _set_runner_state(state: _RunnerState) -> None:
    async with _runner_state_lock:
        _runner_states[
            _task_key(state.agent_id, state.chat_id, state.runner)
        ] = state


async def _append_runner_state_content(
    state: _RunnerState,
    blocks: list[TextBlock],
) -> None:
    if not blocks:
        return
    async with _runner_state_lock:
        state.content.extend(blocks)
        state.updated_at = time.time()


async def _set_runner_state_status(
    state: _RunnerState,
    status: str,
    *,
    error: Optional[str] = None,
    pending_permission: Any = None,
) -> None:
    async with _runner_state_lock:
        state.status = status
        state.error = error
        state.pending_permission = pending_permission
        state.updated_at = time.time()


def _copy_content_text(blocks: list[TextBlock], limit: int = 12000) -> str:
    parts = [
        str(
            block.get("text")
            if isinstance(block, dict)
            else getattr(block, "text", ""),
        )
        for block in blocks
    ]
    text = "\n\n".join(part.strip() for part in parts if part and part.strip())
    if len(text) <= limit:
        return text
    return text[-limit:]


def _format_task_state_text(
    *,
    runner_name: str,
    session_state: str,
    state: Optional[_RunnerState],
    pending_permission: Any = None,
) -> str:
    lines = [
        f"runner: {runner_name}",
        f"session: {session_state}",
    ]
    if state is None:
        lines.append("task: none")
    else:
        effective_status = (
            "permission_required"
            if pending_permission is not None
            else state.status
        )
        lines.extend(
            [
                f"task: {effective_status}",
                f"last action: {state.action}",
                f"started at: {_format_timestamp(state.created_at)}",
                f"updated at: {_format_timestamp(state.updated_at)}",
            ],
        )
        if state.error:
            lines.append(f"error: {state.error}")
        response_text_value = _copy_content_text(state.content)
        if response_text_value:
            lines.extend(["", "Last response:", response_text_value])
    return "\n".join(lines)


async def _get_runner_session_state(
    service: Any,
    *,
    chat_id: str,
    runner_name: str,
) -> str:
    existing = await service.get_session(chat_id=chat_id, agent=runner_name)
    if existing is None:
        return "closed"
    if getattr(existing.process, "returncode", None) is not None:
        return "exited"
    pending_permission = await service.get_pending_permission(
        chat_id=chat_id,
        agent=runner_name,
    )
    if pending_permission is not None:
        return "waiting_for_permission"
    return "open"


async def _format_acp_runner_states_response() -> ToolResponse:
    runners = _get_available_acp_runners()
    if not runners:
        return response_text(
            "No enabled ACP runners are currently configured.",
        )

    try:
        chat_id = _request_context_chat_id()
    except ValueError:
        chat_id = ""
    service = _get_acp_service() if chat_id else None

    agent_id = _current_agent_id()
    lines = ["Available external ACP runners and states:"]
    for runner_name in runners:
        session_state = ""
        task_state = ""
        if chat_id and service is not None:
            session_state = await _get_runner_session_state(
                service,
                chat_id=chat_id,
                runner_name=runner_name,
            )
            state = await _get_runner_state(
                agent_id=agent_id,
                chat_id=chat_id,
                runner_name=runner_name,
            )
            if state is not None:
                task_state = state.status
        details = []
        if session_state:
            details.append(f"session: {session_state}")
        if task_state:
            details.append(f"task: {task_state}")
        if details:
            lines.append(f"- {runner_name} ({', '.join(details)})")
        else:
            lines.append(f"- {runner_name}")
    return response_text("\n".join(lines))


async def _format_runner_status_response(runner_name: str) -> ToolResponse:
    available_runners = _get_available_acp_runners()
    if runner_name not in available_runners:
        return response_text(
            f"Error: runner '{runner_name}' is not available. "
            + _format_available_runners_text(),
        )
    try:
        chat_id = _request_context_chat_id()
    except ValueError as e:
        return response_text(f"Error: {e}")

    agent_id = _current_agent_id()
    service = _get_acp_service()
    session_state = await _get_runner_session_state(
        service,
        chat_id=chat_id,
        runner_name=runner_name,
    )
    pending_permission = await service.get_pending_permission(
        chat_id=chat_id,
        agent=runner_name,
    )
    state = await _get_runner_state(
        agent_id=agent_id,
        chat_id=chat_id,
        runner_name=runner_name,
    )
    status_text = _format_task_state_text(
        runner_name=runner_name,
        session_state=session_state,
        state=state,
        pending_permission=pending_permission,
    )
    if pending_permission is None:
        return response_text(status_text)

    permission_response = format_permission_suspended_response(
        suspended_permission=pending_permission,
    )
    permission_text = _copy_content_text(permission_response.content)
    return response_text(f"{status_text}\n\n{permission_text}")


async def _format_all_runner_status_response() -> ToolResponse:
    return await _format_acp_runner_states_response()


async def _get_bound_session(
    service: Any,
    *,
    chat_id: str,
    runner_name: str,
) -> Optional[Any]:
    return await service.get_session(chat_id=chat_id, agent=runner_name)


async def _validate_start_request(
    *,
    service: Any,
    chat_id: str,
    runner_name: str,
) -> Optional[str]:
    available_runners = _get_available_acp_runners()
    if runner_name not in available_runners:
        return (
            f"Error: runner '{runner_name}' is not available for ACP start. "
            + _format_available_runners_text()
        )

    existing = await _get_bound_session(
        service,
        chat_id=chat_id,
        runner_name=runner_name,
    )
    if existing is None:
        return None
    if getattr(existing.process, "returncode", None) is not None:
        await service.close_chat_session(chat_id=chat_id, agent=runner_name)
        return None

    return (
        f"Error: an ACP session for runner '{runner_name}' is already open in "
        "the current chat. Use "
        f'delegate_external_agent(action="message", runner="{runner_name}", '
        'message="continue") instead.'
    )


async def _cancel_running_acp_turn(
    *,
    service: Any,
    chat_id: str,
    runner_name: str,
) -> bool:
    try:
        return await service.cancel_turn(chat_id=chat_id, agent=runner_name)
    except Exception:
        logger.warning(
            "Failed to cancel ACP turn for runner '%s' in chat '%s'",
            runner_name,
            chat_id,
            exc_info=True,
        )
        return False


async def _run_action(
    *,
    service: Any,
    chat_id: str,
    action_name: str,
    runner_name: str,
    message_text: str,
    execution_cwd: Path,
    on_message: Any,
) -> Any:
    if action_name == "start":
        return await service.run_turn(
            chat_id=chat_id,
            agent=runner_name,
            prompt_blocks=[{"type": "text", "text": message_text or "hi"}],
            cwd=str(execution_cwd),
            on_message=on_message,
            restart=True,
        )

    if action_name == "message":
        return await service.run_turn(
            chat_id=chat_id,
            agent=runner_name,
            prompt_blocks=[{"type": "text", "text": message_text}],
            cwd=str(execution_cwd),
            on_message=on_message,
            require_existing=True,
        )

    if action_name == "respond":
        bound_session = await _get_bound_session(
            service,
            chat_id=chat_id,
            runner_name=runner_name,
        )
        if bound_session is None:
            raise ValueError(
                "no bound ACP session found for runner "
                f"'{runner_name}' in current chat",
            )
        suspended_permission = await service.get_pending_permission(
            chat_id=chat_id,
            agent=runner_name,
        )
        if suspended_permission is None:
            raise ValueError(
                "current ACP session for runner "
                f"'{runner_name}' is not waiting for permission",
            )
        return await service.resume_permission(
            acp_session_id=bound_session.acp_session_id,
            option_id=message_text.strip(),
            on_message=on_message,
        )

    raise ValueError(f"unsupported action: {action_name}")


async def _stream_action_responses(
    *,
    service: Any,
    chat_id: str,
    action_name: str,
    runner_name: str,
    message_text: str,
    execution_cwd: Path,
    max_runtime: Optional[float] = None,
) -> AsyncGenerator[ToolResponse, None]:
    # pylint: disable=too-many-branches,too-many-statements
    response_queue: asyncio.Queue[ToolResponse] = asyncio.Queue()
    flush_interval = 1.0
    pending_items: list[str] = []
    seen_stream_items: set[str] = set()
    header_sent = False
    flush_task: Optional[asyncio.Task[None]] = None
    final_text_event: Optional[dict[str, Any]] = None
    final_fallback_event: Optional[dict[str, Any]] = None

    async def flush_snapshot() -> None:
        nonlocal header_sent
        if not pending_items:
            return
        snapshot = [
            item.strip() for item in pending_items if item and item.strip()
        ]
        pending_items.clear()
        if not snapshot:
            return
        response = format_stream_snapshot_response(
            snapshot,
            runner_name=runner_name,
            execution_cwd=execution_cwd,
            include_header=not header_sent,
        )
        if response is None:
            return
        header_sent = True
        await response_queue.put(response)

    async def schedule_flush() -> None:
        await asyncio.sleep(flush_interval)
        await flush_snapshot()

    async def ensure_flush_task() -> None:
        nonlocal flush_task
        if flush_task is None or flush_task.done():
            flush_task = asyncio.create_task(schedule_flush())

    async def settle_flush_task() -> None:
        nonlocal flush_task
        current = flush_task
        flush_task = None
        if current is None:
            return
        if current.done():
            try:
                await current
            except asyncio.CancelledError:
                pass
            return
        current.cancel()
        try:
            await current
        except asyncio.CancelledError:
            pass

    async def on_message(message: Any, _is_last: bool) -> None:
        nonlocal final_text_event, final_fallback_event
        if not isinstance(message, dict):
            return
        event = dict(message)
        event_type = str(event.get("type") or "").lower()
        text = render_event_text(event)
        if text:
            normalized = str(text).strip()
            if normalized and normalized not in seen_stream_items:
                seen_stream_items.add(normalized)
                pending_items.append(text)
                await ensure_flush_task()

        if event_type == "text":
            final_text_event = event
        elif event_type == "error":
            final_fallback_event = event

    run_task = asyncio.create_task(
        _run_action(
            service=service,
            chat_id=chat_id,
            action_name=action_name,
            runner_name=runner_name,
            message_text=message_text,
            execution_cwd=execution_cwd,
            on_message=on_message,
        ),
    )
    loop = asyncio.get_running_loop()
    deadline = (
        loop.time() + max_runtime
        if max_runtime is not None and max_runtime > 0
        else None
    )

    try:
        while True:
            if run_task.done():
                await flush_snapshot()
                await settle_flush_task()
                if response_queue.empty():
                    break
            if deadline is not None and not run_task.done():
                remaining = deadline - loop.time()
                if remaining <= 0:
                    await flush_snapshot()
                    await settle_flush_task()
                    while not response_queue.empty():
                        yield await response_queue.get()
                    await _cancel_running_acp_turn(
                        service=service,
                        chat_id=chat_id,
                        runner_name=runner_name,
                    )
                    run_task.cancel()
                    try:
                        await run_task
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.warning(
                            "ACP run_task ended with error after timeout "
                            "cancellation",
                            exc_info=True,
                        )
                    yield response_text(
                        (
                            f"ACP conversation with runner '{runner_name}' "
                            "reached the preset max runtime and was "
                            "interrupted. The ACP session is still open; "
                            "continue with "
                            f'delegate_external_agent(action="message", '
                            f'runner="{runner_name}", '
                            'message="continue") with higher max_runtime.'
                        ),
                        stream=True,
                        is_last=True,
                    )
                    return
            try:
                timeout = 0.1
                if deadline is not None and not run_task.done():
                    timeout = max(0.0, min(timeout, deadline - loop.time()))
                yield await asyncio.wait_for(
                    response_queue.get(),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                continue
    except asyncio.CancelledError:
        if not run_task.done():
            await _cancel_running_acp_turn(
                service=service,
                chat_id=chat_id,
                runner_name=runner_name,
            )
            run_task.cancel()
            try:
                await run_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.warning(
                    "ACP run_task ended with error after cancellation",
                    exc_info=True,
                )
        raise
    finally:
        await settle_flush_task()

    run_result = await run_task
    await flush_snapshot()
    while not response_queue.empty():
        yield await response_queue.get()

    suspended_permission = run_result.get("suspended_permission")
    if suspended_permission is not None:
        yield format_permission_suspended_response(
            suspended_permission=suspended_permission,
        )
        return

    event = final_text_event or final_fallback_event or run_result.get("event")
    yield format_final_assistant_response(
        runner_name=runner_name,
        execution_cwd=execution_cwd,
        final_event=event,
    )


async def _create_runner_state(
    *,
    action_name: str,
    runner_name: str,
    chat_id: str,
) -> _RunnerState:
    state = _RunnerState(
        agent_id=_current_agent_id(),
        chat_id=chat_id,
        runner=runner_name,
        action=action_name,
        status="running",
        created_at=time.time(),
        updated_at=time.time(),
    )
    await _set_runner_state(state)
    return state


async def _handle_immediate_action(
    *,
    action_name: str,
    runner_name: str,
) -> Optional[ToolResponse]:
    if action_name == "list":
        return await _format_acp_runner_states_response()
    if action_name == "status":
        if runner_name:
            return await _format_runner_status_response(runner_name)
        return await _format_all_runner_status_response()
    if action_name == "close":
        chat_id = _request_context_chat_id()
        service = _get_acp_service()
        existing = await service.get_session(
            chat_id=chat_id,
            agent=runner_name,
        )
        await service.close_chat_session(
            chat_id=chat_id,
            agent=runner_name,
        )
        return format_close_response(
            runner_name=runner_name,
            closed=existing is not None,
        )
    return None


async def _finalize_runner_state(
    *,
    service: Any,
    state: _RunnerState,
    chat_id: str,
    runner_name: str,
) -> None:
    pending_permission = await service.get_pending_permission(
        chat_id=chat_id,
        agent=runner_name,
    )
    if pending_permission is not None:
        await _set_runner_state_status(
            state,
            "permission_required",
            pending_permission=pending_permission,
        )
        return
    await _set_runner_state_status(state, "completed")


async def _set_failed_runner_state(
    state: Optional[_RunnerState],
    error: Exception,
) -> None:
    if state is not None:
        await _set_runner_state_status(state, "failed", error=str(error))


def _parse_timeout(
    max_runtime: Optional[float],
) -> tuple[Optional[float], Optional[str]]:
    try:
        timeout_seconds = None if max_runtime is None else float(max_runtime)
    except (TypeError, ValueError):
        return None, "Error: max_runtime must be a number in seconds."
    if timeout_seconds is not None and timeout_seconds <= 0:
        return None, "Error: max_runtime must be greater than 0."
    return timeout_seconds, None


async def _validate_runner_start(
    *,
    service: Any,
    state: _RunnerState,
    action_name: str,
    chat_id: str,
    runner_name: str,
) -> Optional[ToolResponse]:
    if action_name != "start":
        return None
    start_error = await _validate_start_request(
        service=service,
        chat_id=chat_id,
        runner_name=runner_name,
    )
    if start_error is None:
        return None
    await _set_runner_state_status(
        state,
        "failed",
        error=start_error,
    )
    return response_text(start_error, stream=True)


async def _cancel_runner_turn(
    *,
    service: Any,
    chat_id: str,
    action_name: str,
    runner_name: str,
) -> None:
    if (
        service is not None
        and chat_id
        and action_name in {"start", "message", "respond"}
    ):
        await _cancel_running_acp_turn(
            service=service,
            chat_id=chat_id,
            runner_name=runner_name,
        )


def _interrupted_response(runner_name: str) -> ToolResponse:
    return response_text(
        (
            f"ACP conversation with runner '{runner_name}' was "
            "interrupted by the user. The ACP session is still open; "
            "continue with "
            f'delegate_external_agent(action="message", '
            f'runner="{runner_name}", message="continue").'
        ),
        stream=True,
        is_last=True,
    )


async def _run_streaming_agent_action(
    *,
    action_name: str,
    runner_name: str,
    message_text: str,
    execution_cwd: Path,
    timeout_seconds: Optional[float],
) -> AsyncGenerator[ToolResponse, None]:
    service = None
    chat_id = ""
    state = None
    try:
        service = _get_acp_service()
        chat_id = _request_context_chat_id()
        state = await _create_runner_state(
            action_name=action_name,
            runner_name=runner_name,
            chat_id=chat_id,
        )
        start_error_response = await _validate_runner_start(
            service=service,
            state=state,
            action_name=action_name,
            chat_id=chat_id,
            runner_name=runner_name,
        )
        if start_error_response is not None:
            yield start_error_response
            return
        async for item in _stream_action_responses(
            service=service,
            chat_id=chat_id,
            action_name=action_name,
            runner_name=runner_name,
            message_text=message_text,
            execution_cwd=execution_cwd,
            max_runtime=timeout_seconds,
        ):
            await _append_runner_state_content(
                state,
                list(item.content or []),
            )
            yield item
        await _finalize_runner_state(
            service=service,
            state=state,
            chat_id=chat_id,
            runner_name=runner_name,
        )
    except asyncio.CancelledError:
        await _cancel_runner_turn(
            service=service,
            chat_id=chat_id,
            action_name=action_name,
            runner_name=runner_name,
        )
        if state is not None:
            await _set_runner_state_status(state, "cancelled")
        yield _interrupted_response(runner_name)
        raise
    except ImportError as e:
        await _set_failed_runner_state(state, e)
        yield response_text(f"ACP mode not available: {e}.", stream=True)
    except ValueError as e:
        await _set_failed_runner_state(state, e)
        yield response_text(f"Error: {e}", stream=True)
    except Exception as e:
        await _set_failed_runner_state(state, e)
        yield response_text(f"ACP execution error: {e}", stream=True)


async def delegate_external_agent(
    action: str,
    runner: str = "",
    message: str = "",
    cwd: str = "",
    max_runtime: Optional[float] = 300,
) -> ToolResponse | AsyncGenerator[ToolResponse, None]:
    # pylint: disable=too-many-return-statements
    """
    Open, talk to, respond to permissions for, or close an ACP agent session.

    1. Call delegate_external_agent(
        action="list", runner=""
        ) to list available external ACP runners and states.
    2. Call delegate_external_agent(
        action="status", runner=...
        ) to inspect the current runner session, task state, last response, or
        pending permission request.
    3. Call delegate_external_agent(
        action="start", runner=..., message=...
        ) to open a new conversation.
    4. Call delegate_external_agent(
        action="message", runner=..., message=...
        ) to keep talking.
    5. When a permission request appears, first ask the user which option to
       choose. Then call
       delegate_external_agent(
           action="respond", runner=..., message=...
        ) to respond to the pending permission request. You must strictly
        choose one option from the provided permission request, and the chosen
        option must come from the exact options shown in that request.
    6. Call delegate_external_agent(
        action="close", runner=...
        ) to end the conversation.

    Permission responses are always strict in the current ACP flow.

    Args:
        action (`str`):
            One of `list`, `status`, `start`, `message`, `respond`, or
            `close`. Use `list` to show enabled external ACP runners and
            states. Use `status` to inspect one runner or all runners,
            especially when `view_task` or `wait_task` can no longer find an
            async delegate task. Use `respond` only for a pending permission
            request. First ask the user which option to choose, then pass the
            exact selected option id in `message`.
        runner (`str`):
            ACP runner name, for example `qwen_code`, `opencode`,
            `claude_code` or `codex`. Not required for `action="list"` or
            `action="status"` without a specific runner.
        message (`str`):
            The message to send to the external agent. Used for `start` and
            `message`. For `respond`, pass the exact selected permission option
            id from the pending request. When `action="start"` and `message`
            is empty, a default `hi` is sent.
        cwd (`str`):
            Working directory for the agent. Defaults to the current workspace.
        max_runtime (`float | None`):
            Optional max runtime in seconds for a single ACP turn. Defaults to
            300 seconds. `None` means no timeout is applied. When the limit is
            reached, the tool sends ACP cancel for the current turn but keeps
            the ACP session open, so you can continue later with
            `delegate_external_agent(action="message", runner=..., `
            `message="continue")`.

    Returns:
        `AsyncGenerator[ToolResponse, None]`:
            Streaming tool responses for external agent progress, permission
            requests, status, or errors.
    """

    workspace_dir = _current_workspace_dir()
    execution_cwd = _resolve_execution_cwd(cwd, workspace_dir)
    action_name = str(action or "").strip().lower()
    runner_name = str(runner or "").strip()
    message_text = str(message or "")
    timeout_seconds, timeout_error = _parse_timeout(max_runtime)
    if timeout_error:
        return response_text(timeout_error)

    validation_error = _validate_action_inputs(
        action_name=action_name,
        runner_name=runner_name,
        message_text=message_text,
    )
    if validation_error:
        return response_text(validation_error)

    immediate_actions = {"list", "status", "close"}
    if action_name in immediate_actions:
        try:
            immediate_response = await _handle_immediate_action(
                action_name=action_name,
                runner_name=runner_name,
            )
            if immediate_response is not None:
                return immediate_response
        except ImportError as e:
            return response_text(f"ACP mode not available: {e}.")
        except ValueError as e:
            return response_text(f"Error: {e}")
        except Exception as e:
            return response_text(f"ACP execution error: {e}")

    return _run_streaming_agent_action(
        action_name=action_name,
        runner_name=runner_name,
        message_text=message_text,
        execution_cwd=execution_cwd,
        timeout_seconds=timeout_seconds,
    )
