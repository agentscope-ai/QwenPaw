# -*- coding: utf-8 -*-
"""Rule generalization — widen an approved tool-call target via the LLM.

When a user approves a tool call, future *similar* calls should be
auto-approved without prompting again. Given the exact approved target
(e.g. ``"git status"``, ``"/ws/src/foo.py"``), the LLM is asked for a
conservative glob pattern (e.g. ``git *``, ``/ws/src/**``).

The LLM is untrusted: every pattern is validated by
:func:`_is_safe_generalization` before use, and on any failure (no model,
timeout, API/parse error, validation) we fall back to a literal exact
match — the approved call is always recorded and never widened unsafely.
"""

from __future__ import annotations

import asyncio
import logging
from fnmatch import fnmatch
from typing import Any, Optional

from ..utils.model_response import (
    consume_model_response,
    extract_response_text,
)
from .tool_registry import DEFAULT_REGISTRY
from .policy import _parse_match

# Historical private name kept for existing callers/tests.
_extract_response_text = extract_response_text

logger = logging.getLogger(__name__)


# Rule generalization is opt-in per tool type: only ``shell`` and
# ``file`` targets are widened (commands and paths have meaningful
# structure to generalize). Anything else (network URLs, internal
# tools, unknown) stays an exact match.
_GENERALIZABLE_TOOL_TYPES = ("shell", "file")

# Shell commands whose effect is destructive/escalating. We refuse to
# widen these — the user approved one specific invocation, and ``rm *``
# / ``sudo *`` would grant far more than they intended. These still get
# recorded as exact matches, and builtin DENY/ASK rules continue to
# guard sensitive targets at evaluate time.
_NO_GENERALIZE_COMMANDS = frozenset(
    {
        "rm",
        "rmdir",
        "dd",
        "mkfs",
        "sudo",
        "chmod",
        "chown",
        "chgrp",
        "kill",
        "killall",
        "pkill",
        "reboot",
        "shutdown",
        "halt",
        "poweroff",
        "shred",
    },
)

# Hard ceiling on the LLM round-trip so a slow/hung provider can never
# stall an approval indefinitely. On timeout we fall back to the exact
# match, so the approved call is still recorded.
GENERALIZE_TIMEOUT_SECONDS = 6.0

_GENERALIZE_SYSTEM_PROMPT = (
    "You generalize a single tool-call target into a conservative glob "
    "pattern so that future, similar calls are auto-approved without "
    "asking again. You MUST output ONLY the glob pattern — no "
    "explanation, no quotes, no backticks, no tool name, no "
    "parentheses, no leading/trailing whitespace."
)


def _exact_match(tool_name: str, target: str) -> str:
    """The non-generalized fallback: a literal ``ToolName(target)``."""
    return f"{tool_name}({target})"


def _pattern_matches_target(
    pattern: str,
    target: str,
    tool_type: str,
) -> bool:
    """True if ``pattern`` matches ``target`` under the policy's rules.

    Mirrors :meth:`GovernanceRule.matches_tool_call`: shell tools use
    :func:`fnmatch.fnmatch`, file/wildcard tools use ``wcmatch.glob``
    with the same flags (including ``/**`` directory self-match).
    """
    if tool_type == "file":
        from wcmatch import glob

        flags = (
            glob.GLOBSTAR
            | glob.BRACE
            | glob.NEGATE
            | glob.SPLIT
            | glob.DOTGLOB
        )
        if glob.globmatch(target, pattern, flags=flags):
            return True
        if pattern.endswith("/**"):
            if glob.globmatch(target, pattern[:-3], flags=flags):
                return True
        return False
    # shell / default
    return fnmatch(target, pattern)


