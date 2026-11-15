# -*- coding: utf-8 -*-
"""Qoder SDK backend using only the public QwenPaw plugin contract."""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from qoder_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    QoderAgentOptions,
    QoderSDKClient,
    QoderSDKError,
    ToolPermissionContext,
    access_token_from_env,
    delete_session,
    get_session_messages,
    qodercli_auth,
)
from qwenpaw.plugins import SDKError
from qwenpaw.plugins.harnesses import (
    HarnessApprovalSummary,
    HarnessAttachment,
    HarnessAttachmentKind,
    HarnessCallContext,
    HarnessContext,
    HarnessDiscoveredSkill,
    HarnessEvent,
    HarnessHistoryItem,
    HarnessLogin,
    HarnessModel,
    HarnessOperationNotSupportedError,
    HarnessRunRequest,
    HarnessRuntimeCapabilities,
    HarnessStatus,
)
from .discovery import resolve_qoder_binary_info
from .event_mapper import QoderEventMapper, history_items
from .io_helpers import finish, run_io, stop_process
from .projection import materialize_skill_plugin, mcp_servers

_AUTH_ENV = "QODER_PERSONAL_ACCESS_TOKEN"
_CONNECT_TIMEOUT_SECONDS = 30
_STATUS_TIMEOUT_SECONDS = 10


