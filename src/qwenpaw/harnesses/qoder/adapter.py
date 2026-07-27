# -*- coding: utf-8 -*-
"""Qoder implementation of the third-party agent adapter."""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import uuid
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from qoder_agent_sdk import (
    PermissionResultAllow,
    PermissionResultDeny,
    QoderAgentOptions,
    QoderSDKClient,
    ToolPermissionContext,
    access_token_from_env,
    delete_session,
    get_session_messages,
    qodercli_auth,
)

from ...app.approvals import (
    ApprovalRequestSummary,
    get_approval_service,
)
from ...security.tool_guard.approval import ApprovalDecision
from ...utils.io_utils import (
    read_bytes_async,
    read_json,
    write_json_atomic_async,
)
from ..base import HarnessAdapter, HarnessOperationNotSupportedError
from ..capabilities import HarnessRuntimeCapabilities
from ..events import (
    HarnessAttachment,
    HarnessAttachmentKind,
    HarnessDiscoveredSkill,
    HarnessEvent,
    HarnessHistoryItem,
    HarnessModel,
    HarnessProvider,
)
from .discovery import (
    QoderBinaryResolution,
    resolve_qoder_binary_info,
)
from .event_mapper import QoderEventMapper, history_items
from .projection import (
    materialize_skill_plugin,
    mcp_servers,
)

_AUTH_ENV = "QODER_PERSONAL_ACCESS_TOKEN"
_CONNECT_TIMEOUT_SECONDS = 30
_STATUS_TIMEOUT_SECONDS = 10


