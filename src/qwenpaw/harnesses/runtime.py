# -*- coding: utf-8 -*-
"""Workspace-scoped third-party agent lifecycle and translation."""

from __future__ import annotations

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
from .events import HarnessEventKind, HarnessProvider
from .registry import PROVIDER_CATALOG, create_adapter
from .streaming import TextStream, ToolStream


class HarnessRuntime:
    """Own adapters for one workspace and expose QwenPaw envelopes."""

    def __init__(self, workspace_dir: Path) -> None:
        self._state_dir = workspace_dir / "harnesses"
        self._adapters: dict[str, HarnessAdapter] = {}

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
            result.append(await self.adapter(provider_id).status())
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
    ) -> AsyncGenerator[Any, None]:
        """Run a harness turn and emit the established QwenPaw protocol."""
        adapter = self.adapter(backend)
        session_id = str(getattr(request, "session_id", "") or "default")
        prompt = self._prompt_from_request(request)
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

        try:
            async for event in adapter.run_turn(
                session_id=session_id,
                prompt=prompt,
                cwd=cwd,
            ):
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
        except Exception as exc:
            error_text = str(exc)

        for item in text_stream.finish():
            yield tagged(item)

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
        yield tagged(response)

    async def stop(self) -> None:
        """Stop every initialized adapter."""
        for adapter in tuple(self._adapters.values()):
            await adapter.stop()
        self._adapters.clear()

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


__all__ = ["HarnessRuntime"]
