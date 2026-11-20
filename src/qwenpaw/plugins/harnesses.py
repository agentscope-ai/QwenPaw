# -*- coding: utf-8 -*-
"""Public, vendor-independent harness declarations and invocation values.

Factories run on the host event loop when a backend is first used. Keep
construction free of blocking discovery; offload bounded filesystem work
inside asynchronous backend operations instead.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field, fields
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Protocol, TYPE_CHECKING

from pydantic import SecretStr

from .errors import SDKError
from .resources import ResourceScope
from .storage import PluginStorage
from .tools import ConfigField

if TYPE_CHECKING:
    from .logging import PluginLogger

MCPTransport = Literal["stdio", "streamable_http", "sse"]
MCPToolPolicy = Literal["allow", "ask", "deny"]
HarnessApprovalDecision = Literal[
    "approved",
    "rejected",
    "cancelled",
    "timeout",
]


class HarnessOperationNotSupportedError(SDKError):
    """The backend does not support the requested operation."""


class HarnessAttachmentKind(str, Enum):
    IMAGE = "image"
    FILE = "file"


class HarnessEventKind(str, Enum):
    TEXT_DELTA = "text_delta"
    REASONING_DELTA = "reasoning_delta"
    TOOL_STARTED = "tool_started"
    TOOL_PROGRESS = "tool_progress"
    TOOL_COMPLETED = "tool_completed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"


class HarnessHistoryKind(str, Enum):
    USER = "user"
    MESSAGE = "message"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    TOOL_OUTPUT = "tool_output"


@dataclass(frozen=True)
class HarnessAttachment:
    kind: HarnessAttachmentKind
    path: Path
    name: str = ""


@dataclass(frozen=True)
class HarnessEvent:
    kind: HarnessEventKind
    text: str = ""
    item_id: str = ""
    tool_name: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessHistoryItem:
    kind: HarnessHistoryKind
    text: str = ""
    item_id: str = ""
    tool_name: str = ""
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessCommand:
    name: str
    description: str = ""
    accepts_arguments: bool = False


@dataclass(frozen=True)
class HarnessApprovalPreset:
    id: str
    name: str
    description: str = ""
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessCapabilities:
    authentication: bool = False
    model_selection: bool = False
    reasoning_effort: bool = False
    reasoning_stream: bool = False
    tool_stream: bool = False
    session_resume: bool = False
    workspace_ui: bool = False
    native_skills_ui: bool = False
    native_tools_ui: bool = False
    native_mcp_ui: bool = False
    loop_modes: bool = False
    attachments: bool = False
    context_usage: bool = False
    skills_commands: bool = False
    qwenpaw_skills_projection: bool = False
    qwenpaw_mcp_projection: bool = False
    provider_skills_discovery: bool = False
    provider_mcp_discovery: bool = False
    mcp_tool_allowlist: bool = False
    external_history: bool = False
    commands: tuple[HarnessCommand, ...] = ()
    approval_presets: tuple[HarnessApprovalPreset, ...] = ()

    def __post_init__(self):
        for attribute in fields(self):
            value = getattr(self, attribute.name)
            if attribute.name in {"commands", "approval_presets"}:
                expected = (
                    HarnessCommand
                    if attribute.name == "commands"
                    else HarnessApprovalPreset
                )
                if not isinstance(value, tuple) or not all(
                    isinstance(item, expected) for item in value
                ):
                    raise SDKError(
                        f"{attribute.name} must be a tuple of "
                        f"{expected.__name__}",
                    )
            elif not isinstance(value, bool):
                raise SDKError(f"{attribute.name} must be boolean")


@dataclass(frozen=True)
class HarnessModel:
    id: str
    name: str
    description: str = ""
    is_default: bool = False
    reasoning_efforts: tuple[str, ...] = ()
    default_reasoning_effort: str | None = None


@dataclass(frozen=True)
class HarnessDiscoveredMCPServer:
    name: str
    provider_id: str
    transport: str
    enabled: bool
    auth_status: str = ""
    read_only: bool = True
    scope: str = "provider"


@dataclass(frozen=True)
class HarnessDiscoveredSkill:
    name: str
    provider_id: str
    description: str = ""
    source: str = ""
    enabled: bool = True
    read_only: bool = True
    scope: str = "provider"


@dataclass(frozen=True)
class HarnessStatus:
    installed: bool = False
    authenticated: bool = False
    account: dict[str, Any] | None = None
    runtime_path: str | None = None
    runtime_source: str | None = None
    error: str | None = None
    available: bool = False


@dataclass(frozen=True)
class HarnessLogin:
    """Backend-owned JSON login metadata, preserving vendor wire fields."""

    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessSkillDefinition:
    name: str
    directory: Path
    description: str = ""
    revision: str = ""


class _SecretMapping(dict):
    """Read-only credential mapping compatible with dataclasses.asdict."""

    def __init__(self, values=()):
        super().__init__(
            (key, value if isinstance(value, SecretStr) else SecretStr(value))
            for key, value in dict(values).items()
        )

    def _readonly(self, *args, **kwargs):
        raise TypeError("Harness credentials are read-only")

    __setitem__ = __delitem__ = clear = pop = popitem = _readonly
    setdefault = update = __ior__ = _readonly

    def __deepcopy__(self, memo):
        return type(self)(self)


@dataclass(frozen=True)
class HarnessMCPServerDefinition:
    name: str
    display_name: str
    transport: MCPTransport
    command: str = ""
    args: tuple[str, ...] = ()
    cwd: Path | None = None
    url: str = ""
    env: dict[str, SecretStr] = field(default_factory=dict)
    headers: dict[str, SecretStr] = field(default_factory=dict)
    tools: tuple[str, ...] | None = None
    tool_policies: dict[str, MCPToolPolicy] = field(default_factory=dict)
    default_policy: MCPToolPolicy = "ask"
    credential_revision: str = ""
    runtime_revision: str = ""

    def __post_init__(self):
        # Copy, wrap and freeze credentials so later mutation cannot expose
        # plaintext through repr or generic dataclass serialization.
        for attribute in ("env", "headers"):
            object.__setattr__(
                self,
                attribute,
                _SecretMapping(getattr(self, attribute)),
            )

    def revealed_env(self) -> dict[str, str]:
        return {
            key: value.get_secret_value() for key, value in self.env.items()
        }

    def revealed_headers(self) -> dict[str, str]:
        return {
            key: value.get_secret_value()
            for key, value in self.headers.items()
        }

    def fingerprint_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "args": self.args,
            "cwd": str(self.cwd or ""),
            "url": self.url,
            "env_keys": sorted(self.env),
            "header_keys": sorted(self.headers),
            "tools": self.tools,
            "tool_policies": self.tool_policies,
            "default_policy": self.default_policy,
            "credential_revision": self.credential_revision,
            "runtime_revision": self.runtime_revision,
        }


@dataclass(frozen=True)
class HarnessRuntimeCapabilities:
    skills: tuple[HarnessSkillDefinition, ...] = ()
    mcp_servers: tuple[HarnessMCPServerDefinition, ...] = ()

    @property
    def fingerprint(self) -> str:
        payload = {
            "skills": [
                {
                    "name": skill.name,
                    "directory": str(skill.directory),
                    "revision": skill.revision,
                }
                for skill in self.skills
            ],
            "mcp_servers": [
                server.fingerprint_payload() for server in self.mcp_servers
            ],
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode(),
        ).hexdigest()


@dataclass(frozen=True)
class HarnessContext:
    plugin_id: str
    generation: int
    workspace_id: str
    workspace_dir: Path
    state_dir: Path
    storage: PluginStorage
    resources: ResourceScope
    logger: PluginLogger


@dataclass(frozen=True)
class HarnessApprovalSummary:
    tool_name: str
    title: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    severity: str = ""

    def __post_init__(self):
        # Approval crosses a host boundary; retain only a JSON snapshot.
        try:
            snapshot = json.loads(json.dumps(self.parameters, allow_nan=False))
        except (TypeError, ValueError) as exc:
            raise SDKError(
                "Approval parameters must contain only JSON values",
            ) from exc
        if not isinstance(snapshot, dict):
            raise SDKError("Approval parameters must be a JSON object")
        object.__setattr__(self, "parameters", snapshot)


@dataclass(frozen=True)
class HarnessCallContext:
    """Invocation values with a fresh deep copy of all effective settings."""

    request_id: str
    session_id: str
    user_id: str
    channel: str
    cwd: Path
    settings: dict[str, Any]
    runtime_capabilities: HarnessRuntimeCapabilities | None
    resources: ResourceScope
    deadline: float | None = None
    cancelled: bool = False
    _request_approval: (
        Callable[..., Awaitable[HarnessApprovalDecision]] | None
    ) = field(default=None, repr=False, compare=False)

    async def request_approval(
        self,
        summary: HarnessApprovalSummary,
        *,
        timeout: float,
    ) -> HarnessApprovalDecision:
        if self.cancelled:
            return "cancelled"
        if self._request_approval is None:
            raise HarnessOperationNotSupportedError(
                "Approval is unavailable in this call",
            )
        return await self._request_approval(summary, timeout=timeout)


@dataclass(frozen=True)
class HarnessRunRequest:
    prompt: str
    attachments: tuple[HarnessAttachment, ...] = ()


class HarnessBackend(Protocol):
    async def status(self, context: HarnessCallContext) -> HarnessStatus:
        ...

    async def start_login(
        self,
        context: HarnessCallContext,
        *,
        device_code: bool = False,
    ) -> HarnessLogin:
        ...

    async def logout(self, context: HarnessCallContext) -> None:
        ...

    async def models(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessModel, ...]:
        ...

    async def discover_skills(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessDiscoveredSkill, ...]:
        ...

    async def discover_mcp(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessDiscoveredMCPServer, ...]:
        ...

    def run_turn(
        self,
        context: HarnessCallContext,
        request: HarnessRunRequest,
    ) -> AsyncIterator[HarnessEvent]:
        ...

    async def run_command(
        self,
        context: HarnessCallContext,
        command: str,
        arguments: str,
    ) -> tuple[HarnessEvent, ...]:
        ...

    async def history(
        self,
        context: HarnessCallContext,
    ) -> tuple[HarnessHistoryItem, ...]:
        ...

    async def reset_session(self, context: HarnessCallContext) -> None:
        ...

    async def close(self) -> None:
        ...


class HarnessArchiveBackend(Protocol):
    async def list_external_threads(
        self,
        context: HarnessCallContext,
        *,
        limit: int,
        archived: bool,
    ) -> tuple[dict[str, Any], ...]:
        ...

    async def read_external_thread(
        self,
        context: HarnessCallContext,
        thread_id: str,
    ) -> tuple[HarnessHistoryItem, ...]:
        ...

    async def external_skill_records(
        self,
        context: HarnessCallContext,
    ) -> tuple[dict[str, Any], ...]:
        ...

    async def external_mcp_records(
        self,
        context: HarnessCallContext,
    ) -> tuple[dict[str, Any], ...]:
        ...


@dataclass(frozen=True)
class HarnessSpec:
    """Declare a lazy workspace backend and its constructor settings.

    ``instance_settings_keys`` selects the settings that determine instance
    reuse. The factory receives a fresh deep copy of declared, present keys;
    the default selects none. Every call still receives all effective
    settings in ``HarnessCallContext.settings``. Changing an instance setting
    replaces an idle backend and rejects replacement while it is busy.
    """

    id: str
    label: str
    create: Callable[
        [HarnessContext, dict[str, Any]],
        HarnessBackend | Awaitable[HarnessBackend],
    ]
    capabilities: HarnessCapabilities
    config_fields: tuple[ConfigField, ...] = ()
    description: str = ""
    icon: str = ""
    doc_url: str = ""
    instance_settings_keys: tuple[str, ...] = ()

    def __post_init__(self):
        if not isinstance(self.id, str) or not re.fullmatch(
            r"[a-z][a-z0-9_-]*",
            self.id,
        ):
            raise SDKError("Harness ID must match [a-z][a-z0-9_-]*")
        if self.id == "qwenpaw":
            raise SDKError("Harness ID 'qwenpaw' is reserved")
        if not isinstance(self.capabilities, HarnessCapabilities):
            raise SDKError("Harness capabilities must be HarnessCapabilities")
        if not callable(self.create):
            raise SDKError("Harness create must be callable")
        if not isinstance(self.instance_settings_keys, tuple) or any(
            not isinstance(key, str) or not key
            for key in self.instance_settings_keys
        ):
            raise SDKError(
                "Harness instance_settings_keys must be a tuple "
                "of nonempty strings",
            )


__all__ = [
    "HarnessSpec",
    "HarnessContext",
    "HarnessCallContext",
    "HarnessApprovalSummary",
    "HarnessApprovalDecision",
    "HarnessRunRequest",
    "HarnessEvent",
    "HarnessEventKind",
    "HarnessHistoryItem",
    "HarnessHistoryKind",
    "HarnessAttachment",
    "HarnessAttachmentKind",
    "HarnessCapabilities",
    "HarnessCommand",
    "HarnessApprovalPreset",
    "HarnessModel",
    "HarnessStatus",
    "HarnessLogin",
    "HarnessDiscoveredSkill",
    "HarnessDiscoveredMCPServer",
    "HarnessRuntimeCapabilities",
    "HarnessSkillDefinition",
    "HarnessMCPServerDefinition",
    "HarnessBackend",
    "HarnessArchiveBackend",
    "HarnessOperationNotSupportedError",
    "MCPTransport",
    "MCPToolPolicy",
]
