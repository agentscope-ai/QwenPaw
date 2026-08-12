# -*- coding: utf-8 -*-
"""Driver manager and lifecycle owner."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from pathlib import Path

from .approval import ApprovalGate
from .capabilities import (
    DriverCapability,
    DriverInvocation,
    DriverInvocationResult,
    DriverRuntimeInfo,
    parse_capability_id,
)
from .constants import (
    CREDENTIAL_ALIAS_DEFAULT,
    CREDENTIAL_KIND_NONE,
    DRIVER_SCOPE_CONTEXT_KEY,
)
from .credentials.providers import build_provider
from .credentials.store import AsyncCredentialStore
from .credentials.types import CredentialRecord
from .errors import (
    DriverNotFoundError,
    UnsupportedProtocolError,
)
from .handler import DriverHandler
from .contracts import (
    CredentialRef,
    DriverCard,
    coerce_card,
    iter_credential_refs,
    validate_card,
)
from .storage import (
    AsyncDriverCardStore,
)

logger = logging.getLogger(__name__)
_SHUTDOWN_TIMEOUT_SECONDS = 10.0
EndpointValidator = Callable[[DriverCard], None]


class DriverManager:
    """Own external capability storage, lifecycle, and dispatch.

    DriverManager is protocol-neutral at the lifecycle boundary.  The current
    implementation registers MCP as the concrete protocol and exposes MCP tools
    as Driver capabilities with shared policy, credential, and invocation
    handling.
    """

    def __init__(
        self,
        cards_dir: Path,
        credential_store: AsyncCredentialStore,
        approval_gate: ApprovalGate | None = None,
        card_store: AsyncDriverCardStore | None = None,
    ) -> None:
        self._cards_dir = cards_dir
        self._credential_store = credential_store
        self._card_store = card_store or AsyncDriverCardStore(cards_dir)
        self._approval_gate = approval_gate
        self._handler_types: dict[str, type[DriverHandler]] = {}
        self._endpoint_validators: dict[str, EndpointValidator] = {}
        self._handlers: dict[str, DriverHandler] = {}
        self._handler_scopes: dict[str, str] = {}
        self._scope_handlers: dict[str, set[str]] = {}
        self._cleanup_tasks: set[asyncio.Task[None]] = set()
        self._cleanup_handler_ids: set[int] = set()
        self._lock = asyncio.Lock()

    def register_handler_type(
        self,
        protocol: str,
        cls: type[DriverHandler],
        endpoint_validator: EndpointValidator | None = None,
    ) -> None:
        """Register the handler for an exact Driver protocol."""
        if not protocol:
            raise UnsupportedProtocolError(protocol)
        self._handler_types[protocol] = cls
        if endpoint_validator is not None:
            self._endpoint_validators[protocol] = endpoint_validator

    async def start(self) -> None:
        """Build enabled drivers from persisted DriverCards."""
        await self.build_drivers()

    async def build_drivers(self) -> None:
        """Scan cards_dir and build enabled handlers."""
        built: dict[str, DriverHandler] = {}
        for path in await self._card_store.list_paths():
            try:
                card = await self._card_store.load_path(path)
            except Exception as exc:
                logger.warning(
                    "Failed to build Driver from %s: %s",
                    path,
                    exc,
                    exc_info=True,
                )
                continue
            try:
                if not card.enabled:
                    logger.debug(
                        "Driver '%s' is disabled; skipping",
                        card.name,
                    )
                    continue
                handler = await self._build_and_init_handler(card)
                built[card.name] = handler
            except Exception as exc:
                logger.warning(
                    "Failed to build Driver '%s': %s",
                    card.name,
                    exc,
                    exc_info=True,
                )

        collisions: set[str] = set()
        old_handlers: list[DriverHandler] = []
        async with self._lock:
            transient = {
                name: handler
                for name, handler in self._handlers.items()
                if name in self._handler_scopes
            }
            collisions = set(built) & set(transient)
            if not collisions:
                old_handlers = [
                    handler
                    for name, handler in self._handlers.items()
                    if name not in self._handler_scopes
                ]
                self._handlers = {**built, **transient}

        if collisions:
            await self._shutdown_handlers(built.values())
            names = ", ".join(sorted(collisions))
            raise ValueError(
                f"Persistent Drivers collide with transient Drivers: "
                f"{names}",
            )

        await self._shutdown_handlers(old_handlers)

    async def upsert_driver(
        self,
        card: DriverCard,
        credential: CredentialRecord | None = None,
    ) -> DriverRuntimeInfo:
        """Persist Driver data, build handler, then publish after init."""
        if credential is not None:
            await self._credential_store.put(credential)
        await self.register_driver(card)
        return self._runtime_info_from_card(card)

    async def register_driver(self, card: DriverCard) -> None:
        """Persist card, build handler, then publish after init success."""
        card = self._validate_card_for_registered_protocol(card)
        async with self._lock:
            if card.name in self._handler_scopes:
                raise ValueError(
                    f"Persistent Driver '{card.name}' collides with "
                    f"a transient Driver",
                )
            await self._card_store.save(card)

        handler = None
        if card.enabled:
            handler = await self._build_and_init_handler(card)

        old = None
        try:
            async with self._lock:
                if card.name in self._handler_scopes:
                    raise ValueError(
                        f"Persistent Driver '{card.name}' collides with "
                        f"a transient Driver",
                    )
                old = self._handlers.pop(card.name, None)
                if handler is not None:
                    self._handlers[card.name] = handler
        except BaseException:
            if handler is not None:
                await self._shutdown_handler(handler)
            raise

        if old is not None:
            await self._shutdown_handler(old)

    async def reload_driver(self, name: str) -> DriverRuntimeInfo | None:
        """Build-before-swap reload. Failure keeps old handler."""
        path = await self._card_store.stored_path(name)
        if path is None:
            raise DriverNotFoundError(name)
        card = await self._card_store.load_path(path)
        card = self._validate_card_for_registered_protocol(card)
        handler = None
        if card.enabled:
            handler = await self._build_and_init_handler(card)
        old = None
        try:
            async with self._lock:
                if name in self._handler_scopes:
                    raise ValueError(
                        f"Persistent Driver '{name}' collides with "
                        f"a transient Driver",
                    )
                await self._card_store.save(card)
                old = self._handlers.get(name)
                if handler is None:
                    old = self._handlers.pop(name, None)
                else:
                    self._handlers[name] = handler
        except BaseException:
            if handler is not None:
                await self._shutdown_handler(handler)
            raise

        if old is not None:
            await self._shutdown_handler(old)
        return self._runtime_info_from_card(card)

    async def refresh_driver(self, name: str) -> DriverRuntimeInfo | None:
        """Apply an on-disk card change with the lightest safe action."""
        path = await self._card_store.stored_path(name)
        if path is None:
            raise DriverNotFoundError(name)
        card = await self._card_store.load_path(path)
        card = self._validate_card_for_registered_protocol(card)

        async with self._lock:
            handler = self._handlers.get(name)
            if handler is not None and not self._requires_reconnect(
                handler.card,
                card,
            ):
                handler.sync_runtime_metadata(card)
                return self._runtime_info_from_card(card)

        return await self.reload_driver(name)

    async def sync_driver_policy(self, card: DriverCard) -> None:
        """Persist and apply a Driver policy without reconnecting.

        When the Driver is not active, only persistence is needed; the policy
        will be loaded the next time the Driver starts.
        """
        card = self._validate_card_for_registered_protocol(card)
        async with self._lock:
            if card.name in self._handler_scopes:
                raise ValueError(
                    f"Persistent Driver '{card.name}' collides with "
                    f"a transient Driver",
                )
            await self._card_store.save(card)
            handler = self._handlers.get(card.name)
            if handler is None or handler.card.protocol != card.protocol:
                return
            handler.set_policy(card.policy)

    @staticmethod
    def _requires_reconnect(old: DriverCard, new: DriverCard) -> bool:
        return (
            old.name != new.name
            or old.protocol != new.protocol
            or old.endpoint != new.endpoint
            or old.credentials != new.credentials
            or old.enabled != new.enabled
        )

    async def delete_driver(self, name: str) -> None:
        """Delete persisted card and shutdown a published handler."""
        async with self._lock:
            if name in self._handler_scopes:
                raise ValueError(
                    f"Transient Driver '{name}' must be removed by scope",
                )
            await self._card_store.delete(name)
            old = self._handlers.pop(name, None)
        if old is not None:
            await self._shutdown_handler(old)

    async def replace_transient_drivers(
        self,
        scope_id: str,
        cards: list[DriverCard],
    ) -> None:
        """Atomically replace all non-persistent Drivers for one scope.

        Every new handler is initialized before publication. Failure before
        publication leaves the previous scope untouched and shuts down any
        newly built handlers. After publication, retired handlers are cleaned
        up by managed tasks. Transient cards and credentials are never written
        to persistent stores.
        """
        if not scope_id.strip():
            raise ValueError("Transient Driver scope must be non-empty")

        names = [card.name for card in cards]
        if len(names) != len(set(names)):
            raise ValueError(
                f"Transient Driver names must be unique in scope "
                f"'{scope_id}'",
            )

        built: dict[str, DriverHandler] = {}
        try:
            for card in cards:
                built[card.name] = await self._build_and_init_handler(card)
        except BaseException:
            await self._shutdown_handlers(built.values())
            raise

        old_handlers: list[DriverHandler] = []
        try:
            async with self._lock:
                owned_names = self._scope_handlers.get(scope_id, set())
                persistent_names = {
                    name
                    for name in built
                    if await self._card_store.stored_path(name) is not None
                }
                unavailable = {
                    name
                    for name in built
                    if name in self._handlers and name not in owned_names
                } | persistent_names
                if unavailable:
                    joined = ", ".join(sorted(unavailable))
                    raise ValueError(
                        f"Transient Driver names already exist: {joined}",
                    )

                for name in owned_names:
                    old = self._handlers.pop(name, None)
                    if old is not None:
                        old_handlers.append(old)
                    self._handler_scopes.pop(name, None)

                for name, handler in built.items():
                    self._handlers[name] = handler
                    self._handler_scopes[name] = scope_id

                if built:
                    self._scope_handlers[scope_id] = set(built)
                else:
                    self._scope_handlers.pop(scope_id, None)
        except BaseException:
            await self._shutdown_handlers(built.values())
            raise

        self._schedule_handler_cleanup(old_handlers)

    async def remove_transient_drivers(self, scope_id: str) -> None:
        """Unpublish a scope and wait for its managed handler cleanup."""
        async with self._lock:
            names = self._scope_handlers.pop(scope_id, set())
            handlers = []
            for name in names:
                handler = self._handlers.pop(name, None)
                self._handler_scopes.pop(name, None)
                if handler is not None:
                    handlers.append(handler)
        cleanup_task = self._schedule_handler_cleanup(handlers)
        if cleanup_task is not None:
            await asyncio.shield(cleanup_task)

    async def shutdown_all(self) -> None:
        """Unpublish all handlers and wait for every managed cleanup."""
        async with self._lock:
            handlers = list(self._handlers.values())
            self._handlers.clear()
            self._handler_scopes.clear()
            self._scope_handlers.clear()
        self._schedule_handler_cleanup(handlers)
        await self._wait_for_handler_cleanups()

    async def list_drivers(
        self,
        protocol: str | None = None,
    ) -> list[DriverRuntimeInfo]:
        """Return configured Drivers with their current lifecycle status."""
        cards: dict[str, DriverRuntimeInfo] = {}
        for path in await self._card_store.list_paths():
            try:
                card = await self._card_store.load_path(path)
            except Exception as exc:
                cards[path.stem] = DriverRuntimeInfo(
                    name=path.stem,
                    protocol="",
                    enabled=False,
                    status="error",
                    error=str(exc),
                )
                continue
            if protocol is not None and card.protocol != protocol:
                continue
            cards[card.name] = self._runtime_info_from_card(card)
        return sorted(cards.values(), key=lambda item: item.name)

    async def list_capabilities(
        self,
        *,
        protocol: str | None = None,
        kind: str | None = None,
        request_context: dict[str, str] | None = None,
    ) -> list[DriverCapability]:
        """Return capabilities exposed by active handlers."""
        scope_id = str(
            (request_context or {}).get(DRIVER_SCOPE_CONTEXT_KEY) or "",
        )
        handlers = self._iter_handlers(protocol, scope_id=scope_id)
        capabilities: list[DriverCapability] = []
        for handler in handlers:
            try:
                handler_capabilities = await handler.list_capabilities(
                    request_context=request_context,
                )
            except Exception as exc:
                # Keep healthy Drivers available during partial failures.
                logger.warning(
                    "Failed to list capabilities for Driver '%s': %s",
                    handler.name,
                    exc,
                    exc_info=True,
                )
                continue
            for capability in handler_capabilities:
                if kind is None or capability.kind == kind:
                    capabilities.append(capability)
        return sorted(capabilities, key=lambda item: item.capability_id)

    async def list_driver_capabilities(
        self,
        name: str,
        *,
        kind: str | None = None,
        request_context: dict[str, str] | None = None,
    ) -> list[DriverCapability]:
        """Return capabilities from one active Driver only."""
        handler = self._get_handler(name)
        scope_id = self._handler_scopes.get(name)
        request_scope = str(
            (request_context or {}).get(DRIVER_SCOPE_CONTEXT_KEY) or "",
        )
        if scope_id is not None and request_scope != scope_id:
            raise DriverNotFoundError(name)
        capabilities = await handler.list_capabilities(
            request_context=request_context,
        )
        return sorted(
            [
                capability
                for capability in capabilities
                if kind is None or capability.kind == kind
            ],
            key=lambda item: item.capability_id,
        )

    async def invoke_capability(
        self,
        invocation: DriverInvocation,
    ) -> DriverInvocationResult:
        """Dispatch one capability invocation to its owning handler."""
        try:
            _, driver_name, _, _, _ = parse_capability_id(
                invocation.capability_id,
            )
        except ValueError as exc:
            return DriverInvocationResult(
                ok=False,
                error_type="invalid_capability_id",
                message=str(exc),
            )
        try:
            handler = self._get_handler(driver_name)
        except DriverNotFoundError as exc:
            return DriverInvocationResult(
                ok=False,
                error_type="driver_not_found",
                message=str(exc),
                metadata={"driver_name": exc.name},
            )
        scope_id = self._handler_scopes.get(driver_name)
        request_scope = str(
            invocation.request_context.get(DRIVER_SCOPE_CONTEXT_KEY) or "",
        )
        if scope_id is not None and request_scope != scope_id:
            return DriverInvocationResult(
                ok=False,
                error_type="driver_scope_mismatch",
                message=(
                    f"Driver '{driver_name}' is not available in the "
                    f"current request scope"
                ),
                metadata={"driver_name": driver_name},
            )
        return await handler.invoke_capability(invocation)

    def _get_handler(self, name: str) -> DriverHandler:
        handler = self._handlers.get(name)
        if handler is None:
            raise DriverNotFoundError(name)
        return handler

    def _iter_handlers(
        self,
        protocol: str | None = None,
        *,
        scope_id: str = "",
    ) -> list[DriverHandler]:
        handlers = [
            handler
            for name, handler in self._handlers.items()
            if name not in self._handler_scopes
            or self._handler_scopes[name] == scope_id
        ]
        if protocol is not None:
            handlers = [
                handler
                for handler in handlers
                if handler.card.protocol == protocol
            ]
        return sorted(handlers, key=lambda handler: handler.name)

    async def _build_and_init_handler(self, card: DriverCard) -> DriverHandler:
        handler = self._build_handler(card)
        try:
            await handler.init()
        except asyncio.CancelledError:
            # CancelledError is not caught by ``Exception`` on Python 3.11+.
            await self._shutdown_handler(handler)
            raise
        except Exception:
            await self._shutdown_handler(handler)
            raise
        return handler

    def _build_handler(self, card: DriverCard) -> DriverHandler:
        card = self._validate_card_for_registered_protocol(card)
        handler_type = self._resolve_handler_type(card.protocol)
        refs = iter_credential_refs(card)
        if refs:
            providers = {
                alias: build_provider(ref, self._credential_store)
                for alias, ref in refs.items()
            }
            primary = providers.get(CREDENTIAL_ALIAS_DEFAULT) or next(
                iter(providers.values()),
            )
        else:
            primary = build_provider(
                CredentialRef(kind=CREDENTIAL_KIND_NONE),
                self._credential_store,
            )
            providers = {CREDENTIAL_ALIAS_DEFAULT: primary}
        return handler_type(
            card,
            primary,
            providers,
            approval_gate=self._approval_gate,
        )

    def _resolve_handler_type(self, protocol: str) -> type[DriverHandler]:
        if protocol in self._handler_types:
            return self._handler_types[protocol]
        raise UnsupportedProtocolError(protocol)

    def _validate_card_for_registered_protocol(
        self,
        card: DriverCard,
    ) -> DriverCard:
        card = coerce_card(card)
        validate_card(card)
        self._resolve_handler_type(card.protocol)
        validator = self._endpoint_validators.get(card.protocol)
        if validator is not None:
            validator(card)
        return card

    def _runtime_info_from_card(self, card: DriverCard) -> DriverRuntimeInfo:
        active = card.name in self._handlers
        if active:
            status = "active"
        elif card.enabled:
            status = "inactive"
        else:
            status = "disabled"
        return DriverRuntimeInfo(
            name=card.name,
            protocol=card.protocol,
            enabled=card.enabled,
            status=status,
            display_name=str(card.config.get("display_name") or card.name),
            description=str(card.config.get("description") or ""),
        )

    @property
    def cards_dir(self) -> Path:
        return self._cards_dir

    @property
    def credential_store(self) -> AsyncCredentialStore:
        return self._credential_store

    @property
    def card_store(self) -> AsyncDriverCardStore:
        return self._card_store

    async def _shutdown_handlers(self, handlers) -> None:
        results = await asyncio.gather(
            *[
                self._shutdown_handler_with_timeout(handler)
                for handler in handlers
            ],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                logger.warning(
                    "Managed Driver handler cleanup returned an error: %s",
                    result,
                )

    def _schedule_handler_cleanup(
        self,
        handlers: Iterable[DriverHandler],
    ) -> asyncio.Task[None] | None:
        retired = [
            handler
            for handler in handlers
            if id(handler) not in self._cleanup_handler_ids
        ]
        if not retired:
            return None
        handler_ids = {id(handler) for handler in retired}
        self._cleanup_handler_ids.update(handler_ids)
        task = asyncio.create_task(
            self._shutdown_handlers(retired),
            name="driver-handler-cleanup",
        )
        self._cleanup_tasks.add(task)
        task.add_done_callback(
            lambda done: self._finish_handler_cleanup(done, handler_ids),
        )
        return task

    def _finish_handler_cleanup(
        self,
        task: asyncio.Task[None],
        handler_ids: set[int],
    ) -> None:
        self._cleanup_tasks.discard(task)
        self._cleanup_handler_ids.difference_update(handler_ids)
        if task.cancelled():
            logger.warning("Managed Driver handler cleanup was cancelled")
            return
        error = task.exception()
        if error is not None:
            logger.error("Managed Driver handler cleanup failed: %s", error)

    async def _wait_for_handler_cleanups(self) -> None:
        while self._cleanup_tasks:
            tasks = tuple(self._cleanup_tasks)
            await asyncio.shield(
                asyncio.gather(*tasks, return_exceptions=True),
            )

    @staticmethod
    async def _shutdown_handler(handler: DriverHandler) -> None:
        try:
            await handler.shutdown()
        except Exception as exc:
            logger.warning(
                "Error shutting down Driver '%s': %s",
                handler.name,
                exc,
                exc_info=True,
            )

    @classmethod
    async def _shutdown_handler_with_timeout(
        cls,
        handler: DriverHandler,
    ) -> None:
        task = asyncio.create_task(
            cls._shutdown_handler(handler),
            name=f"driver-shutdown:{handler.name}",
        )
        try:
            await asyncio.wait_for(task, timeout=_SHUTDOWN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning(
                "Timed out shutting down Driver '%s' after %.1fs; "
                "cancellation requested",
                handler.name,
                _SHUTDOWN_TIMEOUT_SECONDS,
            )
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug(
                    "Driver '%s' shutdown task cancelled after timeout",
                    handler.name,
                )
