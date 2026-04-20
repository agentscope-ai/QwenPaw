# -*- coding: utf-8 -*-
"""Quote-aware shell evasion and obfuscation detection guardian.

The checks detect obfuscation/evasion techniques that attempt to hide
malicious intent from simpler regex-only detection:

- Command substitution patterns ($(), ``, ${}, =(), <(), etc.)
- ANSI-C quoting ($'...') and locale quoting ($"...") flag obfuscation
- Backslash-escaped whitespace and shell operators
- Newlines / carriage returns that split hidden commands
- Comment-quote desync attacks
- Quoted newline + comment-line stripping attacks
"""
from __future__ import annotations

import re
import uuid
import logging
from typing import Any, Callable

from ..models import GuardFinding, GuardSeverity, GuardThreatCategory
from . import BaseToolGuardian

logger = logging.getLogger(__name__)

# ── Command substitution patterns ────────────────────────────────────
# Checked against content outside single quotes.
_COMMAND_SUBSTITUTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"<\("), "process substitution <()"),
    (re.compile(r">\("), "process substitution >()"),
    (re.compile(r"=\("), "Zsh process substitution =()"),
    (
        re.compile(r"(?:^|[\s;&|])=[a-zA-Z_]"),
        "Zsh equals expansion (=cmd)",
    ),
    (re.compile(r"\$\("), "$() command substitution"),
    (re.compile(r"\$\["), "$[] legacy arithmetic expansion"),
    (re.compile(r"~\["), "Zsh-style parameter expansion"),
    (re.compile(r"\(e:"), "Zsh-style glob qualifiers"),
    (re.compile(r"\(\+"), "Zsh glob qualifier with command execution"),
    (
        re.compile(r"\}\s*always\s*\{"),
        "Zsh always block (try/always construct)",
    ),
    (re.compile(r"<#"), "PowerShell comment syntax"),
]

# Shell operators whose preceding backslash indicates evasion.
_SHELL_OPERATORS = frozenset(";|&<>")

# ANSI-C quoting: $'...' or locale quoting: $"..."
_ANSI_C_QUOTE_RE = re.compile(r"\$'[^']*'")
_LOCALE_QUOTE_RE = re.compile(r'\$"[^"]*"')
_EMPTY_SPECIAL_QUOTE_DASH_RE = re.compile(r"\$['\"]{2}\s*-")
_EMPTY_QUOTE_DASH_RE = re.compile(r"(?:^|\s)(?:''|\"\")+\s*-")
# =====================================================================
# Quote-state tracker
# =====================================================================


class _QuoteState:
    """Tracks shell quoting context character-by-character.
    """

    __slots__ = ("in_single", "in_double", "escaped")

    def __init__(self) -> None:
        self.in_single = False
        self.in_double = False
        self.escaped = False

    @property
    def in_any_quote(self) -> bool:
        return self.in_single or self.in_double

    def feed(self, char: str) -> None:
        """Advance the state machine by one character."""
        if self.escaped:
            self.escaped = False
            return

        if char == "\\" and not self.in_single:
            self.escaped = True
            return

        if char == "'" and not self.in_double:
            self.in_single = not self.in_single
            return

        if char == '"' and not self.in_single:
            self.in_double = not self.in_double


def _extract_outside_single_quotes(command: str) -> str:
    """Return *command* with only single-quoted content removed.

    Keep double-quoted content because shell still expands command
    substitutions inside double quotes.
    """
    state = _QuoteState()
    parts: list[str] = []
    for ch in command:
        was_single = state.in_single
        state.feed(ch)
        if not was_single and not state.in_single:
            parts.append(ch)
    return "".join(parts)


# =====================================================================
# Individual check functions
# =====================================================================
# Each returns a GuardFinding or None.


