# -*- coding: utf-8 -*-
"""Custom plan-to-hint generator for QwenPaw.

Key differences from the AgentScope default:

1. **Confirmation step** -- after creating a plan the agent must
   present it and wait for user approval before execution.
2. **Seamless transitions** -- after finishing one subtask the agent
   moves to the next immediately without pausing.
3. **Compact plan text** -- completed-subtask outcomes and timestamps
   are dropped from the hint so the per-iteration context cost stays
   constant regardless of how many subtasks have finished.  This
   prevents the "overflow -> truncate -> retry -> overflow" loop that
   occurs when the plan hint grows unboundedly.
4. **Scoped ``no_plan`` hint** -- when there is no active plan yet, a
   short hint tells the model to call ``create_plan`` without
   browser/web tools first *only if* the user asked for a plan; heavy
   tooling is deferred to named subtasks after confirmation.
5. **Stall guard** -- if the same subtask stays ``in_progress`` across
   many consecutive hint generations, the hint escalates to force
   ``finish_subtask`` so the ReAct loop does not repeat the same tool
   calls until ``max_iters`` is hit.
6. **No text-only turns during execution** -- hints require at least
   one tool call per turn while a plan runs; otherwise the ReAct loop
   exits early. A short prose line may accompany tools for visibility.
"""
from __future__ import annotations

import logging
import weakref
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agentscope.plan import Plan

logger = logging.getLogger(__name__)

try:
    from agentscope.plan._plan_notebook import DefaultPlanToHint

    _HAS_DEFAULT_HINT = True
except ImportError:
    _HAS_DEFAULT_HINT = False

_DESC_LIMIT = 80
_PLAN_DESC_LIMIT = 200

# After this many consecutive hint generations for the same
# in_progress subtask, replace the normal hint with a forced-finish
# directive.  Keep this low — the agent should finish a subtask in
# a handful of tool calls, not dozens.  Lower bound leaves headroom
# under typical max_iters when many subtasks exist.
_STALL_THRESHOLD = 5

# English-only: instructs the model to mirror the user's language in plan UX.
# Keep this block free of non-ASCII characters so hint files stay ASCII-clean.
_PLAN_RESPONSE_LANGUAGE_BLOCK = (
    "Language consistency: For every user-visible string in plan mode (plan "
    "title, plan description, overall expected_outcome, each subtask name, "
    "description, expected_outcome, short prose before tool calls, "
    "finish_subtask / finish_plan outcome text, and final summaries), use the "
    "same natural language as the user's recent messages when that language "
    "is clear. If the user has written only in one language (including any "
    "script), keep using that language for those strings. "
    "When the agent or UI "
    "locale matches the user's language, stay aligned with that locale. Use "
    "English only when the user wrote in English or when the input language "
    "is genuinely mixed or unclear. Do not default to English for narrative "
    "content if the conversation has been in another language.\n\n"
)


def set_plan_gate(plan_notebook, enabled: bool = True) -> None:
    """Activate or deactivate the plan tool gate on *plan_notebook*.

    The gate ensures that only ``create_plan`` is allowed until an
    active plan exists.  Called by the runner when a ``/plan <desc>``
    command is detected.
    """
    if plan_notebook is not None:
        # pylint: disable-next=protected-access
        plan_notebook._qwenpaw_plan_gate = enabled


def clear_reconfirmation_flag(plan_notebook) -> None:
    """Clear the \"edited plan while all todo\" reconfirmation requirement.

    Called when execution is explicitly allowed (e.g. first subtask moves to
    ``in_progress``). Safe to call on any notebook instance.
    """
    if plan_notebook is not None:
        # pylint: disable-next=protected-access
        plan_notebook._qwenpaw_needs_reconfirmation = False


def _needs_reconfirmation_after_revision(plan_notebook) -> bool:
    if plan_notebook is None:
        return False
    return bool(
        getattr(plan_notebook, "_qwenpaw_needs_reconfirmation", False),
    )


