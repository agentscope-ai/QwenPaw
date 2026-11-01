# -*- coding: utf-8 -*-
# pylint: disable=protected-access
# ChannelManager is the framework owner of BaseChannel and must call
# _is_native_payload and _consume_one_request as part of the contract.

from __future__ import annotations

import asyncio
import logging
import hashlib
import os
from copy import deepcopy
from itertools import groupby
from pathlib import Path

from dataclasses import dataclass, replace
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    TYPE_CHECKING,
)

from .base import BaseChannel, ContentType, ProcessHandler, TextContent
from .renderer import ChannelDisplayConfig
from .isolated_proxy import IsolatedChannelProxy
from .command_registry import CommandRegistry
from .registry import get_channel_registry
from .unified_queue_manager import EnqueueResult, UnifiedQueueManager
from ...config import get_available_channels

if TYPE_CHECKING:
    from ...config.config import Config

logger = logging.getLogger(__name__)

# Callback when user reply was sent: (channel, user_id, session_id)
OnLastDispatch = Optional[Callable[[str, str, str], Awaitable[None]]]

# Default max size per channel queue
_CHANNEL_QUEUE_MAXSIZE = 1000
_CHANNEL_START_STOP_TIMEOUT = 3.0
_CHANNEL_DRAIN_TIMEOUT = 5.0


@dataclass(frozen=True)
class ChannelHandle:
    """Opaque start result. Today the live object is a ``BaseChannel``."""

    key: str
    channel: Any
    manager: Any = None


@dataclass
class StopReceipt:
    """Result of ``ChannelManager.stop_one``."""

    key: str
    stopped: bool
    detail: str = ""
    instance_id: str | None = None
    generation: int | None = None
    exited: bool | None = None
    returncode: int | None = None
    forced: bool = False
    residual: tuple[str, ...] = ()


@dataclass(frozen=True)
class OwnedQueuePayload:
    channel: BaseChannel
    instance_id: str
    generation: int
    payload: Any


def runtime_stop_receipt(receipt, handle):
    """Translate Channel evidence at the adapter boundary."""
    from ...plugins.ownership import RuntimeStopReceipt

    channel = handle.channel
    lease = (
        getattr(channel, "_runtime_lease", None)
        if isinstance(channel, IsolatedChannelProxy)
        else None
    )
    if lease is not None:
        # An already released exact lease is safe even if its Manager now
        # holds a successor. A current lease still requires identity proof.
        if lease not in channel._owner_registry.runtime_owners.leases():
            return RuntimeStopReceipt(True, receipt.detail)
        identity_matches = (
            receipt.instance_id == lease.instance_id
            and receipt.generation == lease.generation
        )
    else:
        identity_matches = True
    process_backed = isinstance(channel, IsolatedChannelProxy)
    return RuntimeStopReceipt(
        receipt.stopped and identity_matches,
        receipt.detail,
        exited=receipt.exited is True if process_backed else True,
        returncode=receipt.returncode,
        forced=receipt.forced,
        residual=receipt.residual,
    )


def channel_cfg_for_key(
    workspace_config: Any,
    key: str,
    *,
    raw: bool = False,
) -> Any | None:
    """Return the config section for *key*, or ``None`` if absent."""
    channels = getattr(workspace_config, "channels", None)
    if channels is None:
        return None
    extra = getattr(channels, "__pydantic_extra__", None) or {}
    ch_cfg = (
        channels.get(key)
        if isinstance(channels, dict)
        else getattr(channels, key, None)
    )
    if ch_cfg is None and key in extra:
        ch_cfg = extra[key]
    if ch_cfg is None:
        return None
    if isinstance(ch_cfg, dict) and not raw:
        from types import SimpleNamespace

        from ...config.config import BaseChannelConfig

        defaults = BaseChannelConfig().model_dump()
        defaults.update(ch_cfg)
        return SimpleNamespace(**defaults)
    return ch_cfg


def channel_enabled(ch_cfg: Any) -> bool:
    if isinstance(ch_cfg, dict):
        return bool(ch_cfg.get("enabled", False))
    return bool(getattr(ch_cfg, "enabled", False))


def live_channel_managers() -> list[Any]:
    """ChannelManager instances on the current live workspace set."""
    from ...plugins.workspace_projector import default_live_workspaces

    managers: list[Any] = []
    seen: set[int] = set()
    for workspace in default_live_workspaces():
        manager = getattr(workspace, "channel_manager", None)
        if manager is None:
            continue
        ident = id(manager)
        if ident in seen:
            continue
        seen.add(ident)
        managers.append(manager)
    return managers


@dataclass
class _ChannelStartContext:
    """One immutable input baseline, retained until start or cleanup finishes."""

    key: str
    config: Any
    source: str
    config_ref: Any
    config_snapshot: Any
    configured_id: Any
    row: Any
    description: Any
    settings: Any
    settings_snapshot: Any
    workspace_dir: Path | None
    state_root: Any
    working_dir: Path
    environment: dict
    manager_config: Any
    manager_dir: Any
    workspace_binding: tuple | None = None
    prepared: Any = None
    candidate: Any = None
    execution: Any = None
    identity: Any = None
    owner: Any = None

    @classmethod
    def capture(cls, manager, key, config, source="config"):
        from ... import constant
        from ...plugins.registry import PluginRegistry

        row = PluginRegistry().get_channel_catalog_entry(key)
        directory = manager._workspace_dir
        if directory is None and manager._workspace is not None:
            directory = getattr(manager._workspace, "workspace_dir", None)
        context = cls(
            key,
            config,
            source,
            channel_cfg_for_key(config, key, raw=True),
            deepcopy(channel_cfg_for_key(config, key)),
            getattr(config, "id", None),
            row,
            row.description_record if row else None,
            row.runtime_settings if row else None,
            deepcopy(row.runtime_settings) if row else None,
            Path(directory).expanduser().resolve() if directory else None,
            constant.WORKING_DIR,
            Path.cwd(),
            dict(os.environ),
            manager._workspace_config,
            manager._workspace_dir,
        )
        context.validate(manager, initial=True)
        return context

    def bind(self, manager):
        # Synchronous factories permit set_workspace before asynchronous start.
        if self.workspace_binding is None:
            self.workspace_binding = (manager._workspace,)

    def prepare(self):
        return self.description.prepare_proxy_config(
            deepcopy(self.config_snapshot),
            workspace_dir=self.workspace_dir,
            config_source=self.source,
            no_text_debounce=getattr(
                self.config_snapshot,
                "no_text_debounce",
                True,
            ),
            working_dir=self.working_dir,
            legacy_state_dir=self.state_root,
            environment=self.environment,
        )

    def adopt(self, manager, channel):
        self.candidate = channel
        spec = channel._launch_spec
        self.execution = replace(
            spec,
            config=deepcopy(dict(spec.config)),
            runtime_identity=(
                deepcopy(dict(spec.runtime_identity))
                if spec.runtime_identity is not None
                else None
            ),
            private_env=dict(spec.private_env),
        )
        self.identity = channel._identity()
        self.owner = channel._runtime_lease
        manager._start_contexts[channel] = self

    def validate(self, manager, channel=None, *, initial=False):
        from ... import constant
        from ...plugins.registry import PluginRegistry
        from .registry import selected_process_channels

        registry = PluginRegistry()
        row = self.row
        error = (
            "CHANNEL_UNAVAILABLE" if initial else "CHANNEL_PREPARATION_STALE"
        )
        if (
            row is None
            or self.settings is None
            or self.description is None
            or registry.get_channel_catalog_entry(self.key) is not row
            or row.description_record is not self.description
            or row.runtime_settings is not self.settings
            or self.settings != self.settings_snapshot
            or not row.global_enabled
            or not self.settings.allows(self.key)
            or self.key not in selected_process_channels()
            or self.key not in get_available_channels()
            or self.config_ref is None
            or channel_cfg_for_key(self.config, self.key, raw=True)
            is not self.config_ref
            or channel_cfg_for_key(self.config, self.key)
            != self.config_snapshot
            or not channel_enabled(self.config_snapshot)
            or getattr(self.config, "id", None) != self.configured_id
        ):
            raise RuntimeError(error)
        if self.workspace_dir is None:
            raise RuntimeError(
                "WORKSPACE_IDENTITY_REQUIRED" if initial else error,
            )
        directory = manager._workspace_dir
        if directory is None and manager._workspace is not None:
            directory = getattr(manager._workspace, "workspace_dir", None)
        if (
            manager._stopping
            or manager._defer_channel_start
            or manager._workspace_config is not self.manager_config
            or manager._workspace_dir != self.manager_dir
            or (
                self.workspace_binding is not None
                and manager._workspace is not self.workspace_binding[0]
            )
            or directory is None
            or Path(directory).expanduser().resolve() != self.workspace_dir
            or constant.WORKING_DIR != self.state_root
            or (
                self.prepared is not None
                and self.prepared.description is not self.description
            )
            or not registry.projector.start_allowed(
                "channel",
                self.key,
                row.plugin_id,
                manager._workspace,
            )
        ):
            raise RuntimeError("CHANNEL_PREPARATION_STALE")
        if channel is not None and (
            channel is not self.candidate
            or manager._start_contexts.get(channel) is not self
            or channel.channel != self.key
            or channel._registration is not row
            or channel._launch_spec != self.execution
            or channel._workspace_dir != self.workspace_dir
            or channel._identity() != self.identity
            or channel._owner_registry is not registry
            or channel._runtime_lease is not self.owner
            or self.owner not in registry.runtime_owners.leases()
            or manager._find_channel(self.key) not in (None, channel)
        ):
            raise RuntimeError("CHANNEL_PREPARATION_STALE")