def _check_command_substitution(
    command: str,
    unquoted: str,
) -> GuardFinding | None:
    """bashSecurity #8: detect command substitution patterns.

    Also detects unescaped backticks (outside quotes) which are the
    legacy command substitution syntax.
    """
    # Backtick check: unescaped ` outside single quotes.
    # Backticks inside double quotes are still command substitution.
    state = _QuoteState()
    for i, ch in enumerate(command):
        if state.escaped:
            state.feed(ch)
            continue
        state.feed(ch)
        if ch == "`" and not state.in_single and not state.escaped:
            snippet_start = max(0, i - 20)
            snippet_end = min(len(command), i + 20)
            return _finding(
                "SHELL_EVASION_COMMAND_SUBSTITUTION",
                GuardSeverity.HIGH,
                "Command contains backtick (`) command substitution",
                command,
                matched=command[snippet_start:snippet_end],
                snippet=command[snippet_start:snippet_end],
            )

    # Other patterns checked against unquoted content
    for pattern, label in _COMMAND_SUBSTITUTION_PATTERNS:
        m = pattern.search(unquoted)
        if m:
            return _finding(
                "SHELL_EVASION_COMMAND_SUBSTITUTION",
                GuardSeverity.HIGH,
                f"Command contains {label}",
                command,
                matched=m.group(0),
                pattern=pattern.pattern,
            )
    return None


def _check_obfuscated_flags(command: str) -> GuardFinding | None:
    """bashSecurity #4: detect ANSI-C / locale quoting and empty-quote
    flag obfuscation.

    These quoting mechanisms can hide flag characters (e.g. ``$'\\x2d exec'``
    hides ``-exec``) and bypass regex-based flag detection.
    """
    if _ANSI_C_QUOTE_RE.search(command):
        return _finding(
            "SHELL_EVASION_OBFUSCATED_FLAGS",
            GuardSeverity.HIGH,
            "Command contains ANSI-C quoting ($'...') "
            "which can hide characters",
            command,
        )

    if _LOCALE_QUOTE_RE.search(command):
        return _finding(
            "SHELL_EVASION_OBFUSCATED_FLAGS",
            GuardSeverity.HIGH,
            'Command contains locale quoting ($"...") '
            "which can hide characters",
            command,
        )

    if _EMPTY_SPECIAL_QUOTE_DASH_RE.search(command):
        return _finding(
            "SHELL_EVASION_OBFUSCATED_FLAGS",
            GuardSeverity.HIGH,
            "Command contains empty special quotes before dash "
            "(potential bypass)",
            command,
        )

    if _EMPTY_QUOTE_DASH_RE.search(command):
        return _finding(
            "SHELL_EVASION_OBFUSCATED_FLAGS",
            GuardSeverity.HIGH,
            "Command contains empty quotes before dash "
            "(potential flag bypass)",
            command,
        )

    # Quoted flag content: whitespace + quote + dash-letter inside quote
    state = _QuoteState()
    prev_char = ""
    for i, ch in enumerate(command):
        if state.escaped:
            state.feed(ch)
            prev_char = ch
            continue

        if not state.in_any_quote and prev_char in (" ", "\t"):
            if ch in ("'", '"'):
                # Peek inside the quote to see if it starts with a dash
                quote_char = ch
                j = i + 1
                inside = []
                while j < len(command) and command[j] != quote_char:
                    inside.append(command[j])
                    j += 1
                content = "".join(inside)
                if re.match(r"^-+[a-zA-Z0-9$`]", content):
                    return _finding(
                        "SHELL_EVASION_OBFUSCATED_FLAGS",
                        GuardSeverity.HIGH,
                        "Command contains quoted flag name "
                        "(potential obfuscation)",
                        command,
                        matched=command[i : j + 1],
                    )

        state.feed(ch)
        prev_char = ch

    return None


def _check_backslash_escaped_whitespace(
    command: str,
) -> GuardFinding | None:
    """bashSecurity #15: detect backslash-escaped space/tab outside quotes.

    ``echo\\ test`` is a single token in bash (command named "echo test"),
    but parsers may decode the escape and produce two separate tokens.
    This enables path traversal and command hiding.
    """
    state = _QuoteState()
    for i, ch in enumerate(command):
        if state.escaped:
            if not state.in_double and ch in (" ", "\t"):
                return _finding(
                    "SHELL_EVASION_BACKSLASH_WHITESPACE",
                    GuardSeverity.HIGH,
                    "Command contains backslash-escaped whitespace"
                    " that could alter command parsing",
                    command,
                    matched=command[max(0, i - 1) : i + 1],
                )
            state.feed(ch)
            continue
        state.feed(ch)
    return None


