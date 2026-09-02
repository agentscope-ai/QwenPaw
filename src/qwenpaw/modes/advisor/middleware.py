# -*- coding: utf-8 -*-
"""``AdvisorMiddleware`` — the teacher plans up front, steps in when the
agent gets stuck, and answers when the agent asks.

Three behaviours, all injected into the agent's context as a tool call +
result pair so the agent reads them as something it asked for:

1. **Plan injection.** On the first model call of a conversation the
   teacher is asked for a strategic plan for the task. The agent then
   sees::

       [system prompt]
       [user: task instruction]
       [assistant: consult_advisor(...)]         ← injected
       [tool_result: advisor plan]               ← injected
       [assistant: first real action]            ← model continues here

2. **Mid-run intervention.** Every later model call feeds the tool results
   that accumulated in context to :class:`InterventionTrigger`. When the
   agent is stuck (repeated failures) the teacher is consulted again with
   the recent calls and answers CONTINUE or ADJUST; only an ADJUST body is
   injected, as a ``consult_advisor_followup`` pair.

3. **On-demand consultation.** :meth:`consult` answers a question the
   agent asks through the real ``consult_advisor`` tool (see
   ``tools.py``), with the same teacher and the recent calls attached.

The teacher conversation (``teacher_history``) is shared across the turns
of one chat session, so every request is answered in light of the plan
and advice already given. The plan is written once per conversation:
later user turns rely on the mid-run intervention and on the agent's own
questions, which always carry the current task.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from agentscope.message import (
    AssistantMsg,
    Msg,
    ToolCallBlock,
    ToolCallState,
    ToolResultBlock,
    ToolResultState,
)
from agentscope.middleware import MiddlewareBase

from .prompts import (
    ADVISOR_SYSTEM_PROMPT,
    CONSULT_REQUEST_TEMPLATE,
    ENV_SECTION_HEADER,
    FOLLOWUP_REQUEST_TEMPLATE,
    PLAN_REQUEST_TEMPLATE,
    SEVERITY_NOTES,
    TRIGGER_NOTES,
)
from .trigger import InterventionTrigger, ObservedStep, TriggerEvent

if TYPE_CHECKING:
    from agentscope.agent import Agent

    from .teacher import AdvisorTeacher

logger = logging.getLogger(__name__)

# Names of the injected pseudo tool calls. ``PLAN_TOOL_NAME`` is also the
# name of the real on-demand tool, so the opening plan reads as an earlier
# call of the same tool.
PLAN_TOOL_NAME = "consult_advisor"
FOLLOWUP_TOOL_NAME = "consult_advisor_followup"

# Tool output can be tens of KB; the teacher only needs enough to judge.
_MAX_OUTPUT_CHARS = 800
_MAX_ARGS_CHARS = 300

# The plan is the whole point of advisor mode, so a failed call is retried
# rather than silently skipped.
_PLAN_ATTEMPTS = 3
_PLAN_RETRY_DELAY_S = 2.0

_CONTINUE = "CONTINUE"
_ADJUST = "ADJUST"
# Re-ask the same question when the verdict line is missing.
_FOLLOWUP_FORMAT_ATTEMPTS = 3

# Default on-demand budget per conversation.
DEFAULT_MAX_CONSULTS = 32
CONSULT_BUDGET_EXHAUSTED = (
    "The advisor is not available for further consultation in this "
    "conversation. Decide with your own best judgment and keep going."
)

# What the agent sees as the arguments of the injected calls. The real
# requests are large (the plan request carries the tool list, environment
# context and planning guidelines; the follow-up carries the agent's own
# failures). Echoing them back would double the context cost and re-show
# the errors verbatim. A fixed stand-in keeps each call short and identical
# every time.
_PLAN_CALL_ARGS = {
    "question": "Before I start, how should I approach this task?",
}
_FOLLOWUP_CALL_ARGS = {
    "question": "My recent steps keep failing. What should I do instead?",
}

# Workspace listing handed to the teacher as environment context.
_LISTING_MAX_ENTRIES = 150
_LISTING_MAX_DEPTH = 2
_LISTING_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".qwenpaw",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".idea",
        ".vscode",
    },
)

# Tools irrelevant for task planning — excluded from the teacher's view.
_EXCLUDED_TOOLS = frozenset(
    {
        "list_agents",
        "chat_with_agent",
        "submit_to_agent",
        "check_agent_task",
        "set_user_timezone",
        "get_token_usage",
        "send_file_to_user",
        "spawn_subagent",
        "delegate_external_agent",
    },
)


def _block_get(block: Any, key: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _result_text(block: Any) -> str:
    """Flatten a tool_result's output, which may be a string or
    TextBlocks."""
    out = _block_get(block, "output")
    if isinstance(out, str):
        return out
    if isinstance(out, list):
        parts = []
        for item in out:
            text = _block_get(item, "text")
            if text:
                parts.append(str(text))
        return "\n".join(parts)
    return "" if out is None else str(out)


def _clip(text: str, limit: int) -> str:
    """Keep both ends — the command and the error usually sit at opposite
    ends."""
    text = text or ""
    if len(text) <= limit:
        return text
    head = limit * 2 // 3
    tail = limit - head
    omitted = len(text) - limit
    return f"{text[:head]}\n  … [{omitted} chars omitted] …\n{text[-tail:]}"


def _parse_followup(reply: str) -> tuple[str, str]:
    """Split a follow-up reply into its verdict and the advice below it.

    The teacher is asked to put CONTINUE or ADJUST alone on the first line.
    Leading blank lines and markdown emphasis around the word are tolerated,
    since models add those readily; anything else counts as unparseable and
    returns ``("", "")`` so the caller can re-ask.
    """
    lines = (reply or "").strip().splitlines()
    if not lines:
        return "", ""
    head = lines[0].strip().strip("*_# ").rstrip(":.-—– ").upper()
    for verdict in (_CONTINUE, _ADJUST):
        if head == verdict:
            return verdict, "\n".join(lines[1:]).strip()
    return "", ""


def _format_recent(recent: list[ObservedStep]) -> str:
    if not recent:
        return "(no recent calls recorded)"
    lines = []
    for i, step in enumerate(recent, 1):
        try:
            args = json.dumps(step.args, ensure_ascii=False, default=str)
        except Exception:
            args = str(step.args)
        status = "FAILED" if step.failed else "ok"
        lines.append(
            f"{i}. {step.tool}({_clip(args, _MAX_ARGS_CHARS)}) -> {status}\n"
            f"   {_clip(step.output, _MAX_OUTPUT_CHARS)}",
        )
    return "\n\n".join(lines)


def _workspace_listing(
    root: Path | str | None,
    *,
    max_entries: int = _LISTING_MAX_ENTRIES,
    max_depth: int = _LISTING_MAX_DEPTH,
) -> str:
    """A shallow, size-annotated listing of ``root`` for the teacher.

    One line per entry — ``path size`` for files, ``path/`` for
    directories — sorted, hidden/vendor directories skipped, capped at
    ``max_entries`` so a huge tree cannot blow up the plan request.
    """
    if not root:
        return ""
    try:
        base = Path(root).expanduser()
        if not base.is_dir():
            return ""
    except Exception:
        return ""

    lines: list[str] = []
    truncated = False

    def walk(directory: Path, depth: int) -> None:
        nonlocal truncated
        if truncated:
            return
        try:
            entries = sorted(
                directory.iterdir(),
                key=lambda p: (not p.is_dir(), p.name.lower()),
            )
        except Exception:
            return
        for entry in entries:
            if len(lines) >= max_entries:
                truncated = True
                return
            rel = entry.relative_to(base).as_posix()
            if entry.is_dir():
                if entry.name in _LISTING_SKIP_DIRS:
                    continue
                lines.append(f"{rel}/")
                if depth + 1 < max_depth:
                    walk(entry, depth + 1)
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                lines.append(f"{rel} {size}")

    walk(base, 0)
    if truncated:
        lines.append(f"… (listing capped at {max_entries} entries)")
    return "\n".join(lines)


def _new_call_id() -> str:
    return uuid.uuid4().hex[:12]


def _exchange_msg(
    agent_name: str,
    tool: str,
    args: dict,
    body: str,
    call_id: str | None = None,
) -> Msg:
    """Build the injected tool call + result pair as one assistant message.

    This mirrors how AgentScope 2.x records a finished tool call: the
    ``ToolCallBlock`` and its ``ToolResultBlock`` share an id and live in
    the same assistant message.
    """
    call_id = call_id or _new_call_id()
    return AssistantMsg(
        name=agent_name,
        content=[
            ToolCallBlock(
                id=call_id,
                name=tool,
                input=json.dumps(args),
                state=ToolCallState.FINISHED,
            ),
            ToolResultBlock(
                id=call_id,
                name=tool,
                output=body,
                state=ToolResultState.SUCCESS,
            ),
        ],
    )


class _LiveExchange:
    """One injected exchange shown in the UI while the teacher is talking.

    The tool call is opened the moment the teacher is asked, the reply is
    relayed as it streams in and the call is closed once the answer (or
    the failure) is in — so the user watches the plan being written
    instead of a spinner. Agents without the live hooks (plain AgentScope
    agents, test doubles) leave ``active`` False and every update is a
    no-op; the exchange still lands in their context.
    """

    def __init__(
        self,
        agent: Any,
        call_id: str,
        tool: str,
        args: dict,
    ) -> None:
        self._agent = agent
        self.call_id = call_id
        self._sent = ""
        self.active = False
        begin = getattr(agent, "begin_injected_exchange", None)
        if not callable(begin):
            return
        try:
            begin(call_id=call_id, name=tool, arguments=json.dumps(args))
            self.active = True
        except Exception:
            logger.debug(
                "AdvisorMiddleware: could not open the live exchange",
                exc_info=True,
            )

    def _emit(self, method: str, **kwargs: Any) -> None:
        fn = getattr(self._agent, method, None)
        if not callable(fn):
            return
        try:
            fn(call_id=self.call_id, **kwargs)
        except Exception:
            logger.debug(
                "AdvisorMiddleware: live exchange update failed",
                exc_info=True,
            )

    def on_text(self, text: str) -> None:
        """Relay the cumulative teacher reply ``text`` as a delta."""
        if not self.active or not text.startswith(self._sent):
            return
        delta = text[len(self._sent) :]
        if not delta:
            return
        self._sent = text
        self._emit("stream_injected_output", delta=delta)

    def note(self, text: str) -> None:
        """Append a harness note (a retry, say) and start a fresh reply."""
        if not self.active:
            return
        prefix = "\n\n" if self._sent else ""
        self._emit("stream_injected_output", delta=f"{prefix}{text}\n\n")
        self._sent = ""

    def finish(self, output: str) -> None:
        """Close the exchange, first sending any tail of ``output`` the
        stream never delivered."""
        if not self.active:
            return
        self.on_text(output)
        self._emit("finish_injected_exchange", state=ToolResultState.SUCCESS)
        self.active = False

    def fail(self, message: str) -> None:
        """Close the exchange as failed, with ``message`` as the output."""
        if not self.active:
            return
        prefix = "\n\n" if self._sent else ""
        self._emit("stream_injected_output", delta=f"{prefix}{message}")
        self._emit("finish_injected_exchange", state=ToolResultState.ERROR)
        self.active = False


# pylint: disable=too-many-instance-attributes
class AdvisorMiddleware(MiddlewareBase):
    """Inject an advisor plan up front, again when the agent gets stuck,
    and answer the agent's own questions."""

    def __init__(
        self,
        *,
        teacher: "AdvisorTeacher",
        followup_enabled: bool = True,
        trigger: InterventionTrigger | None = None,
        env_context_root: Path | str | None = None,
        log_dir: Path | str | None = None,
        session_id: str = "",
        agent_id: str = "",
        teacher_history: list[dict[str, str]] | None = None,
        plan_enabled: bool = True,
        on_demand_enabled: bool = True,
        max_consults: int = DEFAULT_MAX_CONSULTS,
        consults_used: int = 0,
        plan_injected: bool = False,
    ) -> None:
        self._teacher = teacher
        self._followup_enabled = followup_enabled
        self._plan_enabled = plan_enabled
        self._on_demand_enabled = on_demand_enabled
        # The latest user instruction, kept for follow-up and consult
        # requests so they stay self-contained even without an opening
        # plan in the teacher history.
        self._task = ""
        self._trigger = trigger or InterventionTrigger()
        self._env_context_root = env_context_root
        self._log_dir = Path(log_dir) if log_dir else None
        self._session_id = session_id
        self._agent_id = agent_id
        self._max_consults = max(0, int(max_consults))
        self._consults_used = max(0, int(consults_used))

        # True when an earlier request of the same conversation already
        # put the plan in context: this request then skips the opening
        # plan and goes straight to watching the agent.
        self._plan_injected = plan_injected
        # Set when every plan attempt failed, so the run can report that it
        # went ahead without one instead of looking like a normal advisor
        # run.
        self._plan_error: str | None = None
        # The teacher conversation. Shared with the other requests of the
        # same chat session when the caller passes the session's list, so
        # follow-ups keep earlier plans in view.
        self._teacher_history: list[dict[str, str]] = (
            teacher_history if teacher_history is not None else []
        )
        # tool_result block ids already fed to the trigger.
        self._seen_result_ids: set[str] = set()
        self._baselined = False
        # Everything said to / by the teacher, persisted for analysis.
        self._transcript: dict[str, Any] = {
            "agent_id": agent_id,
            "session_id": session_id,
            "teacher": getattr(teacher, "label", ""),
            "plan": None,
            "interventions": [],
            "consults": [],
        }

    # ── properties ──────────────────────────────────────────────────────

    @property
    def plan_injected(self) -> bool:
        """Whether the opening plan has reached the agent's context."""
        return self._plan_injected

    @property
    def plan_error(self) -> str | None:
        """The last error when every plan attempt failed, else ``None``."""
        return self._plan_error

    @property
    def followup_enabled(self) -> bool:
        """Whether mid-run intervention is on."""
        return self._followup_enabled

    @property
    def plan_enabled(self) -> bool:
        """Whether a plan is requested before the first step."""
        return self._plan_enabled

    @property
    def on_demand_enabled(self) -> bool:
        """Whether the agent may ask through ``consult_advisor``."""
        return self._on_demand_enabled

    @property
    def interventions(self) -> list[dict[str, Any]]:
        """Mid-run interventions recorded so far."""
        return list(self._transcript["interventions"])

    @property
    def consults(self) -> list[dict[str, Any]]:
        """On-demand consultations recorded so far."""
        return list(self._transcript["consults"])

    @property
    def consults_used(self) -> int:
        """How many on-demand consultations have been spent."""
        return self._consults_used

    @property
    def consults_left(self) -> int:
        """How many on-demand consultations remain."""
        return max(0, self._max_consults - self._consults_used)

    @property
    def teacher_history(self) -> list[dict[str, str]]:
        """The shared teacher conversation (same list object)."""
        return self._teacher_history

    # ── middleware hook ─────────────────────────────────────────────────

    async def on_model_call(
        self,
        agent: "Agent",
        input_kwargs: dict[str, Any],
        next_handler: Callable[..., Any],
    ) -> Any:
        injected: Msg | None = None
        if not self._baselined:
            # Results that were already in the context when this request
            # started belong to earlier turns: never count them towards an
            # intervention now.
            self._mark_existing_results_seen(agent.state.context)
            self._baselined = True
        self._task = (
            self._extract_instruction(agent.state.context) or self._task
        )
        if not self._plan_injected and self._plan_enabled:
            # Only consume the flag once a plan is actually in context.
            # Setting it first meant a rejected teacher call silently
            # downgraded the run to a plain run, with no retry on this or
            # any later step.
            injected = await self._inject_plan(
                agent,
                tools=input_kwargs.get("tools"),
            )
            self._plan_injected = injected is not None
        elif self._followup_enabled:
            # Tool results reach the context between model calls, so this
            # is where new ones show up. Deliberately NOT the on_acting
            # hook: that wraps raw tool execution only, and schema-
            # validation failures (e.g. write_file called with no
            # ``content``) are raised before it, so on_acting never sees
            # the very loop we most want to break.
            injected = await self._check_and_intervene(agent)
        else:
            # Keep the recent-steps window current for on-demand consults
            # even when automatic intervention is switched off.
            self._consume_new_results(agent.state.context)

        if injected is not None:
            # ``messages`` was assembled from the context *before* this hook
            # ran (``Agent._prepare_model_input``), so appending to the
            # context alone would only reach the *next* call. Make the new
            # exchange visible to the call in flight as well.
            messages = list(input_kwargs.get("messages") or [])
            if not any(m is injected for m in messages):
                messages.append(injected)
            input_kwargs["messages"] = messages
        return await next_handler(**input_kwargs)

    # ── on-demand consultation ──────────────────────────────────────────

    async def consult(
        self,
        question: str,
        on_text: Callable[[str], None] | None = None,
    ) -> str:
        """Answer a question the agent asked through ``consult_advisor``.

        The reply is returned to the agent as the tool result (the toolkit
        records it in context, so nothing is injected here). Consultations
        are capped per conversation; past the cap a fixed notice is
        returned instead of a teacher call. ``on_text`` receives the
        cumulative reply while the teacher is still writing it.
        """
        question = (question or "").strip()
        if not question:
            return "Ask the advisor a concrete question about your approach."
        if self.consults_left <= 0:
            logger.info(
                "AdvisorMiddleware: consult budget exhausted (%d/%d)",
                self._consults_used,
                self._max_consults,
            )
            return CONSULT_BUDGET_EXHAUSTED

        self._consults_used += 1
        request = CONSULT_REQUEST_TEMPLATE.format(
            task=self._task or "(not available)",
            index=self._consults_used,
            max_consults=self._max_consults,
            question=question,
            recent_calls=_format_recent(self._trigger.recent),
        )
        record: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "index": self._consults_used,
            "question": question,
            "request": request,
        }
        try:
            reply = await self._call_teacher(
                request,
                stateful=True,
                on_text=on_text,
            )
        except Exception as exc:
            logger.error(
                "AdvisorMiddleware: on-demand teacher call failed: %s",
                exc,
            )
            record["error"] = str(exc)
            self._record_consult(record)
            return (
                "The advisor could not be reached right now. Decide with "
                "your own best judgment and keep going."
            )
        record["reply"] = reply
        self._record_consult(record)
        # The agent just asked; do not count the same run of failures
        # towards an automatic intervention on top of that.
        self._trigger.reset_counters()
        logger.info(
            "AdvisorMiddleware: on-demand consultation %d/%d answered "
            "(%d chars)",
            self._consults_used,
            self._max_consults,
            len(reply),
        )
        return reply.strip() or "(the advisor had nothing to add)"

    async def consult_stream(self, question: str) -> AsyncIterator[str]:
        """:meth:`consult`, delivered as text deltas while the teacher
        writes, so the ``consult_advisor`` tool can stream its result.

        Yields the pieces of the reply in order; joined, they equal the
        text :meth:`consult` returns (a notice — budget exhausted, teacher
        unreachable — arrives as one piece).
        """
        deltas: asyncio.Queue[str] = asyncio.Queue()
        sent = ""

        def on_text(text: str) -> None:
            nonlocal sent
            if text.startswith(sent) and len(text) > len(sent):
                deltas.put_nowait(text[len(sent) :])
                sent = text

        task = asyncio.ensure_future(self.consult(question, on_text=on_text))
        try:
            while not task.done():
                try:
                    yield await asyncio.wait_for(deltas.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue
            while not deltas.empty():
                yield deltas.get_nowait()
            reply = task.result()
            # Whatever the stream did not carry: the final text when the
            # teacher did not stream, or a notice instead of a reply.
            if reply.startswith(sent):
                tail = reply[len(sent) :]
            else:
                tail = "" if sent else reply
            if tail:
                yield tail
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task

    # ── mid-run intervention ────────────────────────────────────────────

    async def _check_and_intervene(self, agent: "Agent") -> Msg | None:
        """Feed new tool results to the trigger; consult the teacher if
        stuck. Returns the injected message, if any."""
        try:
            event = self._consume_new_results(agent.state.context)
        except Exception as exc:  # never break the agent over bookkeeping
            logger.warning("AdvisorMiddleware: trigger scan failed: %s", exc)
            return None
        if event is None:
            return None
        logger.info(
            "AdvisorMiddleware: intervention %d triggered (%s, %s) "
            "at step %d",
            event.intervention_index,
            event.reason,
            event.severity,
            event.step_index,
        )
        return await self._inject_followup(agent, event)

    def _mark_existing_results_seen(self, context: list[Msg]) -> None:
        """Remember every tool_result id already present in ``context``."""
        for msg in context:
            content = getattr(msg, "content", None)
            if not isinstance(content, list):
                continue
            for block in content:
                if _block_get(block, "type") == "tool_result":
                    bid = _block_get(block, "id") or ""
                    if bid:
                        self._seen_result_ids.add(bid)

    def _consume_new_results(
        self,
        context: list[Msg],
    ) -> TriggerEvent | None:
        """Feed tool results not yet seen to the trigger, oldest first.

        Returns the first event raised, or None. Tool call arguments are
        matched to their result by shared block id so the trigger can tell
        a repeated identical call from varied ones.
        """
        args_by_id: dict[str, Any] = {}
        pending: list[tuple[str, str, Any, str]] = []
        for msg in context:
            content = getattr(msg, "content", None)
            if not isinstance(content, list):
                continue
            for block in content:
                btype = _block_get(block, "type")
                bid = _block_get(block, "id") or ""
                if btype == "tool_call":
                    raw = _block_get(block, "input")
                    try:
                        args_by_id[bid] = (
                            json.loads(raw) if isinstance(raw, str) else raw
                        )
                    except Exception:
                        args_by_id[bid] = raw
                elif btype == "tool_result":
                    if bid and bid in self._seen_result_ids:
                        continue
                    name = _block_get(block, "name") or "unknown"
                    # Never let the advisor's own answers (injected or via
                    # the real tool) look like a failure.
                    if name.startswith(PLAN_TOOL_NAME):
                        if bid:
                            self._seen_result_ids.add(bid)
                        continue
                    pending.append(
                        (bid, name, args_by_id.get(bid), _result_text(block)),
                    )

        event = None
        for bid, name, args, output in pending:
            if bid:
                self._seen_result_ids.add(bid)
            if event is not None:
                continue  # keep marking as seen, but only fire once per call
            event = self._trigger.observe(name, args, output)
        return event

    async def _inject_followup(
        self,
        agent: "Agent",
        event: TriggerEvent,
    ) -> Msg | None:
        request = FOLLOWUP_REQUEST_TEMPLATE.format(
            task=self._task or "(not available)",
            index=event.intervention_index,
            max_interventions=self._trigger.config.max_interventions,
            recent_calls=_format_recent(event.recent),
            trigger_note=TRIGGER_NOTES.get(event.reason, event.reason),
            severity_note=SEVERITY_NOTES.get(event.severity, ""),
        )
        record: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "index": event.intervention_index,
            "reason": event.reason,
            "severity": event.severity,
            "step_index": event.step_index,
            "request": request,
        }
        advice = ""
        action = ""
        body = ""
        # Shown live like the plan. A CONTINUE verdict adds nothing to the
        # agent's context, but the user still sees that the advisor was
        # consulted and what it said.
        call_id = _new_call_id()
        live = _LiveExchange(
            agent,
            call_id,
            FOLLOWUP_TOOL_NAME,
            _FOLLOWUP_CALL_ARGS,
        )
        # Re-ask the SAME request on a malformed reply — a fresh sample of
        # the same question, not a follow-up question about the bad answer.
        for attempt in range(1, _FOLLOWUP_FORMAT_ATTEMPTS + 1):
            try:
                advice = await self._call_teacher(
                    request,
                    stateful=True,
                    on_text=live.on_text if live.active else None,
                )
            except Exception as exc:
                logger.error(
                    "AdvisorMiddleware: follow-up teacher call failed: %s",
                    exc,
                )
                record["error"] = str(exc)
                self._record_intervention(record)
                live.fail(f"The advisor could not be reached: {exc}")
                return None
            action, body = _parse_followup(advice)
            if action:
                break
            logger.warning(
                "AdvisorMiddleware: follow-up reply %d/%d had no "
                "CONTINUE/ADJUST verdict on its first line, retrying",
                attempt,
                _FOLLOWUP_FORMAT_ATTEMPTS,
            )
            if attempt < _FOLLOWUP_FORMAT_ATTEMPTS:
                # The rejected sample must not shape the next answer (or
                # later consultations): drop it from the teacher history.
                del self._teacher_history[-2:]
                live.note("(no CONTINUE/ADJUST verdict; asking again)")
        else:
            # Still unparseable: treat as ADJUST rather than drop the
            # advice, so a teacher that ignored the format is not silently
            # discarded.
            action, body = _ADJUST, advice.strip()
            logger.warning(
                "AdvisorMiddleware: follow-up never produced a verdict, "
                "treating as %s",
                _ADJUST,
            )

        record.update({"action": action, "advice": advice})
        self._record_intervention(record)

        # CONTINUE carries no new instruction. The teacher still remembers
        # it (``_call_teacher`` recorded the exchange), but putting "keep
        # going" in front of the agent only grows an already-large context
        # and can read as an endorsement of whatever it is currently doing.
        if action == _CONTINUE:
            logger.info(
                "AdvisorMiddleware: teacher said %s, nothing injected",
                _CONTINUE,
            )
            live.finish(advice)
            return None
        if not body:
            logger.info(
                "AdvisorMiddleware: %s reply had no body, nothing injected",
                action,
            )
            live.finish(advice)
            return None

        msg = _exchange_msg(
            agent.name,
            FOLLOWUP_TOOL_NAME,
            _FOLLOWUP_CALL_ARGS,
            body,
            call_id=call_id,
        )
        agent.state.context.append(msg)
        live.finish(advice)
        logger.info(
            "AdvisorMiddleware: follow-up advice injected (%d chars)",
            len(body),
        )
        return msg

    # ── opening plan ────────────────────────────────────────────────────

    async def _inject_plan(
        self,
        agent: "Agent",
        tools: list[dict] | None = None,
    ) -> Msg | None:
        """Ask the teacher for a plan and inject it.

        Returns the injected message when it landed, else ``None``.
        """
        instruction = self._extract_instruction(agent.state.context)
        if not instruction:
            logger.warning("AdvisorMiddleware: no user instruction found")
            return None

        tool_list = self._format_tool_list(tools)
        env_context = self._read_env_context()
        env_section = (
            f"{ENV_SECTION_HEADER}\n\n{env_context}" if env_context else ""
        )
        plan_request = PLAN_REQUEST_TEMPLATE.format(
            instruction=instruction,
            tool_list=tool_list,
            env_section=env_section,
        )
        logger.info(
            "AdvisorMiddleware: asking teacher (%s) for a plan ...",
            getattr(self._teacher, "label", "?"),
        )

        # Open the exchange in the UI before the teacher is asked, so the
        # user sees the consultation (and the plan, as it streams) instead
        # of a silent wait before the agent's first token.
        call_id = _new_call_id()
        live = _LiveExchange(agent, call_id, PLAN_TOOL_NAME, _PLAN_CALL_ARGS)

        plan, last_exc = "", None
        for attempt in range(1, _PLAN_ATTEMPTS + 1):
            try:
                plan = await self._call_teacher(
                    plan_request,
                    stateful=True,
                    on_text=live.on_text if live.active else None,
                )
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "AdvisorMiddleware: teacher call failed (%d/%d): %s",
                    attempt,
                    _PLAN_ATTEMPTS,
                    exc,
                )
                if attempt < _PLAN_ATTEMPTS:
                    live.note(f"(advisor call failed: {exc}; retrying)")
                    await asyncio.sleep(_PLAN_RETRY_DELAY_S * attempt)
        else:
            # Every attempt failed. Say so loudly: a silent miss here turns
            # the run into a plain run wearing advisor overheads.
            logger.error(
                "AdvisorMiddleware: NO PLAN INJECTED after %d attempts: %s",
                _PLAN_ATTEMPTS,
                last_exc,
            )
            self._plan_error = str(last_exc)
            self._record_plan(plan_request, error=str(last_exc))
            live.fail(f"The advisor could not be reached: {last_exc}")
            return None

        logger.info(
            "AdvisorMiddleware: plan received (%d chars), injecting into "
            "context",
            len(plan),
        )
        self._record_plan(plan_request, plan=plan)

        msg = _exchange_msg(
            agent.name,
            PLAN_TOOL_NAME,
            _PLAN_CALL_ARGS,
            plan,
            call_id=call_id,
        )
        agent.state.context.append(msg)
        live.finish(plan)
        return msg

    # ── teacher call ────────────────────────────────────────────────────

    async def _call_teacher(
        self,
        message: str,
        stateful: bool = False,
        on_text: Callable[[str], None] | None = None,
    ) -> str:
        """Ask the teacher.

        With ``stateful=True`` the earlier exchange is replayed first, so
        the question is answered in light of the plans already given (and
        any advice already offered) instead of from a blank slate.
        ``on_text`` receives the cumulative reply while it streams.
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": ADVISOR_SYSTEM_PROMPT},
        ]
        if stateful:
            messages.extend(self._teacher_history)
        messages.append({"role": "user", "content": message})
        if on_text is None:
            reply = await self._teacher.ask(messages)
        else:
            reply = await self._teacher.ask(messages, on_text=on_text)
        # Remember the exchange so later questions build on it.
        self._teacher_history.append({"role": "user", "content": message})
        self._teacher_history.append({"role": "assistant", "content": reply})
        return reply

    # ── transcript persistence ──────────────────────────────────────────

    def _record_plan(
        self,
        request: str,
        plan: str | None = None,
        error: str | None = None,
    ) -> None:
        self._transcript["plan"] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "request": request,
            "plan": plan,
            "error": error,
        }
        self._save_transcript()

    def _record_intervention(self, record: dict[str, Any]) -> None:
        self._transcript["interventions"].append(record)
        self._save_transcript()

    def _record_consult(self, record: dict[str, Any]) -> None:
        self._transcript["consults"].append(record)
        self._save_transcript()

    def _save_transcript(self) -> None:
        """Persist the teacher exchange for debugging and analysis.

        Written under ``ADVISOR_DIR/<agent_id>/<session>.json`` — outside
        the agent workspace on purpose, so the agent's own file searches
        never surface the advisor's log as task material.
        """
        if self._log_dir is None:
            return
        try:
            self._log_dir.mkdir(parents=True, exist_ok=True)
            name = self._session_id or time.strftime("%Y%m%dT%H%M%S")
            safe = "".join(
                ch if ch.isalnum() or ch in "-_." else "_" for ch in name
            )
            path = self._log_dir / f"{safe}.json"
            path.write_text(
                json.dumps(self._transcript, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save advisor transcript: %s", exc)

    # ── inputs ──────────────────────────────────────────────────────────

    def _read_env_context(self) -> str:
        """Environment context for the plan: a shallow workspace listing."""
        try:
            return _workspace_listing(self._env_context_root)
        except Exception as exc:
            logger.warning("Failed to build env context: %s", exc)
            return ""

    @staticmethod
    def _format_tool_list(tools: list[dict] | None) -> str:
        """Render tool names and descriptions for the teacher.

        ``tools`` are the schemas of the model call in flight — the very
        list the agent is given on this call — so the teacher plans with
        exactly the tools the student has, and there is one place that
        decides what those are.
        """
        lines = []
        for schema in tools or []:
            func = (
                schema.get("function", {}) if isinstance(schema, dict) else {}
            )
            name = func.get("name", "?")
            if name in _EXCLUDED_TOOLS:
                continue
            lines.append(f"- {name}: {func.get('description', '')}")
        return "\n".join(lines) if lines else "(no tools available)"

    @staticmethod
    def _extract_instruction(context: list[Msg]) -> str:
        """The text of the latest user message in *context*.

        The context of a chat session carries every earlier turn; the
        follow-up and consultation requests must describe the message the
        agent is answering now, not the first one of the conversation.
        """
        for msg in reversed(context):
            if getattr(msg, "role", None) != "user":
                continue
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if _block_get(block, "type") == "text":
                        parts.append(str(_block_get(block, "text", "")))
                return "\n".join(parts)
        return ""


def default_log_dir(agent_id: str) -> Path:
    """Where advisor transcripts for ``agent_id`` are written."""
    from ...constant import ADVISOR_DIR

    safe = "".join(
        ch if ch.isalnum() or ch in "-_." else "_" for ch in (agent_id or "")
    )
    return ADVISOR_DIR / (safe or "default")


__all__ = [
    "AdvisorMiddleware",
    "CONSULT_BUDGET_EXHAUSTED",
    "DEFAULT_MAX_CONSULTS",
    "FOLLOWUP_TOOL_NAME",
    "PLAN_TOOL_NAME",
    "default_log_dir",
]