def instantiate_channel(
    key: str,
    workspace_config: Any,
    *,
    process: ProcessHandler,
    on_last_dispatch: OnLastDispatch = None,
    workspace_dir: Path | None = None,
    config_source: str = "config",
    context=None,
    manager=None,
) -> BaseChannel:
    """Build one channel instance from workspace config (three-gate caller)."""
    from ...plugins.registry import PluginRegistry
    from .registry import selected_process_channels

    plugin_registry = PluginRegistry()
    if key in selected_process_channels():
        if context is None or context.prepared is None:
            raise RuntimeError("CHANNEL_PREPARATION_STALE")
        context.validate(manager)
        row = context.row
        ch_cfg = context.config_snapshot
        workspace_dir = context.workspace_dir
        assert workspace_dir is not None
        config_source = context.source
        prepared_config = context.prepared
        instance_id = (
            "channel:"
            + hashlib.sha256(
                (str(Path(workspace_dir).resolve()) + "\0" + key).encode(),
            ).hexdigest()
        )
        from ...plugins.ownership import RuntimeKey, RuntimeStopReceipt

        identity_claims = ()
        if key == "voice":
            from .conflict import get_channel_bot_identity

            identity_claims = tuple(
                ("channel:voice:" + name, value)
                for name, value in (
                    get_channel_bot_identity(key, ch_cfg) or ()
                )
            )
        lease = plugin_registry.runtime_owners.reserve(
            row.plugin_id,
            RuntimeKey("channel", key, str(Path(workspace_dir).resolve())),
            row.description_record.code_root,
            instance_id=instance_id,
            identity_claims=identity_claims,
        )
        settings = row.runtime_settings
        claims = ()
        runtime_config = ch_cfg
        connection_timeout = settings.connection_timeout
        if connection_timeout is None and row.plugin_id == key == "wechat":
            from ...plugins.official_channel_catalog import (
                official_channel_for_plugin,
            )

            official = official_channel_for_plugin(row.plugin_id)
            if official is not None and official["channel_key"] == key:
                connection_timeout = 330.0
        try:
            if row.plugin_id == key == "wechat":
                runtime_config = prepared_config.config
            plugin_registry.dependency_usage.bind(lease, row.dependency_token)
            channel = row.description_record.create_proxy(
                process,
                runtime_config,
                python_executable=settings.python_executable,
                support_root=settings.support_root,
                qwenpaw_version=settings.qwenpaw_version,
                dependency_paths=settings.dependency_paths,
                runtime_identity=settings.runtime_identity,
                instance_id=instance_id,
                generation=lease.generation,
                workspace_dir=workspace_dir,
                on_reply_sent=on_last_dispatch,
                display_config=ChannelDisplayConfig.from_config(
                    ch_cfg,
                    show_tool_details=getattr(
                        workspace_config,
                        "show_tool_details",
                        True,
                    ),
                ),
                no_text_debounce=getattr(ch_cfg, "no_text_debounce", True),
                startup_timeout=settings.startup_timeout,
                connection_timeout=connection_timeout,
                shutdown_timeout=settings.shutdown_timeout,
                send_timeout=settings.send_timeout_for(key),
                config_source=config_source,
                prepared_config=prepared_config,
            )
            channel._owner_registry = plugin_registry
            channel.bind_dependency_usage(
                plugin_registry.dependency_usage,
                lease,
            )
            channel._runtime_lease = lease
            channel._wechat_auth_claims = claims
            channel._registration = row
            channel._admission_timeout = settings.admission_timeout
            context.adopt(manager, channel)
        except BaseException:
            from .wechat_auth_custody import release_wechat_auth

            evidence = RuntimeStopReceipt(
                True,
                "construction produced no resources",
            )
            release_wechat_auth(plugin_registry, claims, evidence)
            plugin_registry.runtime_owners.release(
                lease,
                evidence,
            )
            raise
        return channel
    registry = get_channel_registry()
    ch_cls = registry.get(key)
    if ch_cls is None:
        raise RuntimeError("CHANNEL_UNAVAILABLE")
    ch_cfg = channel_cfg_for_key(workspace_config, key)
    if ch_cfg is None:
        raise RuntimeError(f"No config found for channel '{key}'")
    show_tool_details = getattr(
        workspace_config,
        "show_tool_details",
        True,
    )
    no_text_debounce = getattr(ch_cfg, "no_text_debounce", True)
    from_config_kwargs: dict[str, Any] = {
        "process": process,
        "config": ch_cfg,
        "on_reply_sent": on_last_dispatch,
        "display_config": ChannelDisplayConfig.from_config(
            ch_cfg,
            show_tool_details=show_tool_details,
        ),
        "no_text_debounce": no_text_debounce,
        "workspace_dir": workspace_dir,
    }
    import inspect

    sig = inspect.signature(ch_cls.from_config)
    if any(
        p.kind == inspect.Parameter.VAR_KEYWORD
        for p in sig.parameters.values()
    ):
        filtered_kwargs = from_config_kwargs
    else:
        filtered_kwargs = {
            k: v for k, v in from_config_kwargs.items() if k in sig.parameters
        }
    return ch_cls.from_config(**filtered_kwargs)


def _acl_identity_of(payload: Any) -> str:
    """Return the ACL identity a payload would be judged by.

    Mirrors the preference order in ``BaseChannel._access_control_gate``
    so grouping and gating never disagree.
    """
    if isinstance(payload, dict):
        return str(
            payload.get("acl_sender_id") or payload.get("sender_id") or "",
        )
    return str(
        getattr(payload, "acl_sender_id", "")
        or getattr(payload, "user_id", "")
        or "",
    )


