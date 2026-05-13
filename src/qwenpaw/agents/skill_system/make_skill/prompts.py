# -*- coding: utf-8 -*-
"""Prompt templates for the ``/make-skill`` flow.

The flow has two distinct LLM phases — and so two prompts:

1. :func:`build_make_skill_plan_prompt` — *phase A* (drafting). The
   runner prepends ``/plan `` to this body. It tells the LLM how to
   shape ``plan.name`` and ``plan.description`` as a COMPACT human
   preview, and instructs it to copy the phase-B prompt verbatim into
   the single subtask's ``description``.

2. :func:`build_make_skill_subtask_description` — *phase B*
   (execution). This is the literal text that lives inside the
   subtask description. After the user approves the plan and the
   LLM transitions the subtask to ``in_progress``,
   :func:`qwenpaw.plan.hints._compact_plan_text` injects the full
   ``subtask.description`` into the per-turn hint.
   It rides on the existing ``/plan`` hint mechanism.

   Two branches selected by ``skill_available``:

   - ``True`` — the built-in ``skill-maker`` agent skill is enabled
     in the current workspace+channel. Subtask body is short and
     points the LLM at the skill (whose path is already in the
     ``# Agent Skills`` system-prompt block). The skill's SKILL.md
     carries the full writing guidance.
   - ``False`` — the skill is not enabled. Subtask body carries an
     inline compact fallback so ``/make-skill`` still works, and
     instructs the LLM to surface a brief enable-the-skill reminder
     to the user *after* ``materialize_skill`` succeeds.
"""
from __future__ import annotations

SKILL_MAKER_NAME = "skill-maker"


_MATERIALIZE_CONTRACT = (
    "Call `materialize_skill` with:\n"
    "   - name = <plan.name>\n"
    "   - description = a tight \"Use this skill when …\" string "
    "distilled from plan.description Part 1 (the trigger preview). "
    "<= 200 chars; preserve synonyms / adjacent phrasings — LLMs "
    "tend to under-trigger skills.\n"
    "   - body = the SKILL.md body (markdown only; the tool adds "
    "the YAML frontmatter for you).\n"
    "\n"
    "Do NOT use `write_file` to save SKILL.md directly — "
    "`materialize_skill` runs the security scanner and writes the "
    "manifest atomically. On error (format / scan / conflict), "
    "correct the input and call again. Do NOT call `finish_subtask` "
    "until `materialize_skill` returns success."
)


def _build_with_skill(focus: str) -> str:
    """Subtask body when `skill-maker` is available.
    """
    return (
        f"Use the `{SKILL_MAKER_NAME}` agent skill to write and "
        f"persist a SKILL.md capturing how `{focus}` was accomplished "
        f"in THIS session.\n"
        f"\n"
        f"Runtime context to apply:\n"
        f"- focus = \"{focus}\"\n"
        f"\n"
        f"Read the `{SKILL_MAKER_NAME}` SKILL.md (its path appears "
        f"in the `# Agent Skills` section of your system prompt) "
        f"carefully and follow it end-to-end. Persist via "
        f"`materialize_skill` (NOT `write_file`); do not call "
        f"`finish_subtask` until `materialize_skill` returns success."
    )


def _build_fallback(focus: str) -> str:
    """Subtask body when `skill-maker` is NOT available.

    Self-contained — no mention of the fallback nature, the
    ``skill-maker`` skill, or the existence of an alternative path.
    The agent only sees the task and the rules.
    """
    return (
        f"## You need to write a SKILL.md for `{focus}`\n"
        f"\n"
        f"The body must capture how `{focus}` was accomplished in "
        f"THIS session, in a way the next agent can replay "
        f"end-to-end. The rules below are not optional — they ensure "
        f"the file is well-formed, useful, and free of invented "
        f"facts.\n"
        f"\n"
        f"## Format rules (must hold for the file to persist)\n"
        f"\n"
        f"- Markdown body only. Do NOT include YAML frontmatter — "
        f"`materialize_skill` adds it from your arguments.\n"
        f"- One `## <step name>` heading per step in "
        f"plan.description's outline, in the same order. Step names "
        f"can be translated to match the user's language.\n"
        f"- Plain text under each heading (paragraphs, bullets, or "
        f"fenced code). No HTML, no raw YAML.\n"
        f"\n"
        f"## Content rules (so the next agent can actually replay it)\n"
        f"\n"
        f"- **Stay on `{focus}`.** Ignore unrelated tangents from the "
        f"conversation, even if they happened in the same session.\n"
        f"- **For each step, draw from THIS conversation**:\n"
        f"  - The specific tool / API / file / command that worked "
        f"(cite the real name).\n"
        f"  - Concrete parameter values that produced a working "
        f"call — copy the real values from the session, not "
        f"placeholders.\n"
        f"  - Errors hit on this path AND how to avoid them, "
        f"phrased preventively (e.g. \"Note: endpoint returns 429 "
        f"if called more than once per second — pass `delay=2` "
        f"from the start.\").\n"
        f"  - If multiple paths were tried and one worked, document "
        f"only the winning path in full. Mention failed paths as "
        f"terse `avoid X` reminders.\n"
        f"- **Don't invent.** If the conversation doesn't contain a "
        f"detail, leave it out rather than guess.\n"
        f"- **Use the imperative form** and explain WHY non-obvious "
        f"instructions matter. One short reason per non-obvious "
        f"step beats a heavy-handed `MUST`.\n"
        f"\n"
        f"## Quick self-check before calling the tool\n"
        f"\n"
        f"Re-read the body once and verify ALL THREE — single pass, "
        f"no second round:\n"
        f"\n"
        f"- **Covers `{focus}` end-to-end**: every step from "
        f"plan.description is present and substantiated.\n"
        f"- **Correct**: every tool name / parameter / error note "
        f"matches what actually happened. No invented facts.\n"
        f"- **Concise**: no redundancy; don't restate what's "
        f"already obvious from earlier steps.\n"
        f"\n"
        + _MATERIALIZE_CONTRACT
    )


