# -*- coding: utf-8 -*-
"""Codex implementation of the third-party agent adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from ...app.approvals import (
    ApprovalRequestSummary,
    get_approval_service,
)
from ...security.tool_guard.approval import ApprovalDecision
from ...utils.io_utils import read_json, write_json_atomic_async
from ..base import HarnessAdapter
from ..events import (
    HarnessEvent,
    HarnessEventKind,
    HarnessHistoryItem,
    HarnessHistoryKind,
    HarnessModel,
    HarnessProvider,
)
from .app_server import CodexAppServerClient, CodexAppServerError

_TOOL_ITEM_TYPES = {
    "collabAgentToolCall",
    "commandExecution",
    "dynamicToolCall",
    "fileChange",
    "imageGeneration",
    "imageView",
    "mcpToolCall",
    "webSearch",
}

_TOOL_PROGRESS_METHODS = {
    "item/commandExecution/outputDelta": "delta",
    "item/fileChange/outputDelta": "delta",
    "item/mcpToolCall/progress": "message",
}


class CodexAdapter(HarnessAdapter):
    """Run Codex threads through one workspace-scoped app-server."""

    def __init__(
        self,
        state_dir: Path,
        client: CodexAppServerClient | None = None,
        binary: str | None = None,
    ) -> None:
        self._state_dir = state_dir
        self._session_path = state_dir / "codex_sessions.json"
        self._client = client or CodexAppServerClient(binary=binary)
        self._session_lock = asyncio.Lock()
        self._threads = self._load_threads()
        self._loaded_threads: set[str] = set()
        self._thread_contexts: dict[str, dict[str, Any]] = {}
        if hasattr(self._client, "set_server_request_handler"):
            self._client.set_server_request_handler(
                self._handle_server_request,
            )

    async def status(self) -> HarnessProvider:
        """Return Codex installation and local account status."""
        resolution = getattr(self._client, "binary_resolution", None)
        runtime_path = str(resolution.path) if resolution is not None else None
        runtime_source = resolution.source if resolution is not None else None
        if not self._client.installed:
            return HarnessProvider(
                id="codex",
                name="Codex",
                available=True,
                installed=False,
                runtime_path=runtime_path,
                runtime_source=runtime_source,
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
                authenticated=bool(account),
                account=public_account,
                runtime_path=runtime_path,
                runtime_source=runtime_source,
            )
        except CodexAppServerError as exc:
            return HarnessProvider(
                id="codex",
                name="Codex",
                available=True,
                installed=True,
                error=str(exc),
                runtime_path=runtime_path,
                runtime_source=runtime_source,
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

    async def models(self) -> list[HarnessModel]:
        """Return the complete Codex model picker catalog."""
        await self._client.start()
        models: list[HarnessModel] = []
        cursor: str | None = None
        while True:
            result = await self._client.request(
                "model/list",
                {"cursor": cursor, "includeHidden": False},
            )
            for item in (result or {}).get("data", []):
                efforts = [
                    str(option.get("reasoningEffort"))
                    for option in item.get("supportedReasoningEfforts", [])
                    if option.get("reasoningEffort")
                ]
                models.append(
                    HarnessModel(
                        id=str(item.get("model") or item.get("id") or ""),
                        name=str(
                            item.get("displayName")
                            or item.get("model")
                            or item.get("id")
                            or "",
                        ),
                        description=str(item.get("description") or ""),
                        is_default=bool(item.get("isDefault")),
                        reasoning_efforts=efforts,
                        default_reasoning_effort=(
                            str(item["defaultReasoningEffort"])
                            if item.get("defaultReasoningEffort")
                            else None
                        ),
                    ),
                )
            cursor = (result or {}).get("nextCursor")
            if not cursor:
                return [model for model in models if model.id]

    async def history(self, session_id: str) -> list[HarnessHistoryItem]:
        """Read the lossy persisted Codex thread for recovery."""
        thread_id = self._threads.get(session_id)
        if not thread_id:
            return []
        await self._client.start()
        result = await self._client.request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": True},
        )
        history: list[HarnessHistoryItem] = []
        for turn in (result or {}).get("thread", {}).get("turns", []):
            for item in turn.get("items", []):
                history.extend(self._history_item(item))
        return history

    async def run_turn(  # pylint: disable=invalid-overridden-method
        self,
        *,
        session_id: str,
        prompt: str,
        cwd: Path,
        settings: dict[str, Any],
    ) -> AsyncIterator[HarnessEvent]:
        """Start or resume a Codex thread and stream one turn."""
        await self._client.start()
        thread_id = await self._thread_for_session(
            session_id,
            cwd,
            settings,
        )
        self._thread_contexts[thread_id] = {
            "session_id": session_id,
            **dict(settings.get("_request_context") or {}),
        }
        queue = self._client.subscribe()
        turn_id = ""
        try:
            params = {
                "threadId": thread_id,
                "cwd": str(cwd),
                "input": [{"type": "text", "text": prompt}],
            }
            if settings.get("model"):
                params["model"] = settings["model"]
            if settings.get("reasoning_effort"):
                params["effort"] = settings["reasoning_effort"]
            params["summary"] = settings.get("reasoning_summary") or "auto"
            if settings.get("approval_policy"):
                params["approvalPolicy"] = settings["approval_policy"]
            sandbox_policy = self._sandbox_policy(settings.get("sandbox"))
            if sandbox_policy:
                params["sandboxPolicy"] = sandbox_policy
            result = await self._client.request("turn/start", params)
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

    async def run_command(
        self,
        *,
        session_id: str,
        command: str,
        arguments: str,
        cwd: Path,
        settings: dict[str, Any],
    ) -> list[HarnessEvent]:
        """Run one Codex app-server command."""
        del arguments
        await self._client.start()
        thread_id = await self._thread_for_session(session_id, cwd, settings)
        if command == "compact":
            await self._client.request(
                "thread/compact/start",
                {"threadId": thread_id},
            )
            text = "Codex context compacted."
        elif command == "review":
            return await self._run_review(
                thread_id,
            )
        elif command == "skills":
            result = await self._client.request(
                "skills/list",
                {"cwds": [str(cwd)], "forceReload": False},
            )
            text = self._format_skills(result)
        elif command == "status":
            provider = await self.status()
            model = settings.get("model") or "default"
            connection = "connected" if provider.authenticated else "offline"
            text = f"Codex: {connection}" f"\nModel: {model}\nWorkspace: {cwd}"
        else:
            return await super().run_command(
                session_id=session_id,
                command=command,
                arguments="",
                cwd=cwd,
                settings=settings,
            )
        return [
            HarnessEvent(kind=HarnessEventKind.TEXT_DELTA, text=text),
            HarnessEvent(kind=HarnessEventKind.COMPLETED),
        ]

    async def reset_session(self, session_id: str) -> None:
        """Start a fresh Codex thread on the next turn."""
        async with self._session_lock:
            thread_id = self._threads.pop(session_id, None)
            if thread_id:
                self._loaded_threads.discard(thread_id)
                self._thread_contexts.pop(thread_id, None)
            await write_json_atomic_async(
                self._session_path,
                self._threads,
            )

    async def stop(self) -> None:
        """Stop the workspace Codex process."""
        await self._client.stop()

    async def _thread_for_session(
        self,
        session_id: str,
        cwd: Path,
        settings: dict[str, Any],
    ) -> str:
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
            params = {
                "cwd": str(cwd),
                "sandbox": settings.get("sandbox") or "workspace-write",
                "approvalPolicy": (
                    settings.get("approval_policy") or "on-request"
                ),
            }
            if settings.get("model"):
                params["model"] = settings["model"]
            result = await self._client.request("thread/start", params)
            thread_id = str((result or {}).get("thread", {}).get("id", ""))
            if not thread_id:
                raise CodexAppServerError("Codex did not return a thread id")
            self._threads[session_id] = thread_id
            self._loaded_threads.add(thread_id)
            await write_json_atomic_async(
                self._session_path,
                self._threads,
            )
            return thread_id

    async def _handle_server_request(
        self,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        method = str(message.get("method") or "")
        if method not in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
        }:
            return {"decision": "decline"}
        params = dict(message.get("params") or {})
        context = self._thread_contexts.get(
            str(params.get("threadId") or ""),
            {},
        )
        session_id = str(context.get("session_id") or "default")
        command = str(params.get("command") or "")
        is_command = "commandExecution" in method
        name = "Codex command" if is_command else "Codex file change"
        detail = command or str(params.get("reason") or "")
        summary = ApprovalRequestSummary(
            source_type="codex",
            name=name,
            severity="high" if is_command else "medium",
            result_summary=detail or name,
            payload={
                "provider": "codex",
                "provider_item_id": params.get("itemId"),
                "command": command,
                "cwd": params.get("cwd"),
            },
        )
        service = get_approval_service()
        pending = await service.create_pending_summary(
            session_id=session_id,
            root_session_id=session_id,
            owner_agent_id=str(context.get("agent_id") or "default"),
            user_id=str(context.get("user_id") or "default"),
            channel=str(context.get("channel") or "console"),
            agent_id=str(context.get("agent_id") or "default"),
            summary=summary,
        )
        decision = await service.wait_for_approval(
            pending.request_id,
            pending.timeout_seconds,
        )
        return {
            "decision": (
                "accept"
                if decision == ApprovalDecision.APPROVED
                else "decline"
            ),
        }

    async def _run_review(self, thread_id: str) -> list[HarnessEvent]:
        queue = self._client.subscribe()
        try:
            result = await self._client.request(
                "review/start",
                {
                    "threadId": thread_id,
                    "target": {"type": "uncommittedChanges"},
                },
            )
            review_thread_id = str(
                (result or {}).get("reviewThreadId") or thread_id,
            )
            turn_id = str((result or {}).get("turn", {}).get("id") or "")
            events: list[HarnessEvent] = []
            while True:
                message = await queue.get()
                params = message.get("params") or {}
                if params.get("threadId") != review_thread_id:
                    continue
                notification_turn_id = self._notification_turn_id(message)
                if turn_id and notification_turn_id not in (None, turn_id):
                    continue
                event = self._convert_notification(message)
                if event is not None:
                    events.append(event)
                if message.get("method") == "turn/completed":
                    return events
        finally:
            self._client.unsubscribe(queue)

    @staticmethod
    def _sandbox_policy(value: Any) -> dict[str, Any] | None:
        policies = {
            "read-only": {"type": "readOnly"},
            "workspace-write": {"type": "workspaceWrite"},
            "danger-full-access": {"type": "dangerFullAccess"},
        }
        return policies.get(str(value or ""))

    @staticmethod
    def _format_skills(result: Any) -> str:
        entries: list[str] = []
        for group in (result or {}).get("data", []):
            for skill in group.get("skills", []):
                name = skill.get("name")
                if name:
                    entries.append(f"- {name}")
        if not entries:
            return "No Codex skills are available in this workspace."
        return "Codex skills:\n" + "\n".join(entries)

    def _load_threads(self) -> dict[str, str]:
        try:
            payload = read_json(self._session_path)
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
    # pylint: disable=too-many-branches,too-many-return-statements
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
        if method == "item/reasoning/summaryTextDelta":
            return HarnessEvent(
                kind=HarnessEventKind.REASONING_DELTA,
                text=str(params.get("delta") or ""),
                item_id=str(params.get("itemId") or ""),
                data={"source": "summary"},
            )
        if method == "item/plan/delta":
            return HarnessEvent(
                kind=HarnessEventKind.REASONING_DELTA,
                text=str(params.get("delta") or ""),
                item_id=str(params.get("itemId") or ""),
                data={"source": "plan"},
            )
        progress_field = _TOOL_PROGRESS_METHODS.get(str(method))
        if progress_field:
            return HarnessEvent(
                kind=HarnessEventKind.TOOL_PROGRESS,
                text=str(params.get(progress_field) or ""),
                item_id=str(params.get("itemId") or ""),
            )
        if method == "item/started":
            item = params.get("item") or {}
            item_type = str(item.get("type") or "")
            if item_type in _TOOL_ITEM_TYPES:
                return CodexAdapter._tool_event(
                    HarnessEventKind.TOOL_STARTED,
                    item,
                )
        if method == "item/completed":
            item = params.get("item") or {}
            item_type = str(item.get("type") or "")
            if item_type in _TOOL_ITEM_TYPES:
                return CodexAdapter._tool_event(
                    HarnessEventKind.TOOL_COMPLETED,
                    item,
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

    @staticmethod
    def _tool_event(
        kind: HarnessEventKind,
        item: dict[str, Any],
    ) -> HarnessEvent:
        item_type = str(item.get("type") or "tool")
        return HarnessEvent(
            kind=kind,
            item_id=str(item.get("id") or ""),
            tool_name=CodexAdapter._tool_name(item),
            text=CodexAdapter._tool_output(item),
            data={
                "arguments": CodexAdapter._tool_arguments(item),
                "provider_type": item_type,
                "status": item.get("status"),
                "exit_code": item.get("exitCode"),
                "duration_ms": item.get("durationMs"),
            },
        )

    @staticmethod
    def _history_item(item: dict[str, Any]) -> list[HarnessHistoryItem]:
        item_type = str(item.get("type") or "")
        item_id = str(item.get("id") or "")
        if item_type == "userMessage":
            text = "\n".join(
                str(block.get("text") or "")
                for block in item.get("content", [])
                if block.get("type") == "text" and block.get("text")
            )
            return (
                [
                    HarnessHistoryItem(
                        kind=HarnessHistoryKind.USER,
                        text=text,
                        item_id=item_id,
                    ),
                ]
                if text
                else []
            )
        if item_type == "agentMessage":
            return [
                HarnessHistoryItem(
                    kind=HarnessHistoryKind.MESSAGE,
                    text=str(item.get("text") or ""),
                    item_id=item_id,
                ),
            ]
        if item_type in {"reasoning", "plan"}:
            values = (
                item.get("summary")
                or item.get("content")
                or [item.get("text")]
            )
            text = "\n".join(str(value) for value in values if value)
            return (
                [
                    HarnessHistoryItem(
                        kind=HarnessHistoryKind.REASONING,
                        text=text,
                        item_id=item_id,
                    ),
                ]
                if text
                else []
            )
        if item_type not in _TOOL_ITEM_TYPES:
            return []
        event = CodexAdapter._tool_event(
            HarnessEventKind.TOOL_COMPLETED,
            item,
        )
        return [
            HarnessHistoryItem(
                kind=HarnessHistoryKind.TOOL_CALL,
                item_id=event.item_id,
                tool_name=event.tool_name,
                data={"arguments": event.data.get("arguments") or {}},
            ),
            HarnessHistoryItem(
                kind=HarnessHistoryKind.TOOL_OUTPUT,
                text=event.text,
                item_id=event.item_id,
                tool_name=event.tool_name,
                data=event.data,
            ),
        ]

    @staticmethod
    # pylint: disable=too-many-return-statements
    def _tool_name(item: dict[str, Any]) -> str:
        item_type = str(item.get("type") or "tool")
        if item_type == "commandExecution":
            return "shell"
        if item_type == "fileChange":
            return "apply_patch"
        if item_type in {"mcpToolCall", "dynamicToolCall"}:
            parts = [
                str(item.get(key) or "")
                for key in ("server", "namespace", "tool")
            ]
            return ".".join(part for part in parts if part) or item_type
        if item_type == "collabAgentToolCall":
            return f"agent.{item.get('tool') or 'collaborate'}"
        if item_type == "webSearch":
            return "web_search"
        if item_type == "imageView":
            return "view_image"
        if item_type == "imageGeneration":
            return "image_generation"
        return item_type

    @staticmethod
    # pylint: disable=too-many-return-statements
    def _tool_arguments(item: dict[str, Any]) -> dict[str, Any]:
        item_type = str(item.get("type") or "")
        if item_type == "commandExecution":
            return {
                "command": item.get("command"),
                "cwd": item.get("cwd"),
            }
        if item_type == "fileChange":
            changes = item.get("changes") or []
            return {
                "changes": [
                    {
                        "path": change.get("path"),
                        "kind": change.get("kind"),
                    }
                    for change in changes
                    if isinstance(change, dict)
                ],
            }
        if item_type in {"mcpToolCall", "dynamicToolCall"}:
            arguments = item.get("arguments")
            return (
                arguments
                if isinstance(arguments, dict)
                else {
                    "arguments": arguments,
                }
            )
        if item_type == "collabAgentToolCall":
            return {
                "prompt": item.get("prompt"),
                "receiver_thread_ids": item.get("receiverThreadIds"),
            }
        if item_type == "webSearch":
            return {"query": item.get("query")}
        if item_type == "imageView":
            return {"path": item.get("path")}
        if item_type == "imageGeneration":
            return {"prompt": item.get("revisedPrompt")}
        return {}

    @staticmethod
    def _tool_output(item: dict[str, Any]) -> str:
        item_type = str(item.get("type") or "")
        if item_type == "commandExecution":
            return str(item.get("aggregatedOutput") or "")
        if item_type == "mcpToolCall":
            value = item.get("result") or item.get("error")
        elif item_type == "dynamicToolCall":
            value = item.get("contentItems")
        elif item_type == "fileChange":
            value = item.get("changes")
        elif item_type == "collabAgentToolCall":
            value = item.get("agentsStates")
        elif item_type == "imageGeneration":
            value = {
                "result": item.get("result"),
                "saved_path": item.get("savedPath"),
            }
        elif item_type == "imageView":
            value = {"path": item.get("path")}
        elif item_type == "webSearch":
            value = item.get("action") or {"query": item.get("query")}
        else:
            value = None
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)


__all__ = ["CodexAdapter"]
