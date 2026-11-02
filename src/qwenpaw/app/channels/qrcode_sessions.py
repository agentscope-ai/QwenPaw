# -*- coding: utf-8 -*-
"""Static, scoped custody for explicit QR operations on installed channels."""

from __future__ import annotations

import asyncio
from collections import Counter, OrderedDict
from collections.abc import Collection, Mapping
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from secrets import token_urlsafe
from time import monotonic
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from ...channel_protocol.management import (
    MANAGEMENT_CAPABILITIES,
    management_options,
)
from ...config.config import load_agent_config
from ...config.channel_config_compat import absolute_execution_paths
from ...config.utils import load_config
from ...constant import WORKING_DIR
from ...plugins.ownership import RuntimeKey, RuntimeLease, RuntimeStopReceipt
from .management import (
    ChannelManagementService,
    ManagementError,
    _source_matches,
)
from .qrcode_auth_handler import PollResult, QRCodeResult
from ...utils.io_utils import run_async_to_completion, run_sync_io
from .wechat_auth_custody import (
    reserve_wechat_auth_async,
    release_wechat_auth,
)

_MAX_SESSIONS = 128
_SESSION_TTL = 300.0
_TERMINAL_TTL = 60.0


class _SessionExpired(HTTPException):
    def __init__(self):
        super().__init__(400, "QR session expired")


@dataclass(frozen=True)
class ChannelManagementScope:
    workspace_id: str
    workspace_dir: Path
    channel_key: str
    config: Mapping[str, Any] = field(repr=False)
    principal_id: str | None = None

    def __post_init__(self):
        object.__setattr__(
            self,
            "workspace_dir",
            Path(self.workspace_dir).expanduser().resolve(),
        )
        object.__setattr__(self, "config", deepcopy(dict(self.config)))


def _read_scope(workspace_id, channel_key, principal_id=None):
    root = load_config()
    profile = root.agents.profiles.get(workspace_id)
    if profile is None:
        raise HTTPException(404, "Agent not found")
    if not profile.enabled:
        raise HTTPException(403, "Agent is disabled")
    channels = load_agent_config(workspace_id).channels
    configs = channels.model_dump() if channels is not None else {}
    config = configs.get(channel_key)
    if not isinstance(config, Mapping):
        raise HTTPException(404, "Channel configuration not found")
    return ChannelManagementScope(
        workspace_id,
        Path(profile.workspace_dir),
        channel_key,
        config,
        principal_id,
    )


async def resolve_channel_management_scope_async(request, channel_key):
    """Capture request values on-loop; resolve disk-backed scope in a worker."""
    workspace_id = getattr(
        request.state,
        "agent_id",
        None,
    ) or request.headers.get("X-Agent-Id")
    user = getattr(request.state, "user", None)
    principal = user.get("username") if isinstance(user, dict) else None

    def read():
        selected = (
            workspace_id or load_config().agents.active_agent or "default"
        )
        return _read_scope(selected, channel_key, principal)

    return await run_sync_io(read)


@dataclass
class _Session:
    scope: ChannelManagementScope
    lease: RuntimeLease
    source_revision: str
    config: dict = field(repr=False)
    expires: float
    options: dict = field(default_factory=dict, repr=False)
    status: str = "fetching"
    continuation: str = field(default="", repr=False)
    credentials: dict = field(default_factory=dict, repr=False)
    metadata: dict = field(default_factory=dict, repr=False)
    public_status: str = "confirmed"
    claims: tuple[RuntimeLease, ...] = ()
    operation: asyncio.Task | None = None
    waiters: int = 0
    validation: asyncio.Task | None = None
    validation_waiters: int = 0
    commit: asyncio.Task | None = None
    timer: asyncio.TimerHandle | None = None
    cleanup: asyncio.Task | None = None
    retained: RuntimeLease | None = None
    cleanup_error: ManagementError | None = None


async def _settle(task):
    """Keep cleanup ownership through repeated cancellation; observe its
    result.
    """
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    return task.result(), cancelled