def _check_backslash_escaped_operators(
    command: str,
) -> GuardFinding | None:
    r"""bashSecurity #21: detect ``\;``, ``\|``, ``\&``, ``\<``, ``\>``
    outside quotes.

    splitCommand normalises ``\;`` to bare ``;`` which causes a false
    split on re-parsing, enabling arbitrary file reads that bypass path
    validation.
    """
    find_exec_terminator_re = re.compile(
        r"-(?:exec|execdir)\b[\s\S]*\{\}\s*\\;$",
    )
    state = _QuoteState()
    for i, ch in enumerate(command):
        if state.escaped:
            if not state.in_double and ch in _SHELL_OPERATORS:
                # find ... -exec ... {} \; is normal shell syntax.
                if ch == ";":
                    prefix = command[: i + 1]
                    if find_exec_terminator_re.search(prefix):
                        state.feed(ch)
                        continue
                return _finding(
                    "SHELL_EVASION_BACKSLASH_OPERATOR",
                    GuardSeverity.HIGH,
                    f"Command contains backslash before shell operator"
                    f" (\\{ch}) which can hide command structure",
                    command,
                    matched=command[max(0, i - 1) : i + 1],
                )
            state.feed(ch)
            continue
        state.feed(ch)
    return None


def _check_newlines(command: str) -> GuardFinding | None:
    """bashSecurity #7: detect newlines and carriage returns that could
    separate hidden commands.
    """
    # Heredoc intentionally relies on multiline input and should not be
    # treated as hidden-command splitting.
    if _looks_like_heredoc(command):
        return None

    # Carriage return outside double quotes (misparsing concern)
    state = _QuoteState()
    for ch in command:
        if state.escaped:
            state.feed(ch)
            continue
        state.feed(ch)
        if ch == "\r" and not state.in_double:
            return _finding(
                "SHELL_EVASION_NEWLINE",
                GuardSeverity.HIGH,
                "Command contains carriage return (\\r) which shell-quote"
                " and bash tokenize differently",
                command,
            )

    # Newline outside quotes followed by non-whitespace (hidden command)
    state = _QuoteState()
    for i, ch in enumerate(command):
        if state.escaped:
            state.feed(ch)
            continue
        state.feed(ch)
        if ch in ("\n", "\r") and not state.in_any_quote:
            rest = command[i + 1 :]
            if rest.lstrip():
                return _finding(
                    "SHELL_EVASION_NEWLINE",
                    GuardSeverity.HIGH,
                    "Command contains newlines that could separate"
                    " multiple commands",
                    command,
                )

    return None


def _looks_like_heredoc(command: str) -> bool:
    """Return True when command appears to include a complete heredoc."""
    opener_re = re.compile(
        r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1",
    )
    lines = command.splitlines()
    if len(lines) < 2:
        return False
    for i, line in enumerate(lines):
        m = opener_re.search(line)
        if not m:
            continue
        delim = m.group(2)
        for next_line in lines[i + 1 :]:
            if next_line.strip() == delim:
                return True
    return False


def _check_comment_quote_desync(command: str) -> GuardFinding | None:
    """bashSecurity #22: detect quote characters inside ``#`` comments.

    Everything after an unquoted ``#`` is a comment in bash, but quote
    trackers don't handle comments — a ``'`` or ``"`` in a comment
    desyncs quote state tracking for subsequent lines.
    """
    if "#" not in command:
        return None

    state = _QuoteState()
    for i, ch in enumerate(command):
        if state.escaped:
            state.feed(ch)
            continue
        state.feed(ch)

        if ch == "#" and not state.in_any_quote:
            line_end = command.find("\n", i)
            comment = command[i + 1 : line_end if line_end != -1 else None]
            if re.search(r"['\"]", comment):
                return _finding(
                    "SHELL_EVASION_COMMENT_QUOTE_DESYNC",
                    GuardSeverity.HIGH,
                    "Command contains quote characters inside a # comment"
                    " which can desync quote tracking",
                    command,
                    matched=command[
                        i : (line_end if line_end != -1 else i + 40)
                    ],
                )
            # Skip rest of comment line
            if line_end == -1:
                break

    return None


