# -*- coding: utf-8 -*-
"""Mission Mode execution engine.

Encapsulates the full Mission Mode lifecycle:

1. **Phase 1 — PRD generation**: The agent explores the codebase and writes
   ``prd.json``.  All tools are available.  Phase ends when the agent
   finishes its turn and a valid ``prd.json`` exists on disk.  Control is
   returned to the user for confirmation.

2. **Phase 2 — Execution loop**: After user confirms, the engine enters a
   code-controlled iteration loop.  Implementation tools are *deactivated*
   (via Toolkit group mechanism), so the master agent physically cannot run
   ``npm``, ``pip``, etc.  Each iteration:
   a. Agent runs one turn.
   b. Engine reads ``prd.json`` and checks ``passes`` on every story.
   c. If all pass → done.  Otherwise inject a continuation message and
      loop back to (a).

This module is called from ``runner.py`` and is the *only* place that
knows about mission phases and iteration logic.  ``handler.py`` remains a
thin command parser; ``prompts.py`` remains a prompt library.

Copyright notice
~~~~~~~~~~~~~~~~
Portions of the prompt-driven workflow are adapted from snarktank/ralph
(MIT License).  See ``prompts.py`` for the full notice.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, AsyncGenerator

from agentscope.message import Msg, TextBlock
from agentscope.pipeline import stream_printing_messages

from .state import read_loop_config, read_prd, write_loop_config

logger = logging.getLogger(__name__)

# ── Tool-group name used for implementation tools ────────────────────────
MISSION_IMPL_GROUP = "mission_impl"

# Tools that are *implementation* tools — only workers should use them in
# Phase 2.  Everything NOT in this set stays in the "basic" group and is
# always available to the master agent.
IMPLEMENTATION_TOOLS = frozenset(
    {
        "execute_shell_command",
        "write_file",
        "edit_file",
        "browser_use",
        "desktop_screenshot",
        "send_file_to_user",
    },
)

# Minimum required fields in a valid prd.json
_REQUIRED_PRD_FIELDS = {"userStories"}
_REQUIRED_STORY_FIELDS = {
    "id",
    "title",
    "description",
    "acceptanceCriteria",
    "priority",
}


# ── PRD validation ───────────────────────────────────────────────────────


class PrdValidationError(ValueError):
    """Raised when prd.json does not conform to the expected schema."""


def validate_prd(prd: dict[str, Any]) -> list[str]:
    """Validate a PRD dict and return a list of problems (empty = valid)."""
    problems: list[str] = []

    if not isinstance(prd, dict):
        return ["prd.json is not a JSON object"]

    if "userStories" not in prd:
        problems.append("Missing top-level 'userStories' array")
        return problems

    stories = prd["userStories"]
    if not isinstance(stories, list) or len(stories) == 0:
        problems.append("'userStories' must be a non-empty array")
        return problems

    for i, story in enumerate(stories):
        if not isinstance(story, dict):
            problems.append(f"userStories[{i}] is not an object")
            continue
        missing = _REQUIRED_STORY_FIELDS - set(story.keys())
        if missing:
            problems.append(
                f"userStories[{i}] ('{story.get('id', '?')}') missing fields: "
                f"{', '.join(sorted(missing))}",
            )

    return problems


# ── Toolkit group helpers ────────────────────────────────────────────────


def migrate_tools_to_group(agent: Any) -> None:
    """Move implementation tools from 'basic' into a dedicated group.

    Must be called *after* agent construction but *before* the first
    ``reply()`` in Phase 2.  Idempotent — safe to call multiple times.
    """
    toolkit = agent.toolkit
    if MISSION_IMPL_GROUP in toolkit.groups:
        return

    toolkit.add_tool_group(
        MISSION_IMPL_GROUP,
        description=(
            "Implementation tools (shell, write, edit).  "
            "Deactivated during Mission Mode Phase 2 — the master "
            "agent must delegate all work to workers."
        ),
        active=True,
    )

    for tool_name in IMPLEMENTATION_TOOLS:
        if tool_name in toolkit.tools:
            toolkit.tools[tool_name].group = MISSION_IMPL_GROUP


def set_phase2_tool_restrictions(agent: Any) -> None:
    """Deactivate implementation tools for Phase 2 (controller-only mode)."""
    migrate_tools_to_group(agent)
    agent.toolkit.update_tool_groups([MISSION_IMPL_GROUP], active=False)
    logger.info(
        "Mission Phase 2: deactivated tool group '%s' — master "
        "is now controller-only",
        MISSION_IMPL_GROUP,
    )


def restore_tools(agent: Any) -> None:
    """Re-activate implementation tools (cleanup / Phase 1)."""
    if MISSION_IMPL_GROUP in agent.toolkit.groups:
        agent.toolkit.update_tool_groups([MISSION_IMPL_GROUP], active=True)
        logger.info("Mission: restored tool group '%s'", MISSION_IMPL_GROUP)


# ── Phase helpers ────────────────────────────────────────────────────────


def _update_phase(loop_dir: Path, phase: str) -> None:
    """Persist current phase into loop_config.json."""
    cfg = read_loop_config(loop_dir)
    cfg["current_phase"] = phase
    write_loop_config(loop_dir, cfg)


def _completion_summary(prd: dict[str, Any]) -> str:
    stories = prd.get("userStories", [])
    passed = sum(1 for s in stories if s.get("passes"))
    total = len(stories)
    lines = [f"**Mission Complete** — {passed}/{total} stories passed ✅\n"]
    for s in stories:
        mark = "✅" if s.get("passes") else "❌"
        lines.append(f"  {mark} {s['id']}: {s['title']}")
    return "\n".join(lines)


def _remaining_summary(
    prd: dict[str, Any],
    iteration: int,
    max_iter: int,
) -> str:
    stories = prd.get("userStories", [])
    remaining = [s for s in stories if not s.get("passes")]
    passed = len(stories) - len(remaining)
    return (
        f"[Mission — iteration {iteration}/{max_iter}] "
        f"{passed}/{len(stories)} stories passed. "
        f"{len(remaining)} remaining:\n"
        + "\n".join(f"  ⬜ {s['id']}: {s['title']}" for s in remaining)
        + "\n\nContinue with the **worker → verifier** pipeline:\n"
        "1. Dispatch **workers** for remaining stories\n"
        "2. Once a worker finishes, dispatch a **verifier** for "
        "that story\n"
        "3. Parse verifier VERDICT: PASS → set `passes: true` "
        "in prd.json; FAIL → retry with error context\n\n"
        "Remember: you are the CONTROLLER — delegate ALL work "
        "via `qwenpaw agents chat --background`."
    )


# ── Main execution ───────────────────────────────────────────────────────


async def run_mission_phase1(
    agent: Any,
    msgs: list,
    loop_dir: Path,
    max_iterations: int = 20,
) -> AsyncGenerator[tuple[Msg, bool], None]:
    """Execute Phase 1 (PRD generation / user follow-up).

    Runs the agent for one turn.  After the agent finishes:
    - If prd.json exists but is invalid → report errors.
    - If the agent set ``current_phase`` to ``"execution_confirmed"``
      in loop_config.json → seamlessly transition to Phase 2.
    - Otherwise → return control to the user.
    """
    async for msg, last in stream_printing_messages(
        agents=[agent],
        coroutine_task=agent(msgs),
    ):
        yield msg, last

    # Check if agent signaled Phase 2 confirmation
    cfg = read_loop_config(loop_dir)
    if cfg.get("current_phase") == "execution_confirmed":
        logger.info("Mission: agent confirmed PRD, transitioning to Phase 2")
        async for msg, last in run_mission_phase2(
            agent=agent,
            msgs=[],
            loop_dir=loop_dir,
            max_iterations=max_iterations,
        ):
            yield msg, last
        return

    # Still in Phase 1 — validate prd.json if it exists
    prd = read_prd(loop_dir)
    if prd:
        problems = validate_prd(prd)
        if problems:
            detail = "\n".join(f"  - {p}" for p in problems)
            yield Msg(
                name="system",
                role="assistant",
                content=[
                    TextBlock(
                        type="text",
                        text=(
                            f"⚠️ **prd.json validation failed**:\n{detail}\n\n"
                            "Please fix the prd.json format before confirming."
                        ),
                    ),
                ],
            ), True


async def run_mission_phase2(
    agent: Any,
    msgs: list,
    loop_dir: Path,
    max_iterations: int = 20,
) -> AsyncGenerator[tuple[Msg, bool], None]:
    """Execute Phase 2 (iteration loop with code-level control).

    1. Deactivate implementation tools.
    2. Run agent in a loop; after each turn, check prd.json.
    3. If not all stories pass, inject a continuation message.
    4. Stop when all pass or max_iterations reached.

    Yields streamed messages throughout.
    """
    _update_phase(loop_dir, "execution")
    set_phase2_tool_restrictions(agent)

    try:
        for iteration in range(1, max_iterations + 1):
            logger.info(
                "Mission Phase 2: iteration %d/%d",
                iteration,
                max_iterations,
            )

            async for msg, last in stream_printing_messages(
                agents=[agent],
                coroutine_task=agent(msgs),
            ):
                yield msg, last

            # Code-level completion check
            prd = read_prd(loop_dir)
            stories = prd.get("userStories", [])

            if not stories:
                logger.warning(
                    "Mission Phase 2: prd.json has no stories — aborting",
                )
                yield Msg(
                    name="system",
                    role="assistant",
                    content=[
                        TextBlock(
                            type="text",
                            text=(  # noqa: E501
                                "⚠️ prd.json has no user stories. "
                                "Loop aborted."
                            ),
                        ),
                    ],
                ), True
                return

            all_passed = all(s.get("passes") for s in stories)
            if all_passed:
                yield Msg(
                    name="system",
                    role="assistant",
                    content=[
                        TextBlock(
                            type="text",
                            text=_completion_summary(prd),
                        ),
                    ],
                ), True
                _update_phase(loop_dir, "completed")
                return

            # Not done — inject continuation and loop
            continuation = _remaining_summary(prd, iteration, max_iterations)
            msgs = [
                Msg(
                    name="user",
                    role="user",
                    content=[TextBlock(type="text", text=continuation)],
                ),
            ]

        # Exhausted iterations
        prd = read_prd(loop_dir)
        stories = prd.get("userStories", [])
        passed = sum(1 for s in stories if s.get("passes"))
        yield Msg(
            name="system",
            role="assistant",
            content=[
                TextBlock(
                    type="text",
                    text=(
                        f"⚠️ **Mission reached max iterations**"
                        f" ({max_iterations}). "
                        f"{passed}/{len(stories)} stories passed."
                        f"\n\nYou can check with `/mission status`"
                        " to see what remains, then start a new"
                        " mission or manually complete the work."
                    ),
                ),
            ],
        ), True
        _update_phase(loop_dir, "max_iterations_reached")

    finally:
        restore_tools(agent)
