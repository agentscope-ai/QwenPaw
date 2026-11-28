# -*- coding: utf-8 -*-
"""Author-facing integration host using the production loader and lifecycle.

This host owns process-wide plugin registries. Use one host per process; run
independent hosts in separate processes, just as independent QwenPaw instances.
"""

# Host adapters access private ownership state behind the public SDK.
# pylint: disable=protected-access

from __future__ import annotations

import asyncio

# Host bridges intentionally use private runtime seams. Local result imports
# also bind the contract types re-exported by this author-facing module.
# pylint: disable=protected-access,redefined-outer-name

import inspect
import os
import sys
from contextlib import aclosing, ExitStack
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import AsyncGenerator, Sequence, Mapping, Any
from .sdk import PluginContext

# Preserve the message types re-exported for plugin authors.
# pylint: disable-next=unused-import
from .messages import (
    Message,
    Attachment as Attachment,
    ContentBlock as ContentBlock,
)
from .apps import ChatRequest
from .events import ChatEvent, JSONValue
from .workflows import WorkflowResult
from .hooks import HookPhase, HookResult
from .markets import SearchPage
from .stops import StopResult
from .providers import ModelInfo, ModelToolChoice, ModelChunk
from .memory import MemoryTask
from .transcription import TranscriptionResult, TranscriptionStatus
from .harnesses import HarnessRunRequest, HarnessStatus
from .channels import ChannelMessage, ChannelHealth
from .results import (
    InstallResult,
    EnableResult,
    UnloadResult,
    ReloadResult,
    ConfigUpdateResult,
)
from .errors import SDKError
from .tools import ToolResult, ToolEvent
from ._testing_http import TestHttpResponse, TestConnection

_ACTIVE_HOST = None


class TestFault:
    """Scoped, finite fault injection around a real loader transaction step."""

    def __init__(self, loader, point, message, times):
        if point not in {"before_commit", "post_commit_cleanup"}:
            raise SDKError(
                "Fault point must be before_commit or post_commit_cleanup",
            )
        if times < 1:
            raise SDKError("Fault injection times must be positive")
        self.point, self.message, self.hits = point, message, 0
        self._loader, self._remaining = loader, times
        self._original = None

    def __enter__(self):
        original = self._original = self._loader._commit_plugin_transaction

        async def wrapped(*args, **kwargs):
            active = self._remaining > 0
            if active:
                self._remaining -= 1
                self.hits += 1
            if active and self.point == "before_commit":
                raise SDKError(self.message)
            result = await original(*args, **kwargs)
            if active:
                # The original durable commit has completed. Its shared error
                # list carries cleanup failure through the real result path.
                result.append(self.message)
            return result

        self._loader._commit_plugin_transaction = wrapped
        return self

    def __exit__(self, *_):
        self._loader._commit_plugin_transaction = self._original


@dataclass(frozen=True)
class TestApproval:
    request_id: str
    session_id: str
    workspace_id: str
    tool_name: str
    policy_name: str = ""


class TestModel:
    """
    A model built through the production formatter, usage and retry wrappers.
    """

    def __init__(self, model, workspace, workspace_id):
        self._model, self._workspace = model, workspace
        self._workspace_id = workspace_id

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict] = (),
        tool_choice: ModelToolChoice | None = None,
        options: dict | None = None,
        session_id: str = "test",
    ) -> AsyncGenerator[ModelChunk, None]:
        from ._models import stream_model

        stream = stream_model(
            self._model,
            self._workspace,
            session_id,
            messages,
            tools,
            tool_choice,
            options,
            workspace_id=self._workspace_id,
        )
        try:
            async for chunk in stream:
                yield chunk
        finally:
            await stream.aclose()


