# -*- coding: utf-8 -*-
"""Mission-mode compatibility testing and repair for imported assets."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..agents.acp.meta import ACP_EPHEMERAL_META_KEY
from ..agents.tools.agent_management import MAX_SPAWN_BATCH_CONCURRENCY
from ..modes.mission import MissionMode
from ..schemas import AgentRequest
from ..utils.io_utils import run_sync_io
from .adaptation_mission import prepare_mission, sync_mission
from .adaptation_prompts import repair_prompt
from .adaptation_staging import component_map, stage_local_assets
from .compatibility import (
    AssetType,
    AssetZone,
    CompatibilityAsset,
    CompatibilityManifest,
    CompatibilityStore,
    counts,
    load_manifest,
    mcp_inline_secret_risks,
    redact_sensitive_text,
    write_summary,
)
from .compatibility_testing import (
    ADAPTATION_TEXT_SUFFIXES,
    CompatibilityTester,
    find_source,
)
from .models import ProviderInventory
from .providers.base import (
    ProgressReporter,
    report_progress as _report,
    report_result,
)

_MAX_REACT_ITERATIONS = 4_000
_HEARTBEAT_SECONDS = 12
_IDLE_SECONDS = 300
_MAX_WORKER_SECONDS = 30 * 60
_WORKER_STOP_GRACE_SECONDS = 3
_MAX_FILE_BYTES = 256 * 1024
_EXCERPT_BYTES = 16 * 1024
_MAX_REPLACEMENT_BYTES = 32 * 1024
_REPAIR_TOOLS = (
    "migration_compat_inspect",
    "migration_compat_read_file",
    "migration_compat_write_file",
    "migration_compat_update",
    "migration_compat_finalize",
)
_PUBLIC_TYPES = {
    AssetType.SKILL: "skill",
    AssetType.MCP: "mcp",
    AssetType.PLUGIN: "plugin",
    AssetType.SCHEDULED_TASK: "cron",
}


@dataclass(frozen=True)
class AdaptationResult:
    manifest: CompatibilityManifest
    summary_path: Path


@dataclass(frozen=True)
class _RequestBinding:
    context: "ActiveAdaptationContext"
    asset_key: str
    completed: asyncio.Event


_ACTIVE_CONTEXTS: dict[str, _RequestBinding] = {}
_DRAINING_WORKERS: dict[str, set[asyncio.Task]] = {}


def _release_worker(agent_id: str, task: asyncio.Task) -> None:
    workers = _DRAINING_WORKERS.get(agent_id)
    if workers is not None:
        workers.discard(task)
        if not workers:
            _DRAINING_WORKERS.pop(agent_id, None)
    try:
        task.exception()
    except (
        asyncio.CancelledError,
        Exception,
    ):  # pylint: disable=broad-exception-caught
        pass


def has_draining_workers(workspace: Any) -> bool:
    """Whether a cancelled Mission worker still owns this Agent."""
    return bool(_DRAINING_WORKERS.get(workspace.agent_id))


async def _stop_worker(workspace: Any, task: asyncio.Task) -> None:
    """Request a stop without blocking on an uncooperative worker."""
    if task.done():
        return
    agent_id = workspace.agent_id
    workers = _DRAINING_WORKERS.setdefault(agent_id, set())
    if task not in workers:
        workers.add(task)
        task.add_done_callback(lambda done: _release_worker(agent_id, done))
    task.cancel()
    await asyncio.wait({task}, timeout=_WORKER_STOP_GRACE_SECONDS)


async def drain_adaptation_workers(*, timeout: float = 5) -> int:
    """Give registered workers one bounded final cancellation attempt."""
    tasks = {
        task
        for workers in _DRAINING_WORKERS.values()
        for task in workers
        if not task.done()
    }
    for task in tasks:
        task.cancel()
    if not tasks:
        return 0
    _done, pending = await asyncio.wait(tasks, timeout=timeout)
    return len(pending)


def _active_binding() -> _RequestBinding:
    from ..app.agent_context import get_current_session_id

    binding = _ACTIVE_CONTEXTS.get(get_current_session_id() or "")
    if binding is None:
        raise PermissionError("migration compatibility tools are unavailable")
    return binding


def get_active_adaptation_context() -> "ActiveAdaptationContext":
    return _active_binding().context


class ActiveAdaptationContext:
    """In-memory capability shared by isolated migration workers."""

    def __init__(
        self,
        *,
        inventory: ProviderInventory,
        store: CompatibilityStore,
        tester: CompatibilityTester,
        staging_root: Path,
        manifest: CompatibilityManifest,
        progress: ProgressReporter | None = None,
    ) -> None:
        self.inventory = inventory
        self.store = store
        self.tester = tester
        self.staging_root = staging_root.resolve()
        self.progress = progress
        self._activities: dict[str, str] = {}
        self.tool_calls = 0
        self.total_tool_budget = sum(
            item.tool_budget for item in manifest.assets
        )
        self._asset_locks = {
            item.asset_key: asyncio.Lock() for item in manifest.assets
        }

    def _binding(self) -> _RequestBinding:
        binding = _active_binding()
        if binding.context is not self:
            raise PermissionError("migration request is not bound")
        return binding

    @property
    def active_asset_key(self) -> str:
        return self._binding().asset_key

    def _asset_lock(self, key: str) -> asyncio.Lock:
        if key != self.active_asset_key:
            raise PermissionError("worker may access only its assigned asset")
        try:
            return self._asset_locks[key]
        except KeyError as exc:
            raise KeyError(f"unknown compatibility asset: {key}") from exc

    def activity(self, session_id: str) -> str:
        return self._activities.get(session_id, "等待 Agent 开始处理。")

    def clear_activity(self, session_id: str) -> None:
        self._activities.pop(session_id, None)

    async def _publish(self, message: str) -> None:
        from ..app.agent_context import get_current_session_id

        session_id = get_current_session_id() or ""
        self._activities[session_id] = message
        await _report(self.progress, message)

    @staticmethod
    def _label(asset: CompatibilityAsset) -> str:
        kind = {
            AssetType.SKILL: "Skill",
            AssetType.MCP: "MCP",
            AssetType.PLUGIN: "插件",
            AssetType.SCHEDULED_TASK: "定时任务",
        }[asset.asset_type]
        name = redact_sensitive_text(asset.name, limit=120).replace("\n", " ")
        return f"{kind}「{name}」"

    async def _consume(
        self,
        key: str,
        *,
        final: bool = False,
    ) -> CompatibilityAsset:
        if key != self.active_asset_key:
            raise PermissionError("worker may access only its assigned asset")

        asset = await run_sync_io(
            self.store.consume,
            key,
            reserve=0 if final else 1,
        )
        self.tool_calls += 1
        return asset

    def _asset(self, key: str) -> CompatibilityAsset:
        return load_manifest(self.store.path).get_asset(key)

    def _asset_root(self, asset: CompatibilityAsset) -> Path:
        source = find_source(self.inventory, asset)
        if asset.asset_type is AssetType.SKILL:
            root = Path(source.directory).resolve(strict=True)
            staging = self.staging_root / "skills"
        elif asset.asset_type is AssetType.PLUGIN:
            root = Path(source.install_source).resolve(strict=True)
            staging = self.staging_root / "plugins"
        else:
            raise ValueError("asset has no readable file tree")
        if not root.is_relative_to(staging.resolve()):
            raise PermissionError("asset is outside the staging area")
        return root

    @staticmethod
    def _asset_file(root: Path, relative_path: str) -> Path:
        relative = Path(relative_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.suffix.lower() not in ADAPTATION_TEXT_SUFFIXES
        ):
            raise PermissionError("asset path is not editable")
        path = root / relative
        parent = path.parent.resolve(strict=False)
        if not parent.is_relative_to(root):
            raise PermissionError("asset path escapes staging")
        if path.exists() and (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve(strict=True).is_relative_to(root)
        ):
            raise PermissionError("asset path is not a regular staged file")
        return path

    @staticmethod
    def _excerpt(path: Path, size: int) -> str:
        with path.open("rb") as stream:
            head = stream.read(_EXCERPT_BYTES)
            if size <= _EXCERPT_BYTES:
                tail = b""
            else:
                stream.seek(max(_EXCERPT_BYTES, size - _EXCERPT_BYTES))
                tail = stream.read(_EXCERPT_BYTES)
        excerpt = head.decode("utf-8", errors="replace")
        if tail:
            excerpt += "\n\n[... middle omitted ...]\n\n"
            excerpt += tail.decode("utf-8", errors="replace")
        return redact_sensitive_text(excerpt)

    def _read_file_payload(
        self,
        asset: CompatibilityAsset,
        relative_path: str,
        start_line: int,
        end_line: int,
    ) -> dict[str, Any]:
        path = self._asset_file(self._asset_root(asset), relative_path)
        if not path.is_file():
            raise FileNotFoundError(relative_path)
        size = path.stat().st_size
        if size > _MAX_FILE_BYTES:
            return {
                "ok": True,
                "path": relative_path,
                "read_mode": "bounded_excerpt",
                "size_bytes": size,
                "text": self._excerpt(path, size),
                "has_more": False,
                "next_line": None,
            }
        lines = redact_sensitive_text(
            path.read_text(encoding="utf-8"),
        ).splitlines()
        start = max(1, start_line)
        end = min(len(lines), max(start, end_line), start + 399)
        finished = end >= len(lines)
        return {
            "ok": True,
            "path": relative_path,
            "text": "\n".join(
                f"{number}: {lines[number - 1]}"
                for number in range(start, end + 1)
            ),
            "has_more": not finished,
            "next_line": end + 1 if not finished else None,
        }

    def _write_file_atomic(
        self,
        asset: CompatibilityAsset,
        relative_path: str,
        content: str,
    ) -> None:
        path = self._asset_file(self._asset_root(asset), relative_path)
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(
                temporary,
                stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600,
            )
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    async def inspect_asset(self, key: str) -> dict[str, Any]:
        async with self._asset_lock(key):
            asset = await self._consume(key)
            await self._publish(
                f"正在检查 {self._label(asset)} 的 QwenPaw 兼容性…",
            )
            result = {
                "ok": True,
                **await run_sync_io(self.tester.inspect, asset),
            }
            return result

    async def read_file(
        self,
        key: str,
        relative_path: str,
        *,
        start_line: int = 1,
        end_line: int = 240,
    ) -> dict[str, Any]:
        async with self._asset_lock(key):
            asset = await self._consume(key)
            await self._publish(
                f"正在阅读 {self._label(asset)}：{relative_path}",
            )
            return await run_sync_io(
                self._read_file_payload,
                asset,
                relative_path,
                start_line,
                end_line,
            )

    async def write_file(
        self,
        key: str,
        relative_path: str,
        content: str,
    ) -> dict[str, Any]:
        async with self._asset_lock(key):
            asset = await self._consume(key)
            if asset.zone is not AssetZone.REPAIR:
                raise RuntimeError("files can only be changed in repair")
            if len(content.encode()) > _MAX_FILE_BYTES:
                raise ValueError("updated text file is too large")
            if redact_sensitive_text(content) != content:
                raise ValueError("updated text contains a possible secret")
            await self._publish(
                f"正在兼容性优化 {self._label(asset)}：{relative_path}",
            )
            await run_sync_io(
                self._write_file_atomic,
                asset,
                relative_path,
                content,
            )
            await run_sync_io(
                self.store.mark_changed,
                key,
                f"写入 {relative_path}",
            )
            await self._publish(
                f"已修改 {self._label(asset)}，等待重新兼容性测试。",
            )
            return {"ok": True, "path": relative_path, "zone": "repair"}

    async def update_asset(  # pylint: disable=too-many-branches
        self,
        key: str,
        field_name: str,
        value_json: str,
    ) -> dict[str, Any]:
        async with self._asset_lock(key):
            asset = await self._consume(key)
            if len(value_json.encode()) > _MAX_REPLACEMENT_BYTES:
                raise ValueError("updated value is too large")
            if asset.zone is not AssetZone.REPAIR:
                raise RuntimeError("assets can only be changed in repair")
            await self._publish(
                f"正在兼容性优化 {self._label(asset)}：{field_name}",
            )
            source = find_source(self.inventory, asset)
            value = json.loads(value_json)
            if asset.asset_type is AssetType.MCP:
                allowed = {"command", "args", "cwd", "url", "transport"}
            elif asset.asset_type is AssetType.SCHEDULED_TASK:
                allowed = {
                    "prompt",
                    "cron",
                    "timezone",
                    "cwd",
                    "schedule_type",
                    "run_at",
                }
            else:
                raise PermissionError("asset has no structured repair surface")
            if field_name not in allowed:
                raise PermissionError("field is not editable")
            if field_name == "args":
                if not isinstance(value, list) or any(
                    not isinstance(item, str) for item in value
                ):
                    raise ValueError("args must be a string list")
            elif field_name == "run_at":
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            elif not isinstance(value, str):
                raise ValueError("field must be a string")
            if (
                field_name == "prompt"
                and redact_sensitive_text(value) != value
            ):
                raise ValueError("updated prompt contains a secret")
            candidate = source.model_copy(update={field_name: value})
            if asset.asset_type is AssetType.MCP and mcp_inline_secret_risks(
                candidate.command,
                candidate.args,
                candidate.url,
                candidate.env,
                candidate.headers,
                candidate.cwd,
            ):
                raise ValueError("updated MCP binding contains a secret")
            setattr(source, field_name, value)
            if (
                asset.asset_type is AssetType.SCHEDULED_TASK
                and field_name == "cwd"
                and value
                and await run_sync_io(Path(value).expanduser().is_dir)
            ):
                source.metadata.update(
                    {
                        "remote_unverified": False,
                        "workspace_status": "local",
                        "execution_environment": "local",
                        "source_target_remote_authority": "",
                        "target_remote_authority": "",
                    },
                )
            await run_sync_io(
                self.store.mark_changed,
                key,
                f"更新字段 {field_name}",
            )
            await self._publish(
                f"已更新 {self._label(asset)}，等待重新兼容性测试。",
            )
            return {"ok": True, "zone": "repair"}

    async def finalize_asset(self, key: str, reason: str) -> dict[str, Any]:
        async with self._asset_lock(key):
            asset = await run_sync_io(self._asset, key)
            if asset.zone is not AssetZone.REPAIR:
                raise RuntimeError("assets can only be finalized in repair")
            if not reason.strip():
                raise ValueError(
                    "finalization requires an evidence-based reason",
                )
            asset = await self._consume(key, final=True)
            await self._publish(
                f"正在测试 {self._label(asset)} 的 QwenPaw 兼容性…",
            )
            result = await run_sync_io(self.tester.test, asset)
            manifest = await run_sync_io(
                self.store.finalize,
                key,
                passed=result.passed,
                summary=result.summary,
                reason=reason,
                evidence=result.evidence,
            )
            if not result.passed:
                await self._publish(
                    f"{self._label(asset)}测试未通过，需要继续兼容性修复。",
                )
                return {
                    "ok": True,
                    "passed": False,
                    "zone": AssetZone.REPAIR.value,
                    "summary": result.summary,
                    "evidence": result.evidence,
                }
            await self._publish(
                f"{self._label(manifest.get_asset(key))}兼容性优化完成，已进入待迁移区。",
            )
            await report_result(
                self.progress,
                "asset",
                _PUBLIC_TYPES[asset.asset_type],
                "ready",
                "-",
                asset.source_id,
            )
            self._binding().completed.set()
            return {
                "ok": True,
                "passed": True,
                "zone": AssetZone.MIGRATE.value,
                "counts": counts(manifest),
            }


def _mission_mode(workspace: Any) -> MissionMode:
    matches = [
        mode
        for mode in getattr(workspace.plugins, "modes", ())
        if isinstance(mode, MissionMode)
    ]
    if len(matches) != 1:
        raise RuntimeError("workspace does not have exactly one MissionMode")
    return matches[0]


def _iteration_budget(tool_budget: int) -> int:
    """Leave room for both tool calls and the reasoning around them."""
    return min(_MAX_REACT_ITERATIONS, max(80, tool_budget * 2))


async def _run_phase(
    workspace: Any,
    context: ActiveAdaptationContext,
    *,
    session_id: str,
    asset: CompatibilityAsset,
    prompt: str,
    tools: tuple[str, ...],
    label: str,
) -> None:
    request = AgentRequest.model_validate(
        {
            "input": [
                {
                    "role": "user",
                    "type": "message",
                    "content": [
                        {"type": "text", "text": prompt},
                    ],
                },
            ],
            "session_id": session_id,
            "user_id": session_id,
            "agent_id": workspace.agent_id,
            "channel": "console",
            "request_context": {
                "source": "portability_adaptation",
                "portability_phase": "mission_repair",
                "max_react_iterations": _iteration_budget(
                    asset.tool_budget - asset.tool_calls,
                ),
                ACP_EPHEMERAL_META_KEY: True,
                "approval_level": "off",
                "subagent_allowed_tools": list(tools),
                "subagent_skills": [],
            },
        },
    )
    binding = _RequestBinding(context, asset.asset_key, asyncio.Event())
    _ACTIVE_CONTEXTS[session_id] = binding
    activity = asyncio.Event()
    task = asyncio.create_task(
        _consume_query(workspace, request, activity.set),
    )
    completed = asyncio.create_task(binding.completed.wait())
    loop = asyncio.get_running_loop()
    started_at = last_activity = loop.time()
    try:
        while not task.done() and not completed.done():
            done, _ = await asyncio.wait(
                {task, completed},
                timeout=_HEARTBEAT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                await _report(
                    context.progress,
                    f"{label}仍在运行：{context.activity(session_id)}",
                )
            if task.done() or completed.done():
                break
            if activity.is_set():
                activity.clear()
                last_activity = loop.time()
            elapsed_seconds = loop.time() - started_at
            if elapsed_seconds >= _MAX_WORKER_SECONDS:
                raise TimeoutError(
                    "compatibility worker exceeded " f"{_MAX_WORKER_SECONDS}s",
                )
            idle_seconds = loop.time() - last_activity
            if idle_seconds >= _IDLE_SECONDS:
                raise TimeoutError(
                    f"compatibility worker was idle for {_IDLE_SECONDS}s",
                )
        if task.done():
            await task
        else:
            _ACTIVE_CONTEXTS.pop(session_id, None)
            await _stop_worker(workspace, task)
    finally:
        _ACTIVE_CONTEXTS.pop(session_id, None)
        context.clear_activity(session_id)
        completed.cancel()
        try:
            await completed
        except asyncio.CancelledError:
            pass
        await _stop_worker(workspace, task)


async def _consume_query(
    workspace: Any,
    request: AgentRequest,
    mark_activity: Any,
) -> None:
    async for event in workspace.stream_query(request):
        if getattr(event, "type", None) != "heartbeat":
            mark_activity()


async def _bounded_parallel(keys: list[str], worker: Any) -> None:
    """Run a rolling Mission-sized worker pool."""
    semaphore = asyncio.Semaphore(MAX_SPAWN_BATCH_CONCURRENCY)

    async def run(key: str) -> None:
        async with semaphore:
            await worker(key)

    results = await asyncio.gather(
        *(run(key) for key in keys),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            raise result


async def _repair_asset(
    workspace: Any,
    context: ActiveAdaptationContext,
    key: str,
    warnings: list[str],
) -> None:
    asset = await run_sync_io(
        context._asset,  # pylint: disable=protected-access
        key,
    )
    label = context._label(asset)  # pylint: disable=protected-access
    try:
        await report_result(
            context.progress,
            "asset",
            _PUBLIC_TYPES[asset.asset_type],
            "repairing",
            "-",
            asset.source_id,
        )
        await _run_phase(
            workspace,
            context,
            session_id=f"migration-worker:{secrets.token_urlsafe(24)}",
            asset=asset,
            prompt=repair_prompt(asset),
            tools=_REPAIR_TOOLS,
            label=f"Mission 正在修复 {label}",
        )
    except Exception as exc:  # pylint: disable=broad-except
        warnings.append(f"{label}修复失败：{type(exc).__name__}: {exc}")


async def _repair_with_mission(
    workspace: Any,
    context: ActiveAdaptationContext,
    root: Path,
    warnings: list[str],
) -> str:
    mode = _mission_mode(workspace)
    max_attempts = mode.max_retries_per_story + 1
    session_id = f"migration-mission:{secrets.token_urlsafe(24)}"
    manifest = await run_sync_io(load_manifest, context.store.path)
    loop_dir = await run_sync_io(
        prepare_mission,
        root,
        manifest,
        session_id,
        max_attempts,
    )
    mode.start_internal_mission(session_id, loop_dir)
    try:
        for round_number in range(1, max_attempts + 1):
            manifest = await run_sync_io(load_manifest, context.store.path)
            pending = [
                item.asset_key
                for item in manifest.by_zone(AssetZone.REPAIR)
                if not item.budget_exhausted
            ]
            if not pending:
                break
            await _report(
                context.progress,
                f"Mission 第 {round_number}/{max_attempts} 轮："
                f"以 {MAX_SPAWN_BATCH_CONCURRENCY} 个并行 Agent "
                f"处理 {len(pending)} 项资产。",
            )
            await _bounded_parallel(
                pending,
                lambda key: _repair_asset(workspace, context, key, warnings),
            )
            manifest = await run_sync_io(load_manifest, context.store.path)
            await run_sync_io(sync_mission, loop_dir, manifest)
            if has_draining_workers(workspace):
                return "兼容性修复 Agent 未能及时停止；已停止本次 Mission，" "待其退出后可重新导入。"
            if await mode.check_internal_mission(session_id):
                return ""
        manifest = await run_sync_io(load_manifest, context.store.path)
        await run_sync_io(sync_mission, loop_dir, manifest, stopped=True)
        await mode.check_internal_mission(session_id)
        remaining = len(manifest.by_zone(AssetZone.REPAIR))
        return (
            f"兼容性修复 Mission 已达到每项最多 {max_attempts} 次尝试，"
            f"仍有 {remaining} 项未通过原生检查。"
        )
    finally:
        mode.finish_internal_mission(session_id)


async def run_adaptation_loop(
    workspace: Any,
    inventory: ProviderInventory,
    migration_id: str,
    progress: ProgressReporter | None = None,
) -> AdaptationResult:
    root = (
        Path(workspace.workspace_dir)
        / ".qwenpaw"
        / "imports"
        / migration_id
        / "adaptation"
    )
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    manifest_path = root / "manifest.json"
    summary_path = root / "summary.md"
    staging_root = root / "staging"
    warnings = await run_sync_io(stage_local_assets, inventory, staging_root)
    store = CompatibilityStore(manifest_path)
    components = await run_sync_io(component_map, inventory)
    manifest = await run_sync_io(
        store.prepare,
        migration_id=migration_id,
        source=inventory.provider_id,
        skills=inventory.skills,
        mcp_servers=inventory.mcp_servers,
        plugins=inventory.plugins,
        scheduled_tasks=inventory.scheduled_tasks,
        components=components,
    )
    await _report(
        progress,
        f"工具和设置已安全暂存，共 {len(manifest.assets)} 项；"
        "正在启动 QwenPaw Mission 并行进行兼容性测试与修复…",
    )
    if not manifest.assets:
        manifest = await run_sync_io(store.finish)
        await run_sync_io(write_summary, summary_path, manifest)
        return AdaptationResult(
            manifest,
            summary_path,
        )

    tester = CompatibilityTester(workspace, inventory)
    context = ActiveAdaptationContext(
        inventory=inventory,
        store=store,
        tester=tester,
        staging_root=staging_root,
        manifest=manifest,
        progress=progress,
    )
    await _report(
        progress,
        f"各资产工具调用预算合计 {context.total_tool_budget} 次；"
        "单个修复 Agent 最长运行 30 分钟，推理上限按剩余预算动态分配。",
    )
    try:
        stopped_reason = await _repair_with_mission(
            workspace,
            context,
            root,
            warnings,
        )
        if stopped_reason:
            warnings.append(stopped_reason)
    except Exception as exc:  # pylint: disable=broad-except
        stopped_reason = f"无法完成 QwenPaw Mission：{type(exc).__name__}: {exc}"
        warnings.append(stopped_reason)

    complete, reason = await run_sync_io(store.complete)
    if not complete and not stopped_reason:
        stopped_reason = reason
    manifest = await run_sync_io(
        store.finish,
        stopped=not complete,
        reason="" if complete else stopped_reason,
    )
    await run_sync_io(write_summary, summary_path, manifest)
    await _report(
        progress,
        "兼容性迁移已结束："
        f"待迁移 {len(manifest.by_zone(AssetZone.MIGRATE))}，"
        f"待修复 {len(manifest.by_zone(AssetZone.REPAIR))}。",
    )
    return AdaptationResult(
        manifest=manifest,
        summary_path=summary_path,
    )
