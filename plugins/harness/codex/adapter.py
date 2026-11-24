# -*- coding: utf-8 -*-
"""Codex implementation of the third-party agent adapter."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from qwenpaw.plugins import SDKError
from qwenpaw.plugins.harnesses import (
    HarnessApprovalSummary,
    HarnessAttachment,
    HarnessAttachmentKind,
    HarnessCallContext,
    HarnessContext,
    HarnessDiscoveredSkill,
    HarnessDiscoveredMCPServer,
    HarnessEvent,
    HarnessEventKind,
    HarnessHistoryItem,
    HarnessHistoryKind,
    HarnessLogin,
    HarnessModel,
    HarnessOperationNotSupportedError,
    HarnessRunRequest,
    HarnessRuntimeCapabilities,
    HarnessStatus,
)
from .io_helpers import finish, run_io, stop_process
from .app_server import CodexAppServerClient, CodexAppServerError
from .projection import project_runtime
from .discovery import CODEX_RUNTIME_NOT_FOUND

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

_CODEX_CLI_INSTALL_MESSAGE = CODEX_RUNTIME_NOT_FOUND


class CodexBackend:
    """Run Codex threads through one workspace-scoped app-server."""

    def __init__(
        self,
        context: HarnessContext,
        settings: dict[str, Any] | None = None,
        *,
        client: CodexAppServerClient | None = None,
        binary: str | None = None,
    ) -> None:
        self._context = context
        self._state_dir = context.state_dir
        self._binary = (
            binary or str((settings or {}).get("binary") or "").strip() or None
        )
        self._injected_client = client is not None
        self._client = client or CodexAppServerClient(binary=self._binary)
        self._runtime_clients: dict[str, Any] = {}
        self._session_clients: dict[str, Any] = {}
        self._session_fingerprints: dict[str, str] = {}
        self._session_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._threads: dict[str, str] = {}
        self._prepared = False
        self._closed = False
        self._loaded_threads: set[tuple[int, str]] = set()
        self._thread_contexts: dict[str, HarnessCallContext] = {}
        self._mcp_tasks: set[asyncio.Task] = set()
        self._mcp_processes: set[Any] = set()
        self._approval_tasks: dict[tuple[str, int], set[asyncio.Task]] = {}
        self._client.set_server_request_handler(self._handle_server_request)

    async def prepare(self) -> None:
        """Validate and atomically copy legacy state on the first real open."""
        async with self._session_lock:
            if self._closed:
                raise SDKError("Codex backend is closed")
            if self._prepared:
                return
            try:
                missing = object()
                payload = await self._context.storage.aread_json(
                    "codex_sessions.json",
                    missing,
                )
                if payload is missing:
                    legacy = (
                        self._context.workspace_dir
                        / "harnesses"
                        / "codex_sessions.json"
                    )
                    try:
                        raw = await run_io(legacy.read_bytes)
                    except FileNotFoundError:
                        payload = {}
                    else:
                        payload = json.loads(raw)
                        self._validate_threads(payload)
                        await self._context.storage.awrite_bytes(
                            "codex_sessions.json",
                            raw,
                        )
                self._validate_threads(payload)
            except (OSError, json.JSONDecodeError, UnicodeError) as exc:
                raise SDKError(
                    "Could not load Codex session state; restore "
                    f"codex_sessions.json or fix file permissions: {exc}",
                ) from exc
            self._threads = dict(payload)
            self._prepared = True

    @staticmethod
    def _validate_threads(payload):
        if not isinstance(payload, dict) or not all(
            isinstance(key, str) and isinstance(value, str) and key and value
            for key, value in payload.items()
        ):
            raise SDKError(
                "Codex session mapping is invalid; "
                "restore its saved JSON state",
            )

    @staticmethod
    def _session_key(context: HarnessCallContext) -> str:
        return json.dumps(
            [context.user_id, context.channel, context.session_id],
        )

    async def _claim_thread(self, context):
        key = self._session_key(context)
        if key not in self._threads and context.session_id in self._threads:
            self._threads[key] = self._threads.pop(context.session_id)
            await self._save_threads()
        return self._threads.get(key)

    async def _save_threads(self):
        try:
            await self._context.storage.awrite_json(
                "codex_sessions.json",
                self._threads,
            )
        except (OSError, UnicodeError) as exc:
            raise SDKError(
                "Could not save Codex session state; "
                f"check storage permissions: {exc}",
            ) from exc

    async def _resolution(self):
        resolve = getattr(self._client, "resolve", None)
        if resolve is not None:
            return await resolve()
        return self._client.binary_resolution

    async def status(self, context: HarnessCallContext) -> HarnessStatus:
        """Return Codex installation and local account status."""
        del context
        await self.prepare()
        resolution = await self._resolution()
        runtime_path = str(resolution.path) if resolution is not None else None
        runtime_source = resolution.source if resolution is not None else None
        if resolution is None:
            return HarnessStatus(
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
            return HarnessStatus(
                available=True,
                installed=True,
                authenticated=bool(account),
                account=public_account,
                runtime_path=runtime_path,
                runtime_source=runtime_source,
            )
        except CodexAppServerError as exc:
            return HarnessStatus(
                available=True,
                installed=True,
                error=str(exc),
                runtime_path=runtime_path,
                runtime_source=runtime_source,
            )

    async def start_login(
        self,
        context: HarnessCallContext,
        *,
        device_code: bool = False,
    ) -> HarnessLogin:
        """Start Codex-managed ChatGPT OAuth."""
        del context
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
        return HarnessLogin(dict(result or {}))

    async def logout(self, context: HarnessCallContext) -> None:
        """Log out through Codex without handling credentials directly."""
        del context
        await self._client.start()
        await self._client.request("account/logout", {})

    async def models(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessModel, ...]:
        """Return the complete Codex model picker catalog."""
        del context
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
                        reasoning_efforts=tuple(efforts),
                        default_reasoning_effort=(
                            str(item["defaultReasoningEffort"])
                            if item.get("defaultReasoningEffort")
                            else None
                        ),
                    ),
                )
            cursor = (result or {}).get("nextCursor")
            if not cursor:
                return tuple(model for model in models if model.id)

    async def discover_mcp(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessDiscoveredMCPServer, ...]:
        """Discover Codex-owned MCP servers without exposing configuration."""
        payload = await self.external_mcp_records(context)
        return tuple(
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
            if item.get("name")
        )

    async def external_mcp_records(
        self,
        context: HarnessCallContext,
    ) -> tuple[dict[str, Any], ...]:
        """Own the short-lived MCP process through cancellation and close."""
        task = asyncio.current_task()
        self._mcp_tasks.add(task)
        process = None
        try:
            resolution = await self._resolution()
            if resolution is None:
                raise HarnessOperationNotSupportedError(
                    _CODEX_CLI_INSTALL_MESSAGE,
                )
            spawn = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    str(resolution.path),
                    "mcp",
                    "list",
                    "--json",
                    cwd=str(context.cwd),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
            )
            try:
                process = await finish(spawn)
            except OSError as exc:
                raise CodexAppServerError(
                    f"Could not launch Codex MCP discovery: {exc}. "
                    "Repair the plugin or configure a valid executable.",
                ) from exc
            except asyncio.CancelledError:
                if not spawn.cancelled():
                    try:
                        process = spawn.result()
                    except Exception:
                        pass
                raise
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
            return (
                tuple(dict(item) for item in payload if isinstance(item, dict))
                if isinstance(payload, list)
                else ()
            )
        finally:
            try:
                if process is not None:
                    self._mcp_processes.add(process)
                    await finish(self._stop_mcp(process))
            finally:
                self._mcp_tasks.discard(task)

    async def _stop_mcp(self, process):
        await stop_process(process, drain=True)
        self._mcp_processes.discard(process)

    async def discover_skills(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessDiscoveredSkill, ...]:
        """Discover Codex-owned Skills through the app-server."""
        discovered: list[HarnessDiscoveredSkill] = []
        seen: set[tuple[str, str]] = set()
        for item in await self._skill_records(context.cwd):
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
        return tuple(discovered)

    async def _skill_records(self, cwd: Path) -> list[dict[str, Any]]:
        await self._client.start()
        result = await self._client.request(
            "skills/list",
            {"cwds": [str(cwd)], "forceReload": False},
        )
        return [
            dict(item)
            for entry in (result or {}).get("data", [])
            if isinstance(entry, dict)
            for item in entry.get("skills") or []
            if isinstance(item, dict)
        ]

    async def external_skill_records(
        self,
        context: HarnessCallContext,
    ) -> tuple[dict[str, Any], ...]:
        """Return full Codex Skill records for migration."""
        records: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in await self._skill_records(context.cwd):
            path = str(item.get("path") or "")
            if not path or path in seen:
                continue
            seen.add(path)
            records.append(item)
        return tuple(records)

    async def list_external_threads(
        self,
        context: HarnessCallContext,
        *,
        limit: int = 500,
        archived: bool = False,
    ) -> tuple[dict[str, Any], ...]:
        """List pre-existing Codex threads through the app-server."""
        del context
        remaining = max(0, min(int(limit), 5000))
        cursor: str | None = None
        records: list[dict[str, Any]] = []
        while remaining:
            page_size = min(remaining, 100)
            params: dict[str, Any] = {
                "limit": page_size,
                "archived": archived,
            }
            if cursor:
                params["cursor"] = cursor
            result = await self._client.request("thread/list", params)
            page = (result or {}).get("data")
            if not isinstance(page, list):
                page = (result or {}).get("threads") or []
            added = 0
            for item in page:
                if not isinstance(item, dict):
                    continue
                records.append({**item, "archived": archived})
                added += 1
                if len(records) >= limit:
                    return tuple(records)
            remaining -= added
            cursor = str((result or {}).get("nextCursor") or "") or None
            if not cursor or not added:
                break
        return tuple(records)

    async def read_external_thread(
        self,
        context: HarnessCallContext,
        thread_id: str,
    ) -> tuple[HarnessHistoryItem, ...]:
        """Normalize one arbitrary Codex thread without resuming it."""
        del context
        result = await self._client.request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": True},
        )
        history: list[HarnessHistoryItem] = []
        for turn in (result or {}).get("thread", {}).get("turns", []):
            if not isinstance(turn, dict):
                continue
            for item in turn.get("items") or []:
                if isinstance(item, dict):
                    history.extend(self._history_item(item))
        return tuple(history)

    async def history(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessHistoryItem, ...]:
        """Read the lossy persisted Codex thread for recovery."""
        await self.prepare()
        async with self._session_lock:
            thread_id = await self._claim_thread(context)
        if not thread_id:
            return ()
        client = (
            self._session_clients.get(self._session_key(context))
            or self._client
        )
        await client.start()
        result = await client.request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": True},
        )
        history: list[HarnessHistoryItem] = []
        for turn in (result or {}).get("thread", {}).get("turns", []):
            for item in turn.get("items", []):
                history.extend(self._history_item(item))
        return tuple(history)

    # The preserved notification/turn protocol has several terminal cases.
    # pylint: disable-next=too-many-branches
    async def run_turn(
        self,
        context: HarnessCallContext,
        request: HarnessRunRequest,
    ) -> AsyncIterator[HarnessEvent]:
        """Start or resume a Codex thread and stream one turn."""
        await self.prepare()
        session_id = self._session_key(context)
        cwd, settings = context.cwd, context.settings
        client = await self._prepare_runtime(
            session_id,
            context.runtime_capabilities,
        )
        thread_id = await self._thread_for_session(
            client,
            context,
            cwd,
            settings,
        )
        self._thread_contexts[thread_id] = context
        queue = client.subscribe()
        turn_id = ""
        try:
            params = {
                "threadId": thread_id,
                "cwd": str(cwd),
                "input": self._turn_input(request.prompt, request.attachments),
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
        except (asyncio.CancelledError, GeneratorExit):
            if turn_id:
                await finish(self._interrupt_turn(client, thread_id, turn_id))
            raise
        finally:
            client.unsubscribe(queue)
            await finish(self._release_context(thread_id, context))

    @staticmethod
    def _turn_input(
        prompt: str,
        attachments: tuple[HarnessAttachment, ...],
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
        context: HarnessCallContext,
        command: str,
        arguments: str,
    ) -> tuple[HarnessEvent, ...]:
        """Run one Codex app-server command."""
        del arguments
        await self.prepare()
        session_id = self._session_key(context)
        cwd, settings = context.cwd, context.settings
        client = await self._prepare_runtime(
            session_id,
            context.runtime_capabilities,
        )
        thread_id = await self._thread_for_session(
            client,
            context,
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
                context,
            )
        elif command == "skills":
            result = await client.request(
                "skills/list",
                {"cwds": [str(cwd)], "forceReload": False},
            )
            text = self._format_skills(result)
        elif command == "status":
            provider = await self.status(context)
            model = settings.get("model") or "default"
            connection = "connected" if provider.authenticated else "offline"
            text = f"Codex: {connection}" f"\nModel: {model}\nWorkspace: {cwd}"
        else:
            raise HarnessOperationNotSupportedError(
                f"Unsupported Codex command: " f"/{command}",
            )
        return (
            HarnessEvent(kind=HarnessEventKind.TEXT_DELTA, text=text),
            HarnessEvent(kind=HarnessEventKind.COMPLETED),
        )

    async def reset_session(self, context: HarnessCallContext) -> None:
        """Forget only this trusted identity's native mapping."""
        await self.prepare()
        async with self._session_lock:
            session_id = self._session_key(context)
            thread_id = await self._claim_thread(context)
            self._threads.pop(session_id, None)
            if thread_id:
                self._loaded_threads = {
                    key for key in self._loaded_threads if key[1] != thread_id
                }
                self._thread_contexts.pop(thread_id, None)
            self._session_clients.pop(session_id, None)
            self._session_fingerprints.pop(session_id, None)
            await self._save_threads()

    async def close(self) -> None:
        """Close clients, readers, RPCs and ephemeral discovery."""
        async with self._close_lock:
            self._closed = True
            await finish(self._close())

    async def _close(self):
        approvals = {
            task for group in self._approval_tasks.values() for task in group
        }
        for task in approvals:
            task.cancel()
        if approvals:
            await asyncio.gather(*approvals, return_exceptions=True)
        tasks = [
            task
            for task in self._mcp_tasks
            if task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        clients = {
            id(client): client
            for client in (self._client, *self._runtime_clients.values())
        }
        for client in clients.values():
            client.set_server_request_handler(None)
        results = await asyncio.gather(
            *(
                self._stop_mcp(process)
                for process in tuple(self._mcp_processes)
            ),
            *(client.stop() for client in clients.values()),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        self._runtime_clients.clear()
        self._session_clients.clear()
        self._session_fingerprints.clear()
        self._thread_contexts.clear()
        self._loaded_threads.clear()

    async def _thread_for_session(
        self,
        client: Any,
        context: HarnessCallContext,
        cwd: Path,
        settings: dict[str, Any],
    ) -> str:
        async with self._session_lock:
            session_id = self._session_key(context)
            thread_id = await self._claim_thread(context)
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
            await self._save_threads()
            return thread_id

    async def _prepare_runtime(
        self,
        session_id: str,
        capabilities: HarnessRuntimeCapabilities | None,
    ) -> Any:
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
        context = self._thread_contexts.get(str(params.get("threadId") or ""))
        is_permissions = "permissions" in method
        if context is None:
            return (
                {"permissions": {}, "scope": "turn"}
                if is_permissions
                else {"decision": "decline"}
            )
        command = str(params.get("command") or "")
        is_command = "commandExecution" in method
        name = (
            "Codex command"
            if is_command
            else "Codex permission request"
            if is_permissions
            else "Codex file change"
        )
        key = (str(params.get("threadId") or ""), id(context))
        task = asyncio.current_task()
        self._approval_tasks.setdefault(key, set()).add(task)
        try:
            decision = await context.request_approval(
                HarnessApprovalSummary(
                    tool_name=name,
                    title=name,
                    description=command
                    or str(params.get("reason") or "")
                    or name,
                    severity="high"
                    if is_command or is_permissions
                    else "medium",
                    parameters={
                        "provider": "codex",
                        "provider_item_id": params.get("itemId"),
                        "command": command,
                        "cwd": params.get("cwd"),
                        "permissions": params.get("permissions"),
                    },
                ),
                timeout=300,
            )
        finally:
            tasks = self._approval_tasks.get(key)
            if tasks is not None:
                tasks.discard(task)
                if not tasks:
                    self._approval_tasks.pop(key, None)
        if is_permissions:
            return {
                "permissions": dict(params.get("permissions") or {})
                if decision == "approved"
                else {},
                "scope": "turn",
            }
        return {"decision": "accept" if decision == "approved" else "decline"}

    async def _release_context(self, thread_id, context):
        if self._thread_contexts.get(thread_id) is context:
            self._thread_contexts.pop(thread_id, None)
        tasks = tuple(self._approval_tasks.get((thread_id, id(context)), ()))
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_review(
        self,
        client: Any,
        thread_id: str,
        context: HarnessCallContext,
    ) -> tuple[HarnessEvent, ...]:
        queue = client.subscribe()
        review_thread_id = thread_id
        turn_id = ""
        self._thread_contexts[thread_id] = context
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
            self._thread_contexts[review_thread_id] = context
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
                    return tuple(events)
        except asyncio.CancelledError:
            if turn_id:
                await finish(
                    self._interrupt_turn(client, review_thread_id, turn_id),
                )
            raise
        finally:
            client.unsubscribe(queue)
            for key in (thread_id, review_thread_id):
                await finish(self._release_context(key, context))

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
                return CodexBackend._tool_event(
                    HarnessEventKind.TOOL_STARTED,
                    item,
                )
        if method == "item/completed":
            item = params.get("item") or {}
            item_type = str(item.get("type") or "")
            if item_type in _TOOL_ITEM_TYPES:
                return CodexBackend._tool_event(
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
            tool_name=CodexBackend._tool_name(item),
            text=CodexBackend._tool_output(item),
            data={
                "arguments": CodexBackend._tool_arguments(item),
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
        event = CodexBackend._tool_event(
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


__all__ = ["CodexBackend"]