class ChannelQRCodeSessions:
    def __init__(self, loader, management: ChannelManagementService):
        self._loader = loader
        self._management = management
        self._owners = loader.registry.runtime_owners
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._closed = False
        self._revoking: Counter[tuple[str, str | None]] = Counter()
        self._working_dir = Path.cwd()

    @staticmethod
    def _identity(scope):
        return (
            scope.workspace_id,
            scope.workspace_dir,
            scope.channel_key,
            scope.principal_id,
        )

    def _check_admission(self, scope):
        if self._closed:
            raise ManagementError("MANAGEMENT_CLOSED")
        if any(
            (scope.workspace_id, key) in self._revoking
            for key in (None, scope.channel_key)
        ):
            raise ManagementError("MANAGEMENT_BUSY")

    async def _admit(self, scope):
        self._check_admission(scope)
        current = await run_sync_io(
            _read_scope,
            scope.workspace_id,
            scope.channel_key,
            scope.principal_id,
        )
        self._check_admission(scope)
        if (
            self._identity(current) != self._identity(scope)
            or current.config != scope.config
        ):
            raise HTTPException(403, "Channel scope changed")

    async def _source(self, scope, source=None):
        if source is None:
            row = self._loader.registry.get_channel_catalog_entry(
                scope.channel_key,
            )
            if row is None:
                raise ManagementError("PLUGIN_NOT_INSTALLED")
            record = self._loader.get_loaded_plugin(row.plugin_id)
            if record is None:
                raise ManagementError("PLUGIN_NOT_INSTALLED")
            snapshot = None
        else:
            row, record, snapshot = source
        description, _ = await self._management._source(
            row,
            record,
            scope.channel_key,
            snapshot=snapshot,
        )
        if (
            MANAGEMENT_CAPABILITIES["qrcode.fetch"]
            not in description.descriptor.capabilities
        ):
            raise ManagementError("MANAGEMENT_UNSUPPORTED")
        return row, description

    @staticmethod
    def _auth_config(session, credentials=None, *, working_dir=None):
        if working_dir is None:
            working_dir = Path.cwd()
        config = {**session.scope.config, **session.config, **session.options}
        config.update({k: v for k, v in (credentials or {}).items() if v})
        configured = config.get("bot_token_file")
        config["bot_token_file"] = str(
            Path(configured).expanduser()
            if configured
            else (WORKING_DIR / "wechat_bot_token").expanduser(),
        )
        return absolute_execution_paths(
            config,
            path_fields=("bot_token_file", "media_dir"),
            working_dir=working_dir,
        )

    def _check_session(self, session):
        if session.status == "expired":
            raise _SessionExpired()
        if session.status in {"cancelled", "consumed", "failed"}:
            raise HTTPException(400, "QR session is no longer active")
        self._check_admission(session.scope)
        if (
            session.lease not in self._owners.leases()
            or self._owners.resource(session.lease) is not session
        ):
            raise ManagementError("IDENTITY_MISMATCH")
        if monotonic() >= session.expires:
            self._invalidate(session, "expired")
            raise _SessionExpired()

    async def _scan_session(self, session, source=None):
        self._check_session(session)
        row, description = await self._source(session.scope, source)
        record = self._loader.get_loaded_plugin(row.plugin_id)
        snapshot = self._management._source_snapshot(
            row,
            record,
            session.scope.channel_key,
        )
        self._check_session(session)
        if (
            description.plugin_id != session.lease.plugin_id
            or description.source_revision != session.source_revision
            or description.code_root != session.lease.code_root
        ):
            raise ManagementError("SOURCE_REVISION_MISMATCH")
        await self._admit(session.scope)
        self._check_session(session)
        current = self._management._source_snapshot(
            row,
            record,
            session.scope.channel_key,
        )
        if not _source_matches(current, snapshot):
            raise ManagementError("SOURCE_REVISION_MISMATCH")

    async def _prepare_fetch(self, session, source):
        await self._scan_session(session, source)
        self._check_session(session)
        if session.scope.channel_key == "wechat":
            await self._reserve_auth(session)
            self._check_session(session)

    async def _wait_validation(self, session):
        task = session.validation
        session.validation_waiters += 1
        try:
            return await asyncio.shield(task)
        finally:
            session.validation_waiters -= 1
            if session.validation_waiters == 0:
                if not task.done():
                    task.cancel()
                    try:
                        await _settle(task)
                    except asyncio.CancelledError:
                        pass
                if session.validation is task:
                    session.validation = None

    async def _validate(self, session):
        self._check_session(session)
        if session.validation is None:
            session.validation = asyncio.create_task(
                self._scan_session(session),
            )
        await self._wait_validation(session)
        self._check_session(session)

    async def _reserve_auth(self, session, credentials=None):
        self._check_session(session)
        claims = await reserve_wechat_auth_async(
            self._loader.registry,
            owner=session.lease,
            workspace_id=session.scope.workspace_id,
            workspace_dir=session.scope.workspace_dir,
            config=self._auth_config(
                session,
                credentials,
                working_dir=self._working_dir,
            ),
            working_dir=WORKING_DIR,
            authorize=lambda: self._check_session(session),
        )
        session.claims = tuple(dict.fromkeys((*session.claims, *claims)))
        self._check_session(session)

    def _lookup(self, scope, token):
        if not isinstance(token, str) or not token:
            raise HTTPException(400, "Unknown QR session")
        session = self._sessions.get(sha256(token.encode()).hexdigest())
        if session is None:
            raise HTTPException(400, "Unknown QR session")
        if self._identity(scope) != self._identity(session.scope):
            raise HTTPException(403, "QR session belongs to another scope")
        if monotonic() >= session.expires and session.status not in {
            "cancelled",
            "consumed",
            "failed",
        }:
            self._invalidate(session, "expired")
            self._schedule_close(session)
        return session

    @staticmethod
    def _invalidate(session, status):
        session.status = status
        session.continuation = ""
        session.credentials.clear()
        session.metadata.clear()
        if session.timer is not None:
            session.timer.cancel()
            session.timer = None

    def _arm_expiry(self, session):
        if session.timer is not None:
            session.timer.cancel()

        def expire():
            self._invalidate(session, "expired")
            self._schedule_close(session)

        session.timer = asyncio.get_running_loop().call_later(
            max(0, session.expires - monotonic()),
            expire,
        )

    def _schedule_close(self, session):
        if session.cleanup is None or session.cleanup.done():
            session.cleanup = asyncio.create_task(self._close(session))

            def observe(task):
                if not task.cancelled():
                    error = task.exception()
                    if error is not None:
                        session.cleanup_error = error

            session.cleanup.add_done_callback(observe)
        return session.cleanup

    async def _stop(self, session):
        """Exact adapter: cancel work, then attest only its actual stop
        proof.
        """
        if session.status not in {"expired", "consumed", "failed"}:
            self._invalidate(session, "cancelled")
        retained = session.retained
        operation = session.operation
        validation = session.validation
        commit = session.commit
        tasks = tuple(
            dict.fromkeys(
                task for task in (validation, operation) if task is not None
            ),
        )
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in (*tasks, *((commit,) if commit is not None else ())):
            try:
                await _settle(task)
            except asyncio.CancelledError:
                pass
            except Exception as error:
                if isinstance(error, ManagementError) and (
                    error.reason_code == "MANAGEMENT_CLEANUP_FAILED"
                ):
                    session.cleanup_error = error
        if session.retained is not None:
            if retained is None:
                # This stop attempt just failed. Recovery is a subsequent
                # stop, never an implicit repeated platform operation or
                # cleanup loop.
                return session.cleanup_error.receipt
            receipt = await self._owners.stop(retained)
            if not receipt.stopped:
                return receipt
            session.retained = None
        receipt = RuntimeStopReceipt(True, "QR_SESSION_STOPPED")
        release_wechat_auth(self._loader.registry, session.claims, receipt)
        session.claims = ()
        session.config.clear()
        session.options.clear()
        session.cleanup_error = None
        session.validation = None
        session.commit = None
        # Waiters retain their own task reference and recheck session
        # authority. Once cleanup is proved, the session must not retain
        # its result secrets.
        if session.operation is operation:
            session.operation = None
        return receipt

    async def _close(self, session):
        stop = asyncio.create_task(self._owners.stop(session.lease))
        receipt, cancelled = await _settle(stop)
        if not receipt.stopped:
            raise ManagementError(
                "MANAGEMENT_CLEANUP_FAILED",
                needs_restart=True,
                receipt=receipt,
                lease=session.retained,
            )
        if cancelled:
            raise asyncio.CancelledError

    async def _execute(self, session, operation):
        remaining = session.expires - monotonic()
        if remaining < 0.001:
            raise ManagementError("MANAGEMENT_TIMEOUT")
        parameters = {"config": deepcopy(session.config)}
        if session.options:
            parameters["options"] = deepcopy(session.options)
        if operation == "qrcode.poll":
            parameters["continuation"] = session.continuation
        try:
            # Unlike Service's RPC deadline this also includes startup/cleanup.
            async with asyncio.timeout(remaining):
                result = await self._management.execute(
                    session.scope.workspace_id,
                    session.scope.channel_key,
                    operation,
                    parameters,
                    timeout=min(
                        35 if operation == "qrcode.fetch" else 65,
                        remaining,
                    ),
                )
        except ManagementError as error:
            if error.reason_code == "MANAGEMENT_CLEANUP_FAILED":
                session.retained = error.lease
                session.cleanup_error = error
                self._invalidate(session, "failed")
            raise
        except TimeoutError:
            self._invalidate(session, "expired")
            raise ManagementError(
                "MANAGEMENT_TIMEOUT",
                side_effect_possible=True,
            ) from None
        if (
            result.plugin_id != session.lease.plugin_id
            or result.workspace_id != session.scope.workspace_id
            or result.channel_key != session.scope.channel_key
            or result.source_revision != session.source_revision
        ):
            raise ManagementError("MANAGEMENT_INVALID_RESULT")
        if result.outcome != "ok":
            raise ManagementError(result.reason_code)
        self._check_session(session)
        payload = result.result
        if (
            session.scope.channel_key == "wechat"
            and operation == "qrcode.poll"
            and payload["status"] in {"confirmed", "success"}
            and payload["credentials"]
            and any(payload["credentials"].values())
            and "fail_reason" not in payload["credentials"]
        ):
            await self._reserve_auth(session, payload["credentials"])
            self._check_session(session)
        return payload

    async def _wait_operation(self, session):
        session.waiters += 1
        task = session.operation
        try:
            return await asyncio.shield(task)
        finally:
            session.waiters -= 1
            if session.waiters == 0 and not task.done():
                task.cancel()
                try:
                    await _settle(task)
                except asyncio.CancelledError:
                    pass

    async def fetch(self, scope, options: Mapping[str, str]) -> QRCodeResult:
        self._check_admission(scope)
        row = self._loader.registry.get_channel_catalog_entry(
            scope.channel_key,
        )
        if row is None:
            raise ManagementError("PLUGIN_NOT_INSTALLED")
        record = self._loader.get_loaded_plugin(row.plugin_id)
        if record is None:
            raise ManagementError("PLUGIN_NOT_INSTALLED")
        description, _, _, _ = self._management._source_snapshot(
            row,
            record,
            scope.channel_key,
        )
        fields = description.descriptor.config_schema.get("properties", {})
        allowed = (
            {"base_url"} if scope.channel_key == "wechat" else set(fields)
        )
        private = ChannelManagementService.private_config_fields()
        try:
            options = management_options(
                options,
                fields=allowed,
                forbidden=private,
            )
        except ValueError:
            raise ManagementError("MANAGEMENT_INVALID_REQUEST") from None
        config = (
            {"base_url": scope.config.get("base_url", "")}
            if scope.channel_key == "wechat"
            else deepcopy(dict(scope.config))
        )
        # Only this already-resolved and revalidated workspace snapshot is
        # projected. Browser options and direct Service calls still reject
        # execution/path fields rather than silently dropping them.
        config = {
            key: value for key, value in config.items() if key not in private
        }
        async with self._loader.execution_source(row.plugin_id) as record:
            self._check_admission(scope)
            snapshot = self._management._source_snapshot(
                row,
                record,
                scope.channel_key,
            )
            if snapshot[0] is not description:
                raise ManagementError("SOURCE_REVISION_MISMATCH")
            runtime_key = RuntimeKey(
                "channel",
                scope.channel_key,
                str(scope.workspace_dir),
            )
            qr_key = RuntimeKey(
                "qrcode_session",
                scope.channel_key,
                str(scope.workspace_dir),
            )
            if any(
                lease.key in (runtime_key, qr_key)
                for lease in self._owners.leases()
            ):
                raise ManagementError("ACCOUNT_IN_USE")
            for digest, old in tuple(self._sessions.items()):
                if old.lease not in self._owners.leases():
                    if len(self._sessions) < _MAX_SESSIONS:
                        break
                    del self._sessions[digest]
            if (
                len(self._sessions) >= _MAX_SESSIONS
                or sum(
                    lease.key.kind == "qrcode_session"
                    for lease in self._owners.leases()
                )
                >= _MAX_SESSIONS
            ):
                raise ManagementError("MANAGEMENT_BUSY")
            lease = self._owners.reserve(
                row.plugin_id,
                qr_key,
                description.code_root,
                instance_id=str(uuid4()),
                custody_only=True,
            )
            session = _Session(
                deepcopy(scope),
                lease,
                description.source_revision,
                config,
                monotonic() + _SESSION_TTL,
                options=dict(options),
            )
            self._owners.attach(
                lease,
                lambda: self._stop(session),
                resource=session,
            )
            token = token_urlsafe(32)
            self._sessions[sha256(token.encode()).hexdigest()] = session
            self._arm_expiry(session)
        try:
            session.validation = asyncio.create_task(
                self._prepare_fetch(session, (row, record, snapshot)),
            )
            await self._wait_validation(session)
            self._check_session(session)
            session.operation = asyncio.create_task(
                self._execute(session, "qrcode.fetch"),
            )
            result = await self._wait_operation(session)
            await self._validate(session)
            self._check_session(session)
            if session.status != "fetching":
                raise HTTPException(400, "QR session is no longer fetching")
            session.continuation = result["continuation"]
            if "expires_in_seconds" in result:
                session.expires = monotonic() + result["expires_in_seconds"]
                self._arm_expiry(session)
            session.status = "waiting"
            return QRCodeResult(result["scan_url"], token)
        except BaseException:
            self._invalidate(session, "failed")
            if session.retained is None:
                await self._close(session)
            raise

    async def poll(self, scope, token: str) -> PollResult:
        session = self._lookup(scope, token)
        if session.status == "expired":
            return PollResult("expired", {})
        if session.status in {"cancelled", "consumed", "failed"}:
            raise HTTPException(400, "QR session is no longer active")
        try:
            await self._validate(session)
        except asyncio.CancelledError:
            raise
        except _SessionExpired:
            await self._close(session)
            return PollResult("expired", {})
        except BaseException:
            self._invalidate(session, "cancelled")
            await self._close(session)
            raise
        self._check_session(session)
        if session.status == "confirmed":
            return PollResult(
                session.public_status,
                deepcopy({**session.metadata, **session.credentials}),
            )
        if session.operation is None or session.operation.done():
            session.operation = asyncio.create_task(
                self._execute(session, "qrcode.poll"),
            )
        try:
            result = await self._wait_operation(session)
        except _SessionExpired:
            await self._close(session)
            return PollResult("expired", {})
        except asyncio.CancelledError:
            if (
                session.status == "expired"
                and not asyncio.current_task().cancelling()
            ):
                return PollResult("expired", {})
            raise
        except BaseException:
            self._invalidate(session, "failed")
            await self._close(session)
            raise
        if session.status == "expired":
            return PollResult("expired", {})
        try:
            await self._validate(session)
        except asyncio.CancelledError:
            raise
        except _SessionExpired:
            await self._close(session)
            return PollResult("expired", {})
        except BaseException:
            self._invalidate(session, "cancelled")
            await self._close(session)
            raise
        if session.status in {"cancelled", "consumed", "failed"}:
            raise HTTPException(400, "QR session is no longer active")
        self._check_session(session)
        if session.status == "confirmed":
            return PollResult(
                session.public_status,
                deepcopy({**session.metadata, **session.credentials}),
            )
        status = result["status"]
        if status in {"confirmed", "success"}:
            if (
                not result["credentials"]
                or not any(result["credentials"].values())
                or "fail_reason" in result["credentials"]
            ):
                self._invalidate(session, "failed")
                await self._close(session)
                raise ManagementError("MANAGEMENT_INVALID_RESULT")
            session.credentials = deepcopy(result["credentials"])
            session.metadata = deepcopy(result.get("metadata", {}))
            session.public_status = status
            session.status = "confirmed"
            session.expires = min(session.expires, monotonic() + _TERMINAL_TTL)
            self._arm_expiry(session)
        elif status in {"expired", "fail"}:
            reason = {
                key: value
                for key, value in result["credentials"].items()
                if key == "fail_reason"
            }
            self._invalidate(
                session,
                "expired" if status == "expired" else "failed",
            )
            await self._close(session)
            return PollResult(status, reason)
        return PollResult(
            status,
            (
                deepcopy({**session.metadata, **session.credentials})
                if session.status == "confirmed"
                else {}
            ),
        )

    async def cancel(self, scope, token: str) -> None:
        session = self._lookup(scope, token)
        if session.status != "expired":
            self._invalidate(session, "cancelled")
        await self._close(session)

    @asynccontextmanager
    async def operation_guard(
        self,
        workspace_id,
        channel_key: str | Collection[str] | None = None,
    ):
        """Close every target's admission before awaiting selected cleanup."""
        if channel_key is None or isinstance(channel_key, str):
            channels = (channel_key,)
        elif isinstance(channel_key, Collection) and all(
            isinstance(key, str) for key in channel_key
        ):
            channels = tuple(dict.fromkeys(channel_key))
        else:
            raise TypeError("Channel guard targets must be strings")
        keys = tuple((workspace_id, key) for key in channels)
        for key in keys:
            self._revoking[key] += 1
        try:
            sessions = [
                session
                for session in self._sessions.values()
                if session.scope.workspace_id == workspace_id
                and (
                    channel_key is None
                    or session.scope.channel_key in channels
                )
            ]
            for session in sessions:
                self._invalidate(session, "cancelled")
            errors = []
            for session in sessions:
                try:
                    await self._close(session)
                except (ManagementError, asyncio.CancelledError) as error:
                    errors.append(error)
            if errors:
                raise errors[0]
            yield
        finally:
            for key in keys:
                self._revoking[key] -= 1
                if not self._revoking[key]:
                    del self._revoking[key]

    async def revoke_workspace(self, workspace_id: str) -> None:
        async with self.operation_guard(workspace_id):
            pass

    async def revoke_channel(
        self,
        workspace_id: str,
        channel_key: str,
    ) -> None:
        async with self.operation_guard(workspace_id, channel_key):
            pass

    async def aclose(self) -> None:
        self._closed = True
        errors = []
        for workspace_id in {
            s.scope.workspace_id for s in self._sessions.values()
        }:
            try:
                await self.revoke_workspace(workspace_id)
            except (ManagementError, asyncio.CancelledError) as error:
                errors.append(error)
        if errors:
            raise errors[0]

    async def save_confirmed(self, scope, token, values, persist):
        """Authorize once, then retain custody until the real commit settles."""
        session = self._lookup(scope, token)
        if session.commit is not None:
            raise HTTPException(409, "QR save is already in progress")
        try:
            await self._validate(session)
        except asyncio.CancelledError:
            raise
        except BaseException:
            if session.status not in {
                "expired",
                "consumed",
                "cancelled",
                "failed",
            }:
                self._invalidate(session, "cancelled")
            await self._close(session)
            raise
        self._check_session(session)
        if session.commit is not None:
            raise HTTPException(409, "QR save is already in progress")
        if session.status != "confirmed":
            raise HTTPException(400, "QR session is not confirmed")
        for key, value in session.credentials.items():
            if key == "base_url" and not value:
                if values.get(key, scope.config.get(key)) != scope.config.get(
                    key,
                ):
                    raise HTTPException(403, "QR credential mismatch")
            elif values.get(key) != value:
                raise HTTPException(403, "QR credential mismatch")
        if scope.channel_key == "wechat" and not session.credentials.get(
            "bot_token",
        ):
            raise HTTPException(400, "QR credential missing")
        if scope.channel_key == "wechat" and values.get(
            "bot_token_file",
            scope.config.get("bot_token_file"),
        ) != scope.config.get("bot_token_file"):
            raise HTTPException(403, "QR authentication path changed")

        async def commit():
            result = await persist()
            self._invalidate(session, "consumed")
            return result

        session.commit = task = asyncio.create_task(commit())
        try:
            return await run_async_to_completion(task)
        finally:
            if task.done() and session.commit is task:
                session.commit = None
            if session.status in {
                "consumed",
                "cancelled",
                "expired",
                "failed",
            }:
                await self._close(session)
