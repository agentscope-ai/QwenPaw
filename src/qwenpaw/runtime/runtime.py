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
        ctx._envelope = envelope  # pylint: disable=protected-access
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
                await self._start_modes(ctx)

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

            # Persist agent state so the interrupted turn is not lost.
            # asyncio.shield protects the save from task re-cancellation.
            await self._try_save_on_cancel(ctx)

            async for ev in envelope.cancel_envelope():
                yield ev
            raise
        except BaseException as e:
            await self._try_save_on_cancel(ctx)

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
            err_code = ctx.extras.get(
                "_error_code",
                e.__class__.__name__,
            )
            async for ev in envelope.error_envelope(
                err_text,
                err_code,
            ):
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

    async def _start_modes(self, ctx: HookContext) -> None:
        """Prepare every registered mode for the current user turn."""
        for mode in self.workspace.plugins.modes:
            try:
                await mode.on_turn_start(ctx)
            except Exception:
                logger.warning(
                    "mode '%s' turn start raised",
                    getattr(mode, "name", "?"),
                    exc_info=True,
                )

    async def _try_save_on_cancel(self, ctx: HookContext) -> None:
        """Best-effort session save on cancellation.

        Before snapshotting, any partial streaming content accumulated in
        the ``Envelope`` is injected into the agent's context so the
        interrupted turn's text is not lost on reload.

        ``state_dict()`` is called synchronously to snapshot the agent
        state *before* any further event-loop iteration.  The I/O write
        is wrapped in ``asyncio.shield`` so it completes even when the
        outer task's ``_must_cancel`` flag triggers a re-cancellation on
        the next ``await``.  In that case the shielded inner task still
        runs to completion in the background; the ``proxy`` owns an
        independent copy of the data so ``agent.close()`` in the
        ``finally`` block cannot corrupt it.

        .. note:: Why hardcoded instead of a hook?

           This runs *outside* the ``try/except`` that wraps
           ``hooks.run(Phase.ON_ERROR)``, so it executes even when
           re-cancellation skips all ON_ERROR hooks.  The synchronous
           parts (inject + state_dict) complete before any ``await``,
           and ``asyncio.shield`` protects the I/O — guarantees that a
           generic hook framework cannot provide.

        TODO: Currently only ``SessionSaveHook`` has a cancel-path
         equivalent here.  Other ``POST_RESPONSE`` hooks (e.g.
         ``CronMemoryRestoreHook``) and plugin-registered hooks are
         skipped on /stop.  A future improvement should unify the
         cancel and normal paths — e.g. via a dedicated ``ON_CANCEL``
         phase with per-hook shield execution — so plugins can
         participate in the cancel lifecycle.  ``ctx._envelope`` should
         also be promoted to a first-class ``HookContext`` field.
        """
        agent = getattr(ctx, "agent", None)
        if agent is None:
            return
        workspace = getattr(ctx, "workspace", None)
        session = getattr(workspace, "session", None) if workspace else None
        if session is None:
            return
        try:
            envelope = getattr(ctx, "_envelope", None)
            if envelope is not None:
                self._inject_partial_response(agent, envelope)

            from ._state_utils import StateProxy

            proxy = StateProxy()
            proxy.data = agent.state_dict()
            request = ctx.request
            user_id = getattr(request, "user_id", "") or ctx.session_id
            channel = getattr(request, "channel", "") or ""
            await asyncio.shield(
                session.save_session_state(
                    session_id=ctx.session_id,
                    user_id=user_id,
                    channel=channel,
                    agent=proxy,
                ),
            )
            logger.info(
                "cancel-save: persisted interrupted turn (session=%s)",
                ctx.session_id,
            )
        except asyncio.CancelledError:
            logger.info(
                "cancel-save: outer await re-cancelled, inner save "
                "continues in background (session=%s)",
                ctx.session_id,
            )
        except Exception:
            logger.debug(
                "cancel-save: failed (session=%s)",
                ctx.session_id,
                exc_info=True,
            )

    # pylint: disable=too-many-branches
    @staticmethod
    def _inject_partial_response(agent: Any, envelope: Any) -> None:
        """Inject accumulated streaming content from *envelope* into the
        agent's context so a cancel-save includes the partial response.

        Two responsibilities:

        1. **Partial text/thinking** — uses ``Envelope.collect_partial_blocks``
           to obtain content from the *interrupted* reasoning iteration, with
           a deduplication guard against double-saving.

        2. **Dangling tool calls** — AgentScope's
           ``_close_unfinished_tool_calls`` normally patches the context in a
           ``finally`` block, but its ``yield`` statements fail when the
           generator is being closed.  We replicate the context-mutation logic
           here (without yields) so that every tool call has a matching
           ``ToolResultBlock`` on reload.
        """
        # pylint: disable=too-many-nested-blocks
        try:
            from agentscope.message import TextBlock, ThinkingBlock

            # --- 1) Partial text/thinking injection ---
            partial = envelope.collect_partial_blocks()
            injected = 0

            if partial:
                agent_state = getattr(agent, "state", None)
                ctx_list = (
                    getattr(agent_state, "context", None)
                    if agent_state
                    else None
                )
                existing_texts: set[str] = set()
                if ctx_list and len(ctx_list) > 0:
                    last = ctx_list[-1]
                    if getattr(last, "role", None) == "assistant":
                        for blk in getattr(last, "content", []) or []:
                            if getattr(blk, "type", None) == "text":
                                existing_texts.add(
                                    getattr(blk, "text", ""),
                                )
                            elif getattr(blk, "type", None) == "thinking":
                                existing_texts.add(
                                    getattr(blk, "thinking", ""),
                                )

                blocks: list = []
                for btype, content in partial:
                    if content in existing_texts:
                        continue
                    if btype == "thinking":
                        blocks.append(ThinkingBlock(thinking=content))
                    else:
                        blocks.append(TextBlock(text=content))
                if blocks:
                    # pylint: disable=protected-access
                    agent._save_to_context(blocks)
                injected = len(blocks)

            # --- 2) Close dangling tool calls ---
            closed = Runtime._close_dangling_tool_calls(agent, envelope)

            if injected or closed:
                logger.info(
                    "cancel-save: injected %d partial block(s), "
                    "closed %d dangling tool call(s)",
                    injected,
                    closed,
                )
        except Exception:
            logger.debug(
                "cancel-save: partial response injection failed",
                exc_info=True,
            )

    @staticmethod
    def _close_dangling_tool_calls(agent: Any, envelope: Any) -> int:
        """Ensure every ``ToolCallBlock`` in the context has a matching
        ``ToolResultBlock``.

        AgentScope's ``_close_unfinished_tool_calls`` patches the context
        inside a generator ``finally`` block, but its ``yield`` statements
        trigger ``RuntimeError`` when the generator is being torn down.
        We replicate the mutation-only logic so dangling tool calls are
        properly closed before ``state_dict()`` is called.

        Returns the number of tool calls closed.
        """
        from agentscope.message import (
            ToolCallBlock,
            ToolCallState,
            ToolResultBlock,
            ToolResultState,
        )

        state = getattr(agent, "state", None)
        context = getattr(state, "context", None) if state else None
        if not context:
            return 0

        last_msg = context[-1]
        if getattr(last_msg, "role", None) != "assistant":
            return 0
        if getattr(last_msg, "name", None) != getattr(agent, "name", ""):
            return 0

        content = getattr(last_msg, "content", None)
        if not isinstance(content, list):
            return 0

        # Find tool calls without matching results.
        awaiting: dict[str, int] = {}
        for idx, block in enumerate(content):
            if isinstance(block, ToolCallBlock):
                awaiting[block.id] = idx
            elif isinstance(block, ToolResultBlock):
                awaiting.pop(block.id, None)

        if not awaiting:
            return 0

        # Incorporate any partial output accumulated in the envelope.
        envelope_tool_output = envelope.collect_tool_output()

        interruption_msg = (
            "<system-reminder>The tool call has been interrupted by "
            "the user.</system-reminder>"
        )

        closed = 0
        for call_id, idx in awaiting.items():
            block = content[idx]
            block.state = ToolCallState.FINISHED

            output = envelope_tool_output.get(call_id, "")
            if output:
                output += "\n" + interruption_msg
            else:
                output = interruption_msg

            content.append(
                ToolResultBlock(
                    id=call_id,
                    name=block.name,
                    output=output,
                    state=ToolResultState.INTERRUPTED,
                ),
            )
            closed += 1

        return closed

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