def check_plan_tool_gate(plan_notebook, tool_name: str):
    """Return an error string if *tool_name* must be blocked, else
    ``None``.

    Enforces that when a ``/plan`` request is pending (plan mode is
    on, no plan exists yet, gate flag is set by the runner), only
    ``create_plan`` may run.  All other tools are rejected with a
    message instructing the model to call ``create_plan`` first.

    The gate flag is set via :func:`set_plan_gate` and is
    cleared once a plan exists (``create_plan`` succeeded) or when the
    HTTP API finishes the plan, so it does not stick across sessions.
    """
    if plan_notebook is None:
        return None
    if plan_notebook.current_plan is not None:
        # No longer in the "must create_plan first" window; drop stale flag.
        if getattr(plan_notebook, "_qwenpaw_plan_gate", False):
            # pylint: disable-next=protected-access
            plan_notebook._qwenpaw_plan_gate = False
        return None
    if not getattr(plan_notebook, "_qwenpaw_plan_gate", False):
        return None
    if tool_name == "create_plan":
        return None
    return (
        f"Tool '{tool_name}' is not available right now. "
        "You MUST call 'create_plan' first to define the "
        "plan and its subtasks. Do NOT call browser_use, "
        "web_search, or any other tool before 'create_plan'. "
        "Decompose the user's request into a **logical pipeline**: "
        "each subtask needs a clear name, description, and measurable "
        "expected_outcome; order steps so dependencies run earlier "
        "(understand → act → verify → report). Put research, repo "
        "reading, and heavy tooling into named subtasks for after "
        "user confirmation. "
        "Write plan and subtask text in the same language as the "
        "user's request when it is identifiable."
    )


def _compact_plan_text(plan: "Plan") -> str:
    """Build a compact markdown representation of *plan*.

    * **Done / abandoned** subtasks -> one-line status + name only.
    * **In-progress** subtask -> name + description + expected outcome.
    * **Todo** subtasks -> name + first ``_DESC_LIMIT`` chars of
      description.

    This keeps the hint O(n) in subtask *count* but with a tiny
    constant per completed subtask, instead of O(sum of outcomes).
    """
    desc = plan.description
    if len(desc) > _PLAN_DESC_LIMIT:
        desc = desc[: _PLAN_DESC_LIMIT - 3] + "..."

    lines = [
        f"# {plan.name}",
        f"Description: {desc}",
        f"State: {plan.state}",
        "## Subtasks",
    ]
    for i, st in enumerate(plan.subtasks):
        if st.state == "done":
            lines.append(f"  {i}. [done] {st.name}")
        elif st.state == "abandoned":
            lines.append(f"  {i}. [abandoned] {st.name}")
        elif st.state == "in_progress":
            lines.append(f"  {i}. [in_progress] {st.name}")
            lines.append(f"     Desc: {st.description}")
            lines.append(
                f"     Expected: {st.expected_outcome}",
            )
        else:
            d = st.description
            if len(d) > _DESC_LIMIT:
                d = d[: _DESC_LIMIT - 3] + "..."
            lines.append(f"  {i}. [todo] {st.name}")
            lines.append(f"     Desc: {d}")
    return "\n".join(lines)


def _subtask_text(subtask) -> str:
    """Concise view for the ``{subtask}`` format variable."""
    return (
        f"Name: {subtask.name}\n"
        f"Description: {subtask.description}\n"
        f"Expected Outcome: {subtask.expected_outcome}"
    )


def _count_states(plan: "Plan"):
    """Return (n_todo, n_ip, n_done, n_abn, ip_idx)."""
    n_todo = n_ip = n_done = n_abn = 0
    ip_idx = None
    for idx, st in enumerate(plan.subtasks):
        if st.state == "todo":
            n_todo += 1
        elif st.state == "in_progress":
            n_ip += 1
            ip_idx = idx
        elif st.state == "done":
            n_done += 1
        elif st.state == "abandoned":
            n_abn += 1
    return n_todo, n_ip, n_done, n_abn, ip_idx