# The integration facade exposes one operation for each supported SDK service.
class PluginTestHost:  # pylint: disable=too-many-public-methods
    def __init__(
        self,
        root: Path,
        *,
        tool_policy: dict[str, str] | None = None,
        workspace_dirs: Mapping[str, str | Path] | None = None,
        process_channels: tuple[str, ...] = (),
    ):
        """Own isolated state; tools default to ALLOW, with explicit overrides.

        ``tool_policy`` maps public tool names to allow/deny/ask. ASK uses the
        real approval service and waits for ``resolve_approval`` from the test.
        """
        self.root = Path(root).resolve()
        self._restore = []
        self._dependency_readers = ExitStack()
        self._loader = None
        self._governors = {}
        self._tool_policy = dict(tool_policy or {})
        self._workspaces = {}
        self._workspace_locks = {}
        self._workspace_dirs = dict(workspace_dirs or {})
        if not isinstance(process_channels, tuple) or any(
            not isinstance(name, str) or not name for name in process_channels
        ):
            raise ValueError(
                "process_channels must be a tuple of channel names",
            )
        self._process_channels = process_channels
        paths = [self._workspace_path(key) for key in self._workspace_dirs]
        if len(set(paths)) != len(paths):
            raise SDKError("Workspace IDs must have distinct directories")
        self._connections = set()
        if set(self._tool_policy.values()) - {"allow", "deny", "ask"}:
            raise ValueError("tool_policy values must be allow, deny or ask")

    async def __aenter__(self) -> PluginTestHost:
        from ..utils.io_utils import run_sync_io

        try:
            result = self._enter()
            if self._process_channels:
                from ..__version__ import __version__
                from .channel_adapter import ChannelRuntimeSettings
                from .dependency_maintenance import scoped_environment_readers

                site = self.root / "channel-dependencies"
                site.mkdir(exist_ok=True)
                await run_sync_io(
                    self._dependency_readers.enter_context,
                    scoped_environment_readers((site,)),
                )
                self._loader.registry.configure_channel_runtime(
                    ChannelRuntimeSettings(
                        python_executable=sys.executable,
                        support_root=Path(__file__).resolve().parents[2],
                        qwenpaw_version=__version__,
                        selected_channels=frozenset(self._process_channels),
                        dependency_paths=(site,),
                        dependency_install_target=site,
                    ),
                )
            await self._app_services.start()
            return result
        except BaseException:
            if _ACTIVE_HOST is self:
                try:
                    await run_sync_io(self._dependency_readers.close)
                finally:
                    self._restore_environment()
            raise

    def _enter(self):
        global _ACTIVE_HOST
        if _ACTIVE_HOST is not None:
            raise SDKError("Only one PluginTestHost can own a process")
        from .. import constant
        from ..config import utils
        from .loader import PluginLoader
        from .registry import PluginRegistry
        from ..governance.audit import AuditLog
        from ..providers.provider_manager import ProviderManager
        from ..app.approvals import service as approvals

        self.root.mkdir(parents=True, exist_ok=True)
        self._old_environment = os.environ.get("QWENPAW_WORKING_DIR")
        old_root = constant.WORKING_DIR.resolve()
        old_secrets = constant.SECRET_DIR.resolve()
        # Imported constants retain values: rebind all already loaded modules,
        # and repeat the reverse mapping for modules imported during this host.
        self._old_roots = (old_root, old_secrets)
        _ACTIVE_HOST = self
        os.environ["QWENPAW_WORKING_DIR"] = str(self.root)
        for module in tuple(sys.modules.values()):
            if not getattr(module, "__name__", "").startswith("qwenpaw."):
                continue
            for name, value in tuple(vars(module).items()):
                if not isinstance(value, Path):
                    continue
                for original, replacement in (
                    (old_root, self.root),
                    (old_secrets, self.root / "secrets"),
                ):
                    if value.is_absolute() and value.is_relative_to(original):
                        self._restore.append((module, name, value))
                        setattr(
                            module,
                            name,
                            replacement / value.relative_to(original),
                        )
                        break
        for module, name, value in (
            (constant, "WORKING_DIR", self.root),
            (constant, "PLUGINS_DIR", self.root / "plugins"),
            (constant, "DEFAULT_MEDIA_DIR", self.root / "media"),
            (utils, "WORKING_DIR", self.root),
            (utils, "_config_cache", None),
            (utils, "_config_mtime", 0),
            (utils, "_agent_config_cache", {}),
            (PluginRegistry, "_instance", None),
            (AuditLog, "_instance", None),
            (ProviderManager, "_instance", None),
            (approvals, "_approval_service", approvals.ApprovalService()),
        ):
            self._restore.append((module, name, getattr(module, name)))
            setattr(module, name, value)
        self._loader = PluginLoader([self.root / "plugins"])
        self._workspace_manager = SimpleNamespace(
            agents=self._workspaces,
            _bootstrap_kwargs={},
        )
        self._loader.registry.set_workspace_manager(self._workspace_manager)
        self._workspace_manager.get_agent = self._workspace
        from fastapi import FastAPI
        from ..app.app_services.app_service_manager import AppServiceManager

        self._app_services = AppServiceManager()
        self._http_app = FastAPI()
        self._http_app.state.multi_agent_manager = self._workspace_manager
        self._http_app.state.app_services = self._app_services
        self._http_app.state.plugin_registry = self._loader.registry
        self._loader.registry.set_plugin_http_app(self._http_app)
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def close(self) -> None:
        """Retry cleanup after a failed close; ownership stays until it succeeds."""
        from .lifecycle import QuiescenceError, UnloadMode
        from ..utils.io_utils import run_sync_io

        if _ACTIVE_HOST is not self:
            return

        for connection in tuple(self._connections):
            await connection.close()
        for workspace_id, workspace in tuple(self._workspaces.items()):
            if workspace.cron_manager is not None:
                await workspace.cron_manager.stop()
            if workspace.channel_manager is not None:
                try:
                    await workspace.channel_manager.stop_all()
                except QuiescenceError as exc:
                    raise SDKError(
                        f"Workspace {workspace_id!r} channel cleanup has not "
                        "stopped; retry close()",
                    ) from exc
            # Native channel producers still persist their completion after
            # leaving the SDK invocation. Keep this host's environment until
            # that workspace-owned tail finishes; do not cancel its I/O.
            tasks = await workspace.task_tracker.snapshot_active_tasks(
                owner=workspace,
            )
            if not await workspace.task_tracker.wait_tasks_done(
                list(tasks.values()),
                timeout=5,
            ):
                raise SDKError(
                    f"Workspace {workspace_id!r} task completion has not "
                    f"stopped; retry close()",
                )
            if "memory_manager" in workspace._service_manager.services:
                await self.stop_memory(workspace_id=workspace_id)
        reports = await self._loader.lifecycle.unload_all(UnloadMode.UNLOAD)
        failures = [r for r in reports if not r.quiescent or not r.clean]
        if failures:
            # Retain registry, module and path ownership until resources stop.
            raise SDKError(f"Test host resources did not stop: {failures}")
        from ..governance.audit import AuditLog
        from ..app.approvals import get_approval_service

        service = get_approval_service()
        for pending in tuple(service._pending.values()):
            if not pending.future.done():
                pending.future.cancel()

        for workspace in self._workspaces.values():
            if workspace.transcript_store is not None:
                workspace.transcript_store.close()
        await self._app_services.stop()
        AuditLog.close_instance()
        for governor in self._governors.values():
            governor.stop()
        await run_sync_io(self._dependency_readers.close)
        self._restore_environment()

    def _restore_environment(self):
        global _ACTIVE_HOST

        recorded = {(id(module), name) for module, name, _ in self._restore}
        for module in tuple(sys.modules.values()):
            if not getattr(module, "__name__", "").startswith("qwenpaw."):
                continue
            for name, value in tuple(vars(module).items()):
                if (
                    (id(module), name) not in recorded
                    and isinstance(value, Path)
                    and value.is_relative_to(self.root)
                ):
                    relative = value.relative_to(self.root)
                    replacement = self._old_roots[0] / relative
                    if relative.parts[:1] == ("secrets",):
                        replacement = self._old_roots[1] / Path(
                            *relative.parts[1:],
                        )
                    setattr(module, name, replacement)
        for module, name, value in reversed(self._restore):
            setattr(module, name, value)
        if self._old_environment is None:
            os.environ.pop("QWENPAW_WORKING_DIR", None)
        else:
            os.environ["QWENPAW_WORKING_DIR"] = self._old_environment
        _ACTIVE_HOST = None

    async def load(
        self,
        path: Path,
        config: dict | None = None,
    ) -> PluginContext:
        _, manifest = self._loader.read_source_manifest(Path(path))
        record = await self._loader.lifecycle.load(
            manifest,
            Path(path),
            config,
        )
        if record.status != "active":
            raise SDKError(
                "; ".join(record.diagnostics)
                or f"Plugin load failed: {record.status}",
            )
        return self.context(manifest.id)

    async def run_workflow(
        self,
        name: str,
        *,
        workspace_id: str = "default",
        parameters: Mapping[str, JSONValue] | None = None,
        scheduled: bool = False,
    ) -> "WorkflowResult":
        """Invoke plugin-id:workflow through the real registered job callback.

        Uses the native scheduler and the production cancellation/notification
        bridge. This test helper is not a production manual-run endpoint.
        """
        from ..app.crons.manager import CronManager
        from ..app.crons.repo.json_repo import JsonJobRepository
        from .workflows import WorkflowResult

        workspace = await self._workspace(workspace_id)
        manager = workspace.cron_manager
        if manager is None:
            manager = CronManager(
                repo=JsonJobRepository(workspace.workspace_dir / "jobs.json"),
                workspace=workspace,
                channel_manager=None,
                agent_id=workspace_id,
            )
            workspace._service_manager.services["cron_manager"] = manager
            await manager.start()
        await self._loader.registry.projector.project_workspace(
            workspace,
            kinds={"sdk_workflow"},
        )
        plugin_id, separator, workflow = name.partition(":")
        job = (
            manager._scheduler.get_job(f"_service:sdk_{plugin_id}:{workflow}")
            if separator
            else None
        )
        if job is None:
            raise SDKError(
                "Workflow is not registered in this workspace: " + name,
            )
        result = await job.args[1].callback(
            scheduled=scheduled,
            parameters_override=parameters,
        )
        if not isinstance(result, WorkflowResult):
            raise SDKError("Workflow did not return a result")
        return result

    def inject_failure(
        self,
        point: str,
        *,
        message="SDK test injected failure",
        times=1,
    ) -> TestFault:
        return TestFault(self._loader, point, message, times)

    async def install(
        self,
        path: Path,
        config: dict | None = None,
        *,
        replace: bool = False,
        interrupt_tasks: bool = False,
    ) -> InstallResult:
        """Copy/install/activate through the real recovery transaction."""

        try:
            record = await self._loader.load_plugin_from_path(
                Path(path),
                config=config,
                install_dir=self.root / "plugins",
                force=replace,
                interrupt_tasks=interrupt_tasks,
            )
        except SDKError:
            raise
        except Exception as exc:
            from .activity import PluginBusyError

            if isinstance(exc, PluginBusyError):
                raise
            raise SDKError(str(exc)) from exc
        instance = self._loader.lifecycle.get_instance(record.manifest.id)
        diagnostics = tuple(
            dict.fromkeys(
                [*record.diagnostics, *getattr(instance, "diagnostics", ())],
            ),
        )
        return InstallResult(
            record.manifest.id,
            record.status == "active",
            record.status,
            record.manifest.version,
            diagnostics,
        )

    async def set_enabled(
        self,
        plugin_id: str,
        enabled: bool,
        *,
        interrupt_tasks: bool = False,
    ) -> EnableResult:
        report = await self._loader.lifecycle.set_enabled(
            plugin_id,
            enabled,
            interrupt_tasks=interrupt_tasks,
        )
        if hasattr(report, "quiescent"):
            return EnableResult(
                plugin_id,
                enabled,
                report.clean and report.quiescent,
                tuple(report.errors),
                report.quiescent,
                report.needs_restart,
            )
        return EnableResult(
            plugin_id,
            enabled,
            report is not None and report.status == "active",
            tuple(getattr(report, "diagnostics", ())),
        )

    async def uninstall(
        self,
        plugin_id: str,
        *,
        interrupt_tasks: bool = False,
    ) -> UnloadResult:
        """
        Delete only installed copies owned by this host's plugins directory.
        """
        async with self._loader.plugin_lifecycle(plugin_id):
            record = self._loader.get_loaded_plugin(plugin_id)
            destination = self.root / "plugins"
            source = (
                record.source_path
                if record is not None
                else self._loader._find_installed_plugin_dir(plugin_id)
            )
            if source is None:
                source = next(
                    (
                        path
                        for manifest, path in self._loader.discover_plugins()
                        if manifest.id == plugin_id
                    ),
                    None,
                )
            if destination.resolve() != destination or (
                source is not None
                and Path(source).resolve().parent != destination
            ):
                raise SDKError(
                    "Cannot uninstall an external plugin source; use unload() "
                    "or install() a copy into this host first",
                )
            return await self._unload(
                plugin_id,
                uninstall=True,
                interrupt_tasks=interrupt_tasks,
            )

    def _workspace_path(self, workspace_id):
        base = self.root / "workspaces"
        if (
            not workspace_id
            or Path(workspace_id).is_absolute()
            or ".." in Path(workspace_id).parts
        ):
            raise SDKError("Invalid workspace ID")
        relative = Path(self._workspace_dirs.get(workspace_id, workspace_id))
        path = (base / relative).resolve()
        if (
            relative.is_absolute()
            or not path.is_relative_to(base)
            or path == base
        ):
            raise SDKError("Workspace directory must be inside the test host")
        for other in self._workspaces.values():
            if (
                other.agent_id != workspace_id
                and other.workspace_dir.resolve() == path
            ):
                raise SDKError("Workspace IDs must have distinct directories")
        return path

    async def _workspace(self, workspace_id):
        lock = self._workspace_locks.setdefault(workspace_id, asyncio.Lock())
        async with lock:
            return await self._ensure_workspace(workspace_id)

    async def _ensure_workspace(self, workspace_id):
        from ..app.workspace.workspace import Workspace

        path = self._workspace_path(workspace_id)
        if workspace_id not in self._workspaces:
            from ..config.config import AgentProfileRef
            from ..config.utils import load_config, save_config

            config = load_config()
            config.agents.profiles[workspace_id] = AgentProfileRef(
                id=workspace_id,
                workspace_dir=str(path),
            )
            save_config(config)
            workspace = Workspace(workspace_id, str(path))
            workspace.set_app_services(self._app_services)
            from ..app.chats.manager import ChatManager
            from ..app.chats.repo.json_repo import JsonChatRepository
            from ..app.chats.session import DatabaseSession
            from ..app.chats.transcript_catalog import TranscriptCatalog

            workspace._service_manager.services["chat_manager"] = ChatManager(
                repo=JsonChatRepository(path / "chats.json"),
                shell_workspace_id=workspace_id,
                shell_targets_dir=self.root / "shell-targets",
            )
            catalog = TranscriptCatalog(path)
            workspace._service_manager.services["transcript_store"] = catalog
            workspace._service_manager.services["session"] = DatabaseSession(
                catalog=catalog,
                legacy_save_dir=str(path / "sessions"),
                backend_runtime=lambda: workspace.backend_runtime,
            )
            from ..hooks.session import SessionLoadHook, SessionSaveHook
            from ..checkpoints.hooks import CheckpointQueryGateHook
            from ..runtime.builtin_commands import (
                collect_builtin_command_specs,
            )

            workspace.bootstrap_plugins(
                builtin_hook_clses=[
                    CheckpointQueryGateHook,
                    SessionLoadHook,
                    SessionSaveHook,
                ],
                builtin_command_specs=collect_builtin_command_specs(),
            )
            self._workspaces[workspace_id] = workspace
            from ..governance.resource_governor import ResourceGovernor
            from ..governance.policy import GovernanceRule, GovernanceAction
            from ..governance.tool_registry import DEFAULT_REGISTRY
            from ..utils.io_utils import run_sync_io

            def configure_policy():
                governor = ResourceGovernor(str(path))
                governor.add_rule(
                    GovernanceRule(
                        "*(**)",
                        GovernanceAction.ALLOW,
                        reason="PluginTestHost explicit test policy",
                    ),
                )
                for tool_name, action in self._tool_policy.items():
                    policy_name = DEFAULT_REGISTRY.python_to_policy_name(
                        tool_name,
                    )
                    governor.add_rule(
                        GovernanceRule(
                            f"{policy_name}(**)",
                            GovernanceAction(action),
                            reason="PluginTestHost explicit policy override",
                        ),
                    )

            await run_sync_io(configure_policy)
            for func in self._workspace_manager._bootstrap_kwargs.get(
                "builtin_tool_funcs",
                [],
            ):
                workspace.plugins.tool_registry.register(func._tool_descriptor)
            for hook in self._loader.registry.get_workspace_created_hooks():
                result = hook.callback(
                    {
                        "workspace": workspace,
                        "agent_id": workspace_id,
                        "workspace_dir": str(path),
                    },
                )
                if inspect.isawaitable(result):
                    await result
        return self._workspaces[workspace_id]

    async def _request_context(
        self,
        workspace_id,
        session_id,
        messages=(),
        *,
        user_id="test",
        channel="console",
        session_saved=None,
    ):
        from ..runtime.hooks import HookContext
        from ..schemas import AgentRequest
        from .._session_signals import SESSION_SAVE_SUCCEEDED_KEY
        from ._messages import to_host

        workspace = await self._workspace(workspace_id)
        return HookContext(
            request=AgentRequest(
                input=[],
                session_id=session_id,
                user_id=user_id,
                channel=channel,
            ),
            session_id=session_id,
            agent_id=workspace_id,
            root_session_id=session_id,
            root_agent_id=workspace_id,
            workspace_dir=workspace.workspace_dir,
            workspace=workspace,
            app_services=None,
            input_msgs=[to_host(message) for message in messages],
            extras={SESSION_SAVE_SUCCEEDED_KEY: session_saved},
        )

    async def call_command(
        self,
        text: str,
        *,
        workspace_id: str = "test",
        session_id: str = "test",
        messages: Sequence[Message] = (),
        user_id: str = "test",
        channel: str = "console",
    ) -> Message | None:
        from ._messages import from_host

        context = await self._request_context(
            workspace_id,
            session_id,
            messages,
            user_id=user_id,
            channel=channel,
        )
        result = (
            await context.workspace.plugins.slash_command_registry.dispatch(
                text,
                context,
            )
        )
        return from_host(result) if result is not None else None

    async def call_control_command(
        self,
        text: str,
        *,
        workspace_id: str = "test",
        session_id: str = "test",
        messages: Sequence[Message] = (),
        user_id: str = "test",
        channel: str = "console",
    ) -> Message | None:
        """Dispatch a declared control command through the real registry.

        This helper verifies declaration and result handling; use a running
        channel to verify immediate queue routing while another turn is busy.
        """
        workspace = await self._workspace(workspace_id)
        match = workspace.plugins.slash_command_registry.resolve(text)
        if match is None or match[0].metadata.get("sdk_control") is not True:
            raise SDKError("Not a registered SDK control command")
        return await self.call_command(
            text,
            workspace_id=workspace_id,
            session_id=session_id,
            messages=messages,
            user_id=user_id,
            channel=channel,
        )

    async def run_hooks(
        self,
        phase: HookPhase | str,
        *,
        messages: Sequence[Message] = (),
        workspace_id: str = "test",
        session_id: str = "test",
        user_id: str = "test",
        channel: str = "console",
        session_saved: bool | None = None,
    ) -> HookResult:
        from ..runtime.phases import Phase
        from ._messages import from_host
        from .hooks import ContextInjection

        context = await self._request_context(
            workspace_id,
            session_id,
            messages,
            user_id=user_id,
            channel=channel,
            session_saved=session_saved,
        )
        initial_messages = tuple(
            from_host(message) for message in context.input_msgs
        )
        result = await context.workspace.plugins.hook_registry.run(
            Phase(phase),
            context,
        )
        final_messages = tuple(
            from_host(message) for message in context.input_msgs
        )
        return HookResult(
            (
                "reply"
                if result.action.value == "short_circuit"
                else result.action.value
            ),
            from_host(result.payload) if result.payload is not None else None,
            final_messages if final_messages != initial_messages else None,
            tuple(
                ContextInjection(item["content"], item["priority"])
                for item in context.context_injections
            ),
        )

    async def build_prompt(
        self,
        *,
        workspace_id: str = "test",
        session_id: str = "test",
        messages: Sequence[Message] = (),
        user_id: str = "test",
        channel: str = "console",
    ) -> str:
        context = await self._request_context(
            workspace_id,
            session_id,
            messages,
            user_id=user_id,
            channel=channel,
        )
        return await context.workspace.plugins.prompt_manager.build(context)

    async def evaluate_stop(
        self,
        *,
        workspace_id: str = "test",
        session_id: str = "test",
        user_id: str = "test",
        channel: str = "console",
        iteration: int = 1,
        max_iterations: int = 20,
        has_tool_calls: bool = False,
        final_message: Message | None = None,
        cancelled: bool = False,
    ) -> "StopResult":
        """Evaluate the real host chain with an explicit simulated turn."""
        from ..loop.gates.runner import run_stop_handlers
        from ._messages import to_host
        from .stops import StopResult

        if iteration < 1 or max_iterations < 1:
            raise ValueError("Iteration counts and budgets must be positive")
        if cancelled:
            return StopResult("stop", reason="User cancelled")
        workspace = await self._workspace(workspace_id)
        agent = SimpleNamespace(
            agent_id=workspace_id,
            react_config=SimpleNamespace(max_iters=max_iterations),
            _request_context={
                "agent_id": workspace_id,
                "session_id": session_id,
                "user_id": user_id,
                "channel": channel,
            },
        )
        final = (
            None
            if has_tool_calls
            else to_host(final_message or Message("assistant", ()))
        )
        result = await run_stop_handlers(
            workspace.plugins.stop_handlers,
            agent=agent,
            final_msg=final,
            iteration=iteration - 1,
        )
        return StopResult(
            (
                "continue"
                if result.action.value == "interrupt_and_continue"
                else "stop"
            ),
            result.continuation_message,
            result.reason,
        )

    async def start_channel(
        self,
        name: str,
        settings: dict | None = None,
        *,
        workspace_id: str = "test",
    ) -> None:
        """
        Start the real queue; None reuses saved settings, {} replaces them.
        """
        from ..app.channels.manager import ChannelManager
        from ..config.config import load_agent_config, save_agent_config
        from ..utils.io_utils import run_sync_io
        from .api import channel_passes_gates

        workspace = await self._workspace(workspace_id)

        def save():
            config = load_agent_config(workspace_id)
            values = (
                getattr(config.channels, name, {})
                if settings is None
                else settings
            )
            if hasattr(values, "model_dump"):
                values = values.model_dump()
            setattr(config.channels, name, {**(values or {}), "enabled": True})
            save_agent_config(workspace_id, config)
            return config

        workspace._config = await run_sync_io(save)
        if not channel_passes_gates(workspace, name):
            raise SDKError("Channel is unavailable or disabled")
        manager = workspace.channel_manager
        if manager is None:
            manager = ChannelManager([])
            manager.set_workspace(workspace)
            workspace._service_manager.services["channel_manager"] = manager
            await manager.start_all()
        registration = self._loader.registry.get_channel_registration(
            name,
        )
        if registration is None:
            raise SDKError("Channel has no active plugin registration")
        try:
            await self._loader.registry.projector.project_one(
                workspace,
                "channel",
                name,
                registration.plugin_id,
            )
            # A deliberate manager stop retains the projector's declaration.
            # Re-enter the real idempotent start primitive with current config;
            # an old projection binding must not suppress the next start.
            await manager.start_one(name, workspace._config)
        except SDKError:
            raise
        except Exception as exc:
            raise SDKError(str(exc)) from exc

    async def receive_channel(
        self,
        name: str,
        message: ChannelMessage,
        *,
        workspace_id: str = "test",
    ) -> None:
        workspace = await self._workspace(workspace_id)
        manager = workspace.channel_manager
        channel = await manager.get_channel(name) if manager else None
        if channel is None or not hasattr(channel, "_sdk_context"):
            raise SDKError("SDK channel is not running")
        channel._sdk_context.receive(message)

    async def stop_channel(
        self,
        name: str,
        *,
        workspace_id: str = "test",
    ) -> None:
        workspace = await self._workspace(workspace_id)
        if workspace.channel_manager is None:
            return
        receipt = await workspace.channel_manager.stop_one(name)
        if not receipt.stopped:
            raise SDKError(receipt.detail)

    async def set_channel_access(
        self,
        name: str,
        user_id: str,
        allowed: bool,
        *,
        workspace_id: str = "test",
    ) -> None:
        """
        Change the real workspace ACL, using the platform sender identity.
        """
        from ..app.channels.access_control import get_access_control_store
        from ..utils.io_utils import run_sync_io

        workspace = await self._workspace(workspace_id)
        if type(allowed) is not bool or not user_id:
            raise SDKError(
                "Channel access requires a sender and boolean decision",
            )
        store = get_access_control_store(workspace.workspace_dir)
        await run_sync_io(
            store.add_to_whitelist if allowed else store.add_to_blacklist,
            name,
            user_id,
        )

    async def send_channel(
        self,
        name: str,
        text: str,
        *,
        user_id: str,
        session_id: str,
        workspace_id: str = "test",
        metadata: dict | None = None,
        require_delivery: bool = True,
    ) -> None:
        """Send through the same ChannelManager path as scheduled messages."""
        workspace = await self._workspace(workspace_id)
        if workspace.channel_manager is None:
            raise SDKError("Channel manager is not running")
        await workspace.channel_manager.send_text(
            channel=name,
            user_id=user_id,
            session_id=session_id,
            text=text,
            meta={**(metadata or {}), "_api_send": require_delivery},
        )

    async def health_channel(
        self,
        name: str,
        *,
        workspace_id: str = "test",
    ) -> ChannelHealth:
        workspace = await self._workspace(workspace_id)
        if workspace.channel_manager is None:
            raise SDKError("Channel manager is not running")
        value = await workspace.channel_manager.get_channel_health(name)
        return ChannelHealth(value["status"], value.get("detail", ""))

    async def configure_tool(
        self,
        name: str,
        settings: dict,
        *,
        workspace_id="test",
    ):
        """Persist declared tool settings through the normal agent.json writer."""
        from ..config.config import (
            load_agent_config,
            save_agent_config,
            BuiltinToolConfig,
        )
        from ..utils.io_utils import run_sync_io

        await self._workspace(workspace_id)
        context = self._tool_context(name)
        spec = context._tools[name][0]
        declared = {field["name"] for field in spec.config_fields}
        if set(settings) - declared:
            raise SDKError("Tool settings must be declared by this tool")

        def save():
            config = load_agent_config(workspace_id)
            entry = config.tools.builtin_tools.setdefault(
                name,
                BuiltinToolConfig(name=name),
            )
            entry.config = dict(settings)
            save_agent_config(workspace_id, config)

        await run_sync_io(save)

    async def mode_names(self, *, workspace_id="test") -> tuple[str, ...]:
        workspace = await self._workspace(workspace_id)
        return tuple(mode.name for mode in workspace.plugins.modes)

    async def active_modes(
        self,
        *,
        workspace_id: str = "test",
        session_id: str = "test",
        messages: Sequence[Message] = (),
        user_id: str = "test",
        channel: str = "console",
    ) -> tuple[str, ...]:
        context = await self._request_context(
            workspace_id,
            session_id,
            messages,
            user_id=user_id,
            channel=channel,
        )
        return tuple(
            mode.name
            for mode in context.workspace.plugins.modes
            if mode.is_active(context)
        )

    async def run_mode(
        self,
        name: str,
        event: str,
        *,
        workspace_id: str = "test",
        session_id: str = "test",
        messages: Sequence[Message] = (),
        user_id: str = "test",
        channel: str = "console",
    ) -> None:
        if event not in {"turn_start", "reset"}:
            raise SDKError("Mode events are turn_start or reset")
        context = await self._request_context(
            workspace_id,
            session_id,
            messages,
            user_id=user_id,
            channel=channel,
        )
        mode = next(
            (
                mode
                for mode in context.workspace.plugins.modes
                if mode.name == name
            ),
            None,
        )
        if mode is None:
            raise SDKError(f"Unknown mode: {name}")
        callback = (
            mode.on_turn_start
            if event == "turn_start"
            else mode.on_conversation_reset
        )
        await callback(context)

    async def available_tools(
        self,
        *,
        workspace_id="test",
        session_id="test",
        messages=(),
        allowed=(),
    ) -> tuple[str, ...]:
        workspace = await self._workspace(workspace_id)
        active = await self.active_modes(
            workspace_id=workspace_id,
            session_id=session_id,
            messages=messages,
        )
        return tuple(
            desc.name
            for desc in workspace.plugins.tool_registry.filter(
                active_modes=set(active),
                allowed=set(allowed),
            )
        )

    async def skill_files(self, *, workspace_id="test") -> tuple[str, ...]:
        from ..agents.skill_system.store import get_workspace_skills_dir

        workspace = await self._workspace(workspace_id)
        root = get_workspace_skills_dir(workspace.workspace_dir)
        return tuple(
            sorted(
                path.relative_to(root).as_posix()
                for path in root.rglob("*")
                if path.is_file()
            ),
        )

    async def read_skill(self, name: str, *, workspace_id="test") -> str:
        from ..agents.skill_system.store import get_workspace_skills_dir

        workspace = await self._workspace(workspace_id)
        root = get_workspace_skills_dir(workspace.workspace_dir).resolve()
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise SDKError("Skill path must stay inside the workspace")
        return path.read_text(encoding="utf-8")

    async def search_market(
        self,
        key: str,
        query: str,
        *,
        page: int = 1,
        limit: int = 10,
        lang: str = "en",
        category: str | None = None,
    ) -> SearchPage:
        from ..market.service import search_market
        from .markets import MarketResult

        results, errors, pagination = await search_market(
            query,
            {key: page},
            limit,
            lang=lang,
            category=category,
        )
        if errors:
            raise SDKError("; ".join(error.message for error in errors))
        if key not in pagination:
            raise SDKError(f"Unknown market: {key}")
        return SearchPage(
            tuple(
                MarketResult(
                    item.slug,
                    item.name,
                    item.source_url,
                    item.description,
                    item.version,
                    item.author,
                    item.icon_url,
                    item.stats or {},
                )
                for item in results
            ),
            *pagination[key],
        )

    async def install_market_skill(
        self,
        key: str,
        url: str,
        *,
        workspace_id="test",
        version="",
        enable=False,
    ) -> str:
        from ..agents.skill_system.hub import install_skill_from_hub

        workspace = await self._workspace(workspace_id)
        result = await install_skill_from_hub(
            workspace_dir=workspace.workspace_dir,
            bundle_url=url,
            provider_key=key,
            version=version,
            enable=enable,
        )
        return result.name

    async def configure_provider(
        self,
        provider_id: str,
        *,
        api_key="",
        base_url=None,
        options=None,
    ):
        from ..providers.provider_manager import ProviderManager

        values = {"api_key": api_key}
        if base_url is not None:
            values["base_url"] = base_url
        if options is not None:
            values["generate_kwargs"] = options
        if not await ProviderManager.get_instance().update_provider_async(
            provider_id,
            values,
        ):
            raise SDKError(f"Unknown provider: {provider_id}")

    async def configure_chat_model(
        self,
        provider_id: str,
        model_id: str,
        *,
        workspace_id="test",
    ):
        from ..config.config import load_agent_config, save_agent_config
        from ..providers.provider_manager import ModelSlotConfig
        from ..utils.io_utils import run_sync_io

        workspace = await self._workspace(workspace_id)

        def configure():
            profile = load_agent_config(workspace_id)
            profile.active_model = ModelSlotConfig(
                provider_id=provider_id,
                model=model_id,
            )
            save_agent_config(workspace_id, profile)
            return profile

        workspace._config = await run_sync_io(configure)

    async def create_model(
        self,
        provider_id: str,
        model_id: str,
        *,
        workspace_id="test",
    ) -> TestModel:
        from ..agents.model_factory import create_model_and_formatter_async
        from ..providers.provider_manager import ModelSlotConfig

        workspace = await self._workspace(workspace_id)
        model, _formatter = await create_model_and_formatter_async(
            agent_id=workspace_id,
            model_slot_override=ModelSlotConfig(
                provider_id=provider_id,
                model=model_id,
            ),
        )
        return TestModel(model, workspace.workspace_dir, workspace_id)

    async def transcribe(
        self,
        backend_id: str,
        file_path: str,
        *,
        workspace_id: str = "",
        session_id: str = "",
    ) -> TranscriptionResult:
        """Invoke the lifecycle-owned production transcription adapter."""
        backend = self._loader.registry.get_transcription_backend(backend_id)
        if backend is None:
            raise SDKError(f"Unknown transcription backend: {backend_id}")
        return await backend.transcribe(
            file_path=file_path,
            workspace_id=workspace_id,
            session_id=session_id,
        )

    async def transcription_status(
        self,
        backend_id: str,
    ) -> TranscriptionStatus:
        backend = self._loader.registry.get_transcription_backend(backend_id)
        if backend is None:
            raise SDKError(f"Unknown transcription backend: {backend_id}")
        return await backend.status()

    async def discover_models(self, provider_id: str) -> tuple[ModelInfo, ...]:
        from ..providers.provider_manager import ProviderManager

        provider = ProviderManager.get_instance().get_provider(provider_id)
        if provider is None:
            raise SDKError(f"Unknown provider: {provider_id}")
        return tuple(
            ModelInfo(
                item.id,
                item.name,
                item.max_input_length,
                item.max_output_length,
                bool(item.supports_image),
                bool(item.supports_video),
                item.is_free,
            )
            for item in await provider.fetch_models()
        )

    async def _driver_manager(self, workspace_id):
        from ..drivers.manager import DriverManager
        from ..drivers.credentials.store import AsyncCredentialStore
        from ..app.approvals.driver_gate import QwenPawDriverApprovalGate
        from ._drivers import attach_driver_protocols

        workspace = await self._workspace(workspace_id)
        services = workspace._service_manager.services
        manager = services.get("driver_manager")
        if manager is None:
            manager = DriverManager(
                workspace.workspace_dir / "drivers",
                AsyncCredentialStore(
                    workspace.workspace_dir / "credentials.yaml",
                ),
                approval_gate=QwenPawDriverApprovalGate(),
            )
            services["driver_manager"] = manager
        attach_driver_protocols(manager, self._loader.registry, workspace)
        return manager

    async def open_driver(
        self,
        source,
        *,
        workspace_id="test",
        session_scope="",
    ):
        from ..drivers.contracts import DriverCard
        from .drivers import _freeze, _thaw

        try:
            card = DriverCard(**_thaw(_freeze(source)))
            manager = await self._driver_manager(workspace_id)
            if session_scope:
                await manager.replace_transient_drivers(session_scope, [card])
            else:
                await manager.register_driver(card)
        except Exception as exc:
            raise SDKError(str(exc)) from exc

    async def list_driver_capabilities(
        self,
        source_id,
        *,
        workspace_id="test",
        session_scope="",
    ):
        from ..drivers.constants import DRIVER_SCOPE_CONTEXT_KEY
        from .drivers import _freeze
        from dataclasses import asdict

        try:
            manager = await self._driver_manager(workspace_id)
            capabilities = await manager.list_driver_capabilities(
                source_id,
                request_context={DRIVER_SCOPE_CONTEXT_KEY: session_scope},
            )
            return tuple(_freeze(asdict(value)) for value in capabilities)
        except Exception as exc:
            raise SDKError(str(exc)) from exc

    async def call_driver(
        self,
        source_id,
        name,
        arguments,
        *,
        workspace_id="test",
        session_scope="",
        session_id="test",
        user_id="test",
        channel="console",
    ):
        from ..drivers.capabilities import (
            DriverInvocation,
            format_capability_id,
        )
        from ..drivers.constants import DRIVER_SCOPE_CONTEXT_KEY

        manager = await self._driver_manager(workspace_id)
        try:
            handler = manager._get_handler(source_id)
            result = await manager.invoke_capability(
                DriverInvocation(
                    format_capability_id(
                        handler.card.protocol,
                        source_id,
                        "tool",
                        "invoke",
                        name,
                    ),
                    dict(arguments),
                    {
                        "agent_id": workspace_id,
                        "session_id": session_id,
                        "user_id": user_id,
                        "channel": channel,
                        DRIVER_SCOPE_CONTEXT_KEY: session_scope,
                    },
                ),
            )
            if not result.ok:
                raise SDKError(result.message)
            return result.value
        except Exception as exc:
            raise SDKError(str(exc)) from exc

    async def close_driver(
        self,
        source_id,
        *,
        workspace_id="test",
        session_scope="",
    ):
        try:
            manager = await self._driver_manager(workspace_id)
            await manager.close_driver(source_id, session_scope=session_scope)
        except Exception as exc:
            raise SDKError(str(exc)) from exc

    async def start_memory(
        self,
        backend_id: str,
        *,
        workspace_id="test",
        config=None,
    ):
        """Select and construct memory via Workspace's real ServiceManager."""
        from ..config.config import load_agent_config, save_agent_config
        from ..utils.io_utils import run_sync_io

        workspace = await self._workspace(workspace_id)
        manager = workspace._service_manager
        if "memory_manager" in manager.services:
            raise SDKError(
                "Stop the workspace's memory service before replacing it",
            )

        def configure():
            profile = load_agent_config(workspace_id)
            profile.running.memory_manager_backend = backend_id
            profile.running.memory_backend_configs[backend_id] = dict(
                config or {},
            )
            save_agent_config(workspace_id, profile)
            return profile

        workspace._config = await run_sync_io(configure)
        await manager._start_service(manager.descriptors["memory_manager"])
        service = manager.services.get("memory_manager")
        if service is None or getattr(service, "_backend", None) is None:
            raise SDKError("Memory service did not start")

    async def stop_memory(self, *, workspace_id="test"):
        from ..config.config import load_agent_config, save_agent_config
        from ..utils.io_utils import run_sync_io

        workspace = await self._workspace(workspace_id)
        manager = workspace._service_manager
        try:
            await manager._stop_service(
                manager.descriptors["memory_manager"],
                final=True,
            )
        except RuntimeError as exc:
            raise SDKError(str(exc)) from exc
        manager.services.pop("memory_manager", None)

        def deselect():
            config = load_agent_config(workspace_id)
            config.running.memory_manager_backend = "remelight"
            save_agent_config(workspace_id, config)
            return config

        workspace._config = await run_sync_io(deselect)

    async def search_memory(
        self,
        query: str,
        *,
        workspace_id="test",
        max_results=5,
    ) -> ToolResult:
        from ._messages import _from_block

        workspace = await self._workspace(workspace_id)
        service = workspace._service_manager.services.get("memory_manager")
        if service is None:
            raise SDKError("Memory service is not started")
        result = await service.memory_search(query, max_results)
        return ToolResult(
            tuple(_from_block(block) for block in result.content),
            str(result.state) == "error",
            dict(result.metadata),
        )

    async def remember(self, messages, *, workspace_id="test") -> str:
        from ._messages import to_host

        workspace = await self._workspace(workspace_id)
        service = workspace._service_manager.services.get("memory_manager")
        if service is None:
            raise SDKError("Memory service is not started")
        return await service.auto_memory(
            [to_host(message) for message in messages],
        )

    async def submit_memory(self, messages, *, workspace_id="test") -> str:
        from ._messages import to_host

        workspace = await self._workspace(workspace_id)
        service = workspace._service_manager.services.get("memory_manager")
        if service is None:
            raise SDKError("Memory service is not started")
        return service.submit_auto_memory(
            [to_host(message) for message in messages],
        )

    async def memory_tasks(
        self,
        *,
        workspace_id: str = "test",
    ) -> tuple[MemoryTask, ...]:
        workspace = await self._workspace(workspace_id)
        service = workspace._service_manager.services.get("memory_manager")
        return (
            tuple(
                MemoryTask(
                    item["task_id"],
                    item["status"],
                    item.get("result"),
                    item.get("error"),
                )
                for item in service.list_auto_memory_tasks()
            )
            if service
            else ()
        )

    def list_harnesses(self) -> tuple[dict[str, Any], ...]:
        """List external backend metadata without constructing any backend."""
        from ._harness_http import backend_catalog

        return tuple(backend_catalog(self._loader.registry)[1:])

    async def harness_status(
        self,
        backend_id: str,
        *,
        workspace_id: str,
    ) -> HarnessStatus:
        workspace = await self._workspace(workspace_id)
        return await workspace.backend_runtime.call(backend_id, "status")

    async def run_harness(
        self,
        backend_id: str,
        request: HarnessRunRequest,
        *,
        workspace_id: str,
        session_id: str,
        user_id: str = "test",
        channel: str = "console",
    ) -> AsyncGenerator[ChatEvent, None]:
        """Run public values through the production backend stream bridge."""
        from ..schemas import AgentRequest
        from ._events import chat_event

        workspace = await self._workspace(workspace_id)
        contents = [{"type": "text", "text": request.prompt}]
        for attachment in request.attachments:
            if attachment.kind == "image":
                contents.append(
                    {"type": "image", "image_url": str(attachment.path)},
                )
            else:
                contents.append(
                    {
                        "type": "file",
                        "file_url": str(attachment.path),
                        "filename": attachment.name,
                    },
                )
        trusted = AgentRequest(
            input=[{"role": "user", "content": contents}],
            session_id=session_id,
            user_id=user_id,
            channel=channel,
            agent_id=workspace_id,
        )
        from ..config.config import load_agent_config, save_agent_config
        from ..utils.io_utils import run_sync_io

        def select_backend():
            config = load_agent_config(workspace_id)
            config.backend = backend_id
            save_agent_config(workspace_id, config)
            return config

        workspace._config = await run_sync_io(select_backend)
        stream = workspace.stream_query(trusted)
        try:
            async for item in stream:
                yield chat_event(item)
        finally:
            await stream.aclose()

    async def stream_chat(
        self,
        text: str | ChatRequest,
        *,
        workspace_id: str = "test",
        session_id: str = "test",
        user_id: str = "test",
    ) -> AsyncGenerator[ChatEvent, None]:
        """
        Run the production Runtime, including registered command/hook routes.
        """
        from ..schemas import AgentRequest
        from ._events import chat_event

        workspace = await self._workspace(workspace_id)

        public = (
            text
            if isinstance(text, ChatRequest)
            else ChatRequest(text, session_id=session_id)
        )
        text = (
            f"/{public.skill} {public.text}" if public.skill else public.text
        )
        request = AgentRequest(
            input=[
                {"role": "user", "content": [{"type": "text", "text": text}]},
            ],
            session_id=public.session_id or session_id,
            user_id=user_id,
            channel="console",
            agent_id=workspace_id,
            request_id=public.request_id,
        )
        async with aclosing(workspace.stream_query(request)) as stream:
            async for result in stream:
                yield chat_event(result)

    def open_http(
        self,
        method: str,
        path: str,
        *,
        workspace_id="test",
        user_id="test",
        headers=None,
        body=b"",
        json=None,
    ) -> TestConnection:
        """Open an unbuffered ASGI response; use async with and chunks()."""

        if json is not None:
            import json as codec

            body = codec.dumps(json).encode()
            headers = {"content-type": "application/json", **(headers or {})}
        return TestConnection(
            self,
            method,
            path,
            workspace_id=workspace_id,
            user_id=user_id,
            headers=headers,
            body=body,
        )

    def websocket(
        self,
        path: str,
        *,
        workspace_id="test",
        user_id="test",
        headers=None,
    ) -> TestConnection:
        return TestConnection(
            self,
            "GET",
            path,
            workspace_id=workspace_id,
            user_id=user_id,
            headers=headers,
            websocket=True,
        )

    async def request(
        self,
        method: str,
        path: str,
        **kwargs,
    ) -> TestHttpResponse:
        async with self.open_http(method, path, **kwargs) as stream:
            body = b"".join([chunk async for chunk in stream.chunks()])
            return TestHttpResponse(stream.status, stream.headers, body)

    def context(self, plugin_id: str) -> PluginContext:
        instance = self._loader.lifecycle.get_instance(plugin_id)
        context = getattr(instance, "sdk_context", None)
        if context is None:
            raise SDKError(f"Plugin {plugin_id!r} has no SDK context")
        return context

    def _tool_context(self, name):
        for instance in self._loader.lifecycle._instances.values():
            context = getattr(instance, "sdk_context", None)
            if context is not None and name in context._tools:
                return context
        raise SDKError(f"Unknown tool: {name}")

    async def _tool_chunks(
        self,
        name: str,
        arguments: dict,
        *,
        workspace_id: str = "test",
        session_id: str = "test",
        user_id: str = "test",
        channel: str = "console",
    ) -> AsyncGenerator[Any, None]:
        from ..governance.tool_registry import DEFAULT_REGISTRY
        from ..governance.tool_adapter import PolicyGuardedTool
        from ..governance.resource_governor import ResourceGovernor
        from ..governance.policy import GovernanceRule, GovernanceAction
        from ..config.context import current_workspace_dir, current_session_id
        from agentscope.permission import PermissionBehavior
        from ..agents import tools

        context = self._tool_context(name)
        if DEFAULT_REGISTRY.get_owner(name) != context.plugin_id:
            raise SDKError(
                f"Tool {name!r} has no active governance registration",
            )
        workspace = self._workspace_path(workspace_id)
        governor = self._governors.get(workspace_id)
        if governor is None:
            governor = ResourceGovernor(
                str(workspace),
                governance_dir=str(self.root / "governance"),
            )
            governor.start()
            governor.policy.user_rules.insert(
                0,
                GovernanceRule(
                    "*(**)",
                    GovernanceAction.ALLOW,
                    reason="PluginTestHost explicit test policy",
                ),
            )
            for tool_name, action in self._tool_policy.items():
                policy_name = DEFAULT_REGISTRY.python_to_policy_name(tool_name)
                governor.policy.user_rules.insert(
                    0,
                    GovernanceRule(
                        f"{policy_name}(**)",
                        GovernanceAction(action),
                        reason="PluginTestHost explicit policy override",
                    ),
                )
            self._governors[workspace_id] = governor
        invoke = getattr(tools, name, None)
        if invoke is None or invoke is not context._tools[name][2]:
            raise SDKError(f"Tool {name!r} is not registered in the runtime")
        # __new__ returns a dynamically constructed FunctionTool subclass.
        tool: Any = PolicyGuardedTool(
            invoke,
            governor=governor,
            request_context={
                "agent_id": workspace_id,
                "session_id": session_id,
                "user_id": user_id,
                "channel": channel,
            },
        )
        decision = await tool.check_permissions(arguments)
        if decision.behavior is not PermissionBehavior.ALLOW:
            raise SDKError(f"Tool invocation denied: {decision.message}")
        # __new__ returns a dynamic FunctionTool subclass with __call__ installed.
        normalized = await tool(**arguments)  # pylint: disable=not-callable
        try:
            while True:
                workspace_token = current_workspace_dir.set(workspace)
                session_token = current_session_id.set(session_id)
                try:
                    chunk = await anext(normalized)
                except StopAsyncIteration:
                    return
                finally:
                    current_session_id.reset(session_token)
                    current_workspace_dir.reset(workspace_token)
                yield chunk
        finally:
            await normalized.aclose()

    async def stream_tool(
        self,
        name: str,
        arguments: dict,
        *,
        workspace_id: str = "test",
        session_id: str = "test",
        user_id: str = "test",
        channel: str = "console",
    ) -> AsyncGenerator[ToolEvent, None]:
        chunks = self._tool_chunks(
            name,
            arguments,
            workspace_id=workspace_id,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        try:
            async for chunk in chunks:
                from ._messages import _from_block, _take_tool_metadata

                if chunk.is_last:
                    yield ToolEvent("end")
                    continue
                (
                    metadata,
                    previews,
                    kind,
                    is_error,
                    block_metadata,
                ) = _take_tool_metadata(chunk.metadata, chunk.content)
                if kind is None:
                    raise SDKError(
                        "Tool returned an invalid SDK result envelope",
                    )
                content = tuple(
                    _from_block(block, previews, block_metadata, str(index))
                    for index, block in enumerate(chunk.content)
                )
                result = (
                    ToolResult(tuple(content), is_error, metadata)
                    if kind == "result"
                    else None
                )
                yield ToolEvent(
                    kind,
                    tuple(content) if kind == "delta" else (),
                    result,
                )
        finally:
            await chunks.aclose()

    async def approval_requests(
        self,
        session_id: str = "test",
    ) -> list[TestApproval]:
        from ..app.approvals import get_approval_service
        from ..governance.tool_registry import DEFAULT_REGISTRY

        pending = await get_approval_service().list_pending_by_session(
            session_id,
        )
        names = {
            DEFAULT_REGISTRY.python_to_policy_name(name): name
            for instance in self._loader.lifecycle._instances.values()
            for name in getattr(
                getattr(instance, "sdk_context", None),
                "_tools",
                {},
            )
        }
        return [
            TestApproval(
                item.request_id,
                item.session_id,
                item.agent_id,
                names.get(item.tool_name, item.tool_name),
                item.tool_name,
            )
            for item in pending
        ]

    async def resolve_approval(
        self,
        request_id: str,
        *,
        approved: bool,
    ) -> bool:
        from ..app.approvals import get_approval_service
        from ..app.approvals.service import ApprovalActor
        from ..security.tool_guard.approval import ApprovalDecision

        service = get_approval_service()
        pending = await service.get_request(request_id)
        if pending is None:
            return False
        actor = ApprovalActor(
            pending.session_id,
            pending.root_session_id,
            pending.user_id,
            pending.channel,
            pending.agent_id,
        )
        resolved = await service.resolve_request(
            request_id,
            ApprovalDecision.APPROVED if approved else ApprovalDecision.DENIED,
            actor=actor,
        )
        return resolved is not None

    async def call_tool(
        self,
        name: str,
        arguments: dict,
        *,
        workspace_id: str = "test",
        session_id: str = "test",
        user_id: str = "test",
        channel: str = "console",
    ) -> ToolResult:
        from agentscope.tool import ToolResponse
        from ._messages import _from_block, _take_tool_metadata

        response = ToolResponse()
        chunks = self._tool_chunks(
            name,
            arguments,
            workspace_id=workspace_id,
            session_id=session_id,
            user_id=user_id,
            channel=channel,
        )
        try:
            async for chunk in chunks:
                response.append_chunk(chunk)
        finally:
            await chunks.aclose()
        metadata, previews, kind, error, block_metadata = _take_tool_metadata(
            response.metadata,
            response.content,
        )
        if kind != "end":
            raise SDKError("Tool returned no terminal SDK result envelope")
        return ToolResult(
            tuple(
                _from_block(block, previews, block_metadata, str(index))
                for index, block in enumerate(response.content)
            ),
            error,
            metadata,
        )

    async def reload(
        self,
        plugin_id: str,
        *,
        interrupt_tasks: bool = False,
        new_source: Path | None = None,
        config: dict | None = None,
    ) -> ReloadResult:
        report = await self._loader.lifecycle.reload(
            plugin_id,
            new_source=new_source,
            config=config,
            interrupt_tasks=interrupt_tasks,
        )
        return ReloadResult(
            report.plugin_id,
            report.ok,
            report.unchanged,
            tuple(report.errors),
            report.generation,
            report.needs_restart,
        )

    async def update_config(
        self,
        plugin_id: str,
        config: dict,
        *,
        interrupt_tasks: bool = False,
    ) -> ConfigUpdateResult:
        report = await self._loader.lifecycle.update_config(
            plugin_id,
            config,
            interrupt_tasks=interrupt_tasks,
        )
        return ConfigUpdateResult(
            report.plugin_id,
            report.ok,
            report.unchanged,
            tuple(report.errors),
            report.requires_confirmation,
            report.conflict,
            tuple(report.legacy_hooks),
            report.needs_restart,
            report.quiescent,
        )

    async def unload(
        self,
        plugin_id: str,
        *,
        interrupt_tasks: bool = False,
    ) -> UnloadResult:
        return await self._unload(
            plugin_id,
            uninstall=False,
            interrupt_tasks=interrupt_tasks,
        )

    async def _unload(self, plugin_id, *, uninstall, interrupt_tasks):
        from .lifecycle import UnloadMode

        report = await self._loader.lifecycle.unload(
            plugin_id,
            UnloadMode.UNINSTALL if uninstall else UnloadMode.UNLOAD,
            interrupt_tasks=interrupt_tasks,
        )
        return UnloadResult(
            report.plugin_id,
            report.mode.value,
            report.clean,
            tuple(report.errors),
            tuple(report.leftovers),
            tuple(report.workspace_leaks),
            report.quiescent,
            report.needs_restart,
        )

    def resource_snapshot(self, plugin_id: str) -> dict:
        instance = self._loader.lifecycle.get_instance(plugin_id)
        if instance is None:
            return {"closed": True, "resources": (), "active_calls": 0}
        context = getattr(instance, "sdk_context", None)
        result = context.resources.snapshot() if context else {"resources": ()}
        return {
            **result,
            "active_calls": sum(instance.activity.tasks.values())
            + instance.activity.sync_calls,
            "generation": instance.generation,
            "state": instance.state.value,
        }

    def assert_quiescent(self, plugin_id: str) -> None:
        state = self.resource_snapshot(plugin_id)
        if state["resources"] or state["active_calls"]:
            raise AssertionError(f"Plugin resources remain active: {state}")