def _split_batch_by_acl_identity(batch: List[Any]) -> List[List[Any]]:
    """Split a drained batch into runs that share one ACL identity.

    A shared-session group chat (``share_session_in_group=True``) routes
    every member to the same queue key, so a drained batch can hold
    messages from different senders. Merging those would concatenate all
    senders' content while keeping only the first sender's
    ``acl_sender_id``, letting one member's message be judged by another
    member's access-control decision. Grouping first keeps the original
    intent (merge one sender's rapid-fire messages) without ever merging
    across senders. Arrival order is preserved.
    """
    groups: List[List[Any]] = []
    current_identity: Optional[str] = None
    for payload in batch:
        identity = _acl_identity_of(payload)
        if groups and identity == current_identity:
            groups[-1].append(payload)
        else:
            groups.append([payload])
            current_identity = identity
    return groups


async def _process_batch(ch: BaseChannel, batch: List[Any]) -> None:
    """Merge if needed and process one payload (native or request)."""
    if ch.channel == "dingtalk" and batch and ch._is_native_payload(batch[0]):
        first = batch[0] if isinstance(batch[0], dict) else {}
        logger.info(
            "manager _process_batch dingtalk: batch_len=%s first_has_sw=%s",
            len(batch),
            bool(first.get("session_webhook")),
        )
    if len(batch) > 1 and ch._is_native_payload(batch[0]):
        merged = ch.merge_native_items(batch)
        if ch.channel == "dingtalk" and isinstance(merged, dict):
            logger.info(
                "manager _process_batch dingtalk merged: has_sw=%s",
                bool(merged.get("session_webhook")),
            )
        await ch._consume_one_request(merged)
    elif len(batch) > 1:
        merged = ch.merge_requests(batch)
        if merged is not None:
            await ch._consume_one_request(merged)
        else:
            await ch.consume_one(batch[0])
    elif ch._is_native_payload(batch[0]):
        await ch._consume_one_request(batch[0])
    else:
        await ch.consume_one(batch[0])


async def _process_owned_batch(default_channel, batch):
    """Keep queued process messages on their original owner and generation."""

    def owner(item):
        return (
            (item.channel, item.instance_id, item.generation)
            if isinstance(item, OwnedQueuePayload)
            else (default_channel, None, None)
        )

    for (bound_channel, instance_id, generation), items in groupby(
        batch,
        key=owner,
    ):
        values = list(items)
        if instance_id is not None:
            identity = bound_channel._identity()
            if (identity.instance_id, identity.generation) != (
                instance_id,
                generation,
            ):
                logger.warning(
                    "Discarding stale queued channel generation",
                )
                continue
            values = [item.payload for item in values]
        for group in _split_batch_by_acl_identity(values):
            await _process_batch(bound_channel, group)


async def _complete_queue_batch(channel, batch):
    # Plugin invocation ownership belongs to this request, never to the
    # long-lived queue consumer. Its cancellation must leave that consumer
    # available for the next batch.
    execution = asyncio.create_task(_process_owned_batch(channel, batch))
    try:
        await asyncio.shield(execution)
        return True
    except asyncio.CancelledError:
        if not asyncio.current_task().cancelling():
            return False
        # Cancelling the consumer still owns cancellation and cleanup of its
        # request. Repeated cancellation must not interrupt that cleanup.
        if not execution.done() and not execution.cancelling():
            execution.cancel()
        from ...utils.io_utils import run_async_to_completion

        await run_async_to_completion(
            asyncio.gather(execution, return_exceptions=True),
        )
        raise