if _HAS_DEFAULT_HINT:

    class QwenPawPlanToHint(DefaultPlanToHint):
        """Plan-to-hint generator with bounded context cost.

        Overrides ``__call__`` so that ``{plan}`` is replaced with
        a **compact** representation once execution starts.
        At the very beginning (all subtasks *todo*, no outcomes yet)
        the full ``plan.to_markdown()`` is used because it is small
        and the agent needs full details to present the plan.
        """

        def __init__(self) -> None:
            self._ip_call_count: int = 0
            self._last_ip_name: str | None = None
            self._last_ip_idx: int | None = None
            self._notebook_ref: Any = None

        def bind_notebook(self, plan_notebook) -> None:
            """Weak link for reading reconfirmation state in hints."""
            if plan_notebook is None:
                self._notebook_ref = None
            else:
                self._notebook_ref = weakref.ref(plan_notebook)

        def _bound_notebook(self):
            ref = self._notebook_ref
            return ref() if ref is not None else None

        _stalled_subtask: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            + _PLAN_RESPONSE_LANGUAGE_BLOCK
            + "IMPORTANT: Subtask {subtask_idx} ('{subtask_name}') has been "
            "in_progress for {call_count} iterations without completion.\n"
            "In the SAME turn: include one short sentence to the user, then "
            "call 'finish_subtask' with subtask_idx={subtask_idx} and a "
            "summary of progress (even if incomplete).\n"
            "CRITICAL: Your response MUST include a 'finish_subtask' tool "
            "call. Text-only replies end the run and interrupt the plan.\n"
        )

        at_the_beginning: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            + _PLAN_RESPONSE_LANGUAGE_BLOCK
            + "STEP 1 — Check the user's LATEST message first:\n"
            "- If it is a confirmation (words or short phrases that mean "
            "proceed, start, or confirm in the language the user has been "
            "using—including typical English such as 'go ahead', 'start', "
            "'confirm', 'yes', 'ok', 'sure', 'begin', 'execute', "
            "'proceed'), IMMEDIATELY call "
            "'update_subtask_state' with subtask_idx=0 and "
            "state='in_progress', then begin executing it. "
            "Do NOT present the plan again or ask for "
            "confirmation a second time.\n"
            "- If the user asks to modify the plan, use "
            "'revise_current_plan' to make changes. Then "
            "present the updated plan and ask again.\n"
            "- If the user cancels, call 'finish_plan' with "
            "state='abandoned'.\n"
            "\n"
            "STEP 2 — Only if the plan was JUST created "
            "(i.e. the user has NOT yet seen it), present "
            "this plan and ask the user to confirm, edit, "
            "or cancel before you start. Do NOT execute any "
            "subtask until the user explicitly confirms.\n"
            "When presenting, walk through subtasks in order and briefly "
            "explain why the sequence makes sense (dependencies, "
            "understand-before-change, verify-before-close).\n"
            "Until confirmed, do NOT use browser, web search, "
            "or other tools to research the task. Summarize "
            "from the user's request and reasonable assumptions. "
            "Any browsing, repo inspection, or heavy "
            "investigation must appear as explicit todo "
            "subtasks and run only after confirmation when "
            "that subtask is in_progress.\n"
        )

        after_revision_needs_reconfirm: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            + _PLAN_RESPONSE_LANGUAGE_BLOCK
            + "The plan was edited (a subtask was added, changed, or removed) "
            "while every subtask was still todo. Any earlier generic "
            "confirmation does NOT authorize starting until the user confirms "
            "again after seeing this version.\n"
            "STEP 1 — If you have not yet presented this exact version to the "
            "user after the edit, present it now and ask them to confirm, "
            "further edit, or cancel. Do NOT call 'update_subtask_state' with "
            "state='in_progress' before that.\n"
            "STEP 2 — If your last assistant message already presented this "
            "same version and the user's LATEST message is an explicit "
            "confirmation (including typical phrases such as 'go ahead', "
            "'start', 'confirm', 'yes', 'ok', 'sure', 'begin', 'execute', "
            "'proceed' in the language the user has been using), call "
            "'update_subtask_state' with subtask_idx=0 and "
            "state='in_progress', "
            "then begin executing. Do NOT present the plan again.\n"
            "STEP 3 — If the user asks for more changes, use "
            "'revise_current_plan', then return to presenting the "
            "updated plan "
            "and waiting for confirmation. If they cancel, call 'finish_plan' "
            "with state='abandoned'.\n"
            "Until execution starts (a subtask is in_progress), do NOT use "
            "browser, web search, or other heavy tools; keep research inside "
            "named todo subtasks for after confirmation.\n"
        )

        when_a_subtask_in_progress: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            + _PLAN_RESPONSE_LANGUAGE_BLOCK
            + "Subtask {subtask_idx} ('{subtask_name}') is "
            "in_progress. Details:\n"
            "```\n"
            "{subtask}\n"
            "```\n"
            "Execute this subtask:\n"
            "1. Each turn: one short line of plain text (what you are doing) "
            "plus at least one tool call — same turn.\n"
            "2. Use tools to achieve the objective; avoid repeating the same "
            "tool with the same arguments.\n"
            "3. Completion rule — as soon as the objective is met "
            "(e.g. command "
            "succeeded, tests passed, file validated, syntax OK), call "
            "'finish_subtask' in the SAME turn with a concise outcome. Do NOT "
            "run the same successful check again.\n"
            "4. When stuck after a few tries, call 'finish_subtask' with a "
            "partial outcome anyway. The next subtask activates "
            "automatically.\n"
            "CRITICAL: Do NOT reply with text only. The ReAct loop stops "
            "if there is no tool call; that interrupts the plan on all "
            "channels.\n"
        )

        when_no_subtask_in_progress: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            + _PLAN_RESPONSE_LANGUAGE_BLOCK
            + "The first {index} subtask(s) are done and no "
            "subtask is currently in_progress.\n"
            "In the SAME turn: one short sentence to the user, then call "
            "'update_subtask_state' to mark the next todo subtask as "
            "'in_progress' and continue with tools for that subtask.\n"
            "CRITICAL: Include an 'update_subtask_state' (or other plan) "
            "tool call — text-only replies end the run and interrupt the "
            "plan.\n"
        )

        at_the_end: str = (
            "The current plan:\n"
            "```\n"
            "{plan}\n"
            "```\n"
            + _PLAN_RESPONSE_LANGUAGE_BLOCK
            + "All subtasks are complete. Call 'finish_plan' "
            "with state='done' and a concise outcome summary, then summarize "
            "for the user.\n"
            "CRITICAL: Include a 'finish_plan' tool call in this turn — "
            "text-only replies end the run before the plan is closed.\n"
        )

        # Shown only when plan mode is on and there is no current plan.
        # Wording avoids autonomous plans: applies when the user is
        # asking for a breakdown (/plan, etc.), not on every chat turn.
        no_plan: str | None = (
            "There is no active plan yet.\n"
            + _PLAN_RESPONSE_LANGUAGE_BLOCK
            + "If and only if the user is asking for a structured plan "
            "or step-by-step breakdown (e.g. a /plan-style request), "
            "call 'create_plan' next. Do NOT call browser_use, web_search, "
            "or similar tools before 'create_plan'; put browsing, repo "
            "research, and heavy tooling into explicit todo subtasks that "
            "run after the user confirms the plan.\n"
            "If the user is not requesting a plan, ignore this block.\n"
            "\n"
            "When you call 'create_plan', decompose the user's instruction "
            "into a **coherent, fine-grained pipeline**:\n"
            "\n"
            "**Plan-level fields**\n"
            "- name: Short, specific title (what is being delivered "
            "or reviewed).\n"
            "- description: Context, constraints, scope boundaries, "
            "and what is "
            "out of scope if unclear.\n"
            "- expected_outcome: One paragraph on what success "
            "looks like for the "
            'entire task (deliverables, quality bar, "done" definition).\n'
            "\n"
            "**Subtask design (each subtask: name, description, "
            "expected_outcome)**\n"
            "- **Order & logic**: Arrange subtasks in dependency "
            "order—typically "
            "orientation/clarify → explore or read → analyze or implement → "
            "validate or test → fix or refine → summarize or hand off. "
            "Put "
            "steps that need prior results after the steps that "
            "produce them.\n"
            "- **One main focus per subtask**: Each step should have a single "
            "clear objective; avoid overlapping scope between subtasks unless "
            "one explicitly builds on another.\n"
            "- **Verifiable outcomes**: For every subtask, "
            "expected_outcome must "
            'state concrete signals of completion (e.g. "list of findings", '
            '"tests green", "patch applied", "report section written"), '
            'not vague phrases like "understand better".\n'
            "- **Granularity**: For non-trivial work, prefer several "
            "medium steps "
            "over one huge step or dozens of tiny redundant steps; "
            "merge trivial "
            "checks that belong together.\n"
            "- **Naming**: Use short verb-led titles in the user's "
            "language when "
            'known (for English-only requests, examples: "Map module '
            'dependencies", "Run unit tests", "Document API risks") '
            "so the "
            "flow reads as a story from top to bottom.\n"
            "- **Risks & verification**: If the task involves code "
            "or systems, "
            "include explicit validation or review steps before "
            "declaring success; "
            'separate "try a quick fix" from "confirm with tests" '
            "when both "
            "matter.\n"
            "\n"
            "After 'create_plan' succeeds, present the plan to the "
            "user and wait "
            "for confirmation before executing subtasks, unless the "
            "product flow "
            "already says otherwise.\n"
        )

        # ---- override __call__ for compact context ----

        def _ip_hint(self, plan, ip_idx):
            """Hint for the in-progress subtask, with stall guard."""
            st = plan.subtasks[ip_idx]
            ip_key = st.name
            if ip_key == self._last_ip_name:
                self._ip_call_count += 1
            else:
                self._last_ip_name = ip_key
                self._ip_call_count = 1
            compact = _compact_plan_text(plan)
            if self._ip_call_count > _STALL_THRESHOLD:
                return self._stalled_subtask.format(
                    plan=compact,
                    subtask_idx=ip_idx,
                    subtask_name=st.name,
                    call_count=self._ip_call_count,
                )
            return self.when_a_subtask_in_progress.format(
                plan=compact,
                subtask_idx=ip_idx,
                subtask_name=st.name,
                subtask=_subtask_text(st),
            )

        def __call__(
            self,
            plan: "Plan | None",
        ) -> str | None:
            """Generate a compact hint.

            At the beginning (all subtasks *todo*) the full
            ``plan.to_markdown()`` is used.  Once execution
            starts, ``_compact_plan_text`` keeps the hint small.
            """
            if plan is None:
                self._last_ip_name = None
                self._ip_call_count = 0
                hint = self.no_plan
            else:
                _, n_ip, n_done, n_abn, ip_idx = _count_states(plan)
                if n_ip == 0:
                    self._last_ip_name = None
                    self._ip_call_count = 0
                    self._last_ip_idx = None
                elif ip_idx is not None and ip_idx != self._last_ip_idx:
                    # New in_progress subtask (e.g. after finish_subtask):
                    # reset stall guard so counts do not carry across subtasks.
                    self._last_ip_idx = ip_idx
                    self._last_ip_name = None
                    self._ip_call_count = 0

                hint = self._pick_hint(
                    plan,
                    n_ip,
                    n_done,
                    n_abn,
                    ip_idx,
                )

            if hint:
                return f"{self.hint_prefix}" f"{hint}" f"{self.hint_suffix}"
            return hint

        def _pick_hint(self, plan, n_ip, n_done, n_abn, ip_idx):
            """Select the right hint template for the plan state."""
            if n_ip == 0 and n_done == 0:
                if _needs_reconfirmation_after_revision(
                    self._bound_notebook(),
                ):
                    return self.after_revision_needs_reconfirm.format(
                        plan=plan.to_markdown(),
                    )
                return self.at_the_beginning.format(
                    plan=plan.to_markdown(),
                )
            if n_ip > 0 and ip_idx is not None:
                return self._ip_hint(plan, ip_idx)
            if n_done + n_abn == len(plan.subtasks):
                return self.at_the_end.format(
                    plan=_compact_plan_text(plan),
                )
            if n_ip == 0 and n_done > 0:
                return self.when_no_subtask_in_progress.format(
                    plan=_compact_plan_text(plan),
                    index=n_done,
                )
            return None

else:
    QwenPawPlanToHint = None  # type: ignore[misc,assignment]