def _is_safe_generalization(
    target: str,
    pattern: str,
    tool_type: str,
) -> bool:
    """Validate an LLM-produced pattern before trusting it.

    Three guards, all required:

    1. **Well-formed**: non-empty, not a bare wildcard (``*`` / ``**`` /
       ``*/*``) — a bare wildcard is an allow-all for the tool, which is
       what ``add_session_allowall_rule`` is for, not generalization.
    2. **Covers the original**: the pattern MUST still match ``target``
       under the policy's matcher. If it doesn't, the just-approved call
       would no longer be covered by the recorded rule — a correctness
       bug — so we reject it.
    3. **Anchor preserved**: the pattern must keep the target's anchor
       (the leading command token for shell, the parent directory for
       file). This blocks over-broad widening like ``git status`` →
       ``*`` or ``/ws/src/a.py`` → ``/ws/**``.
    """
    p = pattern.strip().strip("\"'`“”‘’")
    # Reject empty / bare-wildcard / root-level allow-alls.
    if not p or p.strip("*?/ ") == "":
        return False

    # Guard 2: must re-match the approved target.
    if not _pattern_matches_target(p, target, tool_type):
        return False

    # Guard 3: keep the anchor.
    if tool_type == "shell":
        # First whitespace-delimited token of the command must remain a
        # literal prefix of the pattern (e.g. "git status" -> "git *").
        head = target.strip().split(None, 1)[0] if target.strip() else ""
        if not head or not p.startswith(head):
            return False
        # Refuse to widen destructive/escalating commands — the user
        # approved one specific call, not ``rm *`` / ``sudo *``.
        if head in _NO_GENERALIZE_COMMANDS:
            return False
    elif tool_type == "file":
        # Parent directory must remain a prefix of the pattern at a path
        # segment boundary, so the rule can't widen upward past the approved
        # file's folder. A bare ``startswith(parent)`` is too loose: a pattern
        # like ``/ws/src*/**`` passes it (and re-matches ``/ws/src/foo.py``)
        # yet also matches sibling dirs ``/ws/src-bar/**``. Requiring the
        # boundary char after ``parent`` closes that hole.
        parent = target.rsplit("/", 1)[0] if "/" in target else ""
        if parent and not (p.startswith(parent + "/") or p == parent):
            return False
    return True


def _build_model(agent_id: Optional[str]) -> Any:
    """Build a fresh chat-model instance for *agent_id*.

    Returns ``None`` if no model can be built — never raises.
    """
    try:
        from ..agents.model_factory import create_model_and_formatter

        model, _ = create_model_and_formatter(agent_id=agent_id)
        return model
    except Exception as exc:  # noqa: BLE001 - never block generalization
        logger.debug(
            "rule generalization: could not build model instance (%s)",
            exc,
        )
        return None


async def _consume_model_text(
    model: Any,
    messages: list,
    **call_kwargs: Any,
) -> str:
    """Await ``model(messages, **call_kwargs)`` and return its text content.

    Some providers return an ``async_generator`` that streams chunks;
    others return a non-streaming response object. Streaming chunks are
    assumed to carry cumulative text, so the latest non-empty chunk wins.

    ``disable_thinking=True`` here — a single neutral flag that each
    provider's compat ``_call_api`` translates into its own thinking-disable
    wire params (``enable_thinking=False`` / ``thinking={"type":"disabled"}``
    / …). This is the lever that actually works for the DashScope provider
    family, where setting ``parameters.thinking_enable`` on the instance is
    masked or ignored.
    """
    return await consume_model_response(model, messages, **call_kwargs)


def _extract_pattern(raw: str) -> str:
    """Normalize raw LLM output into a single glob pattern.

    Takes the first non-empty line and, if the model ignored the
    "no parentheses" instruction and emitted ``ToolName(pattern)``,
    unwraps it back to the inner pattern. Strips surrounding quotes.
    """
    if not raw:
        return ""
    stripped = raw.strip()
    if not stripped:
        return ""
    line = stripped.splitlines()[0].strip()
    if "(" in line and line.endswith(")"):
        try:
            _, inner = _parse_match(line)
            line = inner
        except (ValueError, IndexError):
            pass
    return line.strip().strip("\"'`“”‘’")