def _check_quoted_newline(command: str) -> GuardFinding | None:
    """bashSecurity #23: detect newlines inside quoted strings where the
    next line starts with ``#``.

    Line-based processing (like stripCommentLines) drops ``#``-prefixed
    lines without tracking quote state, hiding arguments from path
    validation.
    """
    if "\n" not in command or "#" not in command:
        return None

    state = _QuoteState()
    for i, ch in enumerate(command):
        if state.escaped:
            state.feed(ch)
            continue
        state.feed(ch)

        if ch == "\n" and state.in_any_quote:
            line_start = i + 1
            next_nl = command.find("\n", line_start)
            line_end = next_nl if next_nl != -1 else len(command)
            next_line = command[line_start:line_end]
            if next_line.strip().startswith("#"):
                return _finding(
                    "SHELL_EVASION_QUOTED_NEWLINE",
                    GuardSeverity.HIGH,
                    "Command contains a quoted newline followed by a"
                    " #-prefixed line, which can hide arguments from"
                    " line-based permission checks",
                    command,
                    matched=command[
                        max(0, i - 10) : min(len(command), line_end + 10)
                    ],
                )

    return None


# =====================================================================
# Finding factory
# =====================================================================


def _finding(
    rule_id: str,
    severity: GuardSeverity,
    description: str,
    command: str,
    *,
    matched: str | None = None,
    pattern: str | None = None,
    snippet: str | None = None,
) -> GuardFinding:
    return GuardFinding(
        id=f"GUARD-{uuid.uuid4().hex}",
        rule_id=rule_id,
        category=GuardThreatCategory.CODE_EXECUTION,
        severity=severity,
        title=f"[{severity.value}] {description}",
        description=(
            f"ShellEvasionGuardian: {description}\n\n"
            "This pattern is commonly used to bypass shell command"
            " security checks."
        ),
        tool_name="execute_shell_command",
        param_name="command",
        matched_value=matched,
        matched_pattern=pattern,
        snippet=snippet or command[:120],
        remediation=(
            "Review the command carefully. If the pattern is"
            " intentional, approve manually."
        ),
        guardian="shell_evasion_guardian",
    )


# =====================================================================
# Guardian class
# =====================================================================

# All checks, executed in order, collecting all matched findings.
_ShellCheckFn = Callable[..., GuardFinding | None]
_CHECKS: tuple[_ShellCheckFn, ...] = (
    _check_command_substitution,
    _check_obfuscated_flags,
    _check_backslash_escaped_whitespace,
    _check_backslash_escaped_operators,
    _check_newlines,
    _check_comment_quote_desync,
    _check_quoted_newline,
)


class ShellEvasionGuardian(BaseToolGuardian):
    """Quote-aware shell evasion / obfuscation detection.

    Detects command substitution, flag obfuscation, backslash-escaped
    whitespace/operators, hidden newlines, comment-quote desync, and
    quoted-newline attacks.  Only fires for ``execute_shell_command``.
    """

    def __init__(self) -> None:
        super().__init__(name="shell_evasion_guardian")

    def guard(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> list[GuardFinding]:
        if tool_name != "execute_shell_command":
            return []

        command = params.get("command")
        if not isinstance(command, str) or not command.strip():
            return []

        # Pre-compute content outside single quotes for checks that need it.
        outside_single_quotes = _extract_outside_single_quotes(command)

        findings: list[GuardFinding] = []
        for check in _CHECKS:
            # Checks that need unquoted content have 2-arg signature;
            # others take only the raw command.
            try:
                if check is _check_command_substitution:
                    result = check(command, outside_single_quotes)
                else:
                    result = check(command)
            except Exception as exc:
                logger.warning(
                    "ShellEvasionGuardian check failed: %s: %s",
                    getattr(check, "__name__", str(check)),
                    exc,
                    exc_info=True,
                )
                continue
            if result is not None:
                findings.append(result)

        return findings
