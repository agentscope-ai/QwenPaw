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
from ..capabilities import HarnessRuntimeCapabilities
from ..events import (
    HarnessAttachment,
    HarnessAttachmentKind,
    HarnessDiscoveredSkill,
    HarnessEvent,
    HarnessEventKind,
    HarnessHistoryItem,
    HarnessHistoryKind,
    HarnessDiscoveredMCPServer,
    HarnessModel,
    HarnessProvider,
)
from .app_server import CodexAppServerClient, CodexAppServerError
from .projection import project_runtime

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

_CODEX_CLI_INSTALL_MESSAGE = (
    "Codex runtime not found. Install qwenpaw[codex] or provide a "
    "standalone Codex CLI."
)


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
        self._binary = binary
        self._injected_client = client is not None
        self._client = client or CodexAppServerClient(binary=binary)
        self._runtime_clients: dict[str, Any] = {}
        self._session_clients: dict[str, Any] = {}
        self._session_fingerprints: dict[str, str] = {}
        self._session_lock = asyncio.Lock()
        self._threads = self._load_threads()
        self._loaded_threads: set[tuple[int, str]] = set()
        self._thread_contexts: dict[str, dict[str, Any]] = {}
        if hasattr(self._client, "set_server_request_handler"):
            self._client.set_server_request_handler(
                self._handle_server_request,
            )

    @property
    def capability_unavailable_message(self) -> str | None:
        """Explain why Codex capability discovery is unavailable."""
        if not self._client.installed:
            return _CODEX_CLI_INSTALL_MESSAGE
        return None

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
                error=_CODEX_CLI_INSTALL_MESSAGE,
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

    async def discover_mcp(
        self,
        cwd: Path,
    ) -> list[HarnessDiscoveredMCPServer]:
        """Discover Codex-owned MCP servers without exposing configuration."""
        resolution = getattr(self._client, "binary_resolution", None)
        if resolution is None:
            return []
        process = await asyncio.create_subprocess_exec(
            str(resolution.path),
            "mcp",
            "list",
            "--json",
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            detail = stderr.decode(errors="replace").strip()
            raise CodexAppServerError(
                f"Failed to discover Codex MCP servers: {detail}",
            )
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise CodexAppServerError(
                "Codex returned invalid MCP discovery data",
            ) from exc
        if not isinstance(payload, list):
            return []
        return [
            HarnessDiscoveredMCPServer(
                name=str(item.get("name") or ""),
                provider_id="codex",
                transport=str(
                    (item.get("transport") or {}).get("type") or "",
                ),
                enabled=bool(item.get("enabled")),
                auth_status=str(item.get("auth_status") or ""),
            )
            for item in payload
            if isinstance(item, dict) and item.get("name")
        ]

    async def discover_skills(
        self,
        cwd: Path,
    ) -> list[HarnessDiscoveredSkill]:
        """Discover Codex-owned Skills through the app-server."""
        await self._client.start()
        result = await self._client.request(
            "skills/list",
            {"cwds": [str(cwd)], "forceReload": False},
        )
        discovered: list[HarnessDiscoveredSkill] = []
        seen: set[tuple[str, str]] = set()
        for entry in (result or {}).get("data", []):
            if not isinstance(entry, dict):
                continue
            for item in entry.get("skills") or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "")
                source = str(item.get("scope") or "")
                key = (name, source)
                if not name or key in seen:
                    continue
                seen.add(key)
                discovered.append(
                    HarnessDiscoveredSkill(
                        name=name,
                        description=str(item.get("description") or ""),
                        provider_id="codex",
                        source=source,
                        enabled=bool(item.get("enabled", True)),
                    ),
                )
        return discovered

    async def history(self, session_id: str) -> list[HarnessHistoryItem]:
        """Read the lossy persisted Codex thread for recovery."""
        thread_id = self._threads.get(session_id)
        if not thread_id:
            return []
        client = self._session_clients.get(session_id) or self._client
        await client.start()
        result = await client.request(
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
        attachments: list[HarnessAttachment] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        """Start or resume a Codex thread and stream one turn."""
        client = await self._prepare_runtime(session_id, settings)
        thread_id = await self._thread_for_session(
            client,
            session_id,
            cwd,
            settings,
        )
        self._thread_contexts[thread_id] = {
            "session_id": session_id,
            **dict(settings.get("_request_context") or {}),
        }
        queue = client.subscribe()
        turn_id = ""
        try:
            params = {
                "threadId": thread_id,
                "cwd": str(cwd),
                "input": self._turn_input(prompt, attachments or []),
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
            result = await client.request("turn/start", params)
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
                await self._interrupt_turn(client, thread_id, turn_id)
            raise
        finally:
            client.unsubscribe(queue)

    @staticmethod
    def _turn_input(
        prompt: str,
        attachments: list[HarnessAttachment],
    ) -> list[dict[str, Any]]:
        """Build Codex app-server user input from one QwenPaw turn."""
        result: list[dict[str, Any]] = []
        if prompt:
            result.append({"type": "text", "text": prompt})
        for attachment in attachments:
            path = str(attachment.path)
            if attachment.kind == HarnessAttachmentKind.IMAGE:
                result.append({"type": "localImage", "path": path})
                continue
            name = attachment.name or attachment.path.name
            result.append(
                {
                    "type": "text",
                    "text": f"Attached file {name}: {path}",
                },
            )
        return result

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
        client = await self._prepare_runtime(session_id, settings)
        thread_id = await self._thread_for_session(
            client,
            session_id,
            cwd,
            settings,
        )
        if command == "compact":
            await client.request(
                "thread/compact/start",
                {"threadId": thread_id},
            )
            text = "Codex context compacted."
        elif command == "review":
            return await self._run_review(
                client,
                thread_id,
            )
        elif command == "skills":
            result = await client.request(
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
                self._loaded_threads = {
                    key for key in self._loaded_threads if key[1] != thread_id
                }
                self._thread_contexts.pop(thread_id, None)
            self._session_clients.pop(session_id, None)
            self._session_fingerprints.pop(session_id, None)
            await write_json_atomic_async(
                self._session_path,
                self._threads,
            )

    async def stop(self) -> None:
        """Stop the workspace Codex process."""
        clients = {
            id(client): client
            for client in (
                self._client,
                *self._runtime_clients.values(),
            )
        }
        for client in clients.values():
            await client.stop()
        self._runtime_clients.clear()
        self._session_clients.clear()
        self._session_fingerprints.clear()
        self._loaded_threads.clear()

    async def _thread_for_session(
        self,
        client: Any,
        session_id: str,
        cwd: Path,
        settings: dict[str, Any],
    ) -> str:
        async with self._session_lock:
            thread_id = self._threads.get(session_id)
            if thread_id:
                loaded_key = (id(client), thread_id)
                if loaded_key not in self._loaded_threads:
                    try:
                        await client.request(
                            "thread/resume",
                            {"threadId": thread_id},
                        )
                        self._loaded_threads.add(loaded_key)
                        return thread_id
                    except CodexAppServerError:
                        self._threads.pop(session_id, None)
                        thread_id = None
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
            result = await client.request("thread/start", params)
            thread_id = str((result or {}).get("thread", {}).get("id", ""))
            if not thread_id:
                raise CodexAppServerError("Codex did not return a thread id")
            self._threads[session_id] = thread_id
            self._loaded_threads.add((id(client), thread_id))
            await write_json_atomic_async(
                self._session_path,
                self._threads,
            )
            return thread_id

    async def _prepare_runtime(
        self,
        session_id: str,
        settings: dict[str, Any],
    ) -> Any:
        capabilities = settings.get("_runtime_capabilities")
        if not isinstance(capabilities, HarnessRuntimeCapabilities):
            capabilities = HarnessRuntimeCapabilities()
        projection = project_runtime(capabilities)
        fingerprint = capabilities.fingerprint
        existing = self._session_clients.get(session_id)
        if (
            existing is not None
            and self._session_fingerprints.get(session_id) == fingerprint
        ):
            await existing.start()
            return existing
        if self._injected_client:
            client = self._client
            configure = getattr(client, "configure_runtime", None)
        else:
            client = self._runtime_clients.get(fingerprint)
            configure = None
            if client is None:
                client = CodexAppServerClient(
                    binary=self._binary,
                    config_overrides=projection.config_overrides,
                    environment=projection.environment,
                )
                client.set_server_request_handler(
                    self._handle_server_request,
                )
                self._runtime_clients[fingerprint] = client
        if configure is not None:
            restarted = await configure(
                projection.config_overrides,
                projection.environment,
            )
            if restarted:
                self._loaded_threads.clear()
        await client.start()
        await client.request(
            "skills/extraRoots/set",
            {"extraRoots": list(projection.skill_roots)},
        )
        self._session_clients[session_id] = client
        self._session_fingerprints[session_id] = fingerprint
        return client

    async def _handle_server_request(
        self,
        message: dict[str, Any],
    ) -> dict[str, Any]:
        method = str(message.get("method") or "")
        if method not in {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/permissions/requestApproval",
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
        is_permissions = "permissions" in method
        if is_command:
            name = "Codex command"
        elif is_permissions:
            name = "Codex permission request"
        else:
            name = "Codex file change"
        detail = command or str(params.get("reason") or "") or name
        summary = ApprovalRequestSummary(
            source_type="codex",
            name=name,
            severity="high" if is_command or is_permissions else "medium",
            result_summary=detail,
            payload={
                "provider": "codex",
                "provider_item_id": params.get("itemId"),
                "command": command,
                "cwd": params.get("cwd"),
                "permissions": params.get("permissions"),
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
        if is_permissions:
            permissions = (
                dict(params.get("permissions") or {})
                if decision == ApprovalDecision.APPROVED
                else {}
            )
            return {
                "permissions": permissions,
                "scope": "turn",
            }
        return {
            "decision": (
                "accept"
                if decision == ApprovalDecision.APPROVED
                else "decline"
            ),
        }

    async def _run_review(
        self,
        client: Any,
        thread_id: str,
    ) -> list[HarnessEvent]:
        queue = client.subscribe()
        try:
            result = await client.request(
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
            client.unsubscribe(queue)

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

    async def _interrupt_turn(
        self,
        client: Any,
        thread_id: str,
        turn_id: str,
    ) -> None:
        try:
            await client.request(
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