class QoderAdapter(HarnessAdapter):
    """Run Qoder SDK sessions inside one QwenPaw agent workspace."""

    def __init__(
        self,
        state_dir: Path,
        binary: str | None = None,
        client_factory: Callable[[QoderAgentOptions], Any] | None = None,
    ) -> None:
        self._state_dir = state_dir
        self._session_path = state_dir / "qoder_sessions.json"
        self._binary = binary
        self._client_factory = client_factory or QoderSDKClient
        self._sessions = self._load_sessions()
        self._clients: dict[str, Any] = {}
        self._client_keys: dict[str, tuple[Any, ...]] = {}
        self._contexts: dict[str, dict[str, Any]] = {}
        self._session_lock = asyncio.Lock()
        self._login_process: asyncio.subprocess.Process | None = None

    async def status(self) -> HarnessProvider:
        """Return Qoder CLI installation and authentication status."""
        resolution = self._resolution()
        if resolution is None:
            return HarnessProvider(
                id="qoder",
                name="Qoder",
                available=True,
                installed=False,
            )
        try:
            output = await self._run_cli("status")
        except (OSError, asyncio.TimeoutError) as exc:
            return self._provider(
                resolution,
                error=str(exc),
            )
        access_token = bool(os.environ.get(_AUTH_ENV))
        status_fields = self._status_fields(output)
        account_value = status_fields.get("account", "")
        username = status_fields.get("username", "")
        email = status_fields.get("email", "")
        cli_authenticated = bool(username or email) or (
            bool(account_value) and account_value.lower() != "not logged in"
        )
        authenticated = access_token or cli_authenticated
        account: dict[str, Any] | None = None
        if authenticated:
            account = {
                "type": "accessToken" if access_token else "qodercli",
            }
            if email:
                account["email"] = email
            elif account_value and "@" in account_value:
                account["email"] = account_value
            if username:
                account["username"] = username
        return self._provider(
            resolution,
            authenticated=authenticated,
            account=account,
        )

    async def start_login(self, device_code: bool = False) -> dict[str, Any]:
        """Start Qoder's browser login command in the background."""
        del device_code
        resolution = self._require_resolution()
        if (
            self._login_process is None
            or self._login_process.returncode is not None
        ):
            self._login_process = await asyncio.create_subprocess_exec(
                str(resolution.path),
                "login",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        return {
            "type": "external",
            "loginId": f"qoder-{uuid.uuid4().hex}",
            "command": f"{resolution.path} login",
        }

    async def logout(self) -> None:
        """Explain the provider-owned logout limitation."""
        raise HarnessOperationNotSupportedError(
            "Qoder CLI does not expose a non-interactive logout command.",
        )

    async def models(self) -> list[HarnessModel]:
        """Return models available to the current Qoder account."""
        client = self._new_client(
            QoderAgentOptions(
                auth=self._auth(),
                cli_path=self._require_resolution().path,
            ),
        )
        try:
            async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                await client.connect()
                catalog = await client.get_available_models()
        finally:
            await client.disconnect()
        models: list[HarnessModel] = []
        for item in catalog:
            if not item.get("isEnabled", True):
                continue
            thinking = item.get("thinking_config") or {}
            enabled = thinking.get("enabled") or {}
            efforts_data = enabled.get("efforts") or {}
            efforts = [str(value) for value in efforts_data]
            default_effort = next(
                (
                    str(value)
                    for value, metadata in efforts_data.items()
                    if metadata.get("is_default")
                ),
                None,
            )
            model_id = str(item.get("value") or "")
            models.append(
                HarnessModel(
                    id=model_id,
                    name=str(item.get("displayName") or model_id),
                    description=str(item.get("description") or ""),
                    is_default=model_id == "auto",
                    reasoning_efforts=efforts,
                    default_reasoning_effort=default_effort,
                ),
            )
        if models and not any(model.is_default for model in models):
            models[0].is_default = True
        return [model for model in models if model.id]

    async def history(self, session_id: str) -> list[HarnessHistoryItem]:
        """Read Qoder's local JSONL transcript through the official SDK."""
        qoder_session_id = self._sessions.get(session_id)
        context = self._contexts.get(session_id) or {}
        cwd = context.get("cwd")
        if not qoder_session_id:
            return []
        messages = await asyncio.to_thread(
            get_session_messages,
            qoder_session_id,
            str(cwd) if cwd else None,
        )
        history: list[HarnessHistoryItem] = []
        for message in messages:
            history.extend(history_items(message))
        return history

    async def discover_skills(
        self,
        cwd: Path,
    ) -> list[HarnessDiscoveredSkill]:
        """Discover Qoder-owned Skills through the SDK handshake."""
        client = self._new_client(
            QoderAgentOptions(
                auth=self._auth(),
                cli_path=self._require_resolution().path,
                cwd=cwd,
                setting_sources=["user", "project", "local"],
                skills="all",
            ),
        )
        try:
            async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                await client.connect()
                info = await client.get_server_info()
        finally:
            await client.disconnect()
        discovered: list[HarnessDiscoveredSkill] = []
        seen: set[tuple[str, str]] = set()
        for item in (info or {}).get("skills", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            source = str(item.get("source") or "")
            key = (name, source)
            if not name or name.startswith("qwenpaw-runtime:") or key in seen:
                continue
            seen.add(key)
            discovered.append(
                HarnessDiscoveredSkill(
                    name=name,
                    description=str(item.get("description") or ""),
                    provider_id="qoder",
                    source=source,
                ),
            )
        return discovered

    async def run_turn(  # pylint: disable=invalid-overridden-method
        self,
        *,
        session_id: str,
        prompt: str,
        cwd: Path,
        settings: dict[str, Any],
        attachments: list[HarnessAttachment] | None = None,
    ) -> AsyncIterator[HarnessEvent]:
        """Send one turn to a persistent Qoder SDK client."""
        self._contexts[session_id] = {
            "session_id": session_id,
            "cwd": str(cwd),
            **dict(settings.get("_request_context") or {}),
        }
        client = await self._client_for_session(
            session_id,
            cwd,
            settings,
        )
        mapper = QoderEventMapper()
        try:
            query_input: str | AsyncIterator[dict[str, Any]] = prompt
            if attachments:
                query_input = self._attachment_input(
                    prompt,
                    cwd,
                    attachments,
                )
            await client.query(query_input)
            async for message in client.receive_response():
                for event in mapper.convert(message):
                    yield event
        except asyncio.CancelledError:
            await asyncio.shield(client.interrupt())
            raise

    async def _attachment_input(
        self,
        prompt: str,
        cwd: Path,
        attachments: list[HarnessAttachment],
    ) -> AsyncIterator[dict[str, Any]]:
        """Build one Qoder SDK user message with images and file mentions."""
        content: list[dict[str, Any]] = []
        file_references: list[str] = []
        for attachment in attachments:
            if attachment.kind == HarnessAttachmentKind.IMAGE:
                image_data = await read_bytes_async(attachment.path)
                media_type = (
                    mimetypes.guess_type(attachment.path.name)[0]
                    or "image/png"
                )
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.b64encode(image_data).decode(
                                "ascii",
                            ),
                        },
                    },
                )
                continue
            file_references.append(
                self._file_reference(attachment.path, cwd),
            )
        text = "\n".join(
            part for part in (" ".join(file_references), prompt) if part
        )
        if text:
            content.insert(0, {"type": "text", "text": text})
        yield {
            "type": "user",
            "message": {
                "role": "user",
                "content": content,
            },
            "parent_tool_use_id": None,
        }

    @staticmethod
    def _file_reference(path: Path, cwd: Path) -> str:
        """Return a Qoder @file reference portable across host platforms."""
        resolved_path = path.expanduser().resolve(strict=False)
        resolved_cwd = cwd.expanduser().resolve(strict=False)
        try:
            display_path = resolved_path.relative_to(resolved_cwd)
        except ValueError:
            display_path = resolved_path
        path_text = display_path.as_posix()
        if any(character.isspace() for character in path_text):
            escaped_path = path_text.replace("\\", "\\\\").replace(
                '"',
                '\\"',
            )
            return f'@"{escaped_path}"'
        return f"@{path_text}"

    async def run_command(
        self,
        *,
        session_id: str,
        command: str,
        arguments: str,
        cwd: Path,
        settings: dict[str, Any],
    ) -> list[HarnessEvent]:
        """Execute a Qoder local slash command through the same session."""
        if command != "compact":
            return await super().run_command(
                session_id=session_id,
                command=command,
                arguments=arguments,
                cwd=cwd,
                settings=settings,
            )
        prompt = f"/{command}"
        if arguments:
            prompt = f"{prompt} {arguments}"
        return [
            event
            async for event in self.run_turn(
                session_id=session_id,
                prompt=prompt,
                cwd=cwd,
                settings=settings,
            )
        ]

    async def reset_session(self, session_id: str) -> None:
        """Disconnect and remove one Qoder conversation."""
        async with self._session_lock:
            client = self._clients.pop(session_id, None)
            self._client_keys.pop(session_id, None)
            self._contexts.pop(session_id, None)
            qoder_session_id = self._sessions.pop(session_id, None)
            if client is not None:
                await client.disconnect()
            if qoder_session_id:
                await asyncio.to_thread(delete_session, qoder_session_id)
            await write_json_atomic_async(
                self._session_path,
                self._sessions,
            )

    async def stop(self) -> None:
        """Disconnect every Qoder SDK client owned by this adapter."""
        async with self._session_lock:
            for client in tuple(self._clients.values()):
                await client.disconnect()
            self._clients.clear()
            self._client_keys.clear()
        if self._login_process is not None:
            if self._login_process.returncode is None:
                self._login_process.terminate()
                await self._login_process.wait()
            self._login_process = None

    async def _client_for_session(
        self,
        session_id: str,
        cwd: Path,
        settings: dict[str, Any],
    ) -> Any:
        key = self._client_key(cwd, settings)
        existing = self._clients.get(session_id)
        if existing is not None and self._client_keys.get(session_id) == key:
            return existing
        capabilities = settings.get("_runtime_capabilities")
        if not isinstance(capabilities, HarnessRuntimeCapabilities):
            capabilities = HarnessRuntimeCapabilities()
        plugin_path = await asyncio.to_thread(
            materialize_skill_plugin,
            self._state_dir,
            capabilities,
        )
        async with self._session_lock:
            existing = self._clients.get(session_id)
            if (
                existing is not None
                and self._client_keys.get(session_id) == key
            ):
                return existing
            if existing is not None:
                await existing.disconnect()
            qoder_session_id = self._sessions.get(session_id)
            is_resume = bool(qoder_session_id)
            qoder_session_id = qoder_session_id or str(uuid.uuid4())
            options = self._options(
                session_id=session_id,
                qoder_session_id=qoder_session_id,
                is_resume=is_resume,
                cwd=cwd,
                settings=settings,
                plugin_path=plugin_path,
            )
            client = self._new_client(options)
            async with asyncio.timeout(_CONNECT_TIMEOUT_SECONDS):
                await client.connect()
            if not is_resume:
                self._sessions[session_id] = qoder_session_id
                await write_json_atomic_async(
                    self._session_path,
                    self._sessions,
                )
            self._clients[session_id] = client
            self._client_keys[session_id] = key
            return client

    def _options(
        self,
        *,
        session_id: str,
        qoder_session_id: str,
        is_resume: bool,
        cwd: Path,
        settings: dict[str, Any],
        plugin_path: Path | None,
    ) -> QoderAgentOptions:
        permission_mode = str(settings.get("permission_mode") or "default")
        effort = settings.get("reasoning_effort")
        capabilities = settings.get("_runtime_capabilities")
        if not isinstance(capabilities, HarnessRuntimeCapabilities):
            capabilities = HarnessRuntimeCapabilities()
        projected_mcp = mcp_servers(capabilities)
        extra_args = {}
        if effort in {"low", "medium", "high", "max"}:
            extra_args["reasoning-effort"] = effort
        return QoderAgentOptions(
            auth=self._auth(),
            cli_path=self._require_resolution().path,
            cwd=cwd,
            resume=qoder_session_id if is_resume else None,
            session_id=None if is_resume else qoder_session_id,
            model=str(settings.get("model") or "") or None,
            extra_args=extra_args,
            include_partial_messages=True,
            permission_mode=permission_mode,
            allow_dangerously_skip_permissions=permission_mode
            in {"bypassPermissions", "yolo"},
            can_use_tool=lambda tool_name, input_data, context: (
                self._approve_tool(
                    session_id,
                    tool_name,
                    input_data,
                    context,
                )
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

    async def _approve_tool(
        self,
        session_id: str,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        request_context = self._contexts.get(session_id) or {}
        detail = context.description or context.decision_reason or tool_name
        summary = ApprovalRequestSummary(
            source_type="qoder",
            name=context.display_name or context.title or tool_name,
            severity="high" if tool_name == "Bash" else "medium",
            result_summary=detail,
            payload={
                "provider": "qoder",
                "provider_item_id": context.tool_use_id,
                "tool_name": tool_name,
                "input": input_data,
                "blocked_path": context.blocked_path,
            },
        )
        service = get_approval_service()
        pending = await service.create_pending_summary(
            session_id=session_id,
            root_session_id=session_id,
            owner_agent_id=str(
                request_context.get("agent_id") or "default",
            ),
            user_id=str(request_context.get("user_id") or "default"),
            channel=str(request_context.get("channel") or "console"),
            agent_id=str(request_context.get("agent_id") or "default"),
            summary=summary,
        )
        decision = await service.wait_for_approval(
            pending.request_id,
            pending.timeout_seconds,
        )
        if decision == ApprovalDecision.APPROVED:
            return PermissionResultAllow(updated_input=input_data)
        return PermissionResultDeny(message="Rejected by the user.")

    async def _run_cli(self, *arguments: str) -> str:
        resolution = self._require_resolution()
        process = await asyncio.create_subprocess_exec(
            str(resolution.path),
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            async with asyncio.timeout(_STATUS_TIMEOUT_SECONDS):
                stdout, _ = await process.communicate()
        except BaseException:
            if process.returncode is None:
                process.kill()
            await asyncio.shield(process.wait())
            raise
        return stdout.decode(errors="replace")

    def _resolution(self) -> QoderBinaryResolution | None:
        return resolve_qoder_binary_info(self._binary)

    def _require_resolution(self) -> QoderBinaryResolution:
        resolution = self._resolution()
        if resolution is None:
            raise RuntimeError("Qoder CLI executable was not found.")
        return resolution

    def _provider(
        self,
        resolution: QoderBinaryResolution,
        *,
        authenticated: bool = False,
        account: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> HarnessProvider:
        return HarnessProvider(
            id="qoder",
            name="Qoder",
            available=True,
            installed=True,
            authenticated=authenticated,
            account=account,
            runtime_path=str(resolution.path),
            runtime_source=resolution.source,
            error=error,
        )

    def _auth(self):
        if os.environ.get(_AUTH_ENV):
            return access_token_from_env()
        return qodercli_auth()

    def _new_client(self, options: QoderAgentOptions) -> Any:
        return self._client_factory(options)

    def _client_key(
        self,
        cwd: Path,
        settings: dict[str, Any],
    ) -> tuple[Any, ...]:
        return (
            str(cwd.resolve()),
            str(settings.get("model") or ""),
            str(settings.get("reasoning_effort") or ""),
            str(settings.get("permission_mode") or "default"),
            _runtime_capability_fingerprint(settings),
        )

    def _load_sessions(self) -> dict[str, str]:
        try:
            raw = read_json(self._session_path)
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            str(key): str(value) for key, value in raw.items() if key and value
        }

    @staticmethod
    def _status_fields(output: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        for line in output.splitlines():
            label, separator, value = line.partition(":")
            normalized_label = label.strip().lower()
            if separator and normalized_label in {
                "account",
                "email",
                "username",
            }:
                fields[normalized_label] = value.strip()
        return fields


__all__ = ["QoderAdapter"]


def _runtime_capability_fingerprint(
    settings: dict[str, Any],
) -> str:
    capabilities = settings.get("_runtime_capabilities")
    if isinstance(capabilities, HarnessRuntimeCapabilities):
        return capabilities.fingerprint
    return ""
