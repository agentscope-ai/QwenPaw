# -*- coding: utf-8 -*-
"""Resolve QwenPaw-managed capabilities for third-party harnesses."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from ...agents.skill_system import (
    ensure_skills_initialized,
    get_workspace_skills_dir,
    resolve_effective_skills,
)
from ...agents.skill_system.store import read_skill_from_dir
from ...app.driver_config_service import DriverConfigService
from ...drivers.constants import (
    CAPABILITY_KIND_TOOL,
    CREDENTIAL_ALIAS_DEFAULT,
    CREDENTIAL_KIND_NONE,
    DRIVER_OPERATION_INVOKE,
    PROTOCOL_MCP,
    SUBJECT_UNKNOWN_USER,
)
from ...drivers.contracts import CredentialRef, DriverCard
from ...drivers.credentials.bindings import (
    implicit_auth_headers,
    resolve_binding,
    resolve_credentials,
)
from ...drivers.credentials.providers import build_provider
from ...drivers.policy import DriverInvocationContext, evaluate_policy
from ...drivers.policy_types import PolicyTarget
from .models import (
    HarnessMCPServerDefinition,
    HarnessRuntimeCapabilities,
    HarnessSkillDefinition,
    MCPToolPolicy,
)


class HarnessCapabilityResolver:
    """Build effective runtime capabilities from QwenPaw control data."""

    def __init__(
        self,
        workspace_dir: Path,
        workspace: Any | None = None,
    ) -> None:
        self._workspace_dir = workspace_dir
        self._workspace = workspace or SimpleNamespace(
            workspace_dir=workspace_dir,
        )
        self._driver_config = DriverConfigService(self._workspace)

    async def resolve(
        self,
        request_context: dict[str, Any] | None = None,
    ) -> HarnessRuntimeCapabilities:
        """Resolve Skills and MCP servers for one request context."""
        context = {
            str(key): str(value)
            for key, value in dict(request_context or {}).items()
            if value is not None
        }
        channel = context.get("channel") or "console"
        return HarnessRuntimeCapabilities(
            skills=await asyncio.to_thread(
                self._resolve_skills,
                channel,
            ),
            mcp_servers=await self._resolve_mcp_servers(context),
        )

    def _resolve_skills(self, channel: str) -> list[HarnessSkillDefinition]:
        ensure_skills_initialized(self._workspace_dir)
        skills_dir = get_workspace_skills_dir(self._workspace_dir)
        result: list[HarnessSkillDefinition] = []
        for name in resolve_effective_skills(self._workspace_dir, channel):
            directory = (skills_dir / name).resolve()
            info = read_skill_from_dir(directory, "workspace")
            if info is None:
                continue
            result.append(
                HarnessSkillDefinition(
                    name=name,
                    description=info.description,
                    directory=directory,
                    revision=self._skill_revision(directory),
                ),
            )
        return result

    @staticmethod
    def _skill_revision(directory: Path) -> str:
        """Hash every regular projected file and its relative path."""
        digest = hashlib.sha256()
        paths = sorted(
            directory.rglob("*"),
            key=lambda item: item.relative_to(directory).as_posix(),
        )
        for path in paths:
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(directory).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            with path.open("rb") as file:
                while chunk := file.read(1024 * 1024):
                    digest.update(chunk)
        return digest.hexdigest()

    async def _resolve_mcp_servers(
        self,
        request_context: dict[str, str],
    ) -> list[HarnessMCPServerDefinition]:
        result: list[HarnessMCPServerDefinition] = []
        for card in await self._driver_config.list_cards(
            protocol=PROTOCOL_MCP,
        ):
            if not card.enabled:
                continue
            result.append(
                await self._resolve_mcp_server(card, request_context),
            )
        return result

    async def _resolve_mcp_server(
        self,
        card: DriverCard,
        request_context: dict[str, str],
    ) -> HarnessMCPServerDefinition:
        providers = self._credential_providers(card)
        try:
            credentials = await resolve_credentials(providers)
        finally:
            for provider in providers.values():
                await provider.close()

        endpoint = card.endpoint
        transport = str(endpoint.get("transport") or "stdio")
        env = resolve_binding(endpoint.get("env") or {}, credentials)
        headers = resolve_binding(
            endpoint.get("headers") or {},
            credentials,
        )
        headers.update(implicit_auth_headers(credentials, headers))
        tools = card.config.get("tools")
        tool_names = (
            [str(item) for item in tools] if isinstance(tools, list) else None
        )
        return HarnessMCPServerDefinition(
            name=card.name,
            display_name=str(
                card.config.get("display_name") or card.name,
            ),
            transport=transport,
            command=str(endpoint.get("command") or ""),
            args=[str(item) for item in endpoint.get("args") or []],
            cwd=(
                Path(str(endpoint["cwd"])).expanduser()
                if endpoint.get("cwd")
                else None
            ),
            url=str(endpoint.get("url") or ""),
            env=env,
            headers=headers,
            tools=tool_names,
            tool_policies=self._tool_policies(
                card,
                tool_names,
                request_context,
            ),
            default_policy=card.policy.default_effect,
            credential_revision=self._credential_revision(
                credentials,
            ),
            runtime_revision=self._runtime_revision(env, headers),
        )

    def _credential_providers(
        self,
        card: DriverCard,
    ) -> dict[str, Any]:
        if card.credentials:
            return {
                alias: build_provider(
                    reference,
                    self._driver_config.credential_store,
                )
                for alias, reference in card.credentials.items()
            }
        return {
            CREDENTIAL_ALIAS_DEFAULT: build_provider(
                CredentialRef(kind=CREDENTIAL_KIND_NONE),
                self._driver_config.credential_store,
            ),
        }

    @staticmethod
    def _tool_policies(
        card: DriverCard,
        tools: list[str] | None,
        request_context: dict[str, str],
    ) -> dict[str, MCPToolPolicy]:
        if not tools:
            return {}
        subjects = _subjects_from_context(request_context)
        return {
            name: evaluate_policy(
                card.policy,
                DriverInvocationContext(
                    subject=subjects[0],
                    subjects=subjects,
                    driver_name=card.name,
                    protocol=PROTOCOL_MCP,
                    operation=DRIVER_OPERATION_INVOKE,
                    target=PolicyTarget(
                        kind=CAPABILITY_KIND_TOOL,
                        name=name,
                    ),
                    request_context=request_context,
                ),
            )
            for name in tools
        }

    @staticmethod
    def _credential_revision(
        credentials: dict[str, Any],
    ) -> str:
        revisions = {
            str(value.meta.get("updated_at") or "")
            for value in credentials.values()
            if value.meta
        }
        return "|".join(sorted(revisions))

    @staticmethod
    def _runtime_revision(
        env: dict[str, Any],
        headers: dict[str, Any],
    ) -> str:
        """Hash resolved runtime values without retaining plaintext."""
        payload = {
            "env": {
                key: (
                    value.get_secret_value()
                    if hasattr(value, "get_secret_value")
                    else str(value)
                )
                for key, value in sorted(env.items())
            },
            "headers": {
                key: (
                    value.get_secret_value()
                    if hasattr(value, "get_secret_value")
                    else str(value)
                )
                for key, value in sorted(headers.items())
            },
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _subjects_from_context(
    request_context: dict[str, str],
) -> tuple[str, ...]:
    subjects: list[str] = []
    for prefix, key in (
        ("user", "user_id"),
        ("session", "session_id"),
        ("channel", "channel"),
    ):
        value = str(request_context.get(key) or "").strip()
        if value:
            subjects.append(f"{prefix}:{value}")
    return tuple(subjects or [SUBJECT_UNKNOWN_USER])


__all__ = ["HarnessCapabilityResolver"]