class ChannelManager:  # pylint: disable=too-many-public-methods
    """Owns queues and consumer loops; channels define how to consume via
    consume_one(). Enqueue via enqueue(channel_id, payload) (thread-safe).
    """

    def __init__(self, channels: List[BaseChannel]):
        self.channels = channels
        self._start_contexts: dict[Any, _ChannelStartContext] = {}
        self._lock = asyncio.Lock()
        self._channel_lifecycle_locks: dict[str, asyncio.Lock] = {}
        self._failed_channels: set[str] = set()
        self._prepared_stop_channels: set[str] = set()
        self._stopping = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._process: ProcessHandler | None = None
        self._on_last_dispatch: OnLastDispatch = None
        self._workspace_dir: Path | None = None
        self._workspace_config: Any = None

        # New unified queue system
        self._command_registry = CommandRegistry()
        self._queue_manager: UnifiedQueueManager | None = None
        self._workspace = None

        # Per-channel locks to prevent concurrent restarts
        self._stopping = False
        self._defer_channel_start = False
        self._paused_channels: set[str] = set()
        self._started_channels: set[int] = set()

        # Track enqueue tasks for graceful shutdown
        self._enqueue_tasks: set[asyncio.Task] = set()

        # Track channel-start tasks for graceful shutdown
        self._start_tasks: set[asyncio.Task] = set()
        self._start_task_channels: dict[asyncio.Task, BaseChannel] = {}
        for channel in channels:
            self._attach_runtime(channel)

    def _channel_handle(self, channel):
        handle = channel.__dict__.get("_manager_handle")
        if not isinstance(handle, ChannelHandle) or handle.manager is not self:
            handle = ChannelHandle(channel.channel, channel, self)
            channel._manager_handle = handle
        return handle

    def _attach_runtime(self, channel):
        handle = self._channel_handle(channel)
        if not isinstance(channel, IsolatedChannelProxy):
            return
        lease = getattr(channel, "_runtime_lease", None)
        if lease is None:
            return

        async def stop():
            receipt = await self.stop_one(channel.channel, expected=handle)
            return runtime_stop_receipt(receipt, handle)

        channel._owner_registry.runtime_owners.attach(
            lease,
            stop,
            resource=channel,
        )
        ingress = getattr(
            channel._owner_registry,
            "channel_ingress_service",
            None,
        )
        if ingress is not None:
            ingress.attach(channel)

    def _replace_binding(self, key, old, handle):
        from ...plugins.registry import PluginRegistry

        registry = PluginRegistry()
        row = registry.get_channel_registration(key)
        if self._workspace is not None and row is not None and old is not None:
            registry.projector.replace_binding(
                "channel",
                key,
                row.plugin_id,
                self._workspace,
                expected=self._channel_handle(old),
                token=handle,
            )

    def register_control_command(
        self,
        prefix: str,
        *,
        priority_level: int | None = None,
        owner: str | None = None,
    ) -> None:
        """Register a control command on this workspace's live registry."""
        self._command_registry.register_command(
            prefix,
            priority_level=10 if priority_level is None else priority_level,
            owner=owner,
        )

    def unregister_control_command(
        self,
        prefix: str,
        *,
        owner: str | None = None,
    ) -> bool:
        """Drop one command this *owner* previously registered here."""
        return self._command_registry.unregister_command(
            prefix,
            owner=owner,
        )

    def is_control_command(self, query: str) -> bool:
        """Whether *query* matches a command on this workspace."""
        return self._command_registry.is_control_command(query)

    @classmethod
    def from_env(
        cls,
        process: ProcessHandler,
        on_last_dispatch: OnLastDispatch = None,
        workspace_dir: Path | None = None,
    ) -> "ChannelManager":
        """
        Create channels from env and inject unified process
        (AgentRequest -> Event stream).
        process is typically workspace.stream_query.
        on_last_dispatch: called when a user send+reply was sent.
        """
        available = get_available_channels()
        registry = get_channel_registry()
        import os
        from types import SimpleNamespace
        from ...config.channel_env import read_channel_env
        from ...config.utils import get_config_path
        from ...plugins.registry import PluginRegistry

        channels: list[BaseChannel] = [
            ch_cls.from_env(process, on_reply_sent=on_last_dispatch)
            for key, ch_cls in registry.items()
            if key in available
        ]
        workspace_dir = workspace_dir or get_config_path().parent
        env_channels = {}
        for key, row in PluginRegistry().get_channel_catalog().items():
            if key not in available or row.description_record is None:
                continue
            props = row.description_record.descriptor.config_schema.get(
                "properties",
                {},
            )
            values = {
                name: field["default"]
                for name, field in props.items()
                if "default" in field
            }
            values.update(read_channel_env(key, os.environ) or {})
            env_channels[key] = values
        env_config = SimpleNamespace(channels=env_channels)
        manager = cls(channels)
        manager._workspace_dir = workspace_dir
        manager._workspace_config = env_config
        try:
            for key in env_channels:
                if not channel_enabled(env_channels[key]):
                    continue
                context = _ChannelStartContext.capture(
                    manager,
                    key,
                    env_config,
                    "env",
                )
                context.prepared = context.prepare()
                channels.append(
                    instantiate_channel(
                        key,
                        env_config,
                        process=process,
                        on_last_dispatch=on_last_dispatch,
                        workspace_dir=workspace_dir,
                        config_source="env",
                        context=context,
                        manager=manager,
                    ),
                )
        except BaseException:
            for channel in tuple(manager._start_contexts):
                manager._release_unstarted(channel)
            raise
        for channel in channels:
            manager._attach_runtime(channel)
        manager._process = process
        manager._on_last_dispatch = on_last_dispatch
        return manager

    @classmethod
    def from_config(
        cls,
        process: ProcessHandler,
        config: "Config",
        on_last_dispatch: OnLastDispatch = None,
        workspace_dir: Path | None = None,
        *,
        defer_process_channels: bool = False,
    ) -> "ChannelManager":
        """Create channels from config (config.json or agent.json).

        Args:
            process: Process handler for agent communication
            config: Configuration object with channels
            on_last_dispatch: Callback for dispatch events
            workspace_dir: Agent workspace directory for channel state files
            defer_process_channels: Let the plugin projector construct process
                channels after their dependency admission.
        """
        if type(defer_process_channels) is not bool:
            raise ValueError("Invalid deferred process channel policy")
        available = get_available_channels()
        channels: list[BaseChannel] = []
        from .registry import selected_process_channels

        process_channels = selected_process_channels()
        manager = cls(channels)
        manager._workspace_dir = workspace_dir
        manager._workspace_config = config
        for key in dict.fromkeys((*get_channel_registry(), *process_channels)):
            if defer_process_channels and key in process_channels:
                continue
            if key not in available:
                continue
            ch_cfg = channel_cfg_for_key(config, key)
            if ch_cfg is None or not channel_enabled(ch_cfg):
                continue
            try:
                context = None
                if key in process_channels:
                    context = _ChannelStartContext.capture(
                        manager,
                        key,
                        config,
                    )
                    context.prepared = context.prepare()
                channels.append(
                    instantiate_channel(
                        key,
                        config,
                        process=process,
                        on_last_dispatch=on_last_dispatch,
                        workspace_dir=workspace_dir,
                        context=context,
                        manager=manager,
                    ),
                )
            except Exception as e:
                logger.warning(
                    "Failed to initialize channel '%s', skipping: %s",
                    key,
                    e,
                )
                continue

        for channel in channels:
            manager._attach_runtime(channel)
        manager._process = process
        manager._on_last_dispatch = on_last_dispatch
        return manager

    def _bind_enqueue(self, channel):
        if (
            channel.channel in self._failed_channels
            or channel.channel in self._prepared_stop_channels
        ):
            return
        self._paused_channels.discard(channel.channel)
        if not getattr(channel, "uses_manager_queue", True):
            return
        if isinstance(channel, IsolatedChannelProxy):

            async def admit(payload):
                return await self.enqueue_async(
                    channel,
                    payload,
                    timeout=getattr(channel, "_admission_timeout", 30.0),
                )

            channel.set_enqueue_async(admit)
            channel._ingress_open = True
            channel._admission_wakeup = (
                self._queue_manager.wake_admissions
                if self._queue_manager is not None
                else None
            )
        else:
            channel.set_enqueue(
                self._make_enqueue_cb(channel.channel, channel),
            )

    def _close_ingress(self, channel):
        self._paused_channels.add(channel.channel)
        channel.set_enqueue(None)
        if isinstance(channel, IsolatedChannelProxy):
            channel.set_enqueue_async(None)
        if self._queue_manager is not None:
            self._queue_manager.wake_admissions()

    def _release_unstarted(self, channel):
        self._close_ingress(channel)
        if (
            isinstance(channel, IsolatedChannelProxy)
            and channel._owner_registry is not None
        ):
            from ...plugins.ownership import RuntimeStopReceipt
            from .wechat_auth_custody import release_wechat_auth

            evidence = RuntimeStopReceipt(True, "never started")
            release_wechat_auth(
                channel._owner_registry,
                getattr(channel, "_wechat_auth_claims", ()),
                evidence,
            )
            channel._wechat_auth_claims = ()
            channel._owner_registry.runtime_owners.release(
                channel._runtime_lease,
                evidence,
            )
        self._start_contexts.pop(channel, None)

    async def enqueue_async(
        self,
        channel: BaseChannel,
        payload: Any,
        *,
        timeout: float = 30.0,
    ) -> EnqueueResult:
        queue_manager = self._queue_manager
        if queue_manager is None:
            return EnqueueResult(False, "QUEUE_UNAVAILABLE", True)
        identity = channel._identity()

        def guard():
            current = self._find_channel(channel.channel)
            if (
                current is not None and current is not channel
            ) or channel._identity() != identity:
                return EnqueueResult(False, "STALE_GENERATION", False)
            if current is None or not channel._ingress_open:
                return EnqueueResult(False, "CHANNEL_STOPPING", True)
            return None

        query = channel._extract_query_from_payload(payload)
        return await queue_manager.admit(
            channel.channel,
            self._extract_session_id(channel, payload),
            self._command_registry.get_priority_level(query),
            OwnedQueuePayload(
                channel,
                identity.instance_id,
                identity.generation,
                payload,
            ),
            timeout=timeout,
            admission_guard=guard,
        )

    def _make_enqueue_cb(
        self,
        channel_id: str,
        owner=None,
    ) -> Callable[[Any], None]:
        """Return a callback that enqueues payload for the given channel."""

        def dispatch(payload):
            if owner is None or self._find_channel(channel_id) is owner:
                self._enqueue_one(channel_id, payload)

        def cb(payload: Any) -> None:
            if self._loop is not None:
                self._loop.call_soon_threadsafe(dispatch, payload)

        return cb

    def _extract_session_id(
        self,
        ch: BaseChannel,
        payload: Any,
    ) -> str:
        """Extract normalized session_id from payload.

        Args:
            ch: Channel instance
            payload: Native dict or AgentRequest

        Returns:
            Normalized session_id (e.g. "console:user1")

        Note:
            Uses same logic as ch.get_debounce_key for consistency
        """
        # Check if payload already has normalized session_id
        # (e.g. from batch merge or previous processing)
        if isinstance(payload, dict):
            existing_sid = payload.get("session_id")
            if existing_sid:
                return existing_sid

        if hasattr(payload, "session_id"):
            existing_sid = payload.session_id
            if existing_sid:
                return existing_sid

        # Use channel's debounce key (delegates to resolve_session_id)
        return ch.get_debounce_key(payload)

    def _enqueue_one(self, channel_id: str, payload: Any) -> None:
        """Run on event loop: classify priority and route to queue manager.

        Note:
            This is the new routing layer using UnifiedQueueManager
        """
        if channel_id in self._paused_channels or self._stopping:
            return
        if self._queue_manager is None:
            logger.warning(
                "enqueue: queue_manager not initialized for channel=%s",
                channel_id,
            )
            return

        # Get channel instance
        ch = next(
            (c for c in self.channels if c.channel == channel_id),
            None,
        )
        if not ch:
            logger.warning(
                "enqueue: channel not found: channel_id=%s",
                channel_id,
            )
            return

        # Extract query text for priority classification
        query = ch._extract_query_from_payload(payload)

        # Get priority level
        priority_level = self._command_registry.get_priority_level(query)

        # Extract normalized session_id
        session_id = self._extract_session_id(ch, payload)

        # Route to unified queue manager with task tracking
        task = asyncio.create_task(
            self._enqueue_with_timeout(
                channel_id,
                session_id,
                priority_level,
                payload,
                query,
            ),
        )
        self._enqueue_tasks.add(task)
        task.add_done_callback(self._enqueue_tasks.discard)

    async def _enqueue_with_timeout(
        self,
        channel_id: str,
        session_id: str,
        priority_level: int,
        payload: Any,
        query: str,
    ) -> None:
        """Enqueue with timeout protection to prevent unbounded blocking.

        Args:
            channel_id: Channel identifier
            session_id: Normalized session ID
            priority_level: Priority level
            payload: Message payload
            query: Extracted query text for logging
        """
        try:
            await asyncio.wait_for(
                self._queue_manager.enqueue(
                    channel_id,
                    session_id,
                    priority_level,
                    payload,
                ),
                timeout=30.0,
            )
            logger.debug(
                f"Enqueued: channel={channel_id} "
                f"session={session_id[:30]} "
                f"priority={priority_level} "
                f"query={query[:40] if query else '(empty)'}",
            )
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            logger.debug(
                f"Enqueue cancelled: channel={channel_id} "
                f"session={session_id[:30]}",
            )
            raise
        except Exception as e:
            logger.exception(
                f"Enqueue failed: channel={channel_id} "
                f"session={session_id[:30]} error={e}",
            )

    def enqueue(self, channel_id: str, payload: Any) -> None:
        """Enqueue a payload for the channel. Thread-safe (e.g. from sync
        WebSocket or polling thread). Call after start_all().
        """
        if self._loop is None:
            logger.warning("enqueue: loop not set for channel=%s", channel_id)
            return
        self._loop.call_soon_threadsafe(
            self._enqueue_one,
            channel_id,
            payload,
        )

    async def _consume_queue(
        self,
        queue: asyncio.Queue,
        channel_id: str,
        session_id: str,
        priority_level: int,
    ) -> None:
        """Consumer function for UnifiedQueueManager.

        This implements the per-queue consumer loop with batch merging.

        Args:
            queue: The queue to consume from
            channel_id: Channel identifier
            session_id: Normalized session ID
            priority_level: Priority level

        Note:
            Preserves original batch merging logic (drain + merge)
        """
        logger.info(
            f"Consumer started: channel={channel_id} "
            f"session={session_id[:30]} "
            f"priority={priority_level}",
        )

        while True:
            batch = []
            try:
                # Get first payload
                payload = await queue.get()
                batch.append(payload)

                # Re-fetch channel each iteration so replace_channel()
                # swaps are picked up automatically.
                ch = (
                    payload.channel
                    if isinstance(payload, OwnedQueuePayload)
                    else await self.get_channel(channel_id)
                )
                if not ch:
                    # Channel may be temporarily absent during a
                    # replace_channel() swap.  Retry a few times before
                    # giving up so we don't silently drop the payload.
                    for _retry in range(3):
                        await asyncio.sleep(0.5)
                        ch = await self.get_channel(channel_id)
                        if ch:
                            break
                    if not ch:
                        logger.error(
                            "Consumer: channel not found after"
                            " retries: channel_id=%s",
                            channel_id,
                        )
                        return

                # Drain queue for same-key payloads (batch merge logic)
                # Note: In new architecture, same-key means same QueueKey,
                # so all payloads in this queue already have same
                # (channel_id, session_id, priority_level).
                # We still drain to merge rapid-fire messages (e.g. images)
                while True:
                    try:
                        next_payload = queue.get_nowait()
                        batch.append(next_payload)
                    except asyncio.QueueEmpty:
                        break

                # Process batch (with merge logic). A shared-session
                # group chat can put several senders in one queue key, so
                # never merge across ACL identities.
                if not await _complete_queue_batch(ch, batch):
                    logger.debug(
                        "Cancelled queue batch: channel=%s session=%s",
                        channel_id,
                        session_id[:30],
                    )
                    continue

                # Update processed count
                if self._queue_manager is not None:
                    await self._queue_manager.increment_processed(
                        channel_id,
                        session_id,
                        priority_level,
                        count=len(batch),
                    )

                logger.debug(
                    f"Processed batch: channel={channel_id} "
                    f"session={session_id[:30]} "
                    f"priority={priority_level} "
                    f"batch_size={len(batch)}",
                )

            except asyncio.CancelledError:
                logger.debug(
                    f"Consumer cancelled: channel={channel_id} "
                    f"session={session_id[:30]} "
                    f"priority={priority_level}",
                )
                raise
            except Exception:
                logger.exception(
                    f"Consumer failed: channel={channel_id} "
                    f"session={session_id[:30]} "
                    f"priority={priority_level}",
                )
            finally:
                # Start custody at the first get, including channel lookup
                # and retries before batch execution can begin.
                for _ in batch:
                    queue.task_done()

    async def start_all(self) -> None:
        """Prepare queues, then connect owned channels in background."""
        self._loop = asyncio.get_running_loop()
        if self._queue_manager is None:
            self._queue_manager = UnifiedQueueManager(
                consumer_fn=self._consume_queue,
                queue_maxsize=_CHANNEL_QUEUE_MAXSIZE,
            )
            self._queue_manager.start_cleanup_loop()
        self._stopping = False
        if self._defer_channel_start:
            return
        for channel in list(self.channels):
            if id(
                channel,
            ) in self._started_channels or self._pending_channel_starts(
                channel,
            ):
                continue
            task = asyncio.create_task(self._start_existing(channel))
            self._start_tasks.add(task)
            self._start_task_channels[task] = channel
            task.add_done_callback(self._forget_start_task)

    async def _reserve_channel_auth(self, channel):
        """Acquire claims before publishing or starting an isolated proxy."""
        if not isinstance(channel, IsolatedChannelProxy):
            return
        context = self._start_contexts.get(channel)
        if context is None:
            raise RuntimeError("CHANNEL_PREPARATION_STALE")
        context.bind(self)
        context.validate(self, channel)
        if context.row.plugin_id != "wechat" or context.key != "wechat":
            return
        from ...utils.io_utils import run_sync_io
        from .wechat_auth_custody import reserve_wechat_auth_async

        registry = channel._owner_registry
        owner = context.owner
        configured_id = context.configured_id
        state_root = context.state_root
        workspace_dir = context.workspace_dir
        runtime_config = context.execution.config

        def authorize():
            context.validate(self, channel)

        authorize()
        if channel._wechat_auth_claims:
            if any(
                claim not in registry.runtime_owners.leases()
                or getattr(
                    registry.runtime_owners.resource(claim),
                    "owner",
                    None,
                )
                != owner
                for claim in channel._wechat_auth_claims
            ):
                raise RuntimeError("CHANNEL_PREPARATION_STALE")
            return

        def resolve_workspace_id():
            if configured_id:
                return configured_id
            from ...config.utils import load_config

            profiles = load_config().agents.profiles
            directory = Path(workspace_dir).expanduser().resolve()
            matches = [
                key
                for key, profile in profiles.items()
                if Path(profile.workspace_dir).expanduser().resolve()
                == directory
            ]
            return matches[0] if len(matches) == 1 else str(directory)

        workspace_id = await run_sync_io(resolve_workspace_id)
        authorize()
        channel._wechat_auth_claims = await reserve_wechat_auth_async(
            registry,
            owner=owner,
            workspace_id=workspace_id,
            workspace_dir=workspace_dir,
            config=runtime_config,
            working_dir=state_root,
            authorize=authorize,
        )

    async def _start_existing(self, channel):
        lock = self._channel_lifecycle_locks.setdefault(
            channel.channel,
            asyncio.Lock(),
        )
        async with lock:
            if (
                self._stopping
                or channel.channel in self._failed_channels
                or channel.channel in self._prepared_stop_channels
                or self._find_channel(channel.channel) is not channel
                or id(channel) in self._started_channels
            ):
                return
            try:
                self._bind_enqueue(channel)
                await self._reserve_channel_auth(channel)
                await channel.start()
                self._started_channels.add(id(channel))
                self._start_contexts.pop(channel, None)
            except BaseException as exc:
                from ...utils.io_utils import run_async_to_completion

                self._forget_start_task(asyncio.current_task())
                await run_async_to_completion(
                    self._stop_one_unlocked(channel.channel),
                )
                if not isinstance(exc, asyncio.CancelledError):
                    logger.exception(
                        "Failed to start channel '%s'",
                        channel.channel,
                    )

    async def _start_owned(self, channel):
        await self._reserve_channel_auth(channel)
        task = asyncio.create_task(channel.start())
        self._start_tasks.add(task)
        self._start_task_channels[task] = channel
        task.add_done_callback(self._forget_start_task)
        await task
        self._started_channels.add(id(channel))
        self._start_contexts.pop(channel, None)

    def _forget_start_task(self, task: asyncio.Task) -> None:
        self._start_tasks.discard(task)
        self._start_task_channels.pop(task, None)

    def _pending_channel_starts(
        self,
        channel: BaseChannel,
    ) -> set[asyncio.Task]:
        return {
            task
            for task, owner in self._start_task_channels.items()
            if owner is channel and not task.done()
        }

    async def _drain_channel(self, key, timeout):
        deadline = asyncio.get_running_loop().time() + timeout
        if self._enqueue_tasks:
            _, pending = await asyncio.wait(
                list(self._enqueue_tasks),
                timeout=timeout,
            )
            if pending:
                return False
        if (
            self._queue_manager is not None
            and not await self._queue_manager.drain(
                key,
                timeout=max(0, deadline - asyncio.get_running_loop().time()),
            )
        ):
            return False
        tracker = getattr(self._workspace, "task_tracker", None)
        if tracker is not None:
            tasks = await tracker.snapshot_active_tasks(
                owner=self._workspace,
                channel_id=key,
            )
            return await tracker.wait_tasks_done(
                list(tasks.values()),
                timeout=max(0, deadline - asyncio.get_running_loop().time()),
            )
        return True

    def resume_ingress(self):
        """Resume retained owners after a rejected drain."""
        self._stopping = False
        for channel in self.channels:
            if channel.channel not in self._failed_channels:
                self._bind_enqueue(channel)

    async def _prepare_channel_stop(self, channel):
        """Retain owners whose preparation failed or cannot be resumed."""
        key = channel.channel
        if self._find_channel(key) is not channel:
            return None
        try:
            # Legacy duck-typed channels may not implement the optional hook.
            prepare = getattr(channel, "prepare_stop", None)
            if (
                prepare is not None
                and await prepare()
                and self._find_channel(key) is channel
            ):
                self._prepared_stop_channels.add(key)
        except asyncio.CancelledError:
            if self._find_channel(key) is channel:
                self._failed_channels.add(key)
            raise
        except Exception as exc:  # noqa: BLE001
            if self._find_channel(key) is not channel:
                return None
            logger.exception("Failed to prepare channel '%s'", key)
            self._failed_channels.add(key)
            return self._stop_receipt(channel, False, str(exc))
        return None

    async def quiesce(self, *, timeout=None, for_stop=False) -> bool:
        """Close admission, drain, and optionally prepare owners to stop."""
        deadline = asyncio.get_running_loop().time() + (
            _CHANNEL_DRAIN_TIMEOUT if timeout is None else timeout
        )
        for channel in self.channels:
            self._close_ingress(channel)
        try:
            if for_stop:
                from ...plugins.lifecycle import QuiescenceError

                self._stopping = True
                for channel in list(self.channels):
                    receipt = await self._prepare_channel_stop(channel)
                    if receipt is not None:
                        raise QuiescenceError(receipt.detail, receipt=receipt)
            if self._enqueue_tasks:
                _, pending = await asyncio.wait(
                    list(self._enqueue_tasks),
                    timeout=max(
                        0,
                        deadline - asyncio.get_running_loop().time(),
                    ),
                )
                if pending:
                    self.resume_ingress()
                    return False
            for channel in list(self.channels):
                if not await self._drain_channel(
                    channel.channel,
                    max(0, deadline - asyncio.get_running_loop().time()),
                ):
                    self.resume_ingress()
                    return False
        except BaseException:
            self.resume_ingress()
            raise
        return True

    async def stop_all(self) -> None:
        """Stop consumers only after all admitted work and owners quiesce."""
        from ...plugins.lifecycle import QuiescenceError

        self._stopping = True
        unowned: set[asyncio.Task] = (
            self._start_tasks - self._start_task_channels.keys()
        )
        for task in unowned:
            task.cancel()
        pending: set[asyncio.Task] = set()
        done: set[asyncio.Task]
        if unowned:
            done, pending = await asyncio.wait(
                unowned,
                timeout=_CHANNEL_START_STOP_TIMEOUT,
            )
            self._start_tasks.difference_update(done)
        if not await self.quiesce(for_stop=True):
            raise QuiescenceError("CHANNEL_DRAIN_TIMEOUT")
        receipts = await asyncio.gather(
            *(self.stop_one(ch.channel) for ch in list(self.channels)),
            return_exceptions=True,
        )
        for result in receipts:
            if isinstance(result, BaseException):
                raise result
        failures = [
            r
            for r in receipts
            if isinstance(r, StopReceipt)
            and not r.stopped
            and r.detail != "not running"
        ]
        if failures:
            raise QuiescenceError(
                "Channel cleanup incomplete",
                receipt=failures[0],
            )
        if pending:
            raise QuiescenceError("Channel startup tasks are still pending")
        if self._queue_manager is not None:
            await self._queue_manager.stop_all()
            self._queue_manager = None
        self._stopping = True

    def _find_channel(self, key: str) -> BaseChannel | None:
        return next((c for c in self.channels if c.channel == key), None)

    async def start_one(
        self,
        key: str,
        workspace_config: Any,
        *,
        expected_registration=None,
    ) -> ChannelHandle:
        """Start one channel on this manager. Idempotent if already running.

        The returned handle is not guaranteed to be a local
        ``BaseChannel`` — callers must treat it as opaque.
        """
        existing = self._find_channel(key)
        if (
            existing is not None
            and not isinstance(existing, IsolatedChannelProxy)
            and self._pending_channel_starts(existing)
            and not self._stopping
            and key not in self._failed_channels
            and key not in self._prepared_stop_channels
        ):
            # Boot already owns this instance. Publish its token so unload can
            # cancel its tracked startup instead of waiting for SDK readiness.
            from ...plugins.registry import PluginRegistry

            if expected_registration is not None and (
                PluginRegistry().get_channel_registration(key)
                is not expected_registration
            ):
                raise RuntimeError("stale channel registration")
            return self._channel_handle(existing)
        lock = self._channel_lifecycle_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if self._stopping or self._defer_channel_start:
                raise RuntimeError("CHANNEL_STOPPING")
            if expected_registration is not None:
                from ...plugins.registry import PluginRegistry

                if (
                    PluginRegistry().get_channel_registration(key)
                    is not expected_registration
                ):
                    raise RuntimeError("stale channel registration")
            return await self._start_one_unlocked(key, workspace_config)

    async def _start_one_unlocked(
        self,
        key: str,
        workspace_config: Any,
        *,
        replace_from=None,
    ) -> ChannelHandle:
        from ...plugins.registry import PluginRegistry

        registry = PluginRegistry()
        row = registry.get_channel_registration(key)
        if not registry.projector.start_allowed(
            "channel",
            key,
            row.plugin_id if row is not None else key,
            self._workspace,
        ):
            raise RuntimeError("CHANNEL_STOPPING")
        existing = self._find_channel(key)
        from .registry import selected_process_channels

        if existing is not None:
            if key in selected_process_channels() and getattr(
                existing,
                "_registration",
                None,
            ) is not PluginRegistry().get_channel_registration(key):
                raise RuntimeError("CHANNEL_ALREADY_OWNED")
            if (
                key in self._failed_channels
                or key in self._prepared_stop_channels
            ):
                exc = RuntimeError(f"Channel '{key}' has not stopped")
                exc.binding = self._channel_handle(existing)
                raise exc
            return self._channel_handle(existing)

        process = self._process
        if process is None and self._workspace is not None:
            process = getattr(self._workspace, "stream_query", None)
        if process is None:
            raise RuntimeError(
                f"Cannot start channel '{key}': no process handler",
            )
        workspace_dir = self._workspace_dir
        if workspace_dir is None and self._workspace is not None:
            workspace_dir = getattr(self._workspace, "workspace_dir", None)
        effective_config = workspace_config or self._workspace_config
        context = None
        if key in selected_process_channels():
            from ...utils.io_utils import run_sync_io

            context = _ChannelStartContext.capture(self, key, effective_config)
            context.bind(self)
            context.prepared = await run_sync_io(context.prepare)
            context.validate(self)
        channel = instantiate_channel(
            key,
            effective_config,
            process=process,
            on_last_dispatch=self._on_last_dispatch,
            workspace_dir=workspace_dir,
            context=context,
            manager=self,
        )
        registered = False
        try:
            await self._reserve_channel_auth(channel)
            self._attach_runtime(channel)
            if self._workspace is not None:
                channel.set_workspace(self._workspace, self._command_registry)
            self._bind_enqueue(channel)
            # Bind before starting; cancellation while waiting for the lock
            # must also release the unstarted process reservation.
            async with self._lock:
                if context is not None:
                    context.validate(self, channel)
                self.channels.append(channel)
                registered = True
                self._replace_binding(
                    key,
                    replace_from,
                    self._channel_handle(channel),
                )
            self._failed_channels.add(key)
            await self._start_owned(channel)
        except BaseException as exc:
            if not registered:
                self._release_unstarted(channel)
                raise
            from ...utils.io_utils import run_async_to_completion

            try:
                receipt = await run_async_to_completion(
                    self._stop_one_unlocked(key),
                )
            except BaseException as cleanup_exc:
                exc.binding = self._channel_handle(channel)
                raise exc from cleanup_exc
            if not receipt.stopped:
                exc.binding = self._channel_handle(channel)
            raise
        self._failed_channels.discard(key)
        return self._channel_handle(channel)

    async def stop_one(
        self,
        key: str,
        *,
        expected: ChannelHandle | None = None,
    ) -> StopReceipt:
        """Stop one channel, retaining its handle until stop succeeds."""
        channel = self._find_channel(key)
        if channel is not None and (
            expected is None or expected.channel is channel
        ):
            self._close_ingress(channel)
            for task in self._pending_channel_starts(channel):
                if task is not asyncio.current_task():
                    task.cancel()
            tasks = self._pending_channel_starts(channel)
            if tasks:
                _, pending = await asyncio.wait(
                    tasks,
                    timeout=_CHANNEL_START_STOP_TIMEOUT,
                )
                if pending:
                    return self._stop_receipt(
                        channel,
                        False,
                        "channel startup is still pending",
                    )
            if self._find_channel(key) is None:
                return self._stop_receipt(channel, True)
        lock = self._channel_lifecycle_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if channel is not None and self._find_channel(key) is None:
                return self._stop_receipt(channel, True)
            if expected is not None and (
                expected.key != key
                or expected.channel is not self._find_channel(key)
            ):
                return StopReceipt(
                    key=key,
                    stopped=True,
                    detail="stale binding",
                )
            from ...utils.io_utils import run_async_to_completion

            return await run_async_to_completion(self._stop_one_unlocked(key))

    async def _stop_one_unlocked(self, key: str) -> StopReceipt:
        async with self._lock:
            channel = self._find_channel(key)
        if channel is None:
            return StopReceipt(key=key, stopped=False, detail="not running")
        tasks = self._pending_channel_starts(channel) - {
            asyncio.current_task(),
        }
        if tasks:
            self._failed_channels.add(key)
            for task in tasks:
                task.cancel()
            _, pending = await asyncio.wait(
                tasks,
                timeout=_CHANNEL_START_STOP_TIMEOUT,
            )
            if pending:
                return StopReceipt(
                    key=key,
                    stopped=False,
                    detail="channel startup is still pending",
                )
        self._close_ingress(channel)
        receipt = await self._prepare_channel_stop(channel)
        if receipt is not None:
            return receipt
        if not await self._drain_channel(key, _CHANNEL_DRAIN_TIMEOUT):
            if not self._stopping:
                self._bind_enqueue(channel)
            return self._stop_receipt(channel, False, "CHANNEL_DRAIN_TIMEOUT")
        if isinstance(channel, IsolatedChannelProxy):
            channel.last_stop_result = None
        try:
            await channel.stop()
        except asyncio.CancelledError:
            self._failed_channels.add(key)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to stop channel '%s'", key)
            self._failed_channels.add(key)
            return self._stop_receipt(
                channel,
                False,
                str(exc),
            )
        receipt = self._stop_receipt(channel, True)
        evidence = runtime_stop_receipt(receipt, self._channel_handle(channel))
        if not evidence.stopped:
            self._failed_channels.add(key)
            receipt.stopped = False
            receipt.detail = receipt.detail or "CHANNEL_STOP_INCOMPLETE"
            return receipt
        async with self._lock:
            self.channels = [
                item for item in self.channels if item is not channel
            ]
        self._failed_channels.discard(key)
        self._prepared_stop_channels.discard(key)
        self._started_channels.discard(id(channel))
        if (
            isinstance(channel, IsolatedChannelProxy)
            and getattr(channel, "_runtime_lease", None) is not None
        ):
            from .wechat_auth_custody import release_wechat_auth

            release_wechat_auth(
                channel._owner_registry,
                getattr(channel, "_wechat_auth_claims", ()),
                evidence,
            )
            channel._wechat_auth_claims = ()
            channel._owner_registry.runtime_owners.release(
                channel._runtime_lease,
                evidence,
            )
        self._start_contexts.pop(channel, None)
        return receipt

    @staticmethod
    def _stop_receipt(channel, stopped, detail=""):
        spec = (
            channel._launch_spec
            if isinstance(channel, IsolatedChannelProxy)
            else None
        )
        result = channel.last_stop_result if spec is not None else None
        return StopReceipt(
            key=channel.channel,
            stopped=stopped,
            detail=detail,
            instance_id=spec.instance_id if spec else None,
            generation=channel._identity().generation if spec else None,
            **(
                {
                    name: getattr(result, name)
                    for name in (
                        "exited",
                        "returncode",
                        "forced",
                        "residual",
                    )
                }
                if result is not None
                else {}
            ),
        )

    async def get_channel(self, channel: str) -> Optional[BaseChannel]:
        async with self._lock:
            for ch in self.channels:
                if ch.channel == channel:
                    return ch
            return None

    async def get_channel_health(
        self,
        channel_name: str,
    ) -> Dict[str, Any]:
        """Get health status for a specific channel.

        Args:
            channel_name: Channel identifier (e.g. "dingtalk", "telegram")

        Returns:
            Health status dict from the channel's health_check() method.

        Raises:
            KeyError: If channel is not found in this manager.
        """
        channel_instance = await self.get_channel(channel_name)
        if channel_instance is None:
            raise KeyError(f"Channel not found: {channel_name}")
        try:
            return await channel_instance.health_check()
        except Exception as exc:
            logger.exception(
                "health_check failed for channel=%s",
                channel_name,
            )
            return {
                "channel": channel_name,
                "status": "unhealthy",
                "detail": str(exc),
            }

    async def restart_channel(self, channel_name: str) -> Dict[str, Any]:
        """Replace the current generation through the workspace factory."""
        if self._find_channel(channel_name) is None:
            raise KeyError(f"Channel not found: {channel_name}")
        from ...config.config import load_agent_config

        config = self._workspace_config
        if self._workspace is None and config is None:
            raise RuntimeError("Cannot restart channel: workspace not set")
        if self._workspace is not None:
            config = load_agent_config(self._workspace.agent_id)
        await self.replace_channel(channel_name, config)
        return {
            "channel": channel_name,
            "status": "restarted",
            "detail": "Channel restarted",
        }

    def set_workspace(self, workspace) -> None:
        """Set workspace and inject to all channels.

        Args:
            workspace: Workspace instance with task_tracker and chat_manager
        """
        self._workspace = workspace
        for ch in self.channels:
            ch.set_workspace(workspace, self._command_registry)
        logger.info(
            f"Injected workspace into {len(self.channels)} channels",
        )

    async def clear_queue(
        self,
        channel_id: str,
        session_id: str,
        priority_level: int,
    ) -> int:
        """Clear a specific queue.

        Args:
            channel_id: Channel identifier
            session_id: Session identifier
            priority_level: Priority level

        Returns:
            Number of messages cleared
        """
        if self._queue_manager is None:
            return 0
        return await self._queue_manager.clear_queue(
            channel_id,
            session_id,
            priority_level,
        )

    async def replace_channel(
        self,
        new_channel: BaseChannel | str,
        workspace_config=None,
    ) -> None:
        """Drain and stop the old owner before constructing its successor."""
        from ...plugins.lifecycle import QuiescenceError
        from ...utils.io_utils import run_async_to_completion

        key = (
            new_channel
            if isinstance(new_channel, str)
            else new_channel.channel
        )
        if isinstance(new_channel, IsolatedChannelProxy):
            if self._find_channel(key) is new_channel:
                raise RuntimeError("CHANNEL_ALREADY_OWNED")
            context = self._start_contexts.get(new_channel)
            if context is None:
                raise RuntimeError("CHANNEL_PREPARATION_STALE")
            context.bind(self)
            context.validate(self, new_channel)
        # Reject pending boot starts before waiting on their lifecycle lock.
        old = self._find_channel(key)
        if old is not None and self._pending_channel_starts(old):
            raise RuntimeError(f"Channel '{key}' is still starting")
        lock = self._channel_lifecycle_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if self._stopping:
                raise RuntimeError("CHANNEL_STOPPING")
            old = self._find_channel(key)
            if old is not None and self._pending_channel_starts(old):
                raise RuntimeError(f"Channel '{key}' is still starting")
            if old is not None:
                receipt = await run_async_to_completion(
                    self._stop_one_unlocked(key),
                )
                if not receipt.stopped:
                    raise QuiescenceError(receipt.detail, receipt=receipt)
            config = workspace_config or self._workspace_config
            if isinstance(new_channel, str):
                cfg = channel_cfg_for_key(config, key)
                if cfg is None or not channel_enabled(cfg):
                    return
                handle = await self._start_one_unlocked(
                    key,
                    config,
                    replace_from=old,
                )
            else:
                # Legacy object callers still use the identical owner lock.
                self.channels.append(new_channel)
                self._attach_runtime(new_channel)
                if self._workspace is not None:
                    new_channel.set_workspace(
                        self._workspace,
                        self._command_registry,
                    )
                self._bind_enqueue(new_channel)
                try:
                    self._replace_binding(
                        key,
                        old,
                        self._channel_handle(new_channel),
                    )
                    await self._start_owned(new_channel)
                except BaseException:
                    await run_async_to_completion(self._stop_one_unlocked(key))
                    raise
                handle = self._channel_handle(new_channel)
            self._replace_binding(key, old, handle)

    async def send_event(
        self,
        *,
        channel: str,
        user_id: str,
        session_id: str,
        event: Any,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        ch = await self.get_channel(channel)
        if not ch:
            raise KeyError(f"channel not found: {channel}")
        merged_meta = dict(meta or {})
        merged_meta["session_id"] = session_id
        merged_meta["user_id"] = user_id
        bot_prefix = getattr(ch, "bot_prefix", None) or getattr(
            ch,
            "_bot_prefix",
            None,
        )
        if bot_prefix and "bot_prefix" not in merged_meta:
            merged_meta["bot_prefix"] = bot_prefix
        await ch.send_event(
            user_id=user_id,
            session_id=session_id,
            event=event,
            meta=merged_meta,
        )

    async def send_text(
        self,
        *,
        channel: str,
        user_id: str,
        session_id: str,
        text: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send plain text to a specific channel
        (used for scheduled jobs like task_type='text').
        """
        ch = await self.get_channel(channel.lower())
        if not ch:
            raise KeyError(f"channel not found: {channel}")

        # Convert (user_id, session_id) into the channel-specific target handle
        to_handle = ch.to_handle_from_target(
            user_id=user_id,
            session_id=session_id,
        )
        ch_name = getattr(ch, "channel", channel)
        logger.info(
            "channel send_text: channel=%s user_id=%s session_id=%s "
            "to_handle=%s",
            ch_name,
            (user_id or "")[:40],
            (session_id or "")[:40],
            (to_handle or "")[:60],
        )

        # Keep the same behavior as the agent pipeline:
        # if the channel has a fixed bot prefix, merge it into meta so
        # send_content_parts can use it.
        merged_meta = dict(meta or {})
        bot_prefix = getattr(ch, "bot_prefix", None) or getattr(
            ch,
            "_bot_prefix",
            None,
        )
        if bot_prefix and "bot_prefix" not in merged_meta:
            merged_meta["bot_prefix"] = bot_prefix
        merged_meta["session_id"] = session_id
        merged_meta["user_id"] = user_id

        # Send as content parts (single text part; use TextContent so channel
        # getattr(p, "type") / getattr(p, "text") work)
        await ch.send_content_parts(
            to_handle,
            [TextContent(type=ContentType.TEXT, text=text)],
            merged_meta,
        )
