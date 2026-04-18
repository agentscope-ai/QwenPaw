# -*- coding: utf-8 -*-
"""Built-in tool for delegating tasks to external agent runners.

Uses the ACP protocol.
"""

import asyncio
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

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


def _current_workspace_dir() -> Path:
    return (get_current_workspace_dir() or Path(WORKING_DIR)).expanduser()


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
    from ...config.config import load_agent_config
    from ..acp import get_acp_service, init_acp_service
    from ..acp.core import ACPConfig

    agent_id = get_current_agent_id()
    agent_config = load_agent_config(agent_id)
    acp_config = agent_config.acp or ACPConfig()
    service = get_acp_service(agent_id)
    if service is None or getattr(service, "config", None) != acp_config:
        service = init_acp_service(agent_id, acp_config)
    return service


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
    if not runner_name:
        return "Error: runner is empty."
    if action_name not in {"start", "message", "respond", "close"}:
        return "Error: action must be one of: start, message, respond, close."
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


async def _get_bound_session(
    service: Any,
    *,
    chat_id: str,
    runner_name: str,
) -> Optional[Any]:
    return await service.get_session(chat_id=chat_id, agent=runner_name)


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
) -> AsyncGenerator[ToolResponse, None]:
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
        snapshot = [item.strip() for item in pending_items if item and item.strip()]
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
        try:
            await asyncio.sleep(flush_interval)
            await flush_snapshot()
        except asyncio.CancelledError:
            raise

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

    try:
        while True:
            if run_task.done():
                await flush_snapshot()
                await settle_flush_task()
                if response_queue.empty():
                    break
            try:
                yield await asyncio.wait_for(response_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
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


async def delegate_external_agent(
    action: str,
    runner: str,
    message: str = "",
    cwd: str = "",
) -> ToolResponse | AsyncGenerator[ToolResponse, None]:
    """
    Open, talk to, respond to permissions for, or close an ACP agent session.

    1. Call delegate_external_agent(
        action="start", runner=..., message=...
        ) to open a new conversation.
    2. Call delegate_external_agent(
        action="message", runner=..., message=...
        ) to keep talking.
    3. When a permission request appears, first ask the user which option to
       choose. Then call
       delegate_external_agent(
           action="respond", runner=..., message=...
        ) to respond to the pending permission request. You must strictly
        choose one option from the provided permission request, and the chosen
        option must come from the exact options shown in that request.
    4. Call delegate_external_agent(
        action="close", runner=...
        ) to end the conversation.

    Permission responses are always strict in the current ACP flow.

    Args:
        action (`str`):
            One of `start`, `message`, `respond`, or `close`. Use `respond`
            only for a pending permission request. First ask the user which
            option to choose, then pass the exact selected option id in
            `message`.
        runner (`str`):
            ACP runner name, for example `qwen_code`, `opencode`,
            `claude_code` or `codex`.
        message (`str`):
            The message to send to the external agent. Used for `start` and
            `message`. For `respond`, pass the exact selected permission option
            id from the pending request. When `action="start"` and `message`
            is empty, a default `hi` is sent.
        cwd (`str`):
            Working directory for the agent. Defaults to the current workspace.

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

    validation_error = _validate_action_inputs(
        action_name=action_name,
        runner_name=runner_name,
        message_text=message_text,
    )
    if validation_error:
        return response_text(validation_error)

    if action_name == "close":
        try:
            chat_id = _request_context_chat_id()
            service = _get_acp_service()
            existing = await service.get_session(chat_id=chat_id, agent=runner_name)
            await service.close_chat_session(chat_id=chat_id, agent=runner_name)
            return format_close_response(
                runner_name=runner_name,
                closed=existing is not None,
            )
        except ImportError as e:
            return response_text(f"ACP mode not available: {e}.")
        except ValueError as e:
            return response_text(f"Error: {e}")
        except Exception as e:
            return response_text(f"ACP execution error: {e}")

    async def _runner() -> AsyncGenerator[ToolResponse, None]:
        try:
            service = _get_acp_service()
            chat_id = _request_context_chat_id()
            async for item in _stream_action_responses(
                service=service,
                chat_id=chat_id,
                action_name=action_name,
                runner_name=runner_name,
                message_text=message_text,
                execution_cwd=execution_cwd,
            ):
                yield item
        except asyncio.CancelledError:
            yield response_text(
                "delegate_external_agent streaming interrupted.",
                stream=True,
                is_last=True,
            )
            raise
        except ImportError as e:
            yield response_text(f"ACP mode not available: {e}.", stream=True)
        except ValueError as e:
            yield response_text(f"Error: {e}", stream=True)
        except Exception as e:
            yield response_text(f"ACP execution error: {e}", stream=True)

    return _runner()
