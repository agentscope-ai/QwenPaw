# -*- coding: utf-8 -*-
"""Built-in tool for delegating tasks to external agent runners.

Uses the ACP protocol.
"""

import asyncio
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from agentscope.tool import ToolResponse

from ...config import load_config
from ...config.context import get_current_workspace_dir
from ...constant import WORKING_DIR
from ..acp.tool_adapter import (
    event_to_stream_response,
    format_close_response,
    format_permission_suspended_response,
    format_run_completion_response,
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
    from ...config.config import ACPConfig
    from ..acp import get_acp_service, init_acp_service

    config = load_config()
    acp_config = getattr(config, "acp", None) or ACPConfig()
    service = get_acp_service()
    if service is None or getattr(service, "config", None) != acp_config:
        service = init_acp_service(acp_config)
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
        return (
            "Error: action must be one of: " "start, message, respond, close."
        )
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
        existing = await _get_bound_session(
            service,
            chat_id=chat_id,
            runner_name=runner_name,
        )
        if existing is not None:
            await service.close_chat_session(
                chat_id=existing.chat_id,
                agent=existing.agent,
            )
        return await service.run_turn(
            chat_id=chat_id,
            agent=runner_name,
            prompt_blocks=[{"type": "text", "text": message_text or "hi"}],
            cwd=str(execution_cwd),
            on_message=on_message,
        )

    if action_name == "message":
        existing = await _get_bound_session(
            service,
            chat_id=chat_id,
            runner_name=runner_name,
        )
        if existing is None:
            raise ValueError(
                "no bound ACP session found for runner "
                f"'{runner_name}' in current chat; call "
                "delegate_external_agent with action='start' first",
            )
        return await service.run_turn(
            chat_id=chat_id,
            agent=runner_name,
            prompt_blocks=[{"type": "text", "text": message_text}],
            cwd=str(execution_cwd),
            on_message=on_message,
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
        selected_option_id = message_text.strip()
        valid_option_ids = {
            str(opt.get("optionId") or opt.get("id") or "").strip()
            for opt in suspended_permission.options
            if isinstance(opt, dict)
        }
        valid_option_ids.discard("")
        if selected_option_id not in valid_option_ids:
            raise ValueError(
                "respond requires the exact selected permission "
                "option id from the provided options.",
            )
        return await service.resume_permission(
            acp_session_id=bound_session.acp_session_id,
            option_id=selected_option_id,
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
    header_sent = False
    final_event: Optional[dict[str, Any]] = None

    async def on_message(message: Any, _is_last: bool) -> None:
        nonlocal header_sent, final_event
        if not isinstance(message, dict):
            return
        event = dict(message)
        if str(event.get("type") or "").lower() in {
            "text",
            "error",
            "permission_request",
        }:
            final_event = event
        response = event_to_stream_response(
            event,
            runner_name=runner_name,
            execution_cwd=execution_cwd,
            include_header=not header_sent,
        )
        if response is None:
            return
        header_sent = True
        await response_queue.put(response)

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

    while True:
        if run_task.done() and response_queue.empty():
            break
        try:
            yield await asyncio.wait_for(response_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue

    run_result = await run_task
    suspended_permission = run_result.get("suspended_permission")
    if suspended_permission is not None:
        yield format_permission_suspended_response(
            suspended_permission=suspended_permission,
        )
        return

    yield format_run_completion_response(
        runner_name=runner_name,
        execution_cwd=execution_cwd,
        final_event=final_event,
    )


async def delegate_external_agent(
    action: str = "",
    runner: str = "",
    message: str = "",
    cwd: str = "",
) -> AsyncGenerator[ToolResponse, None]:
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
    action_name = (action or "").strip().lower()
    runner_name = (runner or "").strip()
    message_text = (message or "").strip()

    validation_error = _validate_action_inputs(
        action_name=action_name,
        runner_name=runner_name,
        message_text=message_text,
    )
    if validation_error is not None:
        yield response_text(validation_error, stream=True)
        return

    execution_cwd = _resolve_execution_cwd(cwd, _current_workspace_dir())

    try:
        service = _get_acp_service()
        chat_id = _request_context_chat_id()

        if action_name == "close":
            existing = await _get_bound_session(
                service,
                chat_id=chat_id,
                runner_name=runner_name,
            )
            if existing is not None:
                await service.close_chat_session(
                    chat_id=existing.chat_id,
                    agent=existing.agent,
                )
            yield format_close_response(
                runner_name=runner_name,
                closed=existing is not None,
            )
            return

        async for response in _stream_action_responses(
            service=service,
            chat_id=chat_id,
            action_name=action_name,
            runner_name=runner_name,
            message_text=message_text,
            execution_cwd=execution_cwd,
        ):
            yield response

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
