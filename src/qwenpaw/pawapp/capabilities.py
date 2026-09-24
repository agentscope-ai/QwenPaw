# -*- coding: utf-8 -*-
"""Scoped Host capability consumption and App-private registries."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import inspect
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi.encoders import jsonable_encoder
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field

from .tasks.contracts import TaskScope

_MAX_SKILL_BYTES = 2 * 1024 * 1024
_TOKEN_LIFETIME_SECONDS = 7 * 24 * 3600


class CapabilityError(Exception):
    """Stable broker error that never contains tool inputs or secrets."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class CapabilityScope(BaseModel):
    """Host-resolved identity attached to every capability operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    principal_id: str = Field(min_length=1, max_length=256)
    workspace_id: str = Field(min_length=1, max_length=256)
    app_id: str = Field(min_length=1, max_length=256)
    task_id: str | None = Field(default=None, max_length=256)
    session_id: str = Field(default="", max_length=512)

    @property
    def task_scope(self) -> TaskScope:
        return TaskScope(
            principal_id=self.principal_id,
            workspace_id=self.workspace_id,
            app_id=self.app_id,
        )


class CapabilityDescriptor(BaseModel):
    """Serializable tool or Skill metadata exposed to an App runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capability_id: str
    name: str
    wire_name: str
    kind: Literal["tool", "skill"]
    scope: Literal["host_public", "app_private"]
    description: str = ""
    input_schema: dict[str, Any] | None = None
    tool_refs: tuple[str, ...] = ()
    is_read_only: bool = False
    digest: str
    available: bool = True
    blocked_reason: str | None = None


@dataclass(frozen=True)
class _ResolvedTool:
    descriptor: CapabilityDescriptor
    callable: Any
    guarded: bool


@dataclass(frozen=True)
class _ResolvedSkill:
    descriptor: CapabilityDescriptor
    directory: Path


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _tool_schema(func: Any, explicit: dict[str, Any] | None = None) -> dict:
    if explicit is not None:
        schema = dict(explicit)
    else:
        from agentscope.tool import FunctionTool

        schema = dict(FunctionTool(func).input_schema)
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


def _skill_dirs(root: Path) -> list[Path]:
    if (root / "SKILL.md").is_file():
        return [root]
    try:
        return [
            child
            for child in sorted(root.iterdir(), key=lambda item: item.name)
            if child.is_dir() and (child / "SKILL.md").is_file()
        ]
    except OSError:
        return []


def _read_skill_header(directory: Path) -> tuple[str, str, tuple[str, ...]]:
    from qwenpaw.agents.skill_system.store import (
        read_skill_content_and_metadata_from_dir,
    )

    result = read_skill_content_and_metadata_from_dir(
        directory.name,
        directory,
        source="pawapp-private",
    )
    if result is None:
        raise CapabilityError("skill_unavailable")
    content, metadata = result
    refs: tuple[str, ...] = ()
    try:
        import frontmatter

        raw = frontmatter.loads(content).metadata.get("tool_refs", ())
        if isinstance(raw, list) and all(
            isinstance(item, str) for item in raw
        ):
            refs = tuple(raw)
    except Exception:  # noqa: BLE001
        refs = ()
    return content, str(metadata.get("description") or ""), refs


