# -*- coding: utf-8 -*-
"""Single-pass filter for model-facing scaffolding in assistant text.

Why a scanner and not a set of regexes: the previous implementation paired
``<thinking>…</thinking>`` with ``.*?``, which rescans the remainder of the
text for every candidate opener (quadratic in the number of unclosed tags),
and it could not tell a tag inside a code block from a real one. Both problems
come from trying to recognise Markdown structure with deeply nested patterns.

The scanner walks the text once, keeping only a handful of boolean/counter
fields. Every character is examined a constant number of times, so the cost is
linear in the input and independent of how many tags are present. Markdown
structure (fenced code, indented code, blockquote lines, inline code spans) is
tracked as it goes, so literal tags inside quoted material are preserved.

The same object also carries state across chunk boundaries and across the text
blocks of one message, which is what the streaming and rendering paths need.
"""

from __future__ import annotations

import re

_REASONING_TAGS = ("thinking", "think", "analysis", "reasoning")
_OPEN_TAGS = tuple(f"<{name}>" for name in _REASONING_TAGS)
_CLOSE_TAGS = tuple(f"</{name}>" for name in _REASONING_TAGS)
_TAG_LITERALS = _OPEN_TAGS + _CLOSE_TAGS

# Framework-injected context notes travel as ordinary assistant text. They are
# hidden the same way reasoning blocks are, but their names are open-ended
# (``system-*``) and their closers may use a different suffix, so they are
# matched with patterns instead of literals.
_INJECT_OPEN_RE = re.compile(r"<system-[a-z0-9_-]+\s*/?>", re.IGNORECASE)
_INJECT_CLOSE_RE = re.compile(
    r"</(?:system-[a-z0-9_-]+|notification|info|warning|reminder|error)\s*>",
    re.IGNORECASE,
)
_INJECT_HEADS = (
    "<system-",
    "</system-",
    "</notification",
    "</info",
    "</warning",
    "</reminder",
    "</error",
)
_TAG_HEADS = _TAG_LITERALS + _INJECT_HEADS
# Only the literal reasoning tags are length-matched here; the injection
# patterns are matched with ``re`` and need no fixed window.
_MAX_TAG_LEN = max(len(tag) for tag in _TAG_LITERALS) + 2
_PARAGRAPH_BREAK_RE = re.compile(r"\r?\n[ \t]*\r?\n")


def _match_tag(text: str, index: int, literals: tuple[str, ...]) -> int:
    """Length of the tag literal starting at *index*, or 0."""
    if text[index] != "<":
        return 0
    head = text[index : index + _MAX_TAG_LEN].lower()
    for literal in literals:
        if head.startswith(literal):
            return len(literal)
    return 0


def _is_tag_prefix(tail: str) -> bool:
    """Whether *tail* could still grow into one of the tags we track."""
    if not tail.startswith("<"):
        return False
    lowered = tail.lower()
    return any(
        head.startswith(lowered) or lowered.startswith(head)
        for head in _TAG_HEADS
    )


def _drop_trailing_paragraph(text: str) -> str:
    """Keep everything before the last blank-line separated paragraph."""
    matches = list(_PARAGRAPH_BREAK_RE.finditer(text))
    if not matches:
        return ""
    return text[: matches[-1].start()]


