# -*- coding: utf-8 -*-
"""Driver manager and lifecycle owner."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Iterable
from copy import deepcopy
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


class DriverManager:  # pylint: disable=too-many-public-methods
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
        self._revisions: dict[str, int] = {}
        self._active_revisions: dict[str, int] = {}
        self._preparing_revisions: set[tuple[str, int]] = set()
        self._accepted_sources: dict[str, DriverCard] = {}
        self._scope_revisions: dict[str, int] = {}
        self._owned: set[DriverHandler] = set()
        self._failed_cleanup: set[DriverHandler] = set()
        self._pending: dict[DriverHandler, asyncio.Task] = {}
        self._closing: dict[DriverHandler, asyncio.Task] = {}
        self._epoch = 0

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
        """Build concurrently while retaining every unpublished success."""
        epoch = self._epoch
        built = {}
        reservations = {}
        collisions = set()
        baseline = dict(self._revisions)
        tasks = []

        async def build(path):
            async with self._lock:
                card = await self._card_store.load_path(path)
                if epoch != self._epoch:
                    raise RuntimeError("Driver manager stopped while loading")
                if card.name in self._handler_scopes:
                    collisions.add(card.name)
                    return
                revision = self._reserve(card.name, card)
                reservations[card.name] = revision
            if not card.enabled:
                return
            handler = await self._build_and_init_handler(
                card,
                revision=revision,
            )
            built[card.name] = (handler, revision)

        try:
            paths = await self._card_store.list_paths()
            tasks = [asyncio.create_task(build(path)) for path in paths]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    logger.warning("Failed to build Driver: %s", result)
            if self._failed_cleanup:
                raise RuntimeError("Driver cleanup has not stopped")
            async with self._lock:
                if collisions:
                    raise ValueError(
                        "Persistent Drivers collide with transient Drivers",
                    )
                if epoch != self._epoch or self._revisions != {
                    **baseline,
                    **reservations,
                }:
                    raise RuntimeError("Driver source revision is stale")
                if set(built) & set(self._handler_scopes):
                    raise ValueError(
                        "Persistent Drivers collide with transient Drivers",
                    )
                for name, (handler, _) in built.items():
                    latest = await self._card_store.load(
                        name,
                        protocol=handler.card.protocol,
                    )
                    if latest != handler.card:
                        raise RuntimeError(
                            "Driver source changed while opening",
                        )
                retained = {
                    name: handler
                    for name, handler in self._handlers.items()
                    if name not in self._handler_scopes
                    and name in reservations
                    and name not in built
                    and self._accepted_sources[name].enabled
                }
                old = [
                    handler
                    for name, handler in self._handlers.items()
                    if name not in self._handler_scopes
                    and name not in retained
                ]
                self._handlers = {
                    **{
                        name: handler
                        for name, handler in self._handlers.items()
                        if name in self._handler_scopes
                    },
                    **retained,
                    **{name: handler for name, (handler, _) in built.items()},
                }
                self._active_revisions = {
                    name: revision
                    for name, revision in self._active_revisions.items()
                    if name in self._handlers
                }
                self._active_revisions.update(
                    {name: revision for name, (_, revision) in built.items()},
                )
                self._preparing_revisions.difference_update(
                    (name, revision) for name, (_, revision) in built.items()
                )
        except BaseException:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._shutdown_handlers(
                handler for handler, _ in built.values()
            )
            raise
        await self._shutdown_handlers(old)

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
        """Persist and publish only the latest reserved source revision."""
        card = self._validate_card_for_registered_protocol(card)
        async with self._lock:
            if card.name in self._handler_scopes:
                raise ValueError(
                    "Persistent Driver collides with a transient Driver",
                )
            revision = self._reserve(card.name, card)
            await self._card_store.save(card)
        await self._replace_persistent(card, revision)

    async def _replace_persistent(self, card, revision):
        handler = None
        if card.enabled:
            handler = await self._build_and_init_handler(
                card,
                revision=revision,
            )
        try:
            async with self._lock:
                if not self.candidate_is_current(card.name, revision):
                    raise RuntimeError("Driver source revision is stale")
                latest = await self._card_store.load(
                    card.name,
                    protocol=card.protocol,
                )
                if latest != card:
                    raise RuntimeError("Driver source changed while opening")
                old = self._handlers.pop(card.name, None)
                self._active_revisions.pop(card.name, None)
                if handler is not None:
                    self._handlers[card.name] = handler
                    self._active_revisions[card.name] = revision
                    self._preparing_revisions.discard((card.name, revision))
        except BaseException:
            if handler is not None:
                await self._shutdown_handler(handler)
            raise
        if old is not None:
            await self._shutdown_handler(old)

    async def reload_driver(self, name: str) -> DriverRuntimeInfo | None:
        """Build-before-swap without overwriting a newer persisted card."""
        async with self._lock:
            path = await self._card_store.stored_path(name)
            if path is None:
                raise DriverNotFoundError(name)
            card = await self._card_store.load_path(path)
            card = self._validate_card_for_registered_protocol(card)
            revision = self._reserve(name, card)
        await self._replace_persistent(card, revision)
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
                self._accepted_sources[name] = deepcopy(card)
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
            self._accepted_sources[card.name] = deepcopy(card)

    @staticmethod
    def _requires_reconnect(old: DriverCard, new: DriverCard) -> bool:
        return (
            old.name != new.name
            or old.protocol != new.protocol
            or old.endpoint != new.endpoint
            or old.credentials != new.credentials
            or old.enabled != new.enabled
            or {
                key: value
                for key, value in old.config.items()
                if key not in {"display_name", "description", "tools"}
            }
            != {
                key: value
                for key, value in new.config.items()
                if key not in {"display_name", "description", "tools"}
            }
        )

    async def delete_driver(self, name: str) -> None:
        """Delete persisted card and shutdown a published handler."""
        async with self._lock:
            if name in self._handler_scopes:
                raise ValueError(
                    f"Transient Driver '{name}' must be removed by scope",
                )
            self._invalidate(name)
            await self._card_store.delete(name)
            old = self._handlers.pop(name, None)
        if old is not None:
            await self._shutdown_handler(old)

    # Keep collision checks and scope publication in one transaction.
    # pylint: disable-next=too-many-branches
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

        async with self._lock:
            owned = self._scope_handlers.get(scope_id, set())
            for name in names:
                if (
                    name in self._handlers and name not in owned
                ) or await self._card_store.stored_path(name) is not None:
                    raise ValueError(
                        f"Transient Driver name already exists: {name}",
                    )
            revisions = {
                card.name: self._reserve(card.name, card) for card in cards
            }
            scope_revision = self._invalidate_scope(scope_id)
        epoch = self._epoch
        built: dict[str, DriverHandler] = {}
        try:
            for card in cards:
                built[card.name] = await self._build_and_init_handler(
                    card,
                    revision=revisions[card.name],
                    session_scope=scope_id,
                )
        except BaseException:
            await self._shutdown_handlers(built.values())
            raise

        old_handlers: list[DriverHandler] = []
        try:
            async with self._lock:
                if (
                    epoch != self._epoch
                    or self._scope_revisions.get(scope_id) != scope_revision
                    or any(
                        not self.candidate_is_current(name, revision)
                        for name, revision in revisions.items()
                    )
                ):
                    raise RuntimeError(
                        "Transient Driver source revision is stale",
                    )
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
                    self._active_revisions.pop(name, None)

                for name, handler in built.items():
                    self._handlers[name] = handler
                    self._active_revisions[name] = revisions[name]
                    self._preparing_revisions.discard((name, revisions[name]))
                    self._handler_scopes[name] = scope_id

                if built:
                    self._scope_handlers[scope_id] = set(built)
                else:
                    self._scope_handlers.pop(scope_id, None)
                # Superseded pending transactions also belong to this scope.
                # Their exact handlers are retired without touching other
                # scopes' same-name publications or reservations.
                old_handlers.extend(
                    handler
                    for handler in self._owned
                    if getattr(handler, "_session_scope", "") == scope_id
                    and handler not in built.values()
                    and handler not in old_handlers
                )
        except BaseException:
            await self._shutdown_handlers(built.values())
            raise

        self._schedule_handler_cleanup(old_handlers)

    async def remove_transient_drivers(self, scope_id: str) -> None:
        """Unpublish only this scope's exact owners and drain their cleanup."""
        async with self._lock:
            self._invalidate_scope(scope_id)
            handlers = [
                handler
                for handler in self._owned
                if getattr(handler, "_session_scope", "") == scope_id
            ]
            self._unpublish_owned_handlers(handlers)
            self._scope_handlers.pop(scope_id, None)
        await self._stop_pending(handlers)
        cleanup_task = self._schedule_handler_cleanup(handlers)
        if cleanup_task is not None:
            await asyncio.shield(cleanup_task)

    def _invalidate_scope(self, scope_id):
        revision = self._scope_revisions.get(scope_id, 0) + 1
        self._scope_revisions[scope_id] = revision
        return revision

    def _unpublish_owned_handlers(self, handlers):
        """Revoke exact owners under the lock; preserve successors."""
        for handler in handlers:
            name = handler.name
            if self._handlers.get(name) is handler:
                self._handlers.pop(name)
                scope_id = self._handler_scopes.pop(name, "")
                self._scope_handlers.get(scope_id, set()).discard(name)
            # Private lifecycle metadata is assigned by this manager.
            # pylint: disable-next=protected-access
            revision = handler._source_revision
            if self._active_revisions.get(name) == revision:
                self._active_revisions.pop(name, None)
            if self.candidate_is_current(name, revision):
                self._revisions[name] += 1

    async def _close_owned_handlers(self, handlers):
        """Descriptor custody release, separate from user close-by-source."""
        async with self._lock:
            owned = [handler for handler in handlers if handler in self._owned]
            self._unpublish_owned_handlers(owned)
        await self._stop_pending(owned)
        await self._shutdown_handlers(owned)

    @property
    def has_owned_sources(self) -> bool:
        """Include pending opens and failed cleanup in runtime custody."""
        return bool(self._owned or self._cleanup_tasks)

    async def close_protocol(self, protocol: str) -> None:
        """Close only this protocol, retaining failed cleanup for retry."""
        await self._close_owned_handlers(
            tuple(h for h in self._owned if h.card.protocol == protocol),
        )

    async def shutdown_all(self) -> None:
        """Revoke pending work and retain failed stops for explicit retry."""
        async with self._lock:
            self._epoch += 1
            for name in tuple(self._revisions):
                self._invalidate(name)
            self._handlers.clear()
            self._handler_scopes.clear()
            self._scope_handlers.clear()
        pending = {
            task
            for task in self._pending.values()
            if task is not asyncio.current_task() and not task.done()
        }
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await self._shutdown_handlers(tuple(self._owned))
        await self._wait_for_handler_cleanups()

    async def close_driver(
        self,
        name: str,
        *,
        session_scope: str = "",
    ) -> None:
        """Stop one source without deleting its persisted configuration."""
        async with self._lock:
            scope = self._handler_scopes.get(name, "")
            if name in self._handlers and scope != session_scope:
                raise DriverNotFoundError(name)
            self._invalidate(name)
            self._handlers.pop(name, None)
            self._handler_scopes.pop(name, None)
            self._scope_handlers.get(session_scope, set()).discard(name)
            handlers = [
                handler
                for handler in self._owned
                if handler.name == name
                and getattr(handler, "_session_scope", "") == session_scope
            ]
        await self._stop_pending(handlers)
        await self._shutdown_handlers(handlers)

    async def _stop_pending(self, handlers):
        pending = {
            self._pending[handler]
            for handler in handlers
            if handler in self._pending
            and self._pending[handler] is not asyncio.current_task()
        }
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def _invalidate(self, name):
        self._active_revisions.pop(name, None)
        self._accepted_sources.pop(name, None)
        self._revisions[name] = self._revisions.get(name, 0) + 1
        return self._revisions[name]

    def _reserve(self, name, card=None):
        if any(
            handler.name == name
            for handler in self._owned
            if handler in self._failed_cleanup
            or handler in self._closing
            or id(handler) in self._cleanup_handler_ids
        ):
            raise RuntimeError(f"Driver '{name}' cleanup has not stopped")
        self._revisions[name] = self._revisions.get(name, 0) + 1
        if card is not None:
            self._accepted_sources[name] = deepcopy(card)
        return self._revisions[name]

    def candidate_is_current(self, name, revision):
        """Only the newest preparation may publish a replacement."""
        return self._revisions.get(name) == revision

    def source_is_current(self, name, revision):
        """Keep committed ownership valid while a candidate is preparing."""
        return self._active_revisions.get(name) == revision or (
            (name, revision) in self._preparing_revisions
            and self.candidate_is_current(name, revision)
        )

    def source_card_is_current(self, card, revision, latest=None):
        """Accept a known replacement without extending old authority."""
        if self._active_revisions.get(card.name) != revision:
            return latest is None or latest == card
        accepted = self._accepted_sources.get(card.name, card)
        if latest is not None and latest not in (card, accepted):
            return False
        authority = latest if latest is not None else accepted
        return (
            authority.enabled == card.enabled
            and authority.protocol == card.protocol
            and authority.credentials == card.credentials
            and authority.policy == card.policy
            and authority.config.get("tools") == card.config.get("tools")
        )

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

    async def _build_and_init_handler(
        self,
        card: DriverCard,
        *,
        revision=None,
        session_scope="",
    ) -> DriverHandler:
        if revision is None:
            revision = self._reserve(card.name, card)
        handler = self._build_handler(card)
        # Private binding shared with the SDK source adapter.
        # pylint: disable-next=protected-access
        handler._session_scope = session_scope
        # pylint: disable-next=protected-access
        handler._source_revision = revision
        self._owned.add(handler)
        self._preparing_revisions.add((card.name, revision))
        self._pending[handler] = asyncio.current_task()
        try:
            bind = getattr(handler, "bind_source", None)
            if bind is not None:
                bind(self, revision, session_scope)
            await handler.init()
            if not self.candidate_is_current(card.name, revision):
                raise RuntimeError("Driver source revision is stale")
        except BaseException:
            await self._shutdown_handler(handler)
            raise
        finally:
            self._pending.pop(handler, None)
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
            *(self._shutdown_handler(handler) for handler in set(handlers)),
            return_exceptions=True,
        )
        errors = [
            str(result)
            for result in results
            if isinstance(result, BaseException)
        ]
        if errors:
            raise RuntimeError("Driver cleanup failed: " + "; ".join(errors))

    def _schedule_handler_cleanup(self, handlers: Iterable[DriverHandler]):
        retired = {
            handler
            for handler in handlers
            if id(handler) not in self._cleanup_handler_ids
        }
        if not retired:
            return None
        ids = {id(handler) for handler in retired}
        self._cleanup_handler_ids.update(ids)

        async def cleanup():
            await self._stop_pending(retired)
            await self._shutdown_handlers(retired)

        task = asyncio.create_task(cleanup(), name="driver-handler-cleanup")
        self._cleanup_tasks.add(task)
        task.add_done_callback(
            lambda done: self._finish_handler_cleanup(done, ids),
        )
        return task

    def _finish_handler_cleanup(self, task, ids):
        self._cleanup_tasks.discard(task)
        self._cleanup_handler_ids.difference_update(ids)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Managed Driver cleanup failed: %s", task.exception())

    async def _wait_for_handler_cleanups(self):
        while self._cleanup_tasks:
            await asyncio.shield(asyncio.gather(*tuple(self._cleanup_tasks)))
        if self._failed_cleanup:
            raise RuntimeError("Driver cleanup has not stopped")

    async def _shutdown_handler(self, handler):
        self._preparing_revisions.discard(
            # pylint: disable-next=protected-access
            (handler.name, handler._source_revision),
        )
        if handler not in self._owned:
            return
        task = self._closing.get(handler)
        if task is None:

            async def stop():
                try:
                    await asyncio.wait_for(
                        handler.shutdown(),
                        timeout=_SHUTDOWN_TIMEOUT_SECONDS,
                    )
                except BaseException:
                    self._failed_cleanup.add(handler)
                    raise
                else:
                    self._owned.discard(handler)
                    self._failed_cleanup.discard(handler)
                finally:
                    self._closing.pop(handler, None)

            task = asyncio.create_task(
                stop(),
                name=f"driver-shutdown:{handler.name}",
            )
            self._closing[handler] = task
        await asyncio.shield(task)