class CapabilityBroker:
    """Resolve, authorize, invoke, and audit capabilities for PawApps."""

    def __init__(
        self,
        *,
        workspace_manager: Any,
        plugin_registry: Any,
        task_runtime: Any = None,
        state_dir: Path,
    ) -> None:
        self._workspaces = workspace_manager
        self._plugins = plugin_registry
        self._tasks = task_runtime
        self._state_dir = state_dir
        self._secret = self._load_secret(state_dir / "capability.key")
        self._audit_path = state_dir / "capability-audit.jsonl"
        self._audit_lock = asyncio.Lock()
        self._governors: dict[str, Any] = {}
        self._governor_lock = asyncio.Lock()

    async def aclose(self) -> None:
        """Stop capability-owned governance resources."""
        async with self._governor_lock:
            governors = list(self._governors.values())
            self._governors.clear()
        await asyncio.gather(
            *(asyncio.to_thread(governor.stop) for governor in governors),
            return_exceptions=True,
        )

    @staticmethod
    def _load_secret(path: Path) -> bytes:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            value = path.read_bytes()
        except FileNotFoundError:
            value = secrets.token_bytes(32)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                value = path.read_bytes()
            else:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(value)
                    handle.flush()
                    os.fsync(handle.fileno())
        if len(value) < 32:
            raise RuntimeError("invalid PawApp capability signing key")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return value

    def issue(self, scope: CapabilityScope, *, created_at: float) -> str:
        """Create a deterministic, expiring token bound to one task scope."""
        if not scope.task_id:
            raise CapabilityError("task_required")
        payload = {
            "v": 1,
            **scope.model_dump(mode="json"),
            "exp": int(created_at) + _TOKEN_LIFETIME_SECONDS,
        }
        encoded = _b64encode(_canonical_json(payload).encode("utf-8"))
        signature = _b64encode(
            hmac.new(
                self._secret,
                encoded.encode("ascii"),
                hashlib.sha256,
            ).digest(),
        )
        return f"{encoded}.{signature}"

    async def authorize_token(self, token: str) -> CapabilityScope:
        """Validate signature, expiry, and the current Host task binding."""
        try:
            encoded, signature = token.split(".", 1)
            expected = _b64encode(
                hmac.new(
                    self._secret,
                    encoded.encode("ascii"),
                    hashlib.sha256,
                ).digest(),
            )
            if not hmac.compare_digest(signature, expected):
                raise ValueError
            payload = json.loads(_b64decode(encoded))
            if (
                payload.pop("v", None) != 1
                or int(payload.pop("exp")) < time.time()
            ):
                raise ValueError
            scope = CapabilityScope.model_validate(payload)
        except (
            ValueError,
            TypeError,
            KeyError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            binascii.Error,
        ):
            raise CapabilityError("invalid_capability_token") from None
        if not scope.task_id or self._tasks is None:
            raise CapabilityError("invalid_capability_scope")
        try:
            submission = await self._tasks.get(scope.task_scope, scope.task_id)
        except Exception:
            raise CapabilityError("invalid_capability_scope") from None
        origin = submission.handle.origin
        expected_session = (
            origin.return_session_ref or origin.app_session_ref or ""
        )
        if expected_session != scope.session_id:
            raise CapabilityError("invalid_capability_scope")
        return scope

    async def catalog(
        self,
        scope: CapabilityScope,
    ) -> list[CapabilityDescriptor]:
        tools = await self._resolve_tools(scope)
        skills = await self._resolve_skills(scope, tools)
        return [
            *(item.descriptor for item in tools.values()),
            *(item.descriptor for item in skills.values()),
        ]

    async def host_skill_import_statuses(
        self,
        *,
        principal_id: str,
        workspace_id: str,
        app_ids: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        """Describe manifest-declared Host Skill imports for settings UI.

        This is an observability surface, not an authorization path. An App
        can still load only the capabilities resolved through its scoped
        token. Installation and enablement remain owned by the workspace's
        normal Skill settings.
        """
        from qwenpaw.agents.skill_system import (
            get_workspace_skills_dir,
            read_skill_manifest,
            resolve_effective_skills,
        )

        unique_app_ids = tuple(dict.fromkeys(app_ids))
        requested = {
            app_id: dict(
                self._plugins.get_pawapp_capabilities(app_id)["host_skills"],
            )
            for app_id in unique_app_ids
        }
        if not any(requested.values()):
            return []

        workspace = await self._workspace(
            CapabilityScope(
                principal_id=principal_id,
                workspace_id=workspace_id,
                app_id=unique_app_ids[0],
            ),
        )
        manifest = await asyncio.to_thread(
            read_skill_manifest,
            workspace.workspace_dir,
        )
        effective = set(
            await asyncio.to_thread(
                resolve_effective_skills,
                workspace.workspace_dir,
                "console",
            ),
        )
        skills_root = get_workspace_skills_dir(workspace.workspace_dir)
        manifest_skills = manifest.get("skills", {})

        statuses: list[dict[str, Any]] = []
        for app_id, imports in requested.items():
            scope = CapabilityScope(
                principal_id=principal_id,
                workspace_id=workspace_id,
                app_id=app_id,
            )
            declared_refs = {ref for refs in imports.values() for ref in refs}
            available_tools: set[str] = set()
            if declared_refs:
                available_tools = {
                    item.descriptor.name
                    for item in (await self._resolve_tools(scope)).values()
                }

            for skill_id, tool_refs in sorted(imports.items()):
                safe_name = Path(skill_id).name == skill_id
                skill_dir = skills_root / skill_id
                installed = bool(
                    safe_name and (skill_dir / "SKILL.md").is_file(),
                )
                raw_entry = (
                    manifest_skills.get(skill_id, {})
                    if isinstance(manifest_skills, dict)
                    else {}
                )
                enabled = bool(
                    isinstance(raw_entry, dict)
                    and raw_entry.get("enabled", False),
                )
                missing_tool_refs = tuple(
                    ref for ref in tool_refs if ref not in available_tools
                )
                description = ""
                if installed:
                    try:
                        _, description, _ = await asyncio.to_thread(
                            _read_skill_header,
                            skill_dir,
                        )
                    except CapabilityError:
                        description = ""

                if not installed:
                    status = "not_installed"
                elif not enabled:
                    status = "disabled"
                elif skill_id not in effective:
                    status = "unavailable"
                elif missing_tool_refs:
                    status = "tool_dependency_unavailable"
                else:
                    status = "available"
                statuses.append(
                    {
                        "app_id": app_id,
                        "skill_id": skill_id,
                        "description": description,
                        "tool_refs": list(tool_refs),
                        "missing_tool_refs": list(missing_tool_refs),
                        "installed": installed,
                        "enabled": enabled,
                        "available": status == "available",
                        "status": status,
                    },
                )
        return statuses

    async def describe(
        self,
        scope: CapabilityScope,
        capability_id: str,
    ) -> CapabilityDescriptor:
        entries = {
            item.capability_id: item for item in await self.catalog(scope)
        }
        try:
            return entries[capability_id]
        except KeyError:
            await self._audit(scope, capability_id, "describe", "scope_denied")
            raise CapabilityError("capability_not_found") from None

    async def invoke(
        self,
        scope: CapabilityScope,
        capability_id: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        tools = await self._resolve_tools(scope)
        resolved = tools.get(capability_id)
        if resolved is None:
            await self._audit(scope, capability_id, "invoke", "scope_denied")
            raise CapabilityError("capability_not_found")
        try:
            error = next(
                Draft202012Validator(
                    resolved.descriptor.input_schema or {"type": "object"},
                ).iter_errors(params),
                None,
            )
            if error is not None:
                raise CapabilityError("invalid_tool_input")
            if resolved.guarded:
                result = await self._invoke_guarded(scope, resolved, params)
            else:
                result = resolved.callable(**params)
                if inspect.isawaitable(result):
                    result = await result
            output = await self._encode_result(result)
        except CapabilityError as exc:
            await self._audit(scope, capability_id, "invoke", exc.code)
            raise
        except Exception:
            await self._audit(scope, capability_id, "invoke", "tool_failed")
            raise CapabilityError("tool_failed") from None
        await self._audit(scope, capability_id, "invoke", "allowed")
        return {"state": "success", "output": output}

    async def load_skill(
        self,
        scope: CapabilityScope,
        capability_id: str,
    ) -> dict[str, Any]:
        tools = await self._resolve_tools(scope)
        skill = (await self._resolve_skills(scope, tools)).get(capability_id)
        if skill is None:
            await self._audit(scope, capability_id, "load", "scope_denied")
            raise CapabilityError("capability_not_found")
        if not skill.descriptor.available:
            await self._audit(
                scope,
                capability_id,
                "load",
                skill.descriptor.blocked_reason or "dependency_unavailable",
            )
            raise CapabilityError(
                skill.descriptor.blocked_reason or "dependency_unavailable",
            )
        try:
            files = await asyncio.to_thread(
                self._read_skill_files,
                skill.directory,
            )
        except CapabilityError as exc:
            await self._audit(scope, capability_id, "load", exc.code)
            raise
        await self._audit(scope, capability_id, "load", "allowed")
        return {
            "descriptor": skill.descriptor.model_dump(mode="json"),
            "files": files,
        }

    async def _workspace(self, scope: CapabilityScope) -> Any:
        try:
            return await self._workspaces.get_agent(scope.workspace_id)
        except Exception:
            raise CapabilityError("workspace_unavailable") from None

    async def _resolve_tools(
        self,
        scope: CapabilityScope,
    ) -> dict[str, _ResolvedTool]:
        config = self._plugins.get_pawapp_capabilities(scope.app_id)
        request_context = {
            "agent_id": scope.workspace_id,
            "user_id": scope.principal_id,
            "session_id": scope.session_id,
            "root_session_id": scope.session_id,
            "channel": "console",
            "pawapp_id": scope.app_id,
            "pawapp_task_id": scope.task_id or "",
        }
        workspace = None
        enabled: dict[str, Any] = {}
        if config["host_tools"]:
            workspace = await self._workspace(scope)
            enabled = {
                tool.name: tool
                for tool in await workspace.local_workspace.list_tools(
                    agent_config=workspace.config,
                    agent_id=scope.workspace_id,
                    request_context=request_context,
                )
            }
        resolved: dict[str, _ResolvedTool] = {}
        public_names = config["host_tools"]
        local_names = set(config["local_tools"])
        collisions = public_names & local_names
        for name in sorted(public_names):
            tool = enabled.get(name)
            if tool is None:
                continue
            capability_id = f"host/tool/{name}"
            descriptor = CapabilityDescriptor(
                capability_id=capability_id,
                name=name,
                wire_name=f"host__{name}" if name in collisions else name,
                kind="tool",
                scope="host_public",
                description=str(getattr(tool, "description", "") or ""),
                input_schema=dict(getattr(tool, "input_schema", {}) or {}),
                is_read_only=bool(getattr(tool, "is_read_only", False)),
                digest=_digest(
                    {
                        "name": name,
                        "description": getattr(tool, "description", "") or "",
                        "input_schema": getattr(tool, "input_schema", {})
                        or {},
                        "is_read_only": bool(
                            getattr(tool, "is_read_only", False),
                        ),
                    },
                ),
            )
            raw = workspace.plugins.tool_registry.get(name)
            if raw is not None:
                resolved[capability_id] = _ResolvedTool(
                    descriptor,
                    raw.func,
                    True,
                )
        for name, registration in sorted(config["local_tools"].items()):
            schema = _tool_schema(registration.func, registration.input_schema)
            capability_id = f"app/tool/{name}"
            descriptor = CapabilityDescriptor(
                capability_id=capability_id,
                name=name,
                wire_name=f"app__{name}" if name in collisions else name,
                kind="tool",
                scope="app_private",
                description=registration.description,
                input_schema=schema,
                is_read_only=registration.is_read_only,
                digest=_digest(
                    {
                        "app_id": scope.app_id,
                        "name": name,
                        "description": registration.description,
                        "input_schema": schema,
                        "is_read_only": registration.is_read_only,
                    },
                ),
            )
            resolved[capability_id] = _ResolvedTool(
                descriptor,
                registration.func,
                False,
            )
        return resolved

    async def _resolve_skills(
        self,
        scope: CapabilityScope,
        tools: dict[str, _ResolvedTool],
    ) -> dict[str, _ResolvedSkill]:
        from qwenpaw.agents.skill_system import (
            get_workspace_skills_dir,
            resolve_effective_skills,
        )

        config = self._plugins.get_pawapp_capabilities(scope.app_id)
        resolved: dict[str, _ResolvedSkill] = {}
        public_names = set(config["host_skills"])
        effective: set[str] = set()
        root: Path | None = None
        if public_names:
            workspace = await self._workspace(scope)
            effective = set(
                await asyncio.to_thread(
                    resolve_effective_skills,
                    workspace.workspace_dir,
                    "console",
                ),
            )
            root = get_workspace_skills_dir(workspace.workspace_dir)
        private_dirs = [
            directory
            for registered in config["local_skill_dirs"]
            for directory in _skill_dirs(Path(registered))
        ]
        private_names = {directory.name for directory in private_dirs}
        collisions = public_names & private_names

        def tool_refs(
            refs: tuple[str, ...],
            preferred_scope: str,
        ) -> tuple[tuple[str, ...], list[str]]:
            found: list[str] = []
            missing: list[str] = []
            for ref in refs:
                match = tools.get(ref)
                if match is None:
                    candidates = [
                        item
                        for item in tools.values()
                        if item.descriptor.name == ref
                    ]
                    match = next(
                        (
                            item
                            for item in candidates
                            if item.descriptor.scope == preferred_scope
                        ),
                        candidates[0] if len(candidates) == 1 else None,
                    )
                if match is None:
                    missing.append(ref)
                else:
                    found.append(match.descriptor.wire_name)
            return tuple(found), missing

        for name, refs in sorted(config["host_skills"].items()):
            assert root is not None
            directory = root / name
            if name not in effective or not (directory / "SKILL.md").is_file():
                continue
            _, description, _ = _read_skill_header(directory)
            resolved_refs, missing = tool_refs(refs, "host_public")
            capability_id = f"host/skill/{name}"
            resolved[capability_id] = _ResolvedSkill(
                CapabilityDescriptor(
                    capability_id=capability_id,
                    name=name,
                    wire_name=f"host__{name}" if name in collisions else name,
                    kind="skill",
                    scope="host_public",
                    description=description,
                    tool_refs=resolved_refs,
                    digest=self._skill_digest(directory),
                    available=not missing,
                    blocked_reason=(
                        "skill_dependency_unavailable" if missing else None
                    ),
                ),
                directory,
            )
        for directory in private_dirs:
            content, description, refs = _read_skill_header(directory)
            del content
            resolved_refs, missing = tool_refs(refs, "app_private")
            name = directory.name
            capability_id = f"app/skill/{name}"
            resolved[capability_id] = _ResolvedSkill(
                CapabilityDescriptor(
                    capability_id=capability_id,
                    name=name,
                    wire_name=f"app__{name}" if name in collisions else name,
                    kind="skill",
                    scope="app_private",
                    description=description,
                    tool_refs=resolved_refs,
                    digest=self._skill_digest(directory),
                    available=not missing,
                    blocked_reason=(
                        "skill_dependency_unavailable" if missing else None
                    ),
                ),
                directory,
            )
        return resolved

    async def _invoke_guarded(
        self,
        scope: CapabilityScope,
        resolved: _ResolvedTool,
        params: dict[str, Any],
    ) -> Any:
        from agentscope.permission import PermissionBehavior, PermissionContext
        from qwenpaw.governance import ResourceGovernor
        from qwenpaw.governance.tool_adapter import PolicyGuardedTool

        workspace = await self._workspace(scope)
        governor = self._governors.get(scope.workspace_id)
        if governor is None:
            async with self._governor_lock:
                governor = self._governors.get(scope.workspace_id)
                if governor is None:
                    governor = ResourceGovernor(str(workspace.workspace_dir))
                    await asyncio.to_thread(governor.start)
                    self._governors[scope.workspace_id] = governor
        tool = PolicyGuardedTool(
            resolved.callable,
            name=resolved.descriptor.name,
            description=resolved.descriptor.description,
            input_schema=resolved.descriptor.input_schema,
            governor=governor,
            request_context={
                "agent_id": scope.workspace_id,
                "user_id": scope.principal_id,
                "session_id": scope.session_id,
                "root_session_id": scope.session_id,
                "channel": "console",
                "pawapp_id": scope.app_id,
                "pawapp_task_id": scope.task_id or "",
            },
        )
        decision = await tool.check_permissions(params, PermissionContext())
        if decision.behavior is not PermissionBehavior.ALLOW:
            raise CapabilityError("tool_permission_denied")
        return await tool(**params)

    @staticmethod
    async def _encode_result(result: Any) -> Any:
        if inspect.isasyncgen(result):
            chunks = [chunk async for chunk in result]
            return jsonable_encoder(chunks)
        return jsonable_encoder(result)

    @staticmethod
    def _skill_digest(directory: Path) -> str:
        entries: list[tuple[str, str]] = []
        for path in sorted(directory.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(directory).as_posix()
            entries.append(
                (rel, hashlib.sha256(path.read_bytes()).hexdigest()),
            )
        return _digest(entries)

    @staticmethod
    def _read_skill_files(directory: Path) -> list[dict[str, str]]:
        files: list[dict[str, str]] = []
        total = 0
        for path in sorted(directory.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                data = path.read_bytes()
            except OSError:
                raise CapabilityError("skill_unavailable") from None
            total += len(data)
            if total > _MAX_SKILL_BYTES:
                raise CapabilityError("skill_too_large")
            rel = path.relative_to(directory).as_posix()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                files.append(
                    {
                        "path": rel,
                        "encoding": "base64",
                        "content": base64.b64encode(data).decode("ascii"),
                    },
                )
            else:
                files.append(
                    {"path": rel, "encoding": "utf-8", "content": text},
                )
        if not any(item["path"] == "SKILL.md" for item in files):
            raise CapabilityError("skill_unavailable")
        return files

    async def _audit(
        self,
        scope: CapabilityScope,
        capability_id: str,
        action: str,
        outcome: str,
    ) -> None:
        entry = {
            "timestamp": time.time(),
            "principal_id": scope.principal_id,
            "workspace_id": scope.workspace_id,
            "app_id": scope.app_id,
            "task_id": scope.task_id,
            "capability_id": capability_id,
            "action": action,
            "outcome": outcome,
        }
        line = _canonical_json(entry) + "\n"
        async with self._audit_lock:
            await asyncio.to_thread(self._append_audit, line)

    def _append_audit(self, line: str) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        with self._audit_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
            handle.flush()


def capability_endpoint() -> str:
    """Resolve the loopback Host endpoint advertised to managed runtimes."""
    from qwenpaw.config.utils import read_last_api

    host, port = read_last_api() or ("127.0.0.1", 8088)
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/api/pawapp-capabilities"


def task_capability_bridge(submission: Any) -> dict[str, Any]:
    """Build the scoped bridge envelope sent with one durable submission."""
    from qwenpaw.constant import WORKING_DIR
    from qwenpaw.plugins.registry import PluginRegistry

    registry = PluginRegistry()
    handle = submission.handle
    session_id = (
        handle.origin.return_session_ref or handle.origin.app_session_ref or ""
    )
    scope = CapabilityScope(
        principal_id=handle.scope.principal_id,
        workspace_id=handle.scope.workspace_id,
        app_id=handle.scope.app_id,
        task_id=handle.task_id,
        session_id=session_id,
    )
    issuer = CapabilityBroker(
        workspace_manager=registry.get_workspace_manager(),
        plugin_registry=registry,
        state_dir=Path(WORKING_DIR) / "pawapp",
    )
    return {
        "protocol_version": 1,
        "endpoint": capability_endpoint(),
        "token": issuer.issue(scope, created_at=handle.created_at),
    }


__all__ = [
    "CapabilityBroker",
    "CapabilityDescriptor",
    "CapabilityError",
    "CapabilityScope",
    "capability_endpoint",
    "task_capability_bridge",
]