class ScaffoldFilter:
    """Incremental remover for reasoning blocks and tool-call shells.

    ``feed`` may be called with arbitrary fragments (streaming deltas) or with
    whole text blocks; the result is the same as feeding the concatenation once,
    except that text already returned cannot be recalled.
    """

    __slots__ = (
        "suppress",
        "inject",
        "pending",
        "at_line_start",
        "fence_char",
        "fence_len",
        "line_literal",
        "line_has_text",
        "ticks",
        "unclosed_opens_are_prose",
    )

    def __init__(self, *, unclosed_opens_are_prose: bool = False) -> None:
        self.suppress = False
        # While true, an injected ``<system-*>`` block is being hidden. It is
        # tracked separately from ``suppress`` so the two closers never cross.
        self.inject = False
        self.pending = ""
        self.at_line_start = True
        self.fence_char: str | None = None
        self.fence_len = 0
        self.line_literal = False
        self.line_has_text = False
        self.ticks = 0
        # Whole-text scans can tell that no closing tag exists at all. Prose
        # that merely mentions an opener mid-sentence must then survive.
        self.unclosed_opens_are_prose = unclosed_opens_are_prose

    # -- helpers ---------------------------------------------------------
    def _literal(self) -> bool:
        return self.line_literal or self.fence_char is not None

    def _classify_line(self, text: str, index: int) -> tuple[int, bool]:
        """Return (index after the line prefix, literal-line flag)."""
        length = len(text)
        cursor = index
        spaces = 0
        quoted = False
        while cursor < length and text[cursor] in " \t>":
            if text[cursor] == ">":
                quoted = True
            elif text[cursor] == "\t":
                spaces += 4
            else:
                spaces += 1
            cursor += 1
            if cursor - index > 12:
                break

        if quoted:
            return cursor, True
        if spaces >= 4:
            return cursor, True
        return cursor, False

    # -- public API ------------------------------------------------------
    def feed(self, text: str) -> str:
        text = self.pending + text
        self.pending = ""
        out: list[str] = []
        index = 0
        length = len(text)

        while index < length:
            char = text[index]

            # 0. Inside an injected system block: hide until its closer.
            # Inspected before the reasoning branch so a ``</thinking>`` that
            # sits inside an injected note cannot end the wrong block.
            if self.inject:
                match = _INJECT_CLOSE_RE.match(text, index)
                if match:
                    index = match.end()
                    self.inject = False
                    continue
                if (
                    char == "<"
                    and length - index < _MAX_TAG_LEN
                    and (_is_tag_prefix(text[index:]))
                ):
                    self.pending = text[index:]
                    break
                index += 1
                continue

            # 1. Inside a reasoning block: swallow until the closing tag.
            if self.suppress:
                size = _match_tag(text, index, _CLOSE_TAGS)
                if size:
                    index += size
                    self.suppress = False
                    continue
                if (
                    char == "<"
                    and length - index < _MAX_TAG_LEN
                    and (_is_tag_prefix(text[index:]))
                ):
                    self.pending = text[index:]
                    break
                index += 1
                continue

            # 2. Line starts: classify Markdown block context once per line.
            if self.at_line_start:
                if index + 1 >= length and text[index] in " \t>":
                    self.pending = text[index:]
                    break
                cursor, literal = self._classify_line(text, index)
                if cursor == length and cursor > index:
                    self.pending = text[index:]
                    break
                self.at_line_start = False
                self.line_literal = literal or self.fence_char is not None
                if not literal and cursor < length:
                    marker = text[cursor]
                    if marker in "`~":
                        run = 1
                        while (
                            cursor + run < length
                            and text[cursor + run] == marker
                        ):
                            run += 1
                        if run >= 3:
                            if self.fence_char is None:
                                self.fence_char = marker
                                self.fence_len = run
                            elif (
                                marker == self.fence_char
                                and run >= self.fence_len
                            ):
                                self.fence_char = None
                                self.fence_len = 0
                            # Both the opening and the closing fence line are
                            # literal; only the closing one clears the state.
                            self.line_literal = True
                continue

            # 3. Literal contexts: emit verbatim.
            if self.line_literal or self.fence_char is not None:
                if char == "\n":
                    out.append(char)
                    index += 1
                    self.at_line_start = True
                    self.line_literal = False
                    self.line_has_text = False
                    continue
                out.append(char)
                index += 1
                continue

            # 4. Inline code spans keep their content literal.
            if char == "`":
                run = 1
                while index + run < length and text[index + run] == "`":
                    run += 1
                if self.ticks == 0:
                    self.ticks = run
                elif run == self.ticks:
                    self.ticks = 0
                out.append(text[index : index + run])
                index += run
                continue
            if self.ticks:
                out.append(char)
                index += 1
                continue

            # 5. Tags.
            if char == "<":
                match = _INJECT_OPEN_RE.match(text, index)
                if match:
                    token = match.group(0)
                    index = match.end()
                    if not token.rstrip().endswith("/>"):
                        self.inject = True
                    continue

                size = _match_tag(text, index, _OPEN_TAGS)
                if size and not (
                    self.unclosed_opens_are_prose and self.line_has_text
                ):
                    index += size
                    self.suppress = True
                    continue

                size = _match_tag(text, index, _CLOSE_TAGS)
                if size:
                    tail = text[index + size :]
                    if tail.strip():
                        # Reasoning head already dropped upstream: only the
                        # reply after the marker belongs to the user.
                        out.clear()
                    else:
                        kept = _drop_trailing_paragraph("".join(out))
                        out = [kept.rstrip()] if kept.strip() else []
                    index += size
                    continue

                if text[index : index + 10].lower().startswith("<parameter"):
                    if self.line_has_text:
                        # Prose that mentions a shell keeps it verbatim.
                        out.append(char)
                        index += 1
                        continue
                    end = text.find(">", index)
                    if end == -1:
                        self.pending = text[index:]
                        break
                    rest = text[index:].lower()
                    if "</parameter>" in rest:
                        out.append(text[index : end + 1])
                        index = end + 1
                    else:
                        # A truncated tool-call shell is not a reply.
                        index = length
                    continue

                if length - index < _MAX_TAG_LEN and _is_tag_prefix(
                    text[index:],
                ):
                    self.pending = text[index:]
                    break

            out.append(char)
            if char not in " \t\r\n":
                self.line_has_text = True
            if char == "\n":
                self.at_line_start = True
                self.line_literal = False
                self.line_has_text = False
                self.ticks = 0
            index += 1

        return "".join(out)

    def flush(self) -> str:
        """Release buffered text when the stream ends."""
        visible = "" if (self.suppress or self.inject) else self.pending
        self.pending = ""
        self.suppress = False
        self.inject = False
        self.at_line_start = True
        self.line_literal = False
        self.line_has_text = False
        self.fence_char = None
        self.fence_len = 0
        self.ticks = 0
        return visible


