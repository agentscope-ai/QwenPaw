# -*- coding: utf-8 -*-
"""Workspace-scoped third-party agent lifecycle and translation."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..schemas import (
    AgentResponse,
    MessageType,
    RunStatus,
)
from .base import HarnessAdapter
from .events import HarnessEvent, HarnessEventKind, HarnessProvider
from .registry import PROVIDER_CATALOG, create_adapter, get_provider
from .session import HarnessSessionBridge
from .streaming import TextStream, ToolStream

logger = logging.getLogger(__name__)


class HarnessRuntime:
    """Own adapters for one workspace and expose QwenPaw envelopes."""

    def __init__(
        self,
        workspace_dir: Path,
        session: Any = None,
        agent_id: str = "default",
    ) -> None:
        self._state_dir = workspace_dir / "harnesses"
        self._agent_id = agent_id
        self._adapters: dict[str, HarnessAdapter] = {}
        self._session_bridge = (
            HarnessSessionBridge(session) if session is not None else None
        )

    async def providers(self) -> list[HarnessProvider]:
        """Return the provider catalog with live status for Codex."""
        result: list[HarnessProvider] = []
        for item in PROVIDER_CATALOG:
            provider_id = item.id
            if item.coming_soon:
                result.append(
                    HarnessProvider(
                        id=provider_id,
                        name=item.name,
                        available=False,
                        coming_soon=True,
                    ),
                )
                continue
            provider = await self.adapter(provider_id).status()
            provider.capabilities = item.capabilities
            result.append(provider)
        return result

    def adapter(self, provider_id: str) -> HarnessAdapter:
        """Return one lazily-created supported adapter."""
        adapter = self._adapters.get(provider_id)
        if adapter is None:
            adapter = create_adapter(provider_id, self._state_dir)
            self._adapters[provider_id] = adapter
        return adapter

    async def stream(  # pylint: disable=too-many-branches,too-many-statements
        self,
        *,
        backend: str,
        request: Any,
        cwd: Path,
        settings: dict[str, Any] | None = None,
    ) -> AsyncGenerator[Any, None]:
        """Run a harness turn and emit the established QwenPaw protocol."""
        adapter = self.adapter(backend)
        session_id = str(getattr(request, "session_id", "") or "default")
        prompt = self._prompt_from_request(request)
        command, arguments = self._parse_command(prompt)
        response = AgentResponse(
            id=f"response_{uuid.uuid4().hex}",
            output=[],
            status=RunStatus.Created,
            created_at=datetime.now(timezone.utc).isoformat(
                timespec="seconds",
            ),
        )
        response.object = "response"
        response.session_id = session_id
        sequence = 0

        def tagged(value: Any) -> Any:
            nonlocal sequence
            sequence += 1
            value.sequence_number = sequence
            return value

        yield tagged(response.model_copy(deep=True))
        response.status = RunStatus.InProgress
        yield tagged(response.model_copy(deep=True))

        text_stream = TextStream(response)
        tool_stream = ToolStream(response)
        error_text = ""
        cancelled = False
        task_cancelled = False

        try:
            if command in {"new", "clear"}:
                await adapter.reset_session(session_id)
                events = [
                    HarnessEvent(
                        kind=HarnessEventKind.TEXT_DELTA,
                        text="Started a fresh conversation.",
                    ),
                    HarnessEvent(kind=HarnessEventKind.COMPLETED),
                ]
                event_stream = self._iter_events(events)
            elif command:
                provider = get_provider(backend)
                supported = {
                    item.name for item in provider.capabilities.commands
                }
                if command not in supported:
                    raise ValueError(
                        f"Unsupported {provider.name} command: /{command}",
                    )
                events = await adapter.run_command(
                    session_id=session_id,
                    command=command,
                    arguments=arguments,
                    cwd=cwd,
                    settings=settings or {},
                )
                event_stream = self._iter_events(events)
            else:
                event_stream = adapter.run_turn(
                    session_id=session_id,
                    prompt=prompt,
                    cwd=cwd,
                    settings=settings or {},
                )
            async for event in event_stream:
                if event.kind == HarnessEventKind.TEXT_DELTA:
                    for item in text_stream.push(
                        MessageType.MESSAGE,
                        event.text,
                    ):
                        yield tagged(item)
                elif event.kind == HarnessEventKind.REASONING_DELTA:
                    for item in text_stream.push(
                        MessageType.REASONING,
                        event.text,
                    ):
                        yield tagged(item)
                elif event.kind == HarnessEventKind.TOOL_STARTED:
                    for item in text_stream.finish():
                        yield tagged(item)
                    for item in tool_stream.start(event):
                        yield tagged(item)
                elif event.kind == HarnessEventKind.TOOL_PROGRESS:
                    for item in tool_stream.progress(event):
                        yield tagged(item)
                elif event.kind == HarnessEventKind.TOOL_COMPLETED:
                    for item in tool_stream.complete(event):
                        yield tagged(item)
                elif event.kind == HarnessEventKind.ERROR:
                    error_text = event.text
                elif event.kind == HarnessEventKind.CANCELLED:
                    cancelled = True
        except asyncio.CancelledError:
            cancelled = True
            task_cancelled = True
        except Exception as exc:
            error_text = str(exc)

        for item in text_stream.finish():
            yield tagged(item)

        clear_history = command in {"new", "clear"}
        if clear_history and response.output:
            response.output[-1].metadata = {
                **dict(response.output[-1].metadata or {}),
                "clear_history": True,
            }

        if error_text:
            response.status = RunStatus.Failed
            response.error = {"code": "harness_error", "message": error_text}
        elif cancelled:
            response.status = RunStatus.Cancelled
        else:
            response.status = RunStatus.Completed
        response.completed_at = datetime.now(timezone.utc).isoformat(
            timespec="seconds",
        )
        if self._session_bridge is not None and clear_history:
            try:
                await self._session_bridge.clear(
                    session_id=session_id,
                    user_id=str(
                        getattr(request, "user_id", "") or session_id,
                    ),
                    channel=str(getattr(request, "channel", "") or ""),
                )
            except Exception:
                logger.warning(
                    "Failed to clear third-party session %s",
                    session_id,
                    exc_info=True,
                )
        elif self._session_bridge is not None:
            try:
                await self._session_bridge.append_turn(
                    request=request,
                    response=response,
                    backend=backend,
                )
            except Exception:
                logger.warning(
                    "Failed to persist third-party session %s",
                    session_id,
                    exc_info=True,
                )
        if task_cancelled:
            raise asyncio.CancelledError
        yield tagged(response)

    async def stop(self) -> None:
        """Stop every initialized adapter."""
        for adapter in tuple(self._adapters.values()):
            await adapter.stop()
        self._adapters.clear()

    async def hydrate_session(
        self,
        *,
        backend: str,
        session_id: str,
        user_id: str,
        channel: str,
    ) -> None:
        """Recover an unmaterialized provider thread into QwenPaw."""
        if self._session_bridge is None:
            return
        if await self._session_bridge.has_history(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        ):
            return
        history = await self.adapter(backend).history(session_id)
        await self._session_bridge.hydrate(
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            backend=backend,
            history=history,
        )

    @staticmethod
    def _prompt_from_request(request: Any) -> str:
        parts: list[str] = []
        for message in getattr(request, "input", None) or []:
            for content in getattr(message, "content", None) or []:
                if isinstance(content, str):
                    parts.append(content)
                    continue
                text = getattr(content, "text", None)
                if text:
                    parts.append(str(text))
        prompt = "\n".join(parts).strip()
        if not prompt:
            raise ValueError("Third-party agent requests require text input")
        return prompt

    @staticmethod
    def _parse_command(prompt: str) -> tuple[str, str]:
        if not prompt.startswith("/"):
            return "", ""
        first_line = prompt.splitlines()[0].strip()
        command, _, arguments = first_line[1:].partition(" ")
        return command.lower(), arguments.strip()

    @staticmethod
    async def _iter_events(
        events: list[Any],
    ) -> AsyncGenerator[Any, None]:
        for event in events:
            yield event


__all__ = ["HarnessRuntime"]