async def _llm_generalize_pattern(
    tool_name: str,
    target: str,
    tool_type: str,
    agent_id: Optional[str] = None,
) -> str:
    """Ask the active chat model for a generalized glob pattern.

    Returns "" on any failure (no model configured, API error, empty
    output) so the caller can fall back to the exact match. Never
    raises.
    """
    model = _build_model(agent_id)
    if model is None:
        logger.debug(
            "rule generalization skipped: no model available for agent=%s",
            agent_id,
        )
        return ""

    if tool_type == "shell":
        guidance = (
            "This is a shell command. Generalize CONSERVATIVELY: replace "
            "varying arguments with '*' while KEEPING the command name and "
            "any subcommand. Examples: 'git status' -> 'git *', "
            "'npm run build' -> 'npm run *'. Do NOT widen destructive "
            "commands (rm, dd, mkfs, sudo, chmod 777, > /dev/...) — return "
            "them unchanged. Never output a bare '*'."
        )
    else:  # file
        guidance = (
            "This is a filesystem path. Generalize CONSERVATIVELY by "
            "widening only the final path segment(s) using '**'. Keep the "
            "parent directory. Examples: '/ws/src/foo.py' -> "
            "'/ws/src/**', 'out/result.txt' -> 'out/**'. Never output a "
            "bare '*' or a root '/**'."
        )

    user_text = (
        f"tool_name: {tool_name}\n"
        f"tool_type: {tool_type}\n"
        f"target: {target}\n\n"
        f"{guidance}\n\n"
        "glob pattern:"
    )

    try:
        from agentscope.message import Msg, TextBlock

        messages = [
            Msg(
                name="system",
                role="system",
                content=[
                    TextBlock(type="text", text=_GENERALIZE_SYSTEM_PROMPT),
                ],
            ),
            Msg(
                name="user",
                role="user",
                content=[TextBlock(type="text", text=user_text)],
            ),
        ]
        # ``disable_thinking=True`` interpreted by compat layer
        raw = await _consume_model_text(
            model,
            messages,
            disable_thinking=True,
        )
    except Exception as exc:
        logger.debug("rule generalization LLM call failed (%s)", exc)
        return ""
    return _extract_pattern(raw)


async def generalize_rule_match(
    tool_name: str,
    target: str,
    agent_id: Optional[str] = None,
) -> str:
    """Return a generalized ``ToolName(pattern)`` match for an approved rule.

    Delegates to the LLM via :func:`_llm_generalize_pattern` (bounded by
    :data:`GENERALIZE_TIMEOUT_SECONDS`), then validates the result with
    :func:`_is_safe_generalization`. Only ``shell`` and ``file`` tool types
    are widened; everything else (and any failure) yields the exact
    ``ToolName(target)``. See the module docstring for the safety rationale.

    Args:
        tool_name: policy tool name, e.g. "Bash"
        target: tool's target argument value
        agent_id: agent whose model should be used for generalization.
            Forwarded to ``create_model_and_formatter`` so the same model
            the agent runs on is reused, instead of falling back to the
            global active model (which may be slower / different).

    Returns:
        match string, e.g. "Bash(git *)" or "Read(/ws/src/**)"
    """
    exact = _exact_match(tool_name, target)
    if not target or not target.strip():
        return exact

    tool_type = DEFAULT_REGISTRY.get_type(tool_name)
    if tool_type not in _GENERALIZABLE_TOOL_TYPES:
        return exact

    try:
        pattern = await asyncio.wait_for(
            _llm_generalize_pattern(tool_name, target, tool_type, agent_id),
            timeout=GENERALIZE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "rule generalization timed out after %ss for %s(%s); "
            "exact match used",
            GENERALIZE_TIMEOUT_SECONDS,
            tool_name,
            target,
        )
        return exact
    except Exception:
        logger.debug(
            "rule generalization failed; exact match used",
            exc_info=True,
        )
        return exact

    if not pattern or not _is_safe_generalization(
        target,
        pattern,
        tool_type,
    ):
        logger.debug(
            "rule generalization rejected unsafe pattern %r for %s(%s); "
            "exact match used",
            pattern,
            tool_name,
            target,
        )
        return exact

    generalized = f"{tool_name}({pattern})"
    logger.debug(
        "generalized approved rule: %s -> %s",
        exact,
        generalized,
    )
    return generalized


# ``GovernanceDecision.source`` values that mark a decision as driven by
# builtin protection (resource ask: .env / .ssh / keys …). Builtin asks
# are never generalized and never recorded — they ask every time.
_BUILTIN_SOURCES = frozenset({"builtin_rules"})


async def generalize_target_for_approval(
    tool_name: str,
    target: str,
    source: str,
    agent_id: Optional[str] = None,
) -> str:
    """Generalize the approved target for the approval card + persistence.

    Returns:
        The generalized target/pattern, e.g. ``"git *"`` or
        ``"/ws/src/**"``. The caller shows it on the approval card and
        passes it to ``add_approved_rule``, which re-wraps it as
        ``ToolName(pattern)`` for persistence.
    """
    if source in _BUILTIN_SOURCES:
        return target
    try:
        match_str = await generalize_rule_match(
            tool_name,
            target,
            agent_id=agent_id,
        )
        _, pattern = _parse_match(match_str)
        return pattern
    except Exception:
        logger.debug(
            "pre-approval generalization failed for %s(%s); "
            "card will show exact target",
            tool_name,
            target,
            exc_info=True,
        )
        return target
