# -*- coding: utf-8 -*-
"""Codex Migration Provider with app-server and rollout JSONL recovery."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ...harnesses.codex.rollout_reader import (
    CodexRolloutReader,
    codex_non_root_session_kind,
)
from ...utils.io_utils import run_sync_io
from ..codex_plugin_adapter import ADAPTER as CODEX_PLUGIN_ADAPTER
from ..models import (
    ProviderInventory,
    SourceLocation,
    SourceMCPServer,
    SourceSession,
    SourceSkill,
)
from ._utils import parse_datetime
from .base import (
    ProgressReporter,
    SessionReadBudget,
    make_inventory,
    progress_milestone,
)
from .external_state import (
    codex_memory_status,
    discover_codex_memory,
    discover_codex_plugin_mcp,
    discover_codex_plugins,
)
from .codex_schedules import discover_codex_scheduled_tasks
from .locator import resolve_source_location

_DISCOVERY_TIMEOUT_SECONDS = 60
_SESSION_TIMEOUT_SECONDS = 90
_SESSION_SCAN_TIMEOUT_SECONDS = 300
_READ_CONCURRENCY = 2


def _error_detail(exc: BaseException) -> str:
    return str(exc).strip() or type(exc).__name__


class CodexMigrationProvider:  # pylint: disable=too-few-public-methods
    """Read Codex sessions, Skills and MCP without changing source data."""

    provider_id = "codex"

    def __init__(
        self,
        workspace: Any,
        rollout_reader: CodexRolloutReader | None = None,
        source_location: SourceLocation | None = None,
    ) -> None:
        self._workspace = workspace
        if source_location is None:
            source_location = resolve_source_location(
                "codex",
                source_home=(
                    rollout_reader.codex_home if rollout_reader else None
                ),
            )
            if rollout_reader is not None:
                source_location.data_home_source = "injected"
        self._source_location = source_location
        self._rollout_reader = rollout_reader or CodexRolloutReader(
            Path(source_location.data_home),
        )

    # pylint: disable-next=R0914,R0912,R0915
    async def inventory(
        self,
        *,
        limit: int,
        progress: ProgressReporter | None = None,
        include_sessions: bool = True,
        session_ids: set[str] | None = None,
    ) -> ProviderInventory:
        """Discover and normalize Codex-owned portable objects."""
        local_only = self._source_location.data_home_source == "explicit"
        adapter = None
        status = None
        if not local_only:
            settings = (
                dict(self._workspace.config.backend_settings)
                if self._workspace.config.backend == self.provider_id
                else {}
            )
            adapter = await self._workspace.harness_runtime.adapter(
                self.provider_id,
                settings,
            )
        rollout_reader = self._rollout_reader
        offline_threads: list[dict[str, Any]] = []
        ignored_session_ids: list[str] = []
        if include_sessions:
            offline_threads = await run_sync_io(
                rollout_reader.list_threads,
                limit=limit,
            )
            ignored_session_ids = await run_sync_io(
                rollout_reader.list_non_root_thread_ids,
            )
        if rollout_reader.index_truncated:
            warnings = [
                "Codex rollout discovery reached its safety limit; older "
                "candidate files were not scanned.",
            ]
        else:
            warnings = []

        if adapter is not None:
            try:
                status = await asyncio.wait_for(
                    adapter.status(),
                    timeout=_DISCOVERY_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                status = None
        installed = bool(status is not None and status.installed)
        if local_only:
            warnings.append(
                "Explicit Codex source-home is local-only; the live "
                "app-server was not queried.",
            )
        elif not installed:
            if offline_threads:
                warnings.append(
                    "Codex CLI was unavailable, so local rollout JSONL files "
                    "were used for session recovery.",
                )
            else:
                warnings.append(
                    "Codex CLI was unavailable; only portable local assets "
                    "from the resolved Codex data directory can be imported.",
                )

        if progress is not None:
            await progress(
                "已连接 Codex，正在检查 Memory、插件、Skill 与 MCP 配置…",
            )

        (
            memory_projects,
            plugin_state,
            memory_state,
            scheduled_task_state,
        ) = await asyncio.gather(
            run_sync_io(
                discover_codex_memory,
                rollout_reader.codex_home,
            ),
            run_sync_io(
                discover_codex_plugins,
                rollout_reader.codex_home,
            ),
            run_sync_io(
                codex_memory_status,
                rollout_reader.codex_home,
            ),
            run_sync_io(
                discover_codex_scheduled_tasks,
                rollout_reader.codex_home,
            ),
        )
        marketplaces, plugins = plugin_state
        (
            scheduled_tasks,
            scheduled_task_warnings,
            _,
            automation_run_thread_ids,
        ) = scheduled_task_state
        warnings.extend(scheduled_task_warnings)
        ignored_session_ids = sorted(
            set(ignored_session_ids) | set(automation_run_thread_ids),
        )
        ignored_source_ids = set(ignored_session_ids)
        if include_sessions and automation_run_thread_ids:
            # Refill the bounded root list after DB-only automation IDs are
            # removed, so internal runs cannot consume the user's session
            # import quota merely because an older rollout lacks the newer
            # structured thread_source marker.
            offline_threads = await run_sync_io(
                rollout_reader.list_threads,
                limit=limit + min(len(automation_run_thread_ids), 5000),
            )
        offline_threads = [
            item
            for item in offline_threads
            if str(item.get("id") or item.get("threadId") or "")
            not in ignored_source_ids
        ][:limit]

        skills = await self._discover_skills(
            adapter,
            rollout_reader,
            plugins,
            installed=installed,
            warnings=warnings,
        )
        mcp_servers = await self._discover_mcp(
            adapter,
            plugins,
            installed=installed,
            warnings=warnings,
        )
        if memory_state["ignored_internal_files"]:
            warnings.append(
                "Ignored Codex memory pipeline artifacts: "
                + ", ".join(memory_state["ignored_internal_files"])
                + ".",
            )
        if memory_state["state"] in {
            "pending_ad_hoc",
            "phase1_only",
            "consolidation_incomplete",
        }:
            warnings.append(
                "Codex memory is not fully consolidated; its state is "
                f"{memory_state['state']}. Only safe source material that "
                "can be represented in QwenPaw was prepared.",
            )

        detected = bool(
            installed
            or offline_threads
            or memory_projects
            or skills
            or mcp_servers
            or plugins
            or marketplaces
            or ignored_session_ids
            or scheduled_tasks,
        )
        if not detected:
            detail = (
                getattr(status, "error", "")
                if status is not None
                else "Codex runtime detection timed out after 60s."
            )
            return make_inventory(
                self.provider_id,
                detected=False,
                locator=str(rollout_reader.codex_home),
                warnings=[
                    *warnings,
                    detail
                    or "Codex runtime and portable local state were not "
                    "found.",
                ],
            )

        if include_sessions and progress is not None:
            await progress("正在合并 Codex 会话索引与本地 JSONL 备份…")
        online_threads: list[dict[str, Any]] = []
        if include_sessions and installed:
            try:
                online_threads = await asyncio.wait_for(
                    adapter.list_external_threads(limit=limit),
                    timeout=_DISCOVERY_TIMEOUT_SECONDS,
                )
            except Exception as exc:  # pylint: disable=broad-except
                warnings.append(
                    "Codex app-server session listing failed; local rollout "
                    f"recovery was used: {_error_detail(exc)}",
                )
        visible_online_threads: list[dict[str, Any]] = []
        for item in online_threads:
            source_id = str(item.get("id") or item.get("threadId") or "")
            if (
                source_id in ignored_session_ids
                or codex_non_root_session_kind(item)
            ):
                if source_id:
                    ignored_session_ids.append(source_id)
                continue
            visible_online_threads.append(item)
        online_threads = visible_online_threads
        ignored_session_ids = sorted(set(ignored_session_ids))
        if ignored_session_ids:
            warnings.append(
                f"Ignored {len(ignored_session_ids)} Codex non-root "
                "internal/subagent/automation session(s). They are "
                "implementation traces rather than top-level user "
                "conversations.",
            )
        raw_threads = _merge_threads(online_threads, offline_threads, limit)
        if session_ids is not None:
            raw_threads = [
                item
                for item in raw_threads
                if str(item.get("id") or item.get("threadId") or "")
                in session_ids
            ]
        if len(raw_threads) >= limit:
            warnings.append(
                f"Codex session safety limit ({limit}) was reached; older "
                "threads beyond this bounded import were not read.",
            )
        if include_sessions and progress is not None:
            await progress(
                f"发现 {len(raw_threads)} 个 Codex 会话，正在读取历史"
                f"（最多 {_READ_CONCURRENCY} 个同时读取，失败会自动改读 JSONL）…",
            )

        sessions: list[SourceSession] = []
        read_warnings: list[str] = []
        recovered = 0
        if include_sessions:
            sessions, read_warnings, recovered = await self._read_sessions(
                adapter,
                rollout_reader,
                raw_threads,
                installed=installed,
                progress=progress,
            )
        warnings.extend(read_warnings)
        if recovered:
            warnings.append(
                f"Recovered {recovered} Codex session(s) from local rollout "
                "JSONL after app-server history was unavailable/incomplete.",
            )
        if skills:
            warnings.append(
                f"Copied {len(skills)} Codex Skill candidate(s) in the "
                "disabled state. Codex-only commands, tools and plugin "
                "dependencies still require review before enabling.",
            )
        if mcp_servers:
            warnings.append(
                f"Prepared {len(mcp_servers)} Codex MCP server(s) for "
                "disabled QwenPaw DriverCards. Literal secrets are moved to "
                "the encrypted credential store; OAuth must be authorized "
                "again.",
            )
        if memory_projects:
            warnings.append(
                f"Prepared {len(memory_projects)} Codex memory scope(s) as "
                "project-scoped source resources. They are not flattened "
                "into QwenPaw MEMORY.md.",
            )
        if plugins:
            native = sum(bool(item.install_source) for item in plugins)
            content = sum(
                item.metadata.get("adapter") == CODEX_PLUGIN_ADAPTER
                for item in plugins
            )
            warnings.append(
                f"Found {len(plugins)} enabled Codex plugin(s) across "
                f"{len(marketplaces)} Marketplace source(s); {native} have "
                f"a native source and {content} contain portable Skills/MCP. "
                "Content caches enter bounded review snapshots and are "
                "installed only through generated QwenPaw wrappers.",
            )
        if scheduled_tasks:
            warnings.append(
                f"Prepared {len(scheduled_tasks)} Codex automation(s) as "
                "disabled QwenPaw Agent jobs. Automation run conversations "
                "were excluded from normal chat migration.",
            )
        warnings.append(
            "Codex built-in tools, sandbox/approval settings, hooks, agents, "
            "and provider runtime state are harness-bound and were not "
            "copied. Historical tool calls remain session data.",
        )

        locator = (
            str(getattr(status, "runtime_path", "") or "")
            if status is not None
            else ""
        )
        self._source_location.runtime_path = locator
        self._source_location.data_home_exists = (
            rollout_reader.codex_home.is_dir()
        )
        return make_inventory(
            self.provider_id,
            detected=True,
            locator=locator or str(rollout_reader.codex_home),
            sessions=sessions,
            ignored_session_ids=ignored_session_ids,
            skills=skills,
            mcp_servers=mcp_servers,
            memory_projects=memory_projects,
            marketplaces=marketplaces,
            plugins=plugins,
            scheduled_tasks=scheduled_tasks,
            warnings=warnings,
        )

    async def _discover_skills(
        self,
        adapter: Any,
        rollout_reader: CodexRolloutReader,
        plugins: list[Any],
        *,
        installed: bool,
        warnings: list[str],
    ) -> list[SourceSkill]:
        records: list[dict[str, Any]] = []
        if installed:
            try:
                records = await asyncio.wait_for(
                    adapter.external_skill_records(
                        self._workspace.workspace_dir.resolve(),
                    ),
                    timeout=_DISCOVERY_TIMEOUT_SECONDS,
                )
            except Exception as exc:  # pylint: disable=broad-except
                warnings.append(
                    "Codex app-server Skill discovery failed; local Skill "
                    f"folders were scanned instead: {_error_detail(exc)}",
                )
        if not records:
            records = await run_sync_io(rollout_reader.skill_records)

        workspace_skills = self._workspace.workspace_dir.resolve() / "skills"
        plugin_roots = []
        for plugin in plugins:
            source = str(plugin.metadata.get("install_path") or "")
            if source:
                try:
                    plugin_roots.append(Path(source).resolve(strict=True))
                except OSError:
                    pass
        skills: list[SourceSkill] = []
        seen: set[Path] = set()
        for item in records:
            raw_path = Path(str(item.get("path") or "")).expanduser()
            if (
                raw_path.is_symlink()
                or raw_path.parent.is_symlink()
                or not raw_path.is_file()
                or raw_path.name != "SKILL.md"
            ):
                continue
            directory = raw_path.parent.resolve()
            if (
                directory in seen
                or directory.is_relative_to(workspace_skills)
                or any(directory.is_relative_to(root) for root in plugin_roots)
            ):
                continue
            seen.add(directory)
            skills.append(
                SourceSkill(
                    source_id=str(directory),
                    name=str(item.get("name") or directory.name),
                    directory=directory,
                    description=str(item.get("description") or ""),
                ),
            )
        return skills

    async def _discover_mcp(
        self,
        adapter: Any,
        plugins: list[Any],
        *,
        installed: bool,
        warnings: list[str],
    ) -> list[SourceMCPServer]:
        plugin_servers, plugin_warnings, _count = discover_codex_plugin_mcp(
            plugins,
        )
        warnings.extend(plugin_warnings)
        if not installed:
            return plugin_servers
        external_records = getattr(adapter, "external_mcp_records", None)
        if external_records is None:
            try:
                discovered = await adapter.discover_mcp(
                    self._workspace.workspace_dir.resolve(),
                )
                if discovered:
                    warnings.append(
                        f"Found {len(discovered)} Codex MCP server(s), but "
                        "this Codex adapter exposes redacted discovery only.",
                    )
                return plugin_servers
            except Exception as exc:  # pylint: disable=broad-except
                warnings.append(
                    f"Codex MCP discovery failed: {_error_detail(exc)}",
                )
                return plugin_servers
        try:
            records = await asyncio.wait_for(
                external_records(self._workspace.workspace_dir.resolve()),
                timeout=_DISCOVERY_TIMEOUT_SECONDS,
            )
        except Exception as exc:  # pylint: disable=broad-except
            warnings.append(
                f"Codex MCP discovery failed: {_error_detail(exc)}",
            )
            return plugin_servers
        servers: list[SourceMCPServer] = []
        for item in records:
            server = _mcp_server(item)
            if server is not None:
                servers.append(server)
        seen = {server.name for server in servers}
        servers.extend(
            server for server in plugin_servers if server.name not in seen
        )
        return servers

    # pylint: disable-next=too-many-locals,too-many-statements
    async def _read_sessions(
        self,
        adapter: Any,
        rollout_reader: CodexRolloutReader,
        raw_threads: list[dict[str, Any]],
        *,
        installed: bool,
        progress: ProgressReporter | None,
    ) -> tuple[list[SourceSession], list[str], int]:
        progress_lock = asyncio.Lock()
        completed = 0
        budget = SessionReadBudget()

        async def _read_one(
            raw: dict[str, Any],
        ) -> tuple[SourceSession | None, str | None, bool]:
            nonlocal completed
            source_id = str(raw.get("id") or raw.get("threadId") or "")
            used_fallback = False
            failure: BaseException | None = None
            history = []
            if source_id and installed and not raw.get("offlineOnly"):
                try:
                    history = await asyncio.wait_for(
                        adapter.read_external_thread(source_id),
                        timeout=_SESSION_TIMEOUT_SECONDS,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    failure = exc
            if source_id and (failure is not None or not history):
                try:
                    history = await run_sync_io(
                        rollout_reader.read_thread,
                        source_id,
                    )
                    used_fallback = bool(history)
                except Exception as exc:  # pylint: disable=broad-except
                    if failure is None:
                        failure = exc

            if not source_id:
                result: tuple[SourceSession | None, str | None, bool] = (
                    None,
                    "Skipped one Codex thread without an id.",
                    False,
                )
            elif failure is not None and not history:
                result = (
                    None,
                    f"Could not read Codex thread {source_id}: "
                    f"{_error_detail(failure)}",
                    False,
                )
            else:
                title = str(
                    raw.get("name")
                    or raw.get("title")
                    or raw.get("preview")
                    or f"Codex {source_id[:8]}",
                )
                result = (
                    SourceSession(
                        source_id=source_id,
                        title=title[:200],
                        cwd=str(raw.get("cwd") or ""),
                        created_at=parse_datetime(
                            raw.get("createdAt") or raw.get("created_at"),
                        ),
                        updated_at=parse_datetime(
                            raw.get("updatedAt") or raw.get("updated_at"),
                        ),
                        history=history,
                        metadata={
                            "status": str(raw.get("status") or ""),
                            "source": str(raw.get("source") or "codex"),
                            "offline_recovery": used_fallback,
                        },
                    ),
                    None,
                    used_fallback,
                )
            async with progress_lock:
                completed += 1
                if progress is not None and progress_milestone(
                    completed,
                    len(raw_threads),
                ):
                    await progress(
                        f"Codex 会话读取进度：{completed}/{len(raw_threads)}",
                    )
            return result

        sessions: list[SourceSession] = []
        warnings: list[str] = []
        recovered = 0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _SESSION_SCAN_TIMEOUT_SECONDS
        for start in range(0, len(raw_threads), _READ_CONCURRENCY):
            remaining = deadline - loop.time()
            if remaining <= 0:
                warnings.append(
                    "Codex session scan reached its 300 second time limit; "
                    "remaining histories were not read.",
                )
                break
            batch = raw_threads[start : start + _READ_CONCURRENCY]
            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*(_read_one(raw) for raw in batch)),
                    timeout=remaining,
                )
            except asyncio.TimeoutError:
                warnings.append(
                    "Codex session scan reached its 300 second time limit; "
                    "remaining histories were not read.",
                )
                break
            for session, warning, used_fallback in results:
                if warning:
                    warnings.append(warning)
                if session is not None:
                    reason = budget.add(session)
                    if reason:
                        warnings.append(reason)
                        if budget.exhausted:
                            break
                    else:
                        sessions.append(session)
                if used_fallback:
                    recovered += 1
            if budget.exhausted:
                break
        return sessions, warnings, recovered


def _merge_threads(
    online: list[dict[str, Any]],
    offline: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    offline_by_id = {
        str(item.get("id") or ""): item for item in offline if item.get("id")
    }
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in online:
        thread_id = str(item.get("id") or item.get("threadId") or "")
        if not thread_id or thread_id in seen:
            continue
        fallback = offline_by_id.get(thread_id, {})
        combined = {**fallback, **item}
        if not combined.get("cwd"):
            combined["cwd"] = fallback.get("cwd", "")
        merged.append(combined)
        seen.add(thread_id)
    for item in offline:
        thread_id = str(item.get("id") or "")
        if not thread_id or thread_id in seen:
            continue
        merged.append({**item, "offlineOnly": True})
        seen.add(thread_id)
    return merged[: max(0, limit)]


def _mcp_server(item: dict[str, Any]) -> SourceMCPServer | None:
    name = str(item.get("name") or "")
    transport = item.get("transport")
    if not name or not isinstance(transport, dict):
        return None
    transport_type = str(transport.get("type") or "stdio")
    env = {
        str(key): str(value)
        for key, value in dict(transport.get("env") or {}).items()
    }
    for var in transport.get("env_vars") or []:
        var_name = str(var)
        if var_name:
            env.setdefault(var_name, f"${{{var_name}}}")
    headers = {
        str(key): str(value)
        for key, value in dict(transport.get("http_headers") or {}).items()
    }
    for header, var in dict(transport.get("env_http_headers") or {}).items():
        var_name = str(var)
        if var_name:
            headers.setdefault(str(header), f"${{{var_name}}}")
    bearer_var = str(transport.get("bearer_token_env_var") or "")
    if bearer_var:
        headers.setdefault("Authorization", f"Bearer ${{{bearer_var}}}")
    command = str(transport.get("command") or "")
    args = [str(value) for value in transport.get("args") or []]
    dependency_text = "\n".join(
        [command, *args, str(transport.get("cwd") or "")],
    )
    source_runtime_bound = any(
        marker in dependency_text
        for marker in (
            "/.codex/",
            "\\.codex\\",
            "ChatGPT.app/Contents/Resources",
            "codex-app-server",
        )
    )
    return SourceMCPServer(
        source_id=name,
        name=name,
        transport=transport_type,
        enabled=bool(item.get("enabled")),
        command=command,
        args=args,
        env=env,
        cwd=str(transport.get("cwd") or ""),
        url=str(transport.get("url") or ""),
        headers=headers,
        auth_status=str(item.get("auth_status") or ""),
        metadata={
            "source_enabled": bool(item.get("enabled")),
            "source_runtime_bound": source_runtime_bound,
        },
    )


__all__ = ["CodexMigrationProvider"]
