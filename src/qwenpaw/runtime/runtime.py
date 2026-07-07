# -*- coding: utf-8 -*-
"""8-phase request orchestration.

Delegates to:

* ``Envelope``       — SSE state machine
* ``AgentBuilder``   — per-request agent assembly
* ``AgentExecutor``  — heartbeat-wrapped reply stream

All insertable features live in ``LifecycleHook`` / ``AgentMode``
instances registered in the per-workspace ``HookRegistry``.  The two
fixed steps (build + execute) are the only agent-touching code.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, AsyncGenerator

from .builder import AgentBuilder
from .envelope import Envelope
from .executor import AgentExecutor
from .hooks import HookAction, HookContext
from .message_convert import _get_last_user_text, _request_input_to_msgs
from .phases import Phase

logger = logging.getLogger(__name__)


class Runtime:
    """Per-workspace request orchestrator.

    One ``Runtime`` instance per ``Workspace``.  ``run()`` is called once
    per ``AgentRequest`` and yields SSE envelope objects identical to
    what the legacy ``Runner.stream_query`` produced.
    """

    def __init__(
        self,
        *,
        workspace: Any,
        app_services: Any,
    ) -> None:
        self.workspace = workspace
        self.app_services = app_services

    async def run(  # pylint: disable=too-many-branches,too-many-statements
        self,
        request: Any,
    ) -> AsyncGenerator[Any, None]:
        """8-phase lifecycle orchestration."""
        request = self._normalize(request)
        ctx = self._build_context(request)
        hooks = self.workspace.plugins.hook_registry

        envelope = Envelope(session_id=ctx.session_id)
        skip_agent = False

        try:
            # --- [phase 1] PRE_DISPATCH ---
            r = await hooks.run(Phase.PRE_DISPATCH, ctx)
            if r.action == HookAction.SHORT_CIRCUIT:
                async for ev in envelope.from_msg(r.payload):
                    yield ev
                return
            if r.action == HookAction.SKIP_AGENT:
                skip_agent = True

            # --- [fixed 1] slash command dispatch ---
            text = _get_last_user_text(ctx.input_msgs)
            cmd_registry = self.workspace.plugins.slash_command_registry
            cmd_msg = await cmd_registry.dispatch(text or "", ctx)
            if cmd_msg is not None:
                async for ev in envelope.from_msg(cmd_msg):
                    yield ev
                skip_agent = True
            else:
                # --- [phase 2] POST_DISPATCH ---
                r = await hooks.run(Phase.POST_DISPATCH, ctx)
                if r.action == HookAction.SHORT_CIRCUIT:
                    async for ev in envelope.from_msg(r.payload):
                        yield ev
                    skip_agent = True
                elif r.action == HookAction.SKIP_AGENT:
                    skip_agent = True

            if not skip_agent:
                # --- [phase 3] PRE_AGENT_BUILD ---
                r = await hooks.run(Phase.PRE_AGENT_BUILD, ctx)
                if r.action == HookAction.SHORT_CIRCUIT:
                    async for ev in envelope.from_msg(r.payload):
                        yield ev
                    skip_agent = True
                elif r.action == HookAction.SKIP_AGENT:
                    skip_agent = True

            if not skip_agent:
                # --- [fixed 2] build agent ---
                builder = AgentBuilder(
                    app_services=self.app_services,
                )
                ctx.agent = await builder.build(ctx)

                # --- [phase 4] POST_AGENT_BUILD ---
                await hooks.run(Phase.POST_AGENT_BUILD, ctx)

                # --- [phase 5] PRE_EXECUTE ---
                r = await hooks.run(Phase.PRE_EXECUTE, ctx)
                if r.action == HookAction.SHORT_CIRCUIT:
                    async for ev in envelope.from_msg(r.payload):
                        yield ev
                    skip_agent = True
                elif r.action == HookAction.SKIP_AGENT:
                    skip_agent = True

            if not skip_agent:
                self._apply_context_injections(ctx)
                # --- [fixed 3] execute agent ---
                async for ev in envelope.emit_response_created():
                    yield ev
                executor = AgentExecutor(ctx.agent, envelope)
                logger.debug(
                    "Agent input: %s",
                    _get_last_user_text(
                        ctx.input_msgs,
                    )
                    or "(empty)",
                )
                async for ev in executor.run(ctx.input_msgs):
                    yield ev

            # --- [phase 6] POST_RESPONSE ---
            await hooks.run(Phase.POST_RESPONSE, ctx)

            # Finalize envelope (complete message + response).
            async for ev in envelope.finalize():
                yield ev

        except (asyncio.CancelledError, KeyboardInterrupt) as e:
            ctx.error = e
            # The Task's _must_cancel flag may still be True after
            # catching CancelledError, causing the next await to raise
            # CancelledError again.  Wrap ON_ERROR hooks so that
            # cancel_envelope is always yielded — the frontend SDK
            # needs the {object:response, status:completed} event to
            # exit loading state.
            try:
                await hooks.run(Phase.ON_ERROR, ctx)
            except asyncio.CancelledError:
                logger.debug(
                    "ON_ERROR hooks skipped due to asyncio "
                    "re-cancellation (session=%s)",
                    getattr(ctx, "session_id", ""),
                )
            async for ev in envelope.cancel_envelope():
                yield ev
            raise
        except BaseException as e:
            ctx.error = e
            logger.error(
                "runtime: unhandled error session=%s: %s",
                getattr(ctx, "session_id", ""),
                e,
                exc_info=True,
            )
            await hooks.run(Phase.ON_ERROR, ctx)
            err_text = ctx.extras.get(
                "_error_text",
                str(e) or e.__class__.__name__,
            )
            async for ev in envelope.error_envelope(err_text):
                yield ev
            raise
        finally:
            # Close agent first so governor can flush audit log and persist
            # policy before downstream FINALLY hooks observe the context.
            # See ``QwenPawAgent.close`` (agents/react_agent.py).
            agent = getattr(ctx, "agent", None)
            if agent is not None and hasattr(agent, "close"):
                try:
                    await agent.close()
                except Exception:  # pylint: disable=broad-except
                    logger.warning(
                        "runtime: agent.close() failed session=%s",
                        getattr(ctx, "session_id", ""),
                        exc_info=True,
                    )
            await hooks.run(Phase.FINALLY, ctx)

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _normalize(request: Any) -> Any:
        from ..schemas import AgentRequest

        if isinstance(request, dict):
            request = AgentRequest(**request)
        if not getattr(request, "session_id", None):
            request.session_id = uuid.uuid4().hex
        if not getattr(request, "user_id", None):
            request.user_id = request.session_id
        return request

    def _build_context(self, request: Any) -> HookContext:
        workspace_dir = getattr(self.workspace, "workspace_dir", None)
        # Prefer the workspace's resolved agent id over a bare "default", so an
        # agent selected by header (no body agent_id) loads its own config.
        agent_id = (
            getattr(request, "agent_id", None)
            or getattr(self.workspace, "agent_id", None)
            or "default"
        )
        session_id = request.session_id
        root_session_id = getattr(request, "root_session_id", "") or session_id
        root_agent_id = getattr(request, "root_agent_id", "") or agent_id

        return HookContext(
            request=request,
            session_id=session_id,
            agent_id=agent_id,
            root_session_id=root_session_id,
            root_agent_id=root_agent_id,
            workspace_dir=workspace_dir,
            workspace=self.workspace,
            app_services=self.app_services,
            input_msgs=_request_input_to_msgs(request.input),
        )

    @staticmethod
    def _apply_context_injections(ctx: HookContext) -> None:
        """Merge context_injections into input_msgs as a system hint.

        Sorts injections by priority (ascending) and prepends a
        single system-role message so the agent sees the dynamic
        context in its current turn.
        """
        injections = ctx.context_injections
        if not injections:
            return
        sorted_inj = sorted(
            injections,
            key=lambda x: x.get("priority", 100),
        )
        parts = [inj["content"] for inj in sorted_inj if inj.get("content")]
        if not parts:
            return
        try:
            from agentscope.message import Msg, TextBlock

            hint_msg = Msg(
                name="system",
                role="system",
                content=[
                    TextBlock(
                        type="text",
                        text="\n\n".join(parts),
                    ),
                ],
            )
            ctx.input_msgs.insert(0, hint_msg)
        except Exception:
            logger.debug(
                "runtime: failed to inject context: %d items",
                len(parts),
            )


__all__ = ["Runtime"]
