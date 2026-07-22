# -*- coding: utf-8 -*-
"""Codex implementation of the third-party agent adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ...utils.atomic_io import write_json_atomic
from ..base import HarnessAdapter
from ..events import HarnessEvent, HarnessEventKind, HarnessProvider
from .app_server import CodexAppServerClient, CodexAppServerError


class CodexAdapter(HarnessAdapter):
    """Run Codex threads through one workspace-scoped app-server."""

    def __init__(
        self,
        state_dir: Path,
        client: CodexAppServerClient | None = None,
    ) -> None:
        self._state_dir = state_dir
        self._session_path = state_dir / "codex_sessions.json"
        self._client = client or CodexAppServerClient()
        self._session_lock = asyncio.Lock()
        self._threads = self._load_threads()
        self._loaded_threads: set[str] = set()

    async def status(self) -> HarnessProvider:
        """Return Codex installation and ChatGPT account status."""
        if not self._client.installed:
            return HarnessProvider(
                id="codex",
                name="Codex",
                available=True,
                installed=False,
            )
        try:
            await self._client.start()
            result = await self._client.request(
                "account/read",
                {"refreshToken": False},
            )
            account = result.get("account") if result else None
            public_account = None
            if account:
                public_account = {
                    key: account.get(key)
                    for key in ("type", "email", "planType")
                    if key in account
                }
            return HarnessProvider(
                id="codex",
                name="Codex",
                available=True,
                installed=True,
                authenticated=(account or {}).get("type") == "chatgpt",
                account=public_account,
            )
        except CodexAppServerError as exc:
            return HarnessProvider(
                id="codex",
                name="Codex",
                available=True,
                installed=True,
                error=str(exc),
            )

    async def start_login(self, device_code: bool = False) -> dict[str, Any]:
        """Start Codex-managed ChatGPT OAuth."""
        await self._client.start()
        login_type = "chatgptDeviceCode" if device_code else "chatgpt"
        params: dict[str, Any] = {"type": login_type}
        if not device_code:
            params.update(
                {
                    "useHostedLoginSuccessPage": True,
                    "appBrand": "codex",
                },
            )
        result = await self._client.request("account/login/start", params)
        return dict(result or {})

    async def logout(self) -> None:
        """Log out through Codex without handling credentials directly."""
        await self._client.start()
        await self._client.request("account/logout", {})

    async def run_turn(  # pylint: disable=invalid-overridden-method
        self,
        *,
        session_id: str,
        prompt: str,
        cwd: Path,
    ) -> AsyncIterator[HarnessEvent]:
        """Start or resume a Codex thread and stream one turn."""
        await self._client.start()
        thread_id = await self._thread_for_session(session_id, cwd)
        queue = self._client.subscribe()
        turn_id = ""
        try:
            result = await self._client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "cwd": str(cwd),
                    "input": [{"type": "text", "text": prompt}],
                },
            )
            turn_id = str((result or {}).get("turn", {}).get("id", ""))
            while True:
                message = await queue.get()
                params = message.get("params") or {}
                if params.get("threadId") != thread_id:
                    continue
                notification_turn_id = self._notification_turn_id(message)
                if turn_id and notification_turn_id not in (None, turn_id):
                    continue
                event = self._convert_notification(message)
                if event is not None:
                    yield event
                if message.get("method") == "turn/completed":
                    break
        except asyncio.CancelledError:
            if turn_id:
                await self._interrupt_turn(thread_id, turn_id)
            raise
        finally:
            self._client.unsubscribe(queue)

    async def stop(self) -> None:
        """Stop the workspace Codex process."""
        await self._client.stop()

    async def _thread_for_session(self, session_id: str, cwd: Path) -> str:
        async with self._session_lock:
            thread_id = self._threads.get(session_id)
            if thread_id and thread_id not in self._loaded_threads:
                try:
                    await self._client.request(
                        "thread/resume",
                        {"threadId": thread_id},
                    )
                    self._loaded_threads.add(thread_id)
                    return thread_id
                except CodexAppServerError:
                    self._threads.pop(session_id, None)
            if thread_id:
                return thread_id
            result = await self._client.request(
                "thread/start",
                {
                    "cwd": str(cwd),
                    "sandbox": "workspace-write",
                    "approvalPolicy": "never",
                },
            )
            thread_id = str((result or {}).get("thread", {}).get("id", ""))
            if not thread_id:
                raise CodexAppServerError("Codex did not return a thread id")
            self._threads[session_id] = thread_id
            self._loaded_threads.add(thread_id)
            write_json_atomic(self._session_path, self._threads)
            return thread_id

    def _load_threads(self) -> dict[str, str]:
        if not self._session_path.is_file():
            return {}
        try:
            payload = json.loads(self._session_path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): str(value)
            for key, value in payload.items()
            if key and value
        }

    async def _interrupt_turn(self, thread_id: str, turn_id: str) -> None:
        try:
            await self._client.request(
                "turn/interrupt",
                {"threadId": thread_id, "turnId": turn_id},
            )
        except CodexAppServerError:
            return

    @staticmethod
    def _notification_turn_id(message: dict[str, Any]) -> str | None:
        params = message.get("params") or {}
        turn_id = params.get("turnId")
        if turn_id:
            return str(turn_id)
        turn = params.get("turn") or {}
        if turn.get("id"):
            return str(turn["id"])
        return None

    @staticmethod
    # pylint: disable=too-many-return-statements
    def _convert_notification(
        message: dict[str, Any],
    ) -> HarnessEvent | None:
        method = message.get("method")
        params = message.get("params") or {}
        if method == "item/agentMessage/delta":
            return HarnessEvent(
                kind=HarnessEventKind.TEXT_DELTA,
                text=str(params.get("delta") or ""),
                item_id=str(params.get("itemId") or ""),
            )
        if method == "item/reasoning/textDelta":
            return HarnessEvent(
                kind=HarnessEventKind.REASONING_DELTA,
                text=str(params.get("delta") or ""),
                item_id=str(params.get("itemId") or ""),
            )
        if method == "item/started":
            item = params.get("item") or {}
            item_type = str(item.get("type") or "")
            if item_type in {"commandExecution", "mcpToolCall"}:
                return HarnessEvent(
                    kind=HarnessEventKind.TOOL_STARTED,
                    item_id=str(item.get("id") or ""),
                    tool_name=item_type,
                    data=item,
                )
        if method == "item/completed":
            item = params.get("item") or {}
            item_type = str(item.get("type") or "")
            if item_type in {"commandExecution", "mcpToolCall"}:
                return HarnessEvent(
                    kind=HarnessEventKind.TOOL_COMPLETED,
                    item_id=str(item.get("id") or ""),
                    tool_name=item_type,
                    data=item,
                )
        if method == "error" and not params.get("willRetry", False):
            error = params.get("error") or {}
            text = str(error.get("message") or "Codex turn failed")
            return HarnessEvent(kind=HarnessEventKind.ERROR, text=text)
        if method == "turn/completed":
            turn = params.get("turn") or {}
            status = str(turn.get("status") or "completed")
            if status == "failed":
                error = turn.get("error") or {}
                text = str(error.get("message") or "Codex turn failed")
                return HarnessEvent(kind=HarnessEventKind.ERROR, text=text)
            if status in {"cancelled", "interrupted"}:
                return HarnessEvent(kind=HarnessEventKind.CANCELLED)
            return HarnessEvent(kind=HarnessEventKind.COMPLETED)
        return None


__all__ = ["CodexAdapter"]