def build_make_skill_subtask_description(
    focus: str,
    *,
    skill_available: bool,
) -> str:
    """Return the subtask-description text (phase B prompt).

    Embedded into the single subtask's ``description`` by phase A.
    Surfaced to the LLM in full once the subtask is ``in_progress``
    via :func:`qwenpaw.plan.hints._compact_plan_text`. Also reusable
    as the system prompt for a future non-interactive make-skill
    path (skips ``/plan`` entirely) — in that case pass
    ``skill_available`` according to the current workspace state.

    Args:
        focus: The verbatim focus string typed by the user.
        skill_available: True if the ``skill-maker`` agent skill
            is enabled in the current workspace+channel. If True the
            subtask defers to the skill; if False an inline compact
            fallback is returned.
    """
    if skill_available:
        return _build_with_skill(focus)
    return _build_fallback(focus)


def build_make_skill_plan_prompt(
    focus: str,
    normalized_name: str,
    *,
    skill_available: bool,
) -> str:
    """Return the prompt body that follows ``/plan `` (phase A).

    The runner prepends ``/plan `` to this and rewrites the user's
    message before handing off to the agent. The body tells the LLM
    how to construct the plan as a compact human preview and embeds
    the phase-B subtask prompt verbatim into the single subtask's
    description.

    The ``skill_available`` flag only steers which phase-B variant is
    embedded; it does NOT add user-visible content to the plan card
    (any fallback notice rides in the success message after
    ``materialize_skill`` succeeds — see :func:`_build_fallback`).

    Args:
        focus: The verbatim focus string typed by the user.
        normalized_name: Result of
            :func:`qwenpaw.agents.skill_system.store.normalize_skill_dir_name`
            on the focus — the on-disk skill directory name the runner
            has already verified is free.
        skill_available: True if the ``skill-maker`` agent skill
            is enabled in the current workspace+channel. Selects the
            phase-B branch embedded into the subtask.
    """
    subtask_desc = build_make_skill_subtask_description(
        focus,
        skill_available=skill_available,
    )

    return (
        f"Make our current session into a reusable workspace skill "
        f"(focus: \"{focus}\").\n"
        f"\n"
        f"Construct the plan as a COMPACT human preview of the skill. "
        f"When the user reviews the plan they are deciding whether "
        f"the skill proposal is right. Confirming approves the "
        f"proposal; refining means call `revise_current_plan` with "
        f"feedback baked into name / description; cancelling means "
        f"call `finish_plan` with state=\"abandoned\".\n"
        f"\n"
        f"Fill in:\n"
        f"\n"
        f"- plan.name: equal to the normalised focus "
        f"`{normalized_name}`.\n"
        f"\n"
        f"- plan.description: a COMPACT preview, two parts. Do NOT "
        f"write a full SKILL.md here — that comes later in the "
        f"subtask.\n"
        f"\n"
        f"  Part 1 — Trigger preview (2-4 sentences, plain language). "
        f"Must explicitly cover all three:\n"
        f"    - **Goal**: the end-result this skill produces for the "
        f"user — the reason it exists.\n"
        f"    - **Trigger**: which user phrasings / contexts should "
        f"invoke it. Be a bit pushy on synonyms and adjacent "
        f"phrasings a future agent might see.\n"
        f"    - **I/O**: what inputs it expects, what outputs it "
        f"produces (shape only — full template lives in the SKILL.md "
        f"body).\n"
        f"  This is human preview prose; it is NOT yet the SKILL.md "
        f"frontmatter format.\n"
        f"\n"
        f"  Part 2 — Step outline.\n"
        f"  Numbered list, one short verb phrase per line. NO "
        f"per-step detail, NO parameters, NO error handling, NO "
        f"sub-bullets, NO `##` sub-headings. Just the shape, so the "
        f"user can quickly judge ordering and scope and refine if "
        f"needed.\n"
        f"\n"
        f"  Format (placeholder example — do NOT copy this content):\n"
        f"    1. <verb phrase, ~5-10 words>\n"
        f"    2. <verb phrase, ~5-10 words>\n"
        f"    3. <…>\n"
        f"\n"
        f"  Draw the step names from what actually happened in THIS "
        f"conversation. Do not fabricate — if a step isn't grounded "
        f"in the conversation, omit it.\n"
        f"\n"
        f"The plan must have exactly ONE subtask:\n"
        f"\n"
        f"  name: \"Write and materialize skill\"\n"
        f"\n"
        f"  description: use the following text as the subtask "
        f"description. You may translate it to match the user's "
        f"language, but PRESERVE the `materialize_skill` parameter "
        f"list (name / description / body / focus / summary) "
        f"exactly:\n"
        f"  ---\n"
        f"{subtask_desc}\n"
        f"  ---\n"
        f"\n"
        f"  expected_outcome: \"Skill created and visible via "
        f"/skills.\"\n"
        f"\n"
        f"Write plan.name and plan.description in the same language "
        f"as the user's recent messages.\n"
        f"\n"
        f"When you present the plan to the user for confirmation, "
        f"render it as the standard plan card (name, description, "
        f"the single subtask). Do NOT add ad-hoc fields."
    )