def strip_scaffold_text(text: str | None) -> str | None:
    """Remove reasoning scaffolding from a complete text block."""
    if not text:
        return text
    lowered = text.lower()
    has_close = any(tag in lowered for tag in _CLOSE_TAGS)
    filtering = ScaffoldFilter(unclosed_opens_are_prose=not has_close)
    visible = filtering.feed(text) + filtering.flush()
    if visible == text:
        return text
    return re.sub(r"\n{3,}", "\n\n", visible).strip()


class ScaffoldDeltaState:
    """Cross-chunk, cross-block state for :class:`ScaffoldFilter`."""

    __slots__ = ("filter",)

    def __init__(self) -> None:
        self.filter = ScaffoldFilter()

    def feed(self, text: str) -> str:
        """Run one fragment through the same scanner, keeping its state."""
        return self.filter.feed(text)

    def flush(self) -> str:
        """Release whatever the scanner still holds once the stream ends."""
        return self.filter.flush()

    # Backwards-compatible views used by the SSE helpers.
    @property
    def pending(self) -> str:
        return self.filter.pending

    @property
    def suppressing(self) -> bool:
        return self.filter.suppress

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ScaffoldDeltaState):
            return NotImplemented
        return (
            self.filter.pending == other.filter.pending
            and self.filter.suppress == other.filter.suppress
        )


def strip_scaffold_delta(
    text: str,
    *,
    state: ScaffoldDeltaState | None = None,
) -> tuple[str, ScaffoldDeltaState]:
    """Remove one streamed scaffolding fragment and return its state."""
    state = state or ScaffoldDeltaState()
    return state.filter.feed(text), state


def flush_scaffold_delta(state: ScaffoldDeltaState) -> str:
    """Finalize one stream, releasing only an unconfirmed tag prefix."""
    return state.filter.flush()
