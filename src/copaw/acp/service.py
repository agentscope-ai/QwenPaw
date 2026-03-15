# -*- coding: utf-8 -*-
"""High-level ACP service used by the main chat runner."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from .config import ACPConfig, ACPHarnessConfig
from .errors import ACPConfigurationError
from .permissions import ACPPermissionAdapter
from .projector import ACPEventProjector
from .runtime import ACPRuntime
from .session_store import ACPSessionStore
from .types import ACPConversationSession, ACPRunResult, AcpEvent

logger = logging.getLogger(__name__)


class ACPService:
    """Run ACP turns and manage per-chat harness sessions."""

    def __init__(self, *, config: ACPConfig):
        self.config = config
        self._store = ACPSessionStore()

    async def run_turn(
        self,
        *,
        chat_id: str,
        session_id: str,
        user_id: str,
        channel: str,
        harness: str,
        prompt_blocks: list[dict[str, Any]],
        cwd: str,
        keep_session: bool,
        existing_session_id: str | None = None,
        on_message: Callable[[Any, bool], Awaitable[None]],
    ) -> ACPRunResult:
        """Run one ACP turn and stream projected messages back to the caller."""
        harness_config = self._get_harness_config(harness)
        projector = ACPEventProjector(harness=harness)

        conversation, ephemeral = await self._get_or_create_conversation(
            chat_id=chat_id,
            harness=harness,
            cwd=cwd,
            keep_session=keep_session,
            existing_session_id=existing_session_id,
            harness_config=harness_config,
        )

        permission_adapter = ACPPermissionAdapter(cwd=conversation.cwd)

        async def _handle_event(event: AcpEvent) -> None:
            projected = projector.project(event)
            if projected:
                logger.debug("ACP service: projecting event %s -> %d messages", event.type, len(projected))
            for message, last in projected:
                logger.debug("ACP service: calling on_message for event %s, msg_id=%s, last=%s", 
                           event.type, getattr(message, 'id', '?'), last)
                await on_message(message, last)
                logger.debug("ACP service: on_message completed for event %s", event.type)

        async def _resolve_permission(payload: dict[str, Any]) -> dict[str, Any]:
            decision = await permission_adapter.resolve_permission(
                session_id=session_id,
                user_id=user_id,
                channel=channel,
                harness=harness,
                request_payload=payload,
            )
            if decision.summary:
                payload = dict(payload)
                payload["summary"] = decision.summary
            return decision.result

        try:
            await conversation.runtime.prompt(
                chat_id=chat_id,
                session_id=conversation.acp_session_id,
                prompt_blocks=prompt_blocks,
                permission_handler=_resolve_permission,
                on_event=_handle_event,
            )
        finally:
            logger.debug("ACP service: finalizing, calling projector.finalize()")
            finalized = projector.finalize()
            logger.debug("ACP service: finalize returned %d messages", len(finalized))
            for message, last in finalized:
                logger.debug("ACP service: calling on_message from finalize, msg_id=%s, last=%s",
                           getattr(message, 'id', '?'), last)
                await on_message(message, last)

            if ephemeral:
                await conversation.runtime.close()
            else:
                await self._store.save(conversation)

        return ACPRunResult(
            harness=harness,
            session_id=conversation.acp_session_id,
            keep_session=keep_session,
            cwd=conversation.cwd,
        )

    async def close_chat_session(
        self,
        *,
        chat_id: str,
        harness: str,
        reason: str,
    ) -> None:
        """Close a persisted ACP chat session."""
        logger.info("Closing ACP chat session %s/%s: %s", chat_id, harness, reason)
        existing = await self._store.delete(chat_id, harness)
        if existing is not None and existing.runtime is not None:
            await existing.runtime.close()

    async def _get_or_create_conversation(
        self,
        *,
        chat_id: str,
        harness: str,
        cwd: str,
        keep_session: bool,
        existing_session_id: str | None,
        harness_config: ACPHarnessConfig,
    ) -> tuple[ACPConversationSession, bool]:
        if keep_session:
            existing = await self._store.get(chat_id, harness)

            if existing is not None and existing.runtime is not None and existing.runtime.transport.is_running():
                existing.keep_session = True
                existing.cwd = cwd or existing.cwd
                return existing, False

            runtime = ACPRuntime(harness, harness_config)
            await runtime.start(cwd or ".")
            if existing_session_id:
                acp_session_id = await runtime.load_session(existing_session_id, cwd)
            else:
                acp_session_id = await runtime.new_session(cwd)

            session = ACPConversationSession(
                chat_id=chat_id,
                harness=harness,
                acp_session_id=acp_session_id,
                cwd=cwd,
                keep_session=True,
                capabilities=runtime.capabilities,
                runtime=runtime,
            )
            await self._store.save(session)
            return session, False

        runtime = ACPRuntime(harness, harness_config)
        await runtime.start(cwd or ".")
        if existing_session_id:
            acp_session_id = await runtime.load_session(existing_session_id, cwd)
        else:
            acp_session_id = await runtime.new_session(cwd)
        session = ACPConversationSession(
            chat_id=chat_id,
            harness=harness,
            acp_session_id=acp_session_id,
            cwd=cwd,
            keep_session=False,
            capabilities=runtime.capabilities,
            runtime=runtime,
        )
        return session, True

    def _get_harness_config(self, harness: str) -> ACPHarnessConfig:
        if not self.config.enabled:
            raise ACPConfigurationError("ACP is disabled in config")

        harness_config = self.config.harnesses.get(harness)
        if harness_config is None:
            raise ACPConfigurationError(f"Unknown ACP harness: {harness}")
        if not harness_config.enabled:
            raise ACPConfigurationError(f"ACP harness '{harness}' is disabled")
        return harness_config
