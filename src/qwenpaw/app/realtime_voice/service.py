"""Realtime voice authorization, leases, and coordinator lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from ...config.config import ModelSlotConfig
from ...providers.realtime_voice import (
    EffectiveRealtimeVoiceConfig,
    MediaConfig,
    RealtimeProviderSession,
)
from ..chats.models import ChatSpec, SessionSource
from ..chats.timeline import ChatTimelineJournal
from .contracts import (
    PROTOCOL_VERSION,
    TOKEN_TTL_SECONDS,
    CreateSessionRequest,
    RealtimeVoiceServiceError,
    SessionBootstrap,
    VoiceAdmissionMode,
)
from .coordinator import VoiceCoordinator
from .task_bridge import VoiceTaskBridge
from .turn_commit import (
    ProviderModelVoiceTurnRouter,
    SpokenTurnCommitter,
    UnavailableVoiceTurnRouter,
)

_LOCAL_PRINCIPAL = "local-single-user"


@dataclass
class LiveVoiceSession:
    session_id: str
    agent_id: str
    chat: ChatSpec
    principal: str
    generation: int
    config: EffectiveRealtimeVoiceConfig
    media: MediaConfig
    router_model: ModelSlotConfig | None
    admission_mode: VoiceAdmissionMode
    api_key: str = field(repr=False)
    workspace: Any = field(repr=False)
    bootstrap_expires_at: datetime
    connected: bool = False
    provider_session: RealtimeProviderSession | None = field(
        default=None,
        repr=False,
    )
    coordinator: VoiceCoordinator | None = field(default=None, repr=False)


@dataclass(frozen=True)
class _BootstrapGrant:
    session_id: str
    principal: str
    agent_id: str
    chat_id: str
    generation: int
    expires_at: datetime


def request_principal(request: Any) -> str:
    """Return the authenticated local principal without inventing accounts."""
    user = getattr(request.state, "user", None)
    return str(user) if user else _LOCAL_PRINCIPAL


class RealtimeVoiceService:
    """Own native voice sessions while the normal Chat owns task execution."""

    def __init__(self, provider_manager: Any) -> None:
        self._provider_manager = provider_manager
        self._leases: dict[str, LiveVoiceSession] = {}
        self._sessions: dict[str, LiveVoiceSession] = {}
        self._grants: dict[str, _BootstrapGrant] = {}
        self._generations: dict[tuple[str, str], int] = {}
        self._bridges: dict[str, VoiceTaskBridge] = {}
        self._lock = asyncio.Lock()

    def resolve_config(
        self,
        workspace: Any,
    ) -> EffectiveRealtimeVoiceConfig:
        """Resolve the Agent's active native voice model."""
        slot: ModelSlotConfig | None = (
            getattr(workspace.config, "active_realtime_model", None)
            or self._provider_manager.get_active_realtime_model()
        )
        if slot is None:
            raise RealtimeVoiceServiceError(
                "model_unconfigured",
                "Select a Voice model in Models settings.",
                409,
            )
        try:
            return self._provider_manager.resolve_realtime_voice_config(slot)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RealtimeVoiceServiceError(
                "model_unavailable",
                str(exc),
                409,
            ) from exc

    def capabilities(self, workspace: Any) -> dict[str, Any]:
        """Return ProviderManager-owned sanitized native capability."""
        effective_model: dict[str, Any] | None = None
        active_model: dict[str, Any] | None = None
        credential_configured = False
        error: dict[str, str] | None = None
        router_override = (
            getattr(workspace.config, "active_voice_router_model", None)
            or self._provider_manager.get_active_voice_router_model()
        )
        effective_router = self.resolve_router_model(workspace)
        try:
            resolved = self.resolve_config(workspace)
            effective_model = resolved.model_dump()
            slot = (
                getattr(workspace.config, "active_realtime_model", None)
                or self._provider_manager.get_active_realtime_model()
            )
            active_model = slot.model_dump() if slot is not None else None
            provider = self._provider_manager.get_provider(
                resolved.provider_id,
            )
            credential_configured = bool(
                provider
                and str(getattr(provider, "api_key", "") or "").strip()
            )
        except RealtimeVoiceServiceError as exc:
            error = {"code": exc.code, "message": exc.message}
        return {
            "protocol_version": PROTOCOL_VERSION,
            "agent_id": workspace.agent_id,
            "providers": (
                self._provider_manager.list_realtime_voice_capabilities()
            ),
            "active_model": active_model,
            "effective_model": effective_model,
            "active_router_model": (
                router_override.model_dump()
                if router_override is not None
                else None
            ),
            "effective_router_model": (
                effective_router.model_dump()
                if effective_router is not None
                else None
            ),
            "credential_configured": credential_configured,
            "configuration_error": error,
        }

    def resolve_router_model(
        self,
        workspace: Any,
    ) -> ModelSlotConfig | None:
        """Resolve optional override, then inherit the ordinary Chat model."""
        return (
            getattr(workspace.config, "active_voice_router_model", None)
            or self._provider_manager.get_active_voice_router_model()
            or getattr(workspace.config, "active_model", None)
            or self._provider_manager.get_active_model()
        )

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _drop_expired_bootstraps(self, now: datetime) -> None:
        expired = [
            digest
            for digest, grant in self._grants.items()
            if grant.expires_at <= now
        ]
        for digest in expired:
            grant = self._grants.pop(digest)
            live = self._sessions.get(grant.session_id)
            if live is not None and not live.connected:
                self._sessions.pop(live.session_id, None)
                if self._leases.get(live.principal) is live:
                    self._leases.pop(live.principal, None)

    @staticmethod
    async def _resolve_chat(
        workspace: Any,
        principal: str,
        chat_id: str | None,
        config: EffectiveRealtimeVoiceConfig,
    ) -> ChatSpec:
        if workspace.chat_manager is None:
            raise RealtimeVoiceServiceError(
                "chat_unavailable",
                "Chat storage is not ready.",
                503,
            )
        if chat_id:
            chat = await workspace.chat_manager.get_chat(chat_id)
            if chat is None:
                raise RealtimeVoiceServiceError(
                    "chat_not_found",
                    "Voice Chat was not found.",
                    404,
                )
            if chat.source != SessionSource.realtime_voice:
                raise RealtimeVoiceServiceError(
                    "invalid_chat_source",
                    "Only a Voice Chat can be resumed as realtime voice.",
                    409,
                )
            if chat.archived:
                raise RealtimeVoiceServiceError(
                    "chat_archived",
                    "Unarchive this Voice Chat before resuming it.",
                    409,
                )
            if chat.user_id != principal:
                raise RealtimeVoiceServiceError(
                    "chat_owner_mismatch",
                    "Voice Chat belongs to a different principal.",
                    403,
                )
            return chat

        chat_uuid = str(uuid4())
        chat = ChatSpec(
            id=chat_uuid,
            name="Voice Chat",
            session_id=f"realtime_voice:{chat_uuid}",
            user_id=principal,
            channel="console",
            source=SessionSource.realtime_voice,
            meta={
                "realtime_voice": {
                    "version": 3,
                    "agent_id": workspace.agent_id,
                    "provider_id": config.provider_id,
                    "model": config.realtime_model,
                    "region": config.region,
                    "voice": config.voice,
                },
            },
        )
        return await workspace.chat_manager.create_chat(chat)

    async def create_session(
        self,
        workspace: Any,
        principal: str,
        request: CreateSessionRequest,
    ) -> SessionBootstrap:
        """Acquire the single live lease and issue one short-lived grant."""
        displaced: LiveVoiceSession | None = None
        async with self._lock:
            now = datetime.now(UTC)
            self._drop_expired_bootstraps(now)
            existing = self._leases.get(principal)
            if existing is not None:
                reconnect = request.previous_session_id == existing.session_id
                replace = request.replace_session_id == existing.session_id
                if not reconnect and not replace:
                    raise RealtimeVoiceServiceError(
                        "live_session_conflict",
                        "Another Voice session is active. Confirm switching "
                        "before replacing it.",
                        409,
                        {
                            "session_id": existing.session_id,
                            "agent_id": existing.agent_id,
                            "chat_id": existing.chat.id,
                        },
                    )
                if reconnect and request.chat_id != existing.chat.id:
                    raise RealtimeVoiceServiceError(
                        "reconnect_mismatch",
                        "Reconnect must target the same Voice Chat.",
                        409,
                    )

            effective = self.resolve_config(workspace)
            provider = self._provider_manager.get_provider(
                effective.provider_id,
            )
            api_key = str(getattr(provider, "api_key", "") or "").strip()
            if not api_key:
                raise RealtimeVoiceServiceError(
                    "credential_unavailable",
                    "The selected Provider record has no API key. Configure "
                    "it in Models settings.",
                    409,
                )
            registration = (
                self._provider_manager.get_realtime_voice_registration(
                    effective.provider_id,
                )
            )
            if registration is None:
                raise RealtimeVoiceServiceError(
                    "provider_unavailable",
                    "The selected voice provider is unavailable.",
                    409,
                )
            chat = await self._resolve_chat(
                workspace,
                principal,
                request.chat_id,
                effective,
            )
            if existing is not None:
                displaced = existing
                self._leases.pop(principal, None)
                self._sessions.pop(existing.session_id, None)
                self._grants = {
                    digest: grant
                    for digest, grant in self._grants.items()
                    if grant.session_id != existing.session_id
                }
            generation_key = (principal, chat.id)
            generation = self._generations.get(generation_key, 0) + 1
            self._generations[generation_key] = generation
            expires_at = now + timedelta(seconds=TOKEN_TTL_SECONDS)
            live = LiveVoiceSession(
                session_id=uuid4().hex,
                agent_id=workspace.agent_id,
                chat=chat,
                principal=principal,
                generation=generation,
                config=effective,
                media=registration.media,
                router_model=self.resolve_router_model(workspace),
                admission_mode=request.admission_mode,
                api_key=api_key,
                workspace=workspace,
                bootstrap_expires_at=expires_at,
            )
            token = secrets.token_urlsafe(32)
            self._leases[principal] = live
            self._sessions[live.session_id] = live
            self._grants[self._token_digest(token)] = _BootstrapGrant(
                session_id=live.session_id,
                principal=principal,
                agent_id=live.agent_id,
                chat_id=chat.id,
                generation=generation,
                expires_at=expires_at,
            )

        if displaced is not None:
            await self._close_live(displaced)
        return SessionBootstrap(
            session_id=live.session_id,
            agent_id=live.agent_id,
            chat_id=chat.id,
            generation=generation,
            media=live.media,
            ws_url=f"/api/realtime-voice/sessions/{live.session_id}/stream",
            token=token,
            expires_at=expires_at.isoformat(),
            admission_mode=live.admission_mode,
        )

    async def consume_grant(
        self,
        session_id: str,
        token: str,
    ) -> LiveVoiceSession:
        """Atomically consume a grant and bind it to its session record."""
        async with self._lock:
            now = datetime.now(UTC)
            self._drop_expired_bootstraps(now)
            grant = self._grants.pop(self._token_digest(token), None)
            live = self._sessions.get(session_id)
            if (
                grant is None
                or live is None
                or grant.session_id != session_id
                or grant.principal != live.principal
                or grant.agent_id != live.agent_id
                or grant.chat_id != live.chat.id
                or grant.generation != live.generation
                or live.connected
            ):
                raise RealtimeVoiceServiceError(
                    "invalid_token",
                    "Realtime Voice authorization is invalid or expired.",
                    401,
                )
            live.connected = True
            return live

    async def connect(
        self,
        live: LiveVoiceSession,
    ) -> VoiceCoordinator:
        """Connect the Provider and construct the current-Chat coordinator."""
        registration = self._provider_manager.get_realtime_voice_registration(
            live.config.provider_id,
        )
        if registration is None:
            raise RealtimeVoiceServiceError(
                "provider_unavailable",
                "The selected voice provider is unavailable.",
                409,
            )
        provider_session = registration.factory(live.config, live.api_key)
        timeline = ChatTimelineJournal(live.workspace, live.chat)

        async def conversation_context() -> str:
            return await timeline.read_context(
                max_turns=live.config.max_history_turns,
                max_chars=4000,
            )

        bridge = self._bridges.get(live.chat.id)
        if bridge is None:
            bridge = VoiceTaskBridge(live.workspace, live.chat)
            self._bridges[live.chat.id] = bridge
        if live.router_model is None:
            router = UnavailableVoiceTurnRouter(
                "No model is configured for semantic voice routing.",
            )
        else:
            router = ProviderModelVoiceTurnRouter(
                live.agent_id,
                live.router_model,
                bridge.routing_snapshots,
                conversation_context,
            )
        committer = SpokenTurnCommitter(
            router,
            continuation_grace_ms=live.config.continuation_grace_ms,
        )
        coordinator = VoiceCoordinator(
            provider_session,
            bridge,
            committer,
            timeline,
            language=live.config.language,
            admission_mode=live.admission_mode,
            presentation_capacity=live.config.presentation_capacity,
            playback_timeout_seconds=live.config.playback_timeout_seconds,
            max_history_turns=live.config.max_history_turns,
            context_max_chars=registration.context_max_chars,
        )
        try:
            await coordinator.start()
            async with self._lock:
                if self._sessions.get(live.session_id) is not live:
                    raise RealtimeVoiceServiceError(
                        "session_closed",
                        "This Voice session has ended.",
                        409,
                    )
                live.provider_session = provider_session
                live.coordinator = coordinator
        except BaseException:
            await coordinator.close()
            raise
        return coordinator

    async def release_session(
        self,
        session_id: str,
        principal: str,
        agent_id: str,
    ) -> None:
        """Release one owned bootstrap/live session idempotently."""
        async with self._lock:
            live = self._sessions.get(session_id)
            if live is None:
                return
            if live.principal != principal or live.agent_id != agent_id:
                raise RealtimeVoiceServiceError(
                    "session_forbidden",
                    "This Voice session belongs to another owner.",
                    403,
                )
        await self.end_session(live)

    async def _close_live(self, live: LiveVoiceSession) -> None:
        if live.coordinator is not None:
            await live.coordinator.close()
            live.coordinator = None
            live.provider_session = None
        elif live.provider_session is not None:
            await live.provider_session.close()
            live.provider_session = None

    async def end_session(self, live: LiveVoiceSession) -> None:
        """Release one exact generation without disrupting a replacement."""
        async with self._lock:
            if self._sessions.get(live.session_id) is live:
                self._sessions.pop(live.session_id, None)
            if self._leases.get(live.principal) is live:
                self._leases.pop(live.principal, None)
            self._grants = {
                digest: grant
                for digest, grant in self._grants.items()
                if grant.session_id != live.session_id
            }
        await self._close_live(live)

    async def shutdown(self) -> None:
        async with self._lock:
            sessions = list(self._sessions.values())
            bridges = list(self._bridges.values())
            self._sessions.clear()
            self._leases.clear()
            self._grants.clear()
            self._bridges.clear()
        await asyncio.gather(
            *(self._close_live(live) for live in sessions),
            *(bridge.close() for bridge in bridges),
            return_exceptions=True,
        )


__all__ = [
    "LiveVoiceSession",
    "RealtimeVoiceService",
    "request_principal",
]