class QoderBackend:
    """Own Qoder clients and mappings inside one trusted workspace."""

    def __init__(
        self,
        context: HarnessContext,
        settings: dict[str, Any] | None = None,
        *,
        binary: str | None = None,
        client_factory: Callable[[QoderAgentOptions], Any] | None = None,
    ) -> None:
        self._context = context
        self._state_dir = context.state_dir
        self._binary = (
            binary or str((settings or {}).get("binary") or "").strip() or None
        )
        self._client_factory = client_factory or QoderSDKClient
        self._sessions: dict[str, str] = {}
        self._clients: dict[str, Any] = {}
        self._client_keys: dict[str, tuple[Any, ...]] = {}
        self._owned_clients: dict[int, Any] = {}
        self._contexts: dict[str, HarnessCallContext] = {}
        self._turn_locks: dict[str, asyncio.Lock] = {}
        self._approval_tasks: dict[str, set[asyncio.Task]] = {}
        self._session_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()
        self._login_process = None
        self._processes: set[Any] = set()
        self._cli_tasks: set[asyncio.Task] = set()
        self._prepared = False
        self._closed = False

    async def prepare(self) -> None:
        """Validate target state, copying the original legacy file once."""
        async with self._session_lock:
            if self._closed:
                raise SDKError("Qoder backend is closed")
            if self._prepared:
                return
            try:
                missing = object()
                payload = await self._context.storage.aread_json(
                    "qoder_sessions.json",
                    missing,
                )
                if payload is missing:
                    legacy = (
                        self._context.workspace_dir
                        / "harnesses"
                        / "qoder_sessions.json"
                    )
                    try:
                        raw = await run_io(legacy.read_bytes)
                    except FileNotFoundError:
                        payload = {}
                    else:
                        payload = json.loads(raw)
                        self._validate_sessions(payload)
                        await self._context.storage.awrite_bytes(
                            "qoder_sessions.json",
                            raw,
                        )
                self._validate_sessions(payload)
            except (OSError, json.JSONDecodeError, UnicodeError) as exc:
                raise SDKError(
                    "Could not load Qoder session state; restore "
                    f"qoder_sessions.json or fix file permissions: {exc}",
                ) from exc
            self._sessions = dict(payload)
            self._prepared = True

    @staticmethod
    def _validate_sessions(payload):
        if not isinstance(payload, dict) or not all(
            isinstance(key, str) and isinstance(value, str) and key and value
            for key, value in payload.items()
        ):
            raise SDKError(
                "Qoder session mapping is invalid; "
                "restore its saved JSON state",
            )

    @staticmethod
    def _session_key(context):
        return json.dumps(
            [context.user_id, context.channel, context.session_id],
        )

    async def _save_sessions(self, payload):
        async def commit():
            try:
                await self._context.storage.awrite_json(
                    "qoder_sessions.json",
                    payload,
                )
            except (OSError, UnicodeError) as exc:
                raise SDKError(
                    "Could not save Qoder session state; "
                    f"check storage permissions: {exc}",
                ) from exc
            self._sessions = payload

        await finish(commit())

    async def _claim_session(self, context):
        key = self._session_key(context)
        if key not in self._sessions and context.session_id in self._sessions:
            payload = dict(self._sessions)
            payload[key] = payload.pop(context.session_id)
            await self._save_sessions(payload)
        return self._sessions.get(key)

    async def _resolution(self):
        try:
            return await run_io(resolve_qoder_binary_info, self._binary)
        except OSError as exc:
            raise SDKError(
                "Could not discover Qoder CLI; "
                f"check its executable path: {exc}",
            ) from exc

    async def _require_resolution(self):
        resolution = await self._resolution()
        if resolution is None:
            raise SDKError(
                "Qoder CLI executable was not found; repair the plugin "
                "or configure a valid executable.",
            )
        return resolution

    async def status(self, context: HarnessCallContext) -> HarnessStatus:
        del context
        await self.prepare()
        resolution = await self._resolution()
        if resolution is None:
            return HarnessStatus(
                installed=False,
                error="Qoder CLI executable was not found.",
            )
        values = {
            "installed": True,
            "runtime_path": str(resolution.path),
            "runtime_source": resolution.source,
        }
        try:
            output = await self._run_cli("status")
        except (SDKError, asyncio.TimeoutError) as exc:
            return HarnessStatus(
                **values,
                error=str(exc) or "Qoder CLI status timed out.",
            )
        fields = self._status_fields(output)
        account_value, username, email = (
            fields.get(name, "") for name in ("account", "username", "email")
        )
        token = bool(os.environ.get(_AUTH_ENV))
        authenticated = (
            token
            or bool(username or email)
            or (
                bool(account_value)
                and account_value.lower() != "not logged in"
            )
        )
        account = None
        if authenticated:
            account = {"type": "accessToken" if token else "qodercli"}
            if email or "@" in account_value:
                account["email"] = email or account_value
            if username:
                account["username"] = username
        return HarnessStatus(
            **values,
            authenticated=authenticated,
            account=account,
        )

    async def _spawn(self, resolution, *arguments, **kwargs):
        launch = asyncio.create_task(
            asyncio.create_subprocess_exec(
                str(resolution.path),
                *arguments,
                **kwargs,
            ),
        )
        try:
            try:
                process = await finish(launch)
            except OSError as exc:
                raise SDKError(
                    f"Could not launch Qoder CLI: {exc}. Repair the plugin "
                    "or configure a valid executable.",
                ) from exc
        except asyncio.CancelledError:
            if (
                launch.done()
                and not launch.cancelled()
                and launch.exception() is None
            ):
                process = launch.result()
                self._processes.add(process)
                await finish(self._stop_process(process))
            raise
        self._processes.add(process)
        return process

    async def _stop_process(self, process):
        await stop_process(process, drain=True)
        self._processes.discard(process)
        if self._login_process is process:
            self._login_process = None

    async def _run_cli(self, *arguments):
        task = asyncio.current_task()
        self._cli_tasks.add(task)
        process = None
        try:
            process = await self._spawn(
                await self._require_resolution(),
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            async with asyncio.timeout(_STATUS_TIMEOUT_SECONDS):
                stdout, _ = await process.communicate()
            return stdout.decode(errors="replace")
        finally:
            try:
                if process is not None:
                    await finish(self._stop_process(process))
            finally:
                self._cli_tasks.discard(task)

    async def start_login(
        self,
        context: HarnessCallContext,
        *,
        device_code: bool = False,
    ) -> HarnessLogin:
        del context, device_code
        resolution = await self._require_resolution()
        if (
            self._login_process is None
            or self._login_process.returncode is not None
        ):
            self._login_process = await self._spawn(
                resolution,
                "login",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        return HarnessLogin(
            {
                "type": "external",
                "loginId": f"qoder-{uuid.uuid4().hex}",
                "command": f"{resolution.path} login",
            },
        )

    async def logout(self, context: HarnessCallContext) -> None:
        del context
        raise HarnessOperationNotSupportedError(
            "Qoder CLI does not expose a non-interactive logout command.",
        )

    def _new_client(self, options):
        client = self._client_factory(options)
        self._owned_clients[id(client)] = client
        return client

    async def _disconnect(self, client):
        try:
            await client.disconnect()
        except (OSError, QoderSDKError) as exc:
            raise SDKError(f"Could not disconnect Qoder SDK: {exc}") from exc
        self._owned_clients.pop(id(client), None)

    async def _evict_client(self, identity, client):
        """Retire a client and its matching cache entry in one operation."""
        # A failed disconnect remains owned, but must never be reused.
        self._client_keys.pop(identity, None)
        await self._disconnect(client)
        self._clients.pop(identity, None)

    async def _interrupt_client(self, identity, client):
        try:
            await client.interrupt()
        finally:
            # SDK interrupt does not drain the cancelled turn's message FIFO.
            # Reconnect with the persisted native ID for the next turn.
            await self._evict_client(identity, client)

    async def _connect(self, client):
        try:
            async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                await client.connect()
        except (OSError, asyncio.TimeoutError, QoderSDKError) as exc:
            raise SDKError(
                "Could not connect Qoder SDK; check CLI installation "
                f"and authentication: {exc}",
            ) from exc

    @asynccontextmanager
    async def _temporary_client(self, context, *, skills=False):
        options = QoderAgentOptions(
            auth=self._auth(),
            cli_path=(await self._require_resolution()).path,
            cwd=context.cwd,
            setting_sources=["user", "project", "local"],
            skills="all" if skills else None,
        )
        client = self._new_client(options)
        try:
            await self._connect(client)
            yield client
        except QoderSDKError as exc:
            raise SDKError(f"Qoder SDK operation failed: {exc}") from exc
        finally:
            await finish(self._disconnect(client))

    async def models(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessModel, ...]:
        async with self._temporary_client(context) as client:
            catalog = await client.get_available_models()
        models = []
        for item in catalog:
            if not item.get("isEnabled", True):
                continue
            efforts_data = (
                (item.get("thinking_config") or {}).get("enabled") or {}
            ).get("efforts") or {}
            model_id = str(item.get("value") or "")
            if not model_id:
                continue
            models.append(
                HarnessModel(
                    id=model_id,
                    name=str(item.get("displayName") or model_id),
                    description=str(item.get("description") or ""),
                    is_default=model_id == "auto",
                    reasoning_efforts=tuple(
                        str(value) for value in efforts_data
                    ),
                    default_reasoning_effort=next(
                        (
                            str(value)
                            for value, metadata in efforts_data.items()
                            if metadata.get("is_default")
                        ),
                        None,
                    ),
                ),
            )
        if models and not any(model.is_default for model in models):
            models[0] = replace(models[0], is_default=True)
        return tuple(models)

    async def discover_skills(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessDiscoveredSkill, ...]:
        async with self._temporary_client(context, skills=True) as client:
            info = await client.get_server_info()
        discovered, seen = [], set()
        for item in (info or {}).get("skills", []):
            if not isinstance(item, dict):
                continue
            name, source = str(item.get("name") or ""), str(
                item.get("source") or "",
            )
            if (
                not name
                or name.startswith("qwenpaw-runtime:")
                or (name, source) in seen
            ):
                continue
            seen.add((name, source))
            discovered.append(
                HarnessDiscoveredSkill(
                    name=name,
                    description=str(item.get("description") or ""),
                    provider_id="qoder",
                    source=source,
                ),
            )
        return tuple(discovered)

    async def discover_mcp(self, context: HarnessCallContext):
        del context
        raise HarnessOperationNotSupportedError(
            "Qoder SDK does not expose provider MCP discovery.",
        )

    async def history(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessHistoryItem, ...]:
        await self.prepare()
        async with self._session_lock:
            native_id = await self._claim_session(context)
            if not native_id:
                return ()
            try:
                messages = await run_io(
                    get_session_messages,
                    native_id,
                    str(context.cwd),
                )
            except (OSError, ValueError) as exc:
                raise SDKError(
                    f"Could not read Qoder session history: {exc}",
                ) from exc
        return tuple(
            item for message in messages for item in history_items(message)
        )

    async def _client_for_session(self, context):
        await self.prepare()
        identity = self._session_key(context)
        capabilities = (
            context.runtime_capabilities or HarnessRuntimeCapabilities()
        )
        settings = context.settings
        key = (
            str(context.cwd),
            str(settings.get("model") or ""),
            str(settings.get("reasoning_effort") or ""),
            str(settings.get("permission_mode") or "default"),
            capabilities.fingerprint,
        )
        async with self._session_lock:
            existing = self._clients.get(identity)
            if existing is not None and self._client_keys.get(identity) == key:
                return existing
            if existing is not None:
                await finish(self._evict_client(identity, existing))
            native_id = await self._claim_session(context)
            resume = bool(native_id)
            native_id = native_id or str(uuid.uuid4())
            try:
                plugin_path = await run_io(
                    materialize_skill_plugin,
                    self._state_dir,
                    capabilities,
                )
            except OSError as exc:
                raise SDKError(
                    f"Could not project Qoder runtime Skills: {exc}",
                ) from exc
            resolution = await self._require_resolution()
            options = self._options(
                context,
                native_id,
                resume,
                plugin_path,
                resolution.path,
            )
            client = self._new_client(options)
            try:
                await self._connect(client)
                if not resume:
                    await self._save_sessions(
                        {**self._sessions, identity: native_id},
                    )
            except BaseException:
                await finish(self._disconnect(client))
                raise
            self._clients[identity] = client
            self._client_keys[identity] = key
            return client

    def _options(self, context, native_id, resume, plugin_path, binary_path):
        settings = context.settings
        permission_mode = str(settings.get("permission_mode") or "default")
        effort = settings.get("reasoning_effort")
        capabilities = (
            context.runtime_capabilities or HarnessRuntimeCapabilities()
        )
        projected_mcp = mcp_servers(capabilities)
        extra_args = (
            {"reasoning-effort": effort}
            if effort in {"low", "medium", "high", "max"}
            else {}
        )
        identity = self._session_key(context)
        return QoderAgentOptions(
            auth=self._auth(),
            cli_path=binary_path,
            cwd=context.cwd,
            resume=native_id if resume else None,
            session_id=None if resume else native_id,
            model=str(settings.get("model") or "") or None,
            extra_args=extra_args,
            include_partial_messages=True,
            permission_mode=permission_mode,
            allow_dangerously_skip_permissions=permission_mode
            in {"bypassPermissions", "yolo"},
            can_use_tool=lambda name, data, permission: self._approve_tool(
                identity,
                name,
                data,
                permission,
            ),
            mcp_servers=projected_mcp,
            allowed_mcp_server_names=sorted(projected_mcp),
            strict_mcp_config=True,
            setting_sources=["user", "project", "local"],
            plugins=(
                [{"type": "local", "path": str(plugin_path)}]
                if plugin_path is not None
                else []
            ),
            skills="all",
        )

    async def run_turn(
        self,
        context: HarnessCallContext,
        request: HarnessRunRequest,
    ) -> AsyncIterator[HarnessEvent]:
        identity = self._session_key(context)
        lock = self._turn_locks.setdefault(identity, asyncio.Lock())
        async with lock:
            self._contexts[identity] = context
            client = None
            try:
                client = await self._client_for_session(context)
                query_input = (
                    self._attachment_input(
                        request.prompt,
                        context.cwd,
                        request.attachments,
                    )
                    if request.attachments
                    else request.prompt
                )
                await client.query(query_input)
                mapper = QoderEventMapper()
                async for message in client.receive_response():
                    for event in mapper.convert(message):
                        yield event
            except (asyncio.CancelledError, GeneratorExit):
                if client is not None:
                    await finish(self._interrupt_client(identity, client))
                raise
            finally:
                self._contexts.pop(identity, None)
                tasks = self._approval_tasks.pop(identity, set())
                for task in tasks:
                    task.cancel()
                if tasks:
                    await finish(
                        asyncio.gather(*tasks, return_exceptions=True),
                    )

    async def _approve_tool(
        self,
        identity: str,
        tool_name: str,
        input_data: dict[str, Any],
        permission: ToolPermissionContext,
    ):
        context = self._contexts.get(identity)
        if context is None:
            return PermissionResultDeny(
                message="No live QwenPaw call owns this permission request.",
            )
        summary = HarnessApprovalSummary(
            tool_name=tool_name,
            title=permission.display_name or permission.title or tool_name,
            description=permission.description
            or permission.decision_reason
            or tool_name,
            severity="high" if tool_name == "Bash" else "medium",
            parameters={
                "provider": "qoder",
                "provider_item_id": permission.tool_use_id,
                "tool_name": tool_name,
                "input": input_data,
                "blocked_path": permission.blocked_path,
            },
        )
        task = asyncio.create_task(
            context.request_approval(summary, timeout=60),
        )
        group = self._approval_tasks.setdefault(identity, set())
        group.add(task)
        try:
            decision = await task
        finally:
            group.discard(task)
        if decision == "approved":
            return PermissionResultAllow(updated_input=input_data)
        return PermissionResultDeny(message="Rejected by the user.")

    async def _attachment_input(
        self,
        prompt: str,
        cwd: Path,
        attachments: tuple[HarnessAttachment, ...],
    ):
        content, references = [], []
        for attachment in attachments:
            if attachment.kind == HarnessAttachmentKind.IMAGE:
                try:
                    raw = await run_io(attachment.path.read_bytes)
                except OSError as exc:
                    raise SDKError(
                        f"Could not read Qoder attachment: {exc}",
                    ) from exc
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mimetypes.guess_type(
                                attachment.path.name,
                            )[0]
                            or "image/png",
                            "data": base64.b64encode(raw).decode("ascii"),
                        },
                    },
                )
            else:
                references.append(
                    await run_io(self._file_reference, attachment.path, cwd),
                )
        text = "\n".join(
            part for part in (" ".join(references), prompt) if part
        )
        if text:
            content.insert(0, {"type": "text", "text": text})
        yield {
            "type": "user",
            "message": {"role": "user", "content": content},
            "parent_tool_use_id": None,
        }

    @staticmethod
    def _file_reference(path, cwd):
        resolved_path, resolved_cwd = path.expanduser().resolve(
            strict=False,
        ), cwd.expanduser().resolve(strict=False)
        try:
            display = resolved_path.relative_to(resolved_cwd)
        except ValueError:
            display = resolved_path
        text = display.as_posix()
        if any(character.isspace() for character in text):
            return '@"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
        return f"@{text}"

    async def run_command(
        self,
        context: HarnessCallContext,
        command: str,
        arguments: str,
    ) -> tuple[HarnessEvent, ...]:
        if command != "compact":
            raise HarnessOperationNotSupportedError(
                f"Unsupported Qoder command: /{command}",
            )
        prompt = f"/{command}" + (f" {arguments}" if arguments else "")
        events = [
            event
            async for event in self.run_turn(
                context,
                HarnessRunRequest(prompt),
            )
        ]
        return tuple(events)

    async def reset_session(self, context: HarnessCallContext):
        await self.prepare()
        identity = self._session_key(context)
        async with self._turn_locks.setdefault(identity, asyncio.Lock()):
            async with self._session_lock:
                # Reset's external effects and local state are one operation.
                # Cancellation retains both locks until transitions settle.
                await finish(self._reset_session(context, identity))

    async def _reset_session(self, context, identity):
        native_id = await self._claim_session(context)
        client = self._clients.get(identity)
        if client is not None:
            await self._evict_client(identity, client)
        if native_id:
            try:
                await run_io(delete_session, native_id)
            except (OSError, ValueError) as exc:
                raise SDKError(
                    f"Could not delete Qoder session: {exc}",
                ) from exc
        payload = dict(self._sessions)
        payload.pop(identity, None)
        await self._save_sessions(payload)

    async def close(self):
        async with self._close_lock:
            self._closed = True
            await finish(self._close())

    async def _close(self):
        tasks = {
            task for group in self._approval_tasks.values() for task in group
        }
        tasks.update(
            task
            for task in self._cli_tasks
            if task is not asyncio.current_task()
        )
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        results = await asyncio.gather(
            *(
                self._disconnect(client)
                for client in tuple(self._owned_clients.values())
            ),
            *(
                self._stop_process(process)
                for process in tuple(self._processes)
            ),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        self._clients.clear()
        self._client_keys.clear()
        self._contexts.clear()
        self._approval_tasks.clear()
        self._turn_locks.clear()

    @staticmethod
    def _auth():
        return (
            access_token_from_env()
            if os.environ.get(_AUTH_ENV)
            else qodercli_auth()
        )

    @staticmethod
    def _status_fields(output):
        fields = {}
        for line in output.splitlines():
            label, separator, value = line.partition(":")
            label = label.strip().lower()
            if separator and label in {"account", "email", "username"}:
                fields[label] = value.strip()
        return fields
